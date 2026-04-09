"""
Qdrant local storage for Code Atlas (embedded mode, on-disk).

Environment:
  QDRANT_PATH — directory for Qdrant data (default: ./data/qdrant_db)
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VECTOR_DB_PATH = "./data/qdrant_db"


class QdrantEmbeddedLockError(RuntimeError):
    """Another process holds the exclusive lock on this embedded Qdrant directory."""


def open_embedded_qdrant_client(persist_directory: str, *, mkdir: bool = True):
    """
    Open Qdrant in embedded (path=) mode with a clear error if the directory is already locked.
    """
    from qdrant_client import QdrantClient

    root = Path(persist_directory).expanduser().resolve()
    if mkdir:
        root.mkdir(parents=True, exist_ok=True)
    path_str = str(root)
    try:
        return QdrantClient(path=path_str)
    except RuntimeError as e:
        low = str(e).lower()
        if "already accessed" in low or "concurrent access" in low:
            raise QdrantEmbeddedLockError(
                "Embedded Qdrant store is already in use by another process.\n"
                f"  Directory: {path_str}\n\n"
                "Only one process at a time may open this folder (exclusive lock).\n"
                "Stop the other process, then retry. Common cases:\n"
                "  - Another query_code.py (interactive or -q) still running\n"
                "  - Bulk indexing: index_all_repos_resume.py / index_one_repo.py\n"
                "  - API: start_api.py\n\n"
                "Hint:  pgrep -af 'query_code|index_all|start_api|VectorDB'\n\n"
                "Do not run two query commands in parallel against the same QDRANT_PATH.\n"
                "For concurrent access, use a Qdrant server and point the client at its URL."
            ) from e
        raise


def vector_db_path() -> str:
    return os.environ.get("QDRANT_PATH", DEFAULT_VECTOR_DB_PATH)


def repo_collection_slug(repo_name: str, base_path: str | None = None) -> str:
    """
    Unique slug for metadata and Qdrant collection suffix when scanning multiple roots.
    Same folder name under different parents (e.g. url-shortener) becomes distinct.
    """
    if base_path:
        p = Path(base_path)
        if p.exists():
            parent = p.name.replace(".", "_")
            return f"{parent}_{repo_name}"
    return repo_name


def repo_collection_name(repo_name: str, base_path: str | None = None) -> str:
    """Qdrant collection name, e.g. repo_workspace1_my-service."""
    return f"repo_{repo_collection_slug(repo_name, base_path)}"


def indexed_repo_slugs() -> set[str]:
    """Repo names with a non-empty repo_<name> collection."""
    p = Path(vector_db_path())
    if not p.exists():
        return set()

    client = open_embedded_qdrant_client(str(p.resolve()), mkdir=False)
    out: set[str] = set()
    for c in client.get_collections().collections:
        if not c.name.startswith("repo_"):
            continue
        if client.count(c.name, exact=True).count > 0:
            out.add(c.name.replace("repo_", "", 1))
    return out


def count_all_repo_chunks() -> int:
    """Total points across all repo_* collections."""
    p = Path(vector_db_path())
    if not p.exists():
        return 0

    client = open_embedded_qdrant_client(str(p.resolve()), mkdir=False)
    total = 0
    for c in client.get_collections().collections:
        if c.name.startswith("repo_"):
            total += client.count(c.name, exact=True).count
    return total


def list_indexed_repos_with_chunks(persist_directory: str | None = None) -> list[dict]:
    """
    List indexed repos using Qdrant only (no embedding model).
    Same shape as RAGRetriever.get_available_repos: name, collection, chunks.
    """
    root = Path(persist_directory or vector_db_path())
    if not root.exists():
        return []
    try:
        client = open_embedded_qdrant_client(str(root.resolve()), mkdir=False)
    except ModuleNotFoundError as e:
        if e.name == "qdrant_client":
            raise ImportError(
                "qdrant-client is required. Install: pip install -r requirements-query.txt"
            ) from e
        raise
    out: list[dict] = []
    for c in client.get_collections().collections:
        if not c.name.startswith("repo_"):
            continue
        n = client.count(c.name, exact=True).count
        if n > 0:
            out.append(
                {
                    "name": c.name.replace("repo_", "", 1),
                    "collection": c.name,
                    "chunks": n,
                }
            )
    out.sort(key=lambda x: x["name"])
    return out
