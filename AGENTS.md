# Code Atlas — agent notes (keep edits small)

**What it is:** Python monorepo for multi-repo **code indexing** (Qdrant embedded), **RAG + multi-provider LLM**, **parallel Git/GitLab tasks**, REST **search API**, workflows.

## Before you explore

1. Read **`.cursor/rules/project-context.mdc`** (always-on architecture).
2. For `src/ai/**`, indexing, or `scripts/query_code.py`: rules also load **`ai-rag-qdrant.mdc`** when those paths are in scope.
3. Prefer **`README.md`**, **`docs/DEVELOPER_ONBOARDING.md`**, and **`docs/SELF_HOSTING.md`** for setup. **`docs/COMPLETE_TECHNICAL_GUIDE.md`** is optional (large reference on libraries and algorithms).

## Commands (repo root)

- Tests: `PYTHONPATH=. python3 -m pytest tests/ -q`
- Interactive RAG CLI: `python3 scripts/query_code.py` (loads **`.env`** via `python-dotenv`; does not override existing env vars).
- API: `PYTHONPATH=. python3 scripts/start_api.py`

## Layout (where to look)

| Path | Role |
|------|------|
| `src/ai/` | RAG, Qdrant, embeddings, `query_engine`, LLM `manager`, `vector_backend` |
| `src/api/search_api.py` | HTTP search surface |
| `src/workflows/`, `src/core/` | Task engine, models, config loading |
| `scripts/` | CLIs: index, query, API startup, utilities |
| `config/` | JSON config; copy from `*.example`; secrets via **`.env`** |
| `tests/` | Pytest; integration tests may skip without index / env |

## Non-obvious

- **Qdrant embedded lock:** only one process should hold `data/qdrant_db`; otherwise expect lock errors — check for other `query_code` / indexer / API instances.
- **Dependencies:** `pip install -r requirements.txt` and **`requirements-ai.txt`** for vector/RAG/LLM stack.
- **Do not** commit `.env`, real `config/*.json` with secrets, or `data/`.

## Config vs scripts

See **`docs/CONFIG_AND_SCRIPTS.md`** for which `config/*.json` files you need (templates are `*.example`) and which `scripts/` tools are for indexing, search, ops, or GitLab automation.

## Project skill

Optional deeper workflow: **`.cursor/skills/code-atlas/SKILL.md`** (invoke when doing multi-file RAG or indexing changes).
