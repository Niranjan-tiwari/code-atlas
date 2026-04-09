"""
LLM response cache: Redis exact match + pgvector semantic similarity (optional).

Flow (aligned with KV → semantic → RAG):
  1. In-process LRU exact match (fast, no Redis required)
  2. Redis exact match (shared across processes)
  3. pgvector: embed question, cosine-similar prior questions → reuse answer
  4. Miss → full RAG + LLM, then write-through to all enabled layers

Skipped when ``include_history`` is True (conversation-dependent).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("llm_response_cache")


def normalize_question(text: str) -> str:
    t = (text or "").strip().lower()
    return re.sub(r"\s+", " ", t)


def cache_key_parts(
    question: str,
    repo_filter: Optional[str],
    n_context: int,
    provider: Optional[str],
    temperature: float,
) -> Dict[str, Any]:
    return {
        "q": normalize_question(question),
        "repo": repo_filter or "",
        "n_ctx": int(n_context),
        "provider": provider or "",
        "temp": round(float(temperature), 3),
    }


def exact_key_hash(parts: Dict[str, Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def param_hash_only(parts: Dict[str, Any]) -> str:
    """Hash retrieval/LLM params without the question (for semantic cache scoping)."""
    sub = {k: v for k, v in parts.items() if k != "q"}
    raw = json.dumps(sub, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class CachedLLMPayload:
    answer: str
    sources: List[Dict]
    provider: str
    model: str
    tokens_used: int
    cost_estimate: float
    context_length: int
    query: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": self.sources,
            "provider": self.provider,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "cost_estimate": self.cost_estimate,
            "context_length": self.context_length,
            "query": self.query,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CachedLLMPayload":
        return CachedLLMPayload(
            answer=d.get("answer") or "",
            sources=list(d.get("sources") or []),
            provider=d.get("provider") or "",
            model=d.get("model") or "",
            tokens_used=int(d.get("tokens_used") or 0),
            cost_estimate=float(d.get("cost_estimate") or 0),
            context_length=int(d.get("context_length") or 0),
            query=d.get("query") or "",
        )


class PgVectorSemanticCache:
    """
    Stores (embedding, param_hash, qnorm, payload). Lookup: same param_hash, nearest neighbors.
    Requires: PostgreSQL + pgvector extension, psycopg2, pgvector Python package.
    """

    def __init__(
        self,
        dsn: str,
        table: str = "code_atlas_llm_q_cache",
        similarity_threshold: float = 0.92,
        max_candidates: int = 8,
    ):
        self.dsn = dsn
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", table or "code_atlas_llm_q_cache")
        self.table = safe[: 63] or "code_atlas_llm_q_cache"
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates
        self._lock = threading.Lock()
        self._dim: Optional[int] = None
        self._available = False
        self._hits = 0
        self._misses = 0
        try:
            import psycopg2  # noqa: F401
            from pgvector.psycopg2 import register_vector  # noqa: F401

            self._available = True
        except ImportError as e:
            logger.info(
                "pgvector semantic cache disabled (install psycopg2-binary pgvector): %s",
                e,
            )

    @property
    def is_available(self) -> bool:
        return self._available

    def _connect(self):
        import psycopg2
        from pgvector.psycopg2 import register_vector

        conn = psycopg2.connect(self.dsn)
        register_vector(conn)
        conn.autocommit = True
        return conn

    def _ensure_table(self, conn, dim: int) -> None:
        if self._dim == dim:
            return
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    id BIGSERIAL PRIMARY KEY,
                    embedding vector({dim}) NOT NULL,
                    param_hash TEXT NOT NULL,
                    qnorm TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table}_param_idx
                ON {self.table} (param_hash)
                """
            )
        self._dim = dim

    def lookup(
        self, embedding: List[float], param_hash: str
    ) -> Optional[CachedLLMPayload]:
        if not self._available or not self.dsn:
            return None
        dim = len(embedding)
        try:
            with self._lock:
                conn = self._connect()
                try:
                    self._ensure_table(conn, dim)
                    with conn.cursor() as cur:
                        # Cosine distance <=> ; similarity ≈ 1 - distance for L2-normalized vectors
                        cur.execute(
                            f"""
                            SELECT payload::text,
                                   1 - (embedding <=> %s::vector) AS sim
                            FROM {self.table}
                            WHERE param_hash = %s
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (embedding, param_hash, embedding, self.max_candidates),
                        )
                        rows = cur.fetchall()
                finally:
                    conn.close()
        except Exception as e:
            logger.debug("pgvector semantic lookup failed: %s", e)
            self._misses += 1
            return None

        best: Optional[Tuple[float, Dict]] = None
        for row in rows or []:
            raw, sim = row[0], float(row[1])
            if sim >= self.similarity_threshold:
                try:
                    payload = json.loads(raw)
                    if best is None or sim > best[0]:
                        best = (sim, payload)
                except (json.JSONDecodeError, TypeError):
                    continue

        if best:
            self._hits += 1
            return CachedLLMPayload.from_dict(best[1])
        self._misses += 1
        return None

    def store(
        self,
        embedding: List[float],
        param_hash: str,
        qnorm: str,
        payload: Dict[str, Any],
    ) -> None:
        if not self._available or not self.dsn:
            return
        dim = len(embedding)
        try:
            with self._lock:
                conn = self._connect()
                try:
                    self._ensure_table(conn, dim)
                    from psycopg2.extras import Json

                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {self.table}
                                (embedding, param_hash, qnorm, payload)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (embedding, param_hash, qnorm, Json(payload)),
                        )
                finally:
                    conn.close()
        except Exception as e:
            logger.debug("pgvector semantic store failed: %s", e)

    def stats(self) -> Dict[str, Any]:
        return {
            "available": self._available,
            "hits": self._hits,
            "misses": self._misses,
            "dim": self._dim,
        }


class LLMQueryCache:
    """
    L0: in-memory LRU exact
    L1: Redis exact (optional)
    L2: pgvector semantic (optional)
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.ttl_seconds = int(cfg.get("ttl_seconds", 86400))
        self.l1_max = int(cfg.get("l1_max_size", 256))

        self._l0 = None
        self._redis = None
        self._semantic: Optional[PgVectorSemanticCache] = None

        self._exact_hits_l0 = 0
        self._exact_hits_redis = 0
        self._semantic_hits = 0
        self._misses = 0

        if not self.enabled:
            logger.info("LLM query cache disabled (config)")
            return

        from .cache import LRUCache, RedisCache

        self._l0 = LRUCache(max_size=self.l1_max, default_ttl=self.ttl_seconds)

        rcfg = cfg.get("redis") or {}
        if rcfg.get("enabled", True):
            self._redis = RedisCache(
                host=rcfg.get("host", "localhost"),
                port=int(rcfg.get("port", 6379)),
                db=int(rcfg.get("db", 1)),
                prefix=str(rcfg.get("prefix", "llmqa:")),
                default_ttl=self.ttl_seconds,
            )
            if not self._redis.is_available:
                self._redis = None
                logger.info("LLM query cache: Redis not available, using L0 + semantic only")

        scfg = cfg.get("semantic") or {}
        if scfg.get("enabled", False):
            dsn = (scfg.get("database_url") or os.environ.get("DATABASE_URL") or "").strip()
            if dsn:
                self._semantic = PgVectorSemanticCache(
                    dsn=dsn,
                    table=str(scfg.get("table", "code_atlas_llm_q_cache")),
                    similarity_threshold=float(scfg.get("similarity_threshold", 0.92)),
                    max_candidates=int(scfg.get("max_candidates", 8)),
                )
                if not self._semantic.is_available:
                    self._semantic = None
            else:
                logger.info("LLM semantic cache enabled but no database_url / DATABASE_URL")

    def _exact_key(self, parts: Dict[str, Any]) -> str:
        return exact_key_hash(parts)

    def try_get(
        self,
        question: str,
        repo_filter: Optional[str],
        n_context: int,
        provider: Optional[str],
        temperature: float,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]],
    ) -> Optional[Tuple[str, CachedLLMPayload]]:
        if not self.enabled or self._l0 is None:
            return None

        parts = cache_key_parts(
            question, repo_filter, n_context, provider, temperature
        )
        ek = self._exact_key(parts)

        hit = self._l0.get(ek)
        if hit is not None:
            self._exact_hits_l0 += 1
            logger.debug("LLM cache L0 exact hit")
            return ("exact_l0", CachedLLMPayload.from_dict(hit))

        if self._redis and self._redis.is_available:
            hit = self._redis.get(ek)
            if hit is not None:
                self._exact_hits_redis += 1
                self._l0.set(ek, hit, self.ttl_seconds)
                logger.debug("LLM cache Redis exact hit")
                return ("exact_redis", CachedLLMPayload.from_dict(hit))

        if self._semantic and embed_fn is not None:
            try:
                vec = embed_fn([question])
                if vec and vec[0]:
                    ph = param_hash_only(parts)
                    found = self._semantic.lookup(vec[0], ph)
                    if found:
                        self._semantic_hits += 1
                        d = found.to_dict()
                        self._l0.set(ek, d, self.ttl_seconds)
                        if self._redis and self._redis.is_available:
                            self._redis.set(ek, d, self.ttl_seconds)
                        logger.debug("LLM cache semantic (pgvector) hit")
                        return ("semantic_pgvector", found)
            except Exception as e:
                logger.debug("LLM semantic lookup skipped: %s", e)

        self._misses += 1
        return None

    def store(
        self,
        question: str,
        repo_filter: Optional[str],
        n_context: int,
        provider: Optional[str],
        temperature: float,
        payload: CachedLLMPayload,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]],
    ) -> None:
        if not self.enabled or self._l0 is None:
            return

        parts = cache_key_parts(
            question, repo_filter, n_context, provider, temperature
        )
        ek = self._exact_key(parts)
        d = payload.to_dict()

        self._l0.set(ek, d, self.ttl_seconds)
        if self._redis and self._redis.is_available:
            self._redis.set(ek, d, self.ttl_seconds)

        if self._semantic and embed_fn is not None:
            try:
                vec = embed_fn([question])
                if vec and vec[0]:
                    self._semantic.store(
                        vec[0],
                        param_hash_only(parts),
                        normalize_question(question),
                        d,
                    )
            except Exception as e:
                logger.debug("LLM semantic store skipped: %s", e)

    def stats(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "enabled": self.enabled,
            "exact_hits_l0": self._exact_hits_l0,
            "exact_hits_redis": self._exact_hits_redis,
            "semantic_hits_pgvector": self._semantic_hits,
            "misses": self._misses,
        }
        if self._l0:
            out["l0"] = self._l0.stats()
        if self._redis:
            out["redis"] = self._redis.stats()
        if self._semantic:
            out["semantic_pgvector"] = self._semantic.stats()
        return out


