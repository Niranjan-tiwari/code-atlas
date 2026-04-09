-- Optional: PostgreSQL + pgvector for semantic LLM answer cache.
-- The app auto-creates this table on first use if semantic cache is enabled.
-- Run manually if your DB user cannot CREATE EXTENSION (use superuser once):

-- CREATE EXTENSION IF NOT EXISTS vector;

-- Table is created dynamically with the correct embedding dimension
-- (must match your sentence-transformers / EMBED_MODEL dims, e.g. 384 or 1024).
