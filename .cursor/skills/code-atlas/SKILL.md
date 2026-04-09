---
name: code-atlas
description: >-
  Code Atlas repository — multi-repo Qdrant indexing, RAG/query_engine, LLM manager,
  search API, Git parallel tasks. Use when editing this repo’s Python, config, tests,
  or scripts; reduces re-exploration by pointing to AGENTS.md and scoped rules.
---

# Code Atlas (project skill)

## First step

Read **`AGENTS.md`** at repo root (short). Architecture detail is in **`.cursor/rules/project-context.mdc`** (always applied in Cursor).

## When changing RAG / Qdrant / query CLI / API search

Cursor loads **`.cursor/rules/ai-rag-qdrant.mdc`** when matching files are in context. Prefer:

- `vector_backend` for embedded Qdrant
- `query_engine.shutdown()` and retriever `close()` for clean lock release
- `tests/qdrant_helpers.py` for skip/lock patterns

## Verify

From repo root: `PYTHONPATH=. python3 -m pytest tests/ -q`

## Do not

- Paste or commit secrets; use **`.env`** and `*.example` configs only in git.
- Load **`docs/COMPLETE_TECHNICAL_GUIDE.md`** unless the user needs that depth.
