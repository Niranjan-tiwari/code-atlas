# Query console (web UI) and scaling to many repos

## LLM answer cache (Redis + pgvector)

`QueryEngine` can short-circuit before RAG + LLM:

1. **In-process LRU** — exact match on normalized question + repo / `n_context` / provider / temperature (`config/ai_config.json` → `llm_query_cache`, enabled by default).
2. **Redis** — same key, shared across API workers (`llm_query_cache.redis`, use DB slot distinct from RAG search cache if both run).
3. **PostgreSQL + pgvector** — embed the question with the same model as code indexing; cosine similarity ≥ threshold reuses a prior answer (`semantic.enabled`, `database_url` or `DATABASE_URL`). Install: `pip install psycopg2-binary pgvector`, enable `CREATE EXTENSION vector`.

Cache is **skipped** when `include_history` is true (multi-turn). Responses include `cache_hit`: `exact_l0`, `exact_redis`, or `semantic_pgvector` when served from cache.

## What ships today

- **Dashboard** at `/` (served by `scripts/start_api.py`): keyword **Search**, **Ask (RAG)** (`POST /api/query`), plus existing tabs.
- **Ask history** is stored in the browser **`localStorage`** (per machine/profile). Export/import JSON is supported for backup and migration.
- **Thread tabs** are separate chats; each thread keeps an ordered message list (your prior questions and answers in that thread).
- **API**: one lazy **`QueryEngine`** reuses the server’s **`RAGRetriever`** so embedded Qdrant is not opened twice. **`_query_lock`** serializes `/api/query` while using embedded storage (many browsers can hit the API; requests queue).

## Scaling to “millions of repos”

Embedded single-folder Qdrant is not the right target for planet-scale multi-tenant data. A practical path:

### 1. Vector tier

- Run **Qdrant as a service** (managed or self-hosted cluster). Point `QdrantClient` at **`url=`** instead of **`path=`** (requires a small adapter in this repo).
- **Shard** by tenant or by hash of `repo_id` (many collections vs few large collections — trade off: collection count limits, query fan-out).
- **Index only** what you search (language filters, path excludes, max chunk age) to control point count.

### 2. Metadata and catalog

- Keep a **registry** (Postgres/SQLite) of repos: `repo_id`, git URL, index version, embedding model id, Qdrant collection(s), last indexed commit.
- Queries first resolve **repo scope** (user selection, ACL, org) then hit vector search **only** on allowed collections or with payload filters.

### 3. Retrieval efficiency at scale

- **Two-stage retrieval**: cheap keyword/BM25 (sparse) or small embedding over a **candidate set** (recent files, owning service), then dense vector rerank on top‑K.
- **Caching**: embed query once; cache retrieval results keyed by `(query_hash, repo_set_hash, index_version)`.
- **Rate limits and quotas** per tenant on the API.

### 4. Indexing pipeline

- **Async workers** (queue) per shard; never index from the request path.
- **Incremental** updates per repo (commit diff) to avoid full reindex.
- Store **embedding model version** with vectors; bump and reindex when the model changes.

### 5. Product history (server-side)

- Replace or supplement `localStorage` with **`GET/POST /api/sessions`** backed by DB + auth, so teams share history and you can audit usage.

## Summary

| Stage | Approach |
|-------|-----------|
| Single team, one host | Embedded Qdrant + one API process + dashboard (current). |
| More concurrent queries | Qdrant server + connection pooling; optional read replicas for search-heavy workloads. |
| Huge repo count | Sharding, catalog DB, filtered retrieval, async indexing workers. |
| Shared chat history | Persist threads server-side with authentication. |
