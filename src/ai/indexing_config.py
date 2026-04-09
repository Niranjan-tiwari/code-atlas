"""
Where to discover Git repos for bulk indexing.

Framework model: clone GitLab (or any remote) into a base folder, then index locally.
Example: git clone https://gitlab.com/your-org/foo.git /path/to/workspace-1/foo

Priority:
  1. CODE_ATLAS_INDEX_PATHS — colon- or comma-separated absolute paths
  2. config/indexing_paths.json — { "base_paths": [ "/path", ... ] }
     (Optional "_readme" string keys are ignored by the loader.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG_CANDIDATES = (
    Path(__file__).resolve().parent.parent.parent / "config" / "indexing_paths.json",
)


def load_indexing_base_paths() -> list[str]:
    raw = os.environ.get("CODE_ATLAS_INDEX_PATHS", "").strip()
    if raw:
        sep = ":" if ":" in raw else ","
        out = [p.strip() for p in raw.split(sep) if p.strip()]
        return out

    for cfg in _CONFIG_CANDIDATES:
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            paths = data.get("base_paths") or data.get("paths")
            if isinstance(paths, list):
                return [str(Path(p).expanduser()) for p in paths if p]
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return []
