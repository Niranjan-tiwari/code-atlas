"""
RAG (Retrieval-Augmented Generation) — Qdrant + embeddings.

1. UNIFIED collection: one query (~0.05s) vs many repo collections
2. Pre-warmed embedding model
3. Pre-computed query embedding
4. Hybrid keyword boost on results
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from .vector_backend import vector_db_path
from .qdrant_rag_support import QdrantCollectionAdapter


class RAGRetriever:
    """Code retriever over Qdrant (local embedded storage)."""

    def __init__(self, persist_directory: Optional[str] = None):
        self.logger = logging.getLogger("rag_retriever")
        self.persist_directory = persist_directory or vector_db_path()

        self._emb_fn = None
        try:
            from src.ai.embeddings.ollama_embed import get_best_embedding_function

            self._emb_fn = get_best_embedding_function()
        except Exception:
            pass

        if self._emb_fn is None:
            from src.ai.embeddings.ollama_embed import SentenceTransformerEmbedding

            emb = SentenceTransformerEmbedding("default")
            emb._load()
            self._emb_fn = emb

        try:
            self._emb_fn(["warmup"])
        except Exception:
            pass

        emb_name = getattr(self._emb_fn, "model", getattr(self._emb_fn, "model_name", "default"))
        self.logger.info(f"Embedding model: {emb_name}")

        from pathlib import Path

        from .vector_backend import open_embedded_qdrant_client

        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
        self.client = open_embedded_qdrant_client(self.persist_directory, mkdir=False)

        self._unified = None
        self._collections: Dict[str, object] = {}
        names = [c.name for c in self.client.get_collections().collections]
        if "unified_code" in names:
            uc = QdrantCollectionAdapter(self.client, "unified_code", self._emb_fn)
            try:
                if uc.count() > 0:
                    self._unified = uc
                    self.logger.info(f"Using unified collection ({uc.count()} chunks)")
            except Exception:
                pass
        if not self._unified:
            for name in names:
                if name.startswith("repo_"):
                    self._collections[name] = QdrantCollectionAdapter(
                        self.client, name, self._emb_fn
                    )
            self.logger.info(f"Using per-repo collections ({len(self._collections)} repos)")

        self._repo_cache: Optional[List[Dict]] = None

    def close(self) -> None:
        """Release embedded Qdrant client so another process can open the same directory."""
        c = getattr(self, "client", None)
        if c is None:
            return
        try:
            if hasattr(c, "close"):
                c.close()
        except Exception:
            self.logger.debug("Qdrant client close failed", exc_info=True)
        finally:
            self.client = None

    def get_available_repos(self) -> List[Dict]:
        if self._repo_cache is None:
            self._repo_cache = []
            repo_names = [
                c.name
                for c in self.client.get_collections().collections
                if c.name.startswith("repo_")
            ]
            for name in repo_names:
                try:
                    count = QdrantCollectionAdapter(self.client, name, self._emb_fn).count()
                    if count > 0:
                        self._repo_cache.append(
                            {
                                "name": name.replace("repo_", ""),
                                "collection": name,
                                "chunks": count,
                            }
                        )
                except Exception:
                    pass
            self._repo_cache.sort(key=lambda x: x["name"])
        return self._repo_cache

    def search_code(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        retrieval_intent: Optional[str] = None,
        fast_fanout: bool = False,
    ) -> List[Dict]:
        query_lower = query.lower()
        query_keywords = set(query_lower.split())
        query_emb = self._emb_fn([query])

        if retrieval_intent == "semantic":
            kw_scale = 0.45
        elif retrieval_intent == "keyword":
            kw_scale = 1.55
        else:
            kw_scale = 1.0

        if self._unified:
            raw = self._search_unified(query_emb, n_results * 3, repo_filter, language_filter)
        else:
            raw = self._search_per_repo(
                query_emb,
                n_results,
                repo_filter,
                language_filter,
                fast_fanout=fast_fanout,
            )

        for r in raw:
            dist = r.get("distance", 2.0) or 2.0
            boost = 0.0
            repo = r.get("repo", "").lower().replace("-", " ").replace("_", " ")
            fpath = r.get("file", "").lower()
            code = r.get("code", "").lower()
            for kw in query_keywords:
                if len(kw) >= 3:
                    if kw in repo:
                        boost += 1.0 * kw_scale
                    if kw in fpath:
                        boost += 0.4 * kw_scale
                    if kw in code:
                        boost += 0.2 * kw_scale
            r["hybrid_score"] = dist - boost
            r["keyword_boost"] = boost

        raw.sort(key=lambda x: x.get("hybrid_score", float("inf")))
        return raw[:n_results]

    def _search_unified(self, query_emb, n_results, repo_filter=None, language_filter=None):
        where = {}
        if repo_filter:
            where["repo"] = repo_filter
        if language_filter:
            where["language"] = language_filter.upper()
        try:
            results = self._unified.query(
                query_embeddings=query_emb,
                n_results=min(n_results, self._unified.count()),
                where=where if where else None,
            )
        except Exception:
            results = self._unified.query(
                query_embeddings=query_emb,
                n_results=min(n_results, self._unified.count()),
            )
        return self._format_results(results, "unified_code")

    def _search_per_repo(
        self,
        query_emb,
        n_results,
        repo_filter=None,
        language_filter=None,
        *,
        fast_fanout: bool = False,
    ):
        if repo_filter:
            col = self._collections.get(f"repo_{repo_filter}")
            if col:
                return self._query_one(col, query_emb, n_results, language_filter)
            return []

        all_results = []
        cols = list(self._collections.values())
        if not cols:
            return []

        per_col = min(n_results, 2 if fast_fanout else 3)
        max_w = int(os.environ.get("CODE_ATLAS_RAG_MAX_WORKERS", "12"))
        with ThreadPoolExecutor(max_workers=min(max_w, len(cols))) as ex:
            futs = {ex.submit(self._query_one, c, query_emb, per_col, language_filter): c for c in cols}
            for f in as_completed(futs):
                try:
                    all_results.extend(f.result())
                except Exception:
                    pass
        return all_results

    def _query_one(self, collection, query_emb, n_results, language_filter=None):
        where = {"language": language_filter.upper()} if language_filter else None
        try:
            cnt = collection.count()
            n = min(n_results, max(1, cnt))
            results = collection.query(query_embeddings=query_emb, n_results=n, where=where)
        except Exception:
            try:
                cnt = collection.count()
                n = min(n_results, max(1, cnt))
                results = collection.query(query_embeddings=query_emb, n_results=n)
            except Exception:
                return []
        return self._format_results(results, collection.name)

    def _format_results(self, results, collection_name):
        formatted = []
        if results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                formatted.append(
                    {
                        "code": results["documents"][0][i],
                        "repo": meta.get("repo", collection_name.replace("repo_", "")),
                        "file": meta.get("file", "unknown"),
                        "language": meta.get("language", "unknown"),
                        "distance": results["distances"][0][i] if results.get("distances") else None,
                        "chunk_idx": meta.get("chunk", 0),
                        "total_chunks": meta.get("total_chunks", 1),
                        "collection": collection_name,
                    }
                )
        return formatted

    def detect_repo_in_query(self, query: str) -> Optional[str]:
        repos = self.get_available_repos()
        repo_names = [r["name"] for r in repos]
        if not repo_names:
            return None

        q_lower = query.lower().strip()

        def norm(s):
            return s.lower().replace("_", "-").replace(" ", "-")

        q_norm = norm(q_lower)
        for name in sorted(repo_names, key=len, reverse=True):
            name_lower = name.lower()
            name_norm = norm(name)
            if name_lower in q_lower or name_norm in q_norm:
                return name

        words = q_lower.replace("-", " ").replace("_", " ").split()
        repo_lookup = {norm(n): n for n in repo_names}
        for window in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - window + 1):
                candidate = "-".join(words[i : i + window])
                if candidate in repo_lookup:
                    return repo_lookup[candidate]
        return None

    def _search_collection_fast(self, collection, query_emb, n_results, language_filter=None):
        return self._query_one(collection, query_emb, n_results, language_filter)

    def _search_collection(self, collection, query, n_results, language_filter=None):
        return self._query_one(collection, self._emb_fn([query]), n_results, language_filter)

    def build_context(
        self,
        query,
        n_results=5,
        repo_filter=None,
        max_context_length=8000,
        retrieval_intent=None,
        fast_fanout: bool = False,
    ):
        results = self.search_code(
            query,
            n_results=n_results,
            repo_filter=repo_filter,
            retrieval_intent=retrieval_intent,
            fast_fanout=fast_fanout,
        )
        if not results:
            return "", []
        parts, sources, total = [], [], 0
        for i, r in enumerate(results, 1):
            s = f"--- Source {i}: {r['repo']}/{r['file']} ({r['language']}) ---\n{r['code']}\n"
            if total + len(s) > max_context_length:
                break
            parts.append(s)
            sources.append(
                {
                    "index": i,
                    "repo": r["repo"],
                    "file": r["file"],
                    "language": r["language"],
                    "relevance": 1 - (r.get("distance", 0) or 0),
                }
            )
            total += len(s)
        return "\n".join(parts), sources

    def get_repo_summary(self, repo_name):
        col = self._collections.get(f"repo_{repo_name}")
        if not col:
            return {"name": repo_name, "chunks": 0, "indexed": False}
        try:
            count = col.count()
            if count > 0:
                sample = col.peek(limit=min(count, 20))
                metas = sample.get("metadatas") or []
                langs = {m.get("language") for m in metas if m.get("language")}
                files = {m.get("file") for m in metas if m.get("file")}
                return {
                    "name": repo_name,
                    "chunks": count,
                    "languages": list(langs),
                    "sample_files": list(files)[:10],
                    "indexed": True,
                }
            return {"name": repo_name, "chunks": 0, "indexed": False}
        except Exception:
            return {"name": repo_name, "chunks": 0, "indexed": False}
