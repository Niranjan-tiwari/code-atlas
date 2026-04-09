# Config files and scripts (what you actually need)

Templates live in git as **`config/*.example`**. Copy to the real name locally (usually **gitignored**). See **`.gitignore`** comments.

---

## Config directory (`config/`)

| File | Role |
|------|------|
| **`indexing_paths.json`** (from **`.example`**) | **Bulk indexing:** `base_paths` where the indexer discovers git repos. |
| **`ai_config.json`** (from **`.example`**) | **Ask / LLM / RAG** options. |
| **`config.json`** (from **`.example`**) | **Worker / Git paths:** `base_paths_config`, optional embedded `repos` / `tasks` / `notifications`. Used by `run_task.py`, `search_clickable.py`, `review_mr.py`, `ConfigLoader`. |
| **`repos_config.json`** / **`tasks_config.json`** / **`notifications_config.json`** (from **`.example`**) | Optional **split files** if you do not embed those sections in `config.json`. |
| **`skip_repos.json`** (from **`.example`**) | Skip repos during bulk index / reindex. |
| **`services_mapping.json`** (from **`.example`**) | Optional metadata (e.g. service inventory); edit by hand if you use it. |

**Minimum for search only:** `indexing_paths.json` + `ai_config.json` + **`.env`** (keys). Add **`config.json`** when using **`run_task.py`** or path-based search helpers.

`ConfigLoader` merges `config.json` with split files when present (`src/core/config_loader.py`).

---

## Scripts directory (`scripts/`)

### Indexing & search

| Script | Purpose |
|--------|---------|
| **`index_all_repos_resume.py`** | Bulk index under `indexing_paths`. |
| **`index_one_repo.py`** | Single repo. |
| **`index_remaining.py`** | Only repos not yet in Qdrant (subprocess + timeouts). |
| **`build_unified_index.py`** | Unified Qdrant collection for cross-repo search. |
| **`reindex_with_ollama.py`** | Reindex with embedding/Ollama options. |
| **`query_code.py`** | CLI search / Ask. |
| **`start_api.py`** | HTTP API + dashboard. |
| **`search_clickable.py`**, **`explain.py`** | Extra search / explain CLIs. |

### Ops & monitoring

| Script | Purpose |
|--------|---------|
| **`indexing_healthcheck.py`**, **`indexing_diagnose.sh`** | Stuck indexer / lock checks. |
| **`monitor_indexing.sh`**, **`watch_indexing.sh`** | Live progress. |
| **`check_indexing_status.py`** | One-shot status text. |
| **`monitor_and_stop_when_done.sh`** | Wait until indexing looks done (optional). |
| **`wait_and_validate_after_index.sh`**, **`restart_indexing.sh`** | Post-index or restart bulk job. |

### Automation

| Script | Purpose |
|--------|---------|
| **`run_task.py`**, **`run_workflow.py`** | Tasks / workflows. |
| **`review_mr.py`**, **`impact_analysis.py`** | GitLab MR / impact helpers. |
| **`auto_discover_repos.py`** | Refresh `repos_config.json` from disk. |

### Setup

| Script | Purpose |
|--------|---------|
| **`verify_setup.sh`**, **`setup_api_keys.sh`**, **`setup_ollama.sh`**, **`setup_advanced_rag.sh`**, **`setup_gitlab_auth.sh`**, **`setup_ai_environment.sh`** | Install / env helpers. |
| **`check-before-github-push.sh`** | Pre-push checks. |

### Tests & smoke

| Script | Purpose |
|--------|---------|
| **`test_all_features.py`** | Broad smoke after indexing. |
| **`test_explain_api.sh`** | Curl explain endpoint. |

### Internal

| Script | Purpose |
|--------|---------|
| **`_bulk_index_single.py`** | Subprocess helper for **`index_all_repos_resume.py`**. |

### SQL

| **`sql/llm_query_cache_pgvector.sql`** | Optional Postgres cache schema (**QUERY_CONSOLE_AND_SCALE**). |

---

## Other entry points

- **`main.py`** — CLI (`python3 main.py`) → `src/cli/`.
