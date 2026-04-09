# Code Atlas

**Multi-repo developer platform:** semantic code search over many Git repositories (**Qdrant** + RAG), multi-provider LLMs (OpenAI, Anthropic, Gemini, Ollama), parallel Git/GitLab task automation, REST API, and a local web dashboard.

**Self-hosting (teams):** clone on your server, configure local paths and secrets, index your clones, run the API — see **[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md)** (setup, security, every config file and env var, production hardening).

**New here?** Start with **[`docs/DEVELOPER_ONBOARDING.md`](docs/DEVELOPER_ONBOARDING.md)** — how local paths map to Qdrant indexing, and what GitHub/GitLab URLs + tokens would mean for a future “clone and index” flow.

---

## About

| | |
|--|--|
| **What it does** | Index code from multiple clones, **search & ask questions** with retrieval + optional LLM, run **batch Git operations** (branches, MRs) across repos, and expose tools via **HTTP API** (`scripts/start_api.py`). |
| **Stack** | Python 3.10+, **Qdrant** (embedded; vectors live under `data/qdrant_db`), **sentence-transformers**, LangChain-related deps, **httpx**/requests, optional **Ollama** for local models. |
| **Typical use** | Teams with **many repos** who want a **self-hosted** “ask the codebase” stack: index clones, search, optional LLM answers, optional GitLab automation. |
| **Status** | Open **framework** — copy `config/*.example` + [`.env.example`](.env.example) locally; real configs and `data/` stay **out of git** ([`.gitignore`](.gitignore), [`docs/GITHUB_PUBLISH.md`](docs/GITHUB_PUBLISH.md)). |

### GitHub “About” box (sidebar on your repo)

That short blurb is edited on GitHub, not in a file: open your repo → **⚙ Settings** → **General** → set **Description**, **Website** (optional), and **Topics**.  
Copy-paste suggestions live in [`.github/ABOUT-github-ui.md`](.github/ABOUT-github-ui.md).

---

## Quick Start

```bash
git clone <your-repo-url>
cd code-atlas   # or your clone folder name
python3 -m venv .venv && source .venv/bin/activate   # optional, recommended
pip install -r requirements.txt        # includes python-dotenv (loads `.env` for scripts/query_code.py)
pip install -r requirements-ai.txt   # Qdrant, RAG, LLM clients — required for search/index/API
```

### First-time setup & verification

1. **Dependencies** — `requirements.txt` (pytest, requests, …) + **`requirements-ai.txt`** (Qdrant, OpenAI/Anthropic clients, LangChain pieces used by RAG).
2. **Local config** (never commit secrets — see [`.gitignore`](.gitignore)):

```bash
mkdir -p logs data
cp config/config.json.example config/config.json
cp config/ai_config.json.example config/ai_config.json
cp config/notifications_config.json.example config/notifications_config.json
cp config/repos_config.json.example config/repos_config.json
cp config/indexing_paths.json.example config/indexing_paths.json
cp config/skip_repos.json.example config/skip_repos.json
cp config/services_mapping.json.example config/services_mapping.json   # optional
cp .env.example .env   # add API keys etc.; never commit
```

Edit **`config/indexing_paths.json`**: set **`base_paths`** to the parent directories of your **git clones**. Edit **`config/config.json`**: `base_path` / **`base_paths_config`** for parallel Git task automation. Full reference: **[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md)**.

3. **Verify install** (structure + smoke import + quick tests):

```bash
chmod +x scripts/verify_setup.sh
./scripts/verify_setup.sh
```

4. **Full test run** (offline-friendly; skips tests that need a live Ollama / vector index):

```bash
cd /path/to/code-atlas
PYTHONPATH=. python3 -m pytest tests/ -q \
  --ignore=tests/test_ollama_search.py \
  --ignore=tests/test_fast_search.py
```

5. **End-to-end (needs index + optional LLM)** — after indexing (see below), start the API and open the dashboard:

```bash
PYTHONPATH=. python3 scripts/start_api.py
# Browser: http://127.0.0.1:8888/  (or http://localhost:8888)
```

Put API keys in **`.env`** (copy from [`.env.example`](.env.example)); `scripts/query_code.py` loads `.env` automatically via `python-dotenv`. The API reads keys from the environment (export or your process manager).

**Publishing a fork?** [`docs/GITHUB_PUBLISH.md`](docs/GITHUB_PUBLISH.md) · **Hosting for your team?** [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) · **systemd:** `code-atlas.service.example` (daemon), `code-atlas-search-api.service.example` (search API).

### Index Your Repos

