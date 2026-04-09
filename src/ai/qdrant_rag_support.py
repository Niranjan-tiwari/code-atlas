"""Qdrant helpers for RAG: collection adapter, upsert, unified merge, filters."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("qdrant_rag")

EmbedFn = Callable[[List[str]], List[List[float]]]


def _point_id(raw: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def where_dict_to_filter(where: Optional[Dict]) -> Any:
    if not where:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in where.items()]
    return Filter(must=must) if must else None


def scored_to_distance(score: float) -> float:
    """Map Qdrant score (higher = more similar) to distance (lower = better) for hybrid ranking."""
    return -float(score)


def client_query_vectors(
    client: Any,
    collection_name: str,
    query_vector: List[float],
    limit: int,
    query_filter: Any = None,
    with_payload: bool = True,
) -> List[Any]:
    """
    Vector search compatible with qdrant-client 1.7+ (local: query_points) and older (search).
    Returns a list of scored points with .id, .score, .payload.
    """
    lim = max(1, int(limit))
    if hasattr(client, "query_points"):
        res = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=lim,
            query_filter=query_filter,
            with_payload=with_payload,
        )
        return list(res.points)
    hits = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=lim,
        query_filter=query_filter,
        with_payload=with_payload,
    )
    return list(hits)


class QdrantCollectionAdapter:
    """Thin adapter so RAGRetriever can call .query / .count / .peek uniformly."""

    def __init__(self, client: Any, collection_name: str, emb_fn: EmbedFn):
        self.client = client
        self.name = collection_name
        self._emb_fn = emb_fn

    def count(self) -> int:
        return int(self.client.count(self.name, exact=True).count)

    def peek(self, limit: int = 20) -> Dict[str, Any]:
        records, _ = self.client.scroll(
            collection_name=self.name,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        metadatas: List[Dict] = []
        documents: List[str] = []
        for r in records:
            p = dict(r.payload or {})
            doc = p.pop("document", "")
            metadatas.append(p)
            documents.append(doc)
        return {"metadatas": metadatas, "documents": documents}

    def query(
        self,
        query_embeddings: Optional[List[List[float]]] = None,
        query_texts: Optional[List[str]] = None,
        n_results: int = 10,
        where: Optional[Dict] = None,
        where_document: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        if query_embeddings is None and query_texts:
            query_embeddings = self._emb_fn(query_texts)
        if not query_embeddings:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        vec = query_embeddings[0]
        meta_filter = where_dict_to_filter(where)

        if where_document and "$contains" in where_document:
            return self._query_contains(
                needle=where_document["$contains"],
                n_results=n_results,
                meta_filter=meta_filter,
                query_vec=vec,
            )

        hits = client_query_vectors(
            self.client,
            self.name,
            vec,
            n_results,
            meta_filter,
            with_payload=True,
        )
        documents: List[str] = []
        metadatas: List[Dict] = []
        distances: List[float] = []
        for hit in hits:
            p = dict(hit.payload or {})
            doc = p.pop("document", "")
            documents.append(doc)
            metadatas.append(p)
            distances.append(scored_to_distance(hit.score))
        return {"documents": [documents], "metadatas": [metadatas], "distances": [distances]}

    def _query_contains(
        self,
        needle: str,
        n_results: int,
        meta_filter: Any,
        query_vec: List[float],
    ) -> Dict[str, Any]:
        """Keyword-style $contains: scroll + filter (bounded work)."""
        documents: List[str] = []
        metadatas: List[Dict] = []
        distances: List[float] = []
        offset = None
        max_scan = max(500, n_results * 200)
        scanned = 0
        while len(documents) < n_results and scanned < max_scan:
            records, offset = self.client.scroll(
                collection_name=self.name,
                limit=64,
                offset=offset,
                with_payload=True,
                with_vectors=False,
                scroll_filter=meta_filter,
            )
            if not records:
                break
            for r in records:
                scanned += 1
                p = dict(r.payload or {})
                doc = p.get("document") or ""
                if needle not in doc:
                    continue
                p2 = {k: v for k, v in p.items() if k != "document"}
                documents.append(doc)
                metadatas.append(p2)
                distances.append(0.0)
                if len(documents) >= n_results:
                    break
            if offset is None:
                break
        return {"documents": [documents[:n_results]], "metadatas": [metadatas[:n_results]], "distances": [distances[:n_results]]}


def ensure_qdrant_collection(client: Any, name: str, dim: int) -> None:
    from qdrant_client.models import Distance, VectorParams

    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def qdrant_upsert_points(
    client: Any,
    collection_name: str,
    documents: List[str],
    vectors: List[List[float]],
    metadatas: List[Dict],
    ids: List[str],
) -> None:
    from qdrant_client.models import PointStruct

    points = []
    for i, doc in enumerate(documents):
        payload = dict(metadatas[i]) if i < len(metadatas) else {}
        payload["document"] = doc
        points.append(
            PointStruct(id=_point_id(ids[i]), vector=vectors[i], payload=payload)
        )
    client.upsert(collection_name=collection_name, points=points)


def delete_points_by_files(client: Any, collection_name: str, file_paths: List[str]) -> None:
    """Remove all points whose payload field `file` matches one of the paths."""
    if not file_paths:
        return
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    should = [FieldCondition(key="file", match=MatchValue(value=fp)) for fp in file_paths]
    try:
        client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=Filter(should=should)),
        )
    except Exception as exc:
        logger.debug("delete_points_by_files %s: %s", collection_name, exc)


def rebuild_unified_collection(storage_path: str | None = None, verbose: bool = True) -> int:
    """
    Merge every repo_* collection into unified_code (same vectors + payloads).
    Returns point count in unified_code, or 0 if nothing merged.
    """
    from pathlib import Path

    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from src.ai.vector_backend import vector_db_path

    p = storage_path or vector_db_path()
    Path(p).mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=p)
    names = [c.name for c in client.get_collections().collections]
    repo_names = sorted(n for n in names if n.startswith("repo_"))
    if not repo_names:
        if verbose:
            print("  No repo_* collections found under", p)
        return 0

    records, _ = client.scroll(
        collection_name=repo_names[0], limit=1, with_vectors=True, with_payload=True
    )
    if not records:
        if verbose:
            print(f"  First collection {repo_names[0]} is empty; cannot infer vector size.")
        return 0
    dim = len(records[0].vector or [])

    if client.collection_exists("unified_code"):
        client.delete_collection(collection_name="unified_code")
        if verbose:
            print("  Deleted old unified_code collection")
    client.create_collection(
        collection_name="unified_code",
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    total_docs = 0
    total_repos = 0
    for i, rn in enumerate(repo_names):
        repo_slug = rn.replace("repo_", "", 1)
        offset = None
        repo_chunks = 0
        while True:
            batch, offset = client.scroll(
                collection_name=rn,
                limit=256,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )
            if not batch:
                break
            points = []
            for r in batch:
                pl = dict(r.payload or {})
                doc = pl.get("document", "")
                meta = {k: v for k, v in pl.items() if k != "document"}
                meta["repo"] = repo_slug
                pl_out = dict(meta)
                pl_out["document"] = doc
                pid = _point_id(f"{rn}:{r.id}")
                points.append(PointStruct(id=pid, vector=r.vector, payload=pl_out))
            client.upsert(collection_name="unified_code", points=points)
            repo_chunks += len(points)
            total_docs += len(points)
            if offset is None:
                break
        if repo_chunks > 0:
            total_repos += 1
        if verbose and ((i + 1) % 10 == 0 or i == len(repo_names) - 1):
            print(f"  [{i+1}/{len(repo_names)}] {total_docs} chunks merged so far")

    cnt = int(client.count("unified_code", exact=True).count)
    if verbose:
        print(f"\n  ✅ Unified collection: {cnt} chunks from {total_repos} repos")
    return cnt
