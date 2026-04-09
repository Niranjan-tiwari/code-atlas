# Developer onboarding

This page helps **new contributors and operators** understand how Code Atlas works today, how to get a first successful search, and how that relates to ideas like “paste a GitHub URL and index it.”

---

## 1. Mental model (what runs where)

| Piece | Role |
|--------|------|
| **Your repos on disk** | Normal **`git clone`** directories. Code Atlas reads **files from these paths** — it does not replace Git. |
| **Indexer** (`scripts/index_*.py`) | Walks those trees, chunks code, computes embeddings, writes vectors into **Qdrant** (embedded, on-disk, default `data/qdrant_db`). |
| **Search / Ask** | `scripts/query_code.py` or `scripts/start_api.py` loads Qdrant + embeddings and answers queries (optional LLM for natural-language answers). |

**Vector store:** **Qdrant** (embedded client, `path=` storage). The live code under `src/ai/` uses Qdrant — see `src/ai/vector_backend.py`, `src/ai/rag.py`.

---

## 2. What you configure today (local paths)

1. **Clone or copy** the repositories you care about onto the machine that will run indexing (same machine as Code Atlas, or shared storage it can read).
2. Edit **`config/indexing_paths.json`** (copy from `config/indexing_paths.json.example`) and set **`base_paths`** to one or more **parent directories**. The indexer discovers **immediate child folders** that contain a `.git` directory.
3. Optionally set **`CODE_ATLAS_INDEX_PATHS`** (colon- or comma-separated) to override `base_paths` without editing JSON.
4. Run bulk indexing (see [SELF_HOSTING.md §8](SELF_HOSTING.md#8-indexing-pipeline) or the [README](../README.md#index-your-repos)).
5. Start the API or CLI and search.

There is **no built-in “paste GitHub URL → clone → index” wizard** in the core repo yet. The supported pattern is: **clones exist on disk → point indexing at their parents → index → query**.

---

## 3. Why “just give a GitHub / GitLab URL” needs tokens

Many teams want: *enter `https://github.com/org/repo` or `https://gitlab.com/group/project`, then index.*

That flow implies:

| Requirement | Why |
|-------------|-----|
| **Clone** | Code must be fetched; for **private** repos the host must authorize you. |
| **Personal Access Token (PAT)** or **OAuth** | **GitHub**: classic PAT with `repo` (private repos) or fine-grained token with Contents read. **GitLab**: PAT or Project Access Token with `read_repository` (and API scope if you use the API). |
| **Where the token lives** | Only in **environment variables** or a secret manager — **never** in git-tracked config. See `.env.example`. |
| **Trust boundary** | Whoever runs the indexer with that token can read everything the token allows. Use least privilege and rotate tokens. |

A future first-class feature might: accept URL + token → clone into a configured cache directory → run the **same** indexing pipeline you use today. Until that ships, teams **clone with normal Git** (`git clone https://x-access-token:TOKEN@github.com/org/repo.git`) or SSH keys, then point **`indexing_paths.json`** at the parent of those clones.

---

## 4. Fastest path for a new developer

```bash
git clone <code-atlas-repo-url>
cd code-atlas
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-ai.txt
mkdir -p logs data
cp config/indexing_paths.json.example config/indexing_paths.json
cp config/ai_config.json.example config/ai_config.json
cp .env.example .env
# Edit indexing_paths.json: base_paths -> parent of your git clones
# Edit .env: at least one LLM key if you use Ask /api/query
```

Index (after your clones exist under `base_paths`):

```bash
export PYTHONPATH=.
python3 scripts/index_all_repos_resume.py
# optional: python3 scripts/build_unified_index.py
```

Try search:

```bash
python3 scripts/query_code.py --search "your term" --list-repos
```

Try the web UI:

```bash
PYTHONPATH=. python3 scripts/start_api.py
# Browser: http://127.0.0.1:8765/
```

**Do not** run `query_code.py` and `start_api.py` at the same time against the same `QDRANT_PATH` (embedded DB single-writer lock). Use one or the other, or Qdrant Server for concurrent access.

---

## 5. Where to read next

| Doc | Use when |
|-----|----------|
| **[README.md](../README.md)** | Overview, commands, API tables |
| **[SELF_HOSTING.md](SELF_HOSTING.md)** | Team deploy, security, all env vars, indexing details |
| **[QUERY_CONSOLE_AND_SCALE.md](QUERY_CONSOLE_AND_SCALE.md)** | Web Ask UI, LLM cache, scaling ideas |
| **[GITHUB_PUBLISH.md](GITHUB_PUBLISH.md)** | What not to commit before pushing a fork |
| **[CONFIG_AND_SCRIPTS.md](CONFIG_AND_SCRIPTS.md)** | Which `config/*.json` files to copy vs optional; which `scripts/` are for indexing, search, ops |

Deeper technical detail (libraries, algorithms, models): `docs/COMPLETE_TECHNICAL_GUIDE.md`.

---

## 6. Summary

- **Today:** local **paths** → **Qdrant**.  
- **Tokens:** required for **private** Git hosting when you automate clone/fetch; store in **`.env`**, not in repo.  
- **URL-only onboarding** is a **reasonable product direction**; implementation would wrap **git clone + existing indexer**, with strong secrets handling.