```bash
# Discover all Git repos
python3 scripts/auto_discover_repos.py

# Index code into vector DB (one-time / resume)
PYTHONPATH=. python3 scripts/index_all_repos_resume.py

# Build unified index (fast search)
python3 scripts/build_unified_index.py

# Reindex with bge-small embeddings (faster than default)
python3 scripts/reindex_with_ollama.py

# Skip stuck/problematic repos
python3 scripts/reindex_with_ollama.py --resume --timeout 300
python3 scripts/reindex_with_ollama.py --skip-file config/skip_repos.json
python3 scripts/reindex_with_ollama.py --skip-repos huge-repo,legacy-monolith
python3 scripts/reindex_with_ollama.py --max-chunks 5000   # skip repos with >5000 chunks
```

### Start the API + Web Dashboard

Always use the repo root on `PYTHONPATH` so `src.*` imports resolve:

```bash
cd /path/to/code-atlas
PYTHONPATH=. python3 scripts/start_api.py
# Optional: --host 127.0.0.1 --port 8890
```

Open **`http://127.0.0.1:8888/`** — the UI is served from [`src/api/dashboard.py`](src/api/dashboard.py) (no separate frontend build).

**Do not** run **`scripts/query_code.py`** at the same time as **`start_api.py`** against the same **`data/qdrant_db`** (embedded Qdrant allows only one process). Stop the CLI first, or use a different `QDRANT_PATH` / Qdrant server for concurrent use.

**Port already in use:** `fuser -k 8888/tcp` then retry, or `PYTHONPATH=. python3 scripts/start_api.py --port 8890`.

---

## How to Use

### 1. Code Search (CLI)

Use **`query_code.py`** (RAG / vector search; needs Qdrant index) or **`search_clickable.py`** (clickable paths in the terminal):

```bash
# Search-only (no LLM answer) — needs indexed data under data/qdrant_db
PYTHONPATH=. python3 scripts/query_code.py --search "error handling"

# Filter by repo
PYTHONPATH=. python3 scripts/query_code.py --search "payment" --repo my-service

# Interactive RAG + LLM session
PYTHONPATH=. python3 scripts/query_code.py

# Clickable paths (uses config/config.json base_path when present)
PYTHONPATH=. python3 scripts/search_clickable.py "ProcessMessage"
PYTHONPATH=. python3 scripts/search_clickable.py "redis" --repo my-service -n 10
```

### 2. Code Search (API)

```bash
# Search
curl "http://localhost:8888/api/search?q=reporting&n=5"

# List repos
curl "http://localhost:8888/api/repos"

# RAG + LLM query (needs LLM configured)
curl -X POST http://localhost:8888/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "how does error handling work in the payment service?"}'
```

### 3. Web Dashboard

Open **`http://127.0.0.1:8888/`** after starting the API. The dashboard includes:

| Area | What it does |
|------|----------------|
| **Search** | Keyword / vector search with repo & language filters (no LLM required beyond embeddings) |
| **Ask (RAG)** | Natural-language questions via `POST /api/query` — same stack as `query_code.py`; optional **thread tabs** and **browser-local history** (export/import JSON) |
| **Repos** | Indexed repositories and chunk counts |
| **Dependencies** | Cross-repo dependency scan |
| **Duplicates** | Similar code across repos |
| **Debug error** | Paste a stack trace for analysis |

`POST /api/query` responses may include **`cache_hit`** when [LLM answer caching](docs/QUERY_CONSOLE_AND_SCALE.md) is enabled in `config/ai_config.json` (`llm_query_cache`: in-process LRU, optional Redis exact match, optional PostgreSQL + pgvector semantic cache).

**Health check:** `curl -s http://127.0.0.1:8888/health`

### 4. Parallel Multi-Repo Git Tasks

Execute one task across multiple repos simultaneously:

```bash
# Branch creation across 5 repos
python3 scripts/run_task.py \
  --repos service-alpha,service-beta,service-gamma \
  --jira PROJ-1234 \
  --description "Add health check endpoint" \
  --source master \
  --branch feature/PROJ-1234-health-check \
  --base-path /path/to/your/repos \
  --branch-only

# From JSON file
python3 scripts/run_task.py --from-json tasks/example_task.json

# Interactive mode
python3 scripts/run_task.py --interactive --base-path /path/to/repos

# Dry run (preview only)
python3 scripts/run_task.py --from-json tasks/my_task.json --dry-run
```

Features: parallel execution, Jira ID in commits/MRs, GitLab MR auto-creation, pre-push validation (`go vet`, `go build`), AI code review, branch-only mode.

### 5. PR Auto-Review

Review code diffs using RAG context + LLM:

