"""Helpers for tests that open embedded Qdrant on disk."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def skip_if_embedded_qdrant_locked(persist_directory: str | None = None) -> None:
    """
    Skip when another process holds the embedded Qdrant lock so pytest can run
    alongside query_code.py or indexing on the same QDRANT_PATH.

    If the store is free, open and close once so the following test can open it.
    """
    raw = persist_directory or os.environ.get("QDRANT_PATH") or "./data/qdrant_db"
    root = Path(raw).expanduser().resolve()
    if not root.exists():
        return

    from src.ai.vector_backend import QdrantEmbeddedLockError, open_embedded_qdrant_client

    try:
        client = open_embedded_qdrant_client(str(root), mkdir=False)
    except QdrantEmbeddedLockError as exc:
        pytest.skip(
            "Embedded Qdrant is locked (e.g. interactive query_code still running). "
            "Quit that session or set QDRANT_PATH to a disposable copy. "
            f"Detail: {exc}"
        )
    else:
        try:
            client.close()
        except Exception:
            pass
