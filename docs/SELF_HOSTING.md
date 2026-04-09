# Self-hosting Code Atlas — setup, security, and configuration

This guide is for **teams** who clone Code Atlas, run it on **their own server**, point it at **their Git repositories**, index code into **Qdrant**, and use the **REST API + dashboard** to search and ask questions. It also covers **what must never be committed** when you publish a fork on GitHub.

---

## Table of contents

1. [Architecture (5-minute mental model)](#1-architecture-5-minute-mental-model)
2. [Security model and leak prevention](#2-security-model-and-leak-prevention)
3. [Prerequisites](#3-prerequisites)
4. [First-time install](#4-first-time-install)
5. [Configuration files](#5-configuration-files)
6. [Environment variables](#6-environment-variables)
7. [Feeding your repositories](#7-feeding-your-repositories) (local paths today; [onboarding](DEVELOPER_ONBOARDING.md) for URLs + tokens)
8. [Indexing pipeline](#8-indexing-pipeline)
9. [Running the API and dashboard](#9-running-the-api-and-dashboard)
10. [Production hardening](#10-production-hardening)
11. [GitLab and Slack hooks](#11-gitlab-and-slack-hooks)
12. [Operations and backups](#12-operations-and-backups)
13. [Troubleshooting](#13-troubleshooting)
14. [Publishing your fork on GitHub (maintainers)](#14-publishing-your-fork-on-github-maintainers)

---

## 1. Architecture (5-minute mental model)

| Layer | Role |
|--------|------|
| **Your clones** | Normal `git clone` directories on disk (one or more “workspace” roots). |
| **Indexer** | Walks those trees, chunks code, embeds, writes vectors to **Qdrant** (embedded, on-disk under `data/qdrant_db` by default). |
| **Optional `unified_code` collection** | Merged view of all `repo_*` collections for faster retrieval (build script). |
| **Search API** | `scripts/start_api.py` — HTTP server + HTML dashboard; loads Qdrant and optional LLMs for `/api/query`, explain, review, etc. |
| **Git / GitLab automation** | Separate path: `config/config.json`, `GITLAB_TOKEN`, `scripts/run_task.py` — optional for your workflow. |

There is **no multi-tenant isolation** inside one process: whoever can reach the API can query whatever is indexed. Treat the deployment as **one trust boundary per team / VPC**.

---

## 2. Security model and leak prevention

### 2.1 What must never be in Git

| Category | Examples | Mitigation |
|----------|-----------|------------|
| **API keys & tokens** | OpenAI, Anthropic, Gemini, Groq, GitLab PAT, Slack webhooks | Environment variables or a secret manager; use `.env` locally (gitignored). |
| **Paths that identify your org** | `/home/…/company-repos/…` | `config/indexing_paths.json` (gitignored) or `CODE_ATLAS_INDEX_PATHS`. |
| **Lists of internal repos / URLs** | `repos_config.json`, `services_mapping.json` | Gitignored; commit only `*.example` files. |
| **Vector database** | `data/qdrant_db` | Gitignored; may embed proprietary source. |
| **Logs** | `logs/*.log` | May contain queries and paths; gitignored. |

See root **`.gitignore`** (comments at top) and **`docs/GITHUB_PUBLISH.md`**. Run **`./scripts/check-before-github-push.sh`** before pushing a fork.

### 2.2 Network exposure

- Default API bind is **`0.0.0.0:8888`** — reachable from other machines on the network. For servers, prefer **`--host 127.0.0.1`** and a reverse proxy (nginx, Caddy) with **TLS** and **authentication**.
- The API sets **`Access-Control-Allow-Origin: *`** on JSON responses — fine for local dev; in production, put **one origin** behind your proxy or extend the app to restrict CORS.
- **Webhooks** (`/api/webhook/gitlab`, `/api/webhook/slack`) accept POST bodies **without built-in shared-secret verification** in all paths — restrict by **firewall**, **private network**, **reverse proxy token**, or GitLab “secret token” validation if you add it in code.

### 2.3 Principle of least privilege

- **GitLab token**: scope minimally (e.g. `api` for MR automation only if needed).
- **LLM keys**: separate project/key per environment; rotate if ever leaked.
- Run the Linux service as a **dedicated user** with read-only access to clone directories if possible.

---

## 3. Prerequisites

- **Python 3.10+** (3.11+ recommended).
- **Git** on the server that runs indexing (same machine as clones, or NFS-mounted paths).
- **Disk**: plan for clones + Qdrant (often **many GB** for large monorepos).
- **RAM**: embedding models load into memory; **8 GB+** comfortable for `bge-small`; more for parallel reindex workers.
- **Optional**: **Ollama** or cloud LLM keys for natural-language answers (search works with embeddings alone).

---

## 4. First-time install

```bash
git clone https://github.com/YOUR_ORG/code-atlas.git
cd code-atlas
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ai.txt
mkdir -p logs data
```

Copy **all** local config templates (adjust paths and enable flags as needed):

```bash
cp config/config.json.example config/config.json
cp config/ai_config.json.example config/ai_config.json
cp config/notifications_config.json.example config/notifications_config.json
cp config/repos_config.json.example config/repos_config.json
cp config/indexing_paths.json.example config/indexing_paths.json
cp config/skip_repos.json.example config/skip_repos.json
cp config/services_mapping.json.example config/services_mapping.json
cp .env.example .env
# Edit .env and JSON files — do not commit them.
```

Smoke check:

```bash
chmod +x scripts/verify_setup.sh
./scripts/verify_setup.sh
```

---

## 5. Configuration files

All paths are under **`config/`** unless noted. **Committed examples** use the `*.example` suffix; **real files** are listed in **`.gitignore`**.

| File | Purpose |
|------|---------|
| **`config.json`** | Work mode, `base_path` / `base_paths_config` (for Git worker & discovery), `max_workers`, `notifications` block, `security` / rate limit flags. |
| **`ai_config.json`** | LLM provider toggles, models, RAG chunking, `vector_db` hints. Prefer **`${ENV_VAR}`** placeholders for keys; actual secrets in **environment**. |
| **`indexing_paths.json`** | **`base_paths`**: list of directories whose **immediate subfolders** with `.git` are indexed. Primary knob for “where our clones live”. |
| **`repos_config.json`** | Explicit repo list (name, `local_path`, `gitlab_url`, branch) when not relying only on auto-discovery. |
| **`notifications_config.json`** | Slack / WhatsApp toggles and non-secret settings (webhooks still better in env). |
| **`skip_repos.json`** | Folder names to skip during bulk indexing. |
| **`services_mapping.json`** | Optional systemd ↔ repo mapping for discovery scripts. |
| **`.env`** | Shell-style `KEY=value` for secrets; load with `set -a; source .env; set +a` before starting Python, or use `EnvironmentFile` in systemd. |

**`base_paths_config`** in `config.json` (array of `{ "path", "default_branch" }`) drives default branch selection for **parallel Git tasks**, not for Qdrant directly. Indexing uses **`indexing_paths.json`** or **`CODE_ATLAS_INDEX_PATHS`**.

---

## 6. Environment variables

| Variable | Used for |
|----------|-----------|
| **`OPENAI_API_KEY`** | OpenAI chat/embeddings where configured. |
| **`ANTHROPIC_API_KEY`** | Claude. |
| **`GEMINI_API_KEY`** | Google Gemini. |
| **`GROQ_API_KEY`** | Groq provider. |
| **`GITLAB_TOKEN`** | GitLab API (MRs, projects). |
| **`SLACK_WEBHOOK_URL`** | Incoming webhook notifications. |
| **`SLACK_BOT_TOKEN`**, **`SLACK_SIGNING_SECRET`** | Slack app / events. |
| **`CALLMEBOT_API_KEY`**, **`WHATSAPP_WEBHOOK_URL`** | WhatsApp notifier paths. |
| **`QDRANT_PATH`** | Override Qdrant on-disk directory (default `./data/qdrant_db`). |
| **`CODE_ATLAS_INDEX_PATHS`** | Colon- or comma-separated list; overrides `indexing_paths.json` when set. |
| **`REPOS_BASE_PATH`** | Extra root for webhook repo lookup (see `auto_reindexer`). |
| **`EMBED_MODEL`** | e.g. `bge-small` for sentence-transformers indexing. |
| **`INDEX_REPO_TIMEOUT_SEC`** | Per-repo timeout for subprocess indexing / reindex. |
| **`INDEX_BULK_IN_PROCESS`** | Set to `1` / `true` so bulk indexing runs **in-process**: embedding model loads **once** (much faster on large farms). Default: one subprocess per repo (hard timeout kills stuck repos). Same as `python3 scripts/index_all_repos_resume.py --no-subprocess`. |
| **`INDEX_HEALTH_STALE_MINUTES`** | Used by `scripts/indexing_healthcheck.py` (default `20`). |
| **`RERANKER`**, **`FLASHRANK_MODEL`** | Reranking behavior. |
| **`LANGCHAIN_API_KEY`** | LangSmith / tracing if enabled in `ai_config.json`. |
| **`SKIP_LLM`** | Non-empty → some tools skip remote LLM (tests / air-gapped). |

See **`.env.example`** for a paste-friendly list.

---

## 7. Feeding your repositories

### 7.1 Supported model today (local paths → Qdrant)

Code Atlas indexes **directories on disk** that contain a **`.git`** folder. The vector store is **Qdrant** (embedded under `data/qdrant_db` by default). Routine indexing does **not** call GitHub/GitLab APIs to clone for you.

Standard pattern:

1. Create one or more **workspace directories** (e.g. `/srv/code/workspaces/{team-a,team-b,…}`).
2. **`git clone`** each repository under the appropriate workspace (same layout you use today). For **private** repos, use SSH keys or HTTPS with a **Personal Access Token** in the clone URL (or credential helper) — same as normal Git.
3. List those workspace roots in **`config/indexing_paths.json`** → **`base_paths`**.

Clones must be **on disk** on the machine that runs the indexer (or on shared storage mounted there). Update remotes and **`git pull`** on your schedule; re-run indexing or incremental reindex as needed.

### 7.2 “Paste a GitHub / GitLab URL” (not built-in yet)

Many users want to **paste a repo URL** and have Code Atlas **clone then index** automatically. That would require:

- A **clone target directory** (cache) on the server.
- For private repositories: a **GitHub PAT** (`repo` / fine-grained read) or **GitLab token** (`read_repository`, etc.) — **never** committed; use `.env` or a secret manager.

Until a dedicated workflow ships, use **§7.1**: clone with normal Git, then point **`base_paths`** at the parent of your clones. See **[`docs/DEVELOPER_ONBOARDING.md`](DEVELOPER_ONBOARDING.md)** for the full onboarding story and token guidance.

---

## 8. Indexing pipeline

**Recommended path for teams** (simple chunking + resume + subprocess timeouts):

```bash
cd /path/to/code-atlas
source .venv/bin/activate
export PYTHONPATH=.
# Optional: export CODE_ATLAS_INDEX_PATHS=/ws1:/ws2
python3 scripts/index_all_repos_resume.py
# Optional after bulk index:
python3 scripts/build_unified_index.py
python3 scripts/query_code.py --stats
```

**Alternative** (AST-heavy, parallel workers, optional incremental hashes):

```bash
export PYTHONPATH=.
python3 scripts/reindex_with_ollama.py --resume --workers 4
```

**Single repo**:

```bash
export PYTHONPATH=.
python3 scripts/index_one_repo.py --repo MY_REPO_FOLDER --base-path /path/to/workspace
```

Collections are named **`repo_<workspaceDir>_<repoFolder>`** when the base path exists, so duplicate folder names under different roots do not collide.

**Health check** (running PIDs, Qdrant counts, log freshness):

```bash
PYTHONPATH=. python3 scripts/indexing_healthcheck.py
PYTHONPATH=. python3 scripts/indexing_healthcheck.py --strict   # exit 1 if log stale while workers run
```

`scripts/monitor_indexing.sh` runs the health check automatically.

**Bulk indexing looks “stuck”** — often it is still working (one large repo, embedding batches, or **subprocess mode reloading the model per repo**). Run **`./scripts/indexing_diagnose.sh`** for PIDs, last log lines, and a short checklist. **Resume** is safe: re-run the same indexer command; repos whose Qdrant collection already has points are **skipped**. For fewer long pauses between repos, use in-process mode: **`INDEX_BULK_IN_PROCESS=1 python3 scripts/index_all_repos_resume.py --no-subprocess`** (single embedding load). If another process holds Qdrant’s writer lock, upserts block — **`python3 scripts/indexing_healthcheck.py --strict`** surfaces that.

---

## 9. Running the API and dashboard

```bash
cd /path/to/code-atlas
source .venv/bin/activate
export PYTHONPATH=.
export QDRANT_PATH=./data/qdrant_db   # if non-default
python3 scripts/start_api.py --host 0.0.0.0 --port 8888
```

- Dashboard: **`http://SERVER:8888/`**
- Health: **`GET /health`**
- Search: **`GET /api/search?q=...`**
- RAG + LLM: **`POST /api/query`** with JSON body `{"query":"..."}` (requires LLM configuration)

For **production**, prefer **`--host 127.0.0.1`** and TLS in front. Template unit: **`code-atlas-search-api.service.example`**.

---

## 10. Production hardening

1. **Systemd** — `User=` dedicated account, `EnvironmentFile=/etc/code-atlas.env` with `chmod 600`, `WorkingDirectory` set.
2. **Reverse proxy** — HTTPS only; optional Basic auth or OAuth2 at proxy; rate limits.
3. **Firewall** — only proxy → app port; no public `8888` if avoidable.
4. **Separate keys** — prod vs staging; rotate on employee exit.
5. **Backups** — snapshot **`QDRANT_PATH`** after large reindexes; document how to rebuild from clones if needed.
6. **Updates** — `git pull`, reinstall requirements if changed, reindex if chunking/embedding schema changes.

---

## 11. GitLab and Slack hooks

- Register GitLab webhook URL pointing to your server’s **`/api/webhook/gitlab`** (Push / MR as needed). Ensure the URL is not guessable or is IP-restricted.
- Slack: configure app credentials via **`SLACK_BOT_TOKEN`** / **`SLACK_SIGNING_SECRET`** and route events to **`/api/webhook/slack`**.

Treat both as **sensitive URLs**; use HTTPS and network controls.

---

## 12. Operations and backups

| Task | Command / note |
|------|----------------|
| Reindex after bulk pull | `index_all_repos_resume.py` (skips already-filled collections) or `reindex_with_ollama.py --resume` |
| Rebuild unified collection | `python3 scripts/build_unified_index.py` |
| Overnight: wait for bulk index → unified → pytest → feature script | `./scripts/wait_and_validate_after_index.sh` (log: `logs/nightly_validate.log`). Detach: `setsid -f ./scripts/wait_and_validate_after_index.sh </dev/null >/dev/null 2>&1` or `nohup ... &` |
| Disk usage | Monitor `data/qdrant_db` and clone roots |
| Logs | `logs/` — rotate or ship to your log stack |

---

## 13. Troubleshooting

| Symptom | Check |
|---------|--------|
| **0 repos in stats** | `indexing_paths.json` paths exist; clones contain `.git`; `PYTHONPATH=.` set |
| **Empty search** | Ran `build_unified_index.py` if you expect `unified_code`; or per-repo collections present |
| **OOM during index** | Lower `--workers` on `reindex_with_ollama.py`; use `index_all_repos_resume.py`; add RAM or `skip_repos.json` |
| **LLM errors** | Keys in env; `ai_config.json` provider enabled; Ollama running if using local models |
| **Wrong branch in Git tasks** | `base_paths_config` in `config.json` |
| **Indexer idle / “stuck”** | `./scripts/indexing_diagnose.sh`; tail `logs/indexing_bulk.log`; try `--no-subprocess` or check Qdrant lock (`indexing_healthcheck.py --strict`) |
| **Repo fails with exit 1, no stderr** | Often **no matching source files** (only go/py/js/ts/java by default); add **`skip_repos.json`** or extend discovery; child now emits **`ATLAS_INDEX_REASON=...`** for the parent summary |

---

## 14. Publishing your fork on GitHub (maintainers)

1. Confirm **`git status`**: no tracked `config.json`, `ai_config.json`, `indexing_paths.json`, `repos_config.json`, `.env`, or `data/`.
2. Run **`./scripts/check-before-github-push.sh`**.
3. Read **`docs/GITHUB_PUBLISH.md`** for history purge if secrets were ever committed.

---

## Related files

| Document / file | Role |
|-----------------|------|
| **[`.gitignore`](../.gitignore)** | Authoritative list of local-only paths |
| **[`GITHUB_PUBLISH.md`](GITHUB_PUBLISH.md)** | Pre-push secrets audit |
| **[`../.env.example`](../.env.example)** | Environment variable template |
| **[`../code-atlas-search-api.service.example`](../code-atlas-search-api.service.example)** | systemd unit for the search API |
| **[`../README.md`](../README.md)** | Project overview and quick links |

---

*Last updated as part of the self-hosting / framework documentation set. Adjust versions and commands to match your pinned Python and dependency versions.*