```bash
# Via API
curl -X POST http://localhost:8888/api/review \
  -H "Content-Type: application/json" \
  -d '{"diff": "+func Pay() { fmt.Println(\"pay\") }", "repo": "service-alpha"}'

# Via GitLab webhook (auto-review on MR creation)
# Set webhook URL: http://your-server:8888/api/webhook/gitlab
```

Detects: hardcoded secrets, missing error handling, `fmt.Println` usage, TODOs, and checks against existing codebase patterns.

### 6. Code Duplication Finder

Find similar code across repos using embedding similarity:

```bash
curl "http://localhost:8888/api/duplicates?threshold=0.15&n=20"
```

### 7. Cross-Repo Dependency Scanner

Scan Go modules, Python packages, Node deps across all repos:

```bash
curl "http://localhost:8888/api/deps"
```

Shows: most common dependencies, per-repo breakdown, version info.

### 8. Documentation Generator

Auto-generate docs from indexed code:

```bash
curl -X POST http://localhost:8888/api/generate-docs \
  -H "Content-Type: application/json" \
  -d '{"repo": "service-alpha"}'
```

Returns: entry points, API endpoints, data models, package list, AI summary (if LLM available).

### 9. Test Generator

Find untested functions and generate test stubs:

```bash
curl -X POST http://localhost:8888/api/generate-tests \
  -H "Content-Type: application/json" \
  -d '{"repo": "service-alpha"}'
```

Returns: tested vs untested functions, coverage %, generated Go test stubs.

### 10. Incident Debugger

Paste an error/stack trace, get the relevant code path and fix suggestions:

```bash
curl -X POST http://localhost:8888/api/debug-error \
  -H "Content-Type: application/json" \
  -d '{"error": "panic: nil pointer dereference\n  main.ProcessPayment /app/handlers/payment.go:45"}'
```

### 11. Migration Automator

Find-and-replace patterns across multiple repos:

```bash
curl -X POST http://localhost:8888/api/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "find": "fmt\\.Println",
    "replace": "log.Info",
    "file_pattern": "*.go",
    "dry_run": true
  }'
```

### 12. Cross-Repo Refactoring

Rename functions/variables across all repos:

```bash
curl -X POST http://localhost:8888/api/refactor \
  -H "Content-Type: application/json" \
  -d '{
    "type": "rename_function",
    "old_name": "GetUser",
    "new_name": "FetchUser",
    "dry_run": true
  }'
```

### 13. Auto-Reindex on Git Push (Webhook)

Set up GitLab webhook to auto-reindex repos when code is pushed:

```bash
# GitLab webhook URL: http://your-server:8888/api/webhook/gitlab
# Triggers: Push Hook -> re-indexes the repo
#           Merge Request Hook -> auto-reviews the MR
```

### 14. Slack Bot

Ask code questions from Slack:

```
@codebot search reporting
@codebot repos
@codebot deps service-alpha
@codebot help
```

Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` env vars. Webhook URL: `http://your-server:8888/api/webhook/slack`

### 15. 24/7 Agent Mode

Run as a daemon that monitors for new tasks:

```bash
./start_daemon.sh          # Start
tail -f logs/daemon.log    # View logs
./stop_service.sh          # Stop
```

---

## Configuration

### Environment Variables

```bash
# GitLab MR creation
export GITLAB_TOKEN=glpat-your-token

# LLM providers (at least one, or use Ollama) — also set in .env for local dev
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AI...

# Optional: PostgreSQL URL for pgvector semantic LLM cache (see ai_config.json llm_query_cache.semantic)
# export DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Hugging Face: higher rate limits when downloading embedding models (optional)
# export HF_TOKEN=hf_...

# Or use Ollama (local, no cloud API keys)
ollama serve
ollama pull codellama

# Slack bot (optional)
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_SIGNING_SECRET=...
```

### Config Files

| File | Purpose |
|------|---------|
| `config/config.json` | Main config: work mode, base path, notifications, security |
| `config/repos_config.json` | Repository list (auto-discovered) |
| `config/tasks_config.json` | Task definitions |
| `config/ai_config.json` | LLM providers, models, fallback chain, RAG/latency, optional **`llm_query_cache`** (exact + semantic answer cache) |

### LLM Fallback Chain

Order and providers are defined in **`config/ai_config.json`** (`llm.fallback_chain`, per-provider `enabled` flags). Point at least one provider at a real API key or enable a local **Ollama** model if you use it.

### Reranker (Env Vars)