def load_llm_query_cache_config(llm_config_path: Optional[str]) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "enabled": False,
        "ttl_seconds": 86400,
        "l1_max_size": 256,
        "redis": {
            "enabled": True,
            "host": "localhost",
            "port": 6379,
            "db": 1,
            "prefix": "llmqa:",
        },
        "semantic": {
            "enabled": False,
            "database_url": "",
            "table": "code_atlas_llm_q_cache",
            "similarity_threshold": 0.92,
            "max_candidates": 8,
        },
    }
    if not llm_config_path or not os.path.isfile(llm_config_path):
        return defaults
    try:
        with open(llm_config_path, encoding="utf-8") as f:
            data = json.load(f)
        merged = data.get("llm_query_cache")
        if not isinstance(merged, dict):
            return defaults
        out = {**defaults, **merged}
        if isinstance(merged.get("redis"), dict):
            out["redis"] = {**defaults["redis"], **merged["redis"]}
        if isinstance(merged.get("semantic"), dict):
            out["semantic"] = {**defaults["semantic"], **merged["semantic"]}
        return out
    except (OSError, json.JSONDecodeError):
        return defaults


def get_retriever_embed_fn(retriever: Any) -> Optional[Callable[[List[str]], List[List[float]]]]:
    if retriever is None:
        return None
    if getattr(retriever, "_emb_fn", None):
        return retriever._emb_fn
    base = getattr(retriever, "base_retriever", None)
    if base is not None and getattr(base, "_emb_fn", None):
        return base._emb_fn
    return None