| Var | Values | Default |
|-----|--------|---------|
| `RERANKER` | `flashrank` \| `bge` \| `simple` | `flashrank` |
| `FLASHRANK_MODEL` | `ms-marco-TinyBERT-L-2-v2` (~4MB, fastest) \| `ms-marco-MiniLM-L-12-v2` (~34MB, best) | TinyBERT |

FlashRank runs on CPU with no PyTorch; use `ms-marco-MiniLM-L-12-v2` for higher quality.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web Dashboard |
| GET | `/health` | Health check |
| GET | `/api/search?q=` | Code search |
| GET | `/api/repos` | List indexed repos |
| GET | `/api/duplicates` | Find code duplicates |
| GET | `/api/deps` | Dependency scanner |
| POST | `/api/query` | RAG + LLM query (`cache_hit`, `latency_seconds` when cached) |
| POST | `/api/review` | AI code review |
| POST | `/api/migrate` | Migration automator |
| POST | `/api/refactor` | Refactoring engine |
| POST | `/api/generate-docs` | Documentation generator |
| POST | `/api/generate-tests` | Test generator |
| POST | `/api/debug-error` | Incident debugger |
| POST | `/api/reindex` | Re-index a repo |
| POST | `/api/webhook/gitlab` | GitLab push/MR webhook |
| POST | `/api/webhook/slack` | Slack events webhook |

---

## Project Structure

```
code-atlas/
  src/
    core/           # Git worker, models, logger, GitLab API, validator
    ai/             # RAG, LLM providers, embeddings, chunking, search
    api/            # REST API server; embedded HTML UI (`dashboard.py`)
    tools/          # All 12 tools (search, review, migrate, debug, etc.)
    cli/            # CLI interface
    notifications/  # Slack, WhatsApp
  scripts/          # CLI scripts (search, index, run_task, start_api)
  config/           # JSON config files
  data/qdrant_db/   # Qdrant vector database (embedded, on-disk)
  tasks/            # Example task JSON files
```

---

## Testing

```bash
# Automated unit / workflow tests (recommended CI gate)
PYTHONPATH=. python3 -m pytest tests/ -q \
  --ignore=tests/test_ollama_search.py \
  --ignore=tests/test_fast_search.py

# Broader feature script (may need API / env)
PYTHONPATH=. python3 scripts/test_all_features.py

# Quick search smoke (needs Qdrant index built first)
PYTHONPATH=. python3 scripts/query_code.py --search "reporting" --list-repos
```

---

## Requirements

- **Python 3.10+** recommended (3.8+ may work; CI is tested on modern 3.x)
- **Git** installed and configured
- **Qdrant** and RAG stack: `pip install -r requirements-ai.txt` (or `requirements-query.txt` for a smaller set)

**Indexing:** set your workspace roots in **`config/indexing_paths.json`** (copy from `config/indexing_paths.json.example`; file is gitignored) or set **`CODE_ATLAS_INDEX_PATHS`**. Then:

1. `pip install -r requirements-query.txt` (or `requirements-ai.txt`)
2. `PYTHONPATH=. python3 scripts/index_all_repos_resume.py` — bulk index all git repos under those folders (optional: `--build-unified`), **or** `PYTHONPATH=. python3 scripts/index_one_repo.py --repo <folder> --base-path <workspace>` per repo
3. `PYTHONPATH=. python3 scripts/build_unified_index.py` — build `unified_code` for faster search
4. `PYTHONPATH=. python3 scripts/query_code.py --stats` — verify
- **Optional local LLM**: Ollama (`ollama serve` + model of your choice, e.g. `codellama`)
- **API keys** (optional): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — see `scripts/setup_api_keys.sh`

---

## Docs

- **`docs/DEVELOPER_ONBOARDING.md`** — **Start here for new developers:** local clones → `indexing_paths` → Qdrant, tokens for private Git (future URL-based flow)
- **`docs/CONFIG_AND_SCRIPTS.md`** — Which **`config/*.json`** files matter and which **`scripts/`** entry points are for indexing, search, ops, and automation
- **`docs/SELF_HOSTING.md`** — **Teams / production:** install, security, all config files & env vars, indexing, API, production hardening
- **`docs/QUERY_CONSOLE_AND_SCALE.md`** — Web Ask UI, LLM answer cache (LRU / Redis / pgvector), scaling notes
- `docs/GITHUB_PUBLISH.md` — Safe open-source push checklist
- `ARCHITECTURE_DIAGRAM.md` — System architecture diagrams
- `docs/COMPLETE_TECHNICAL_GUIDE.md` — Libraries, algorithms, models (Qdrant-centric)
- **`AGENTS.md`** — Short orientation for contributors and automation (optional [`.cursor/rules/`](.cursor/rules/) for Cursor)
