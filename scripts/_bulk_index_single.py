#!/usr/bin/env python3
"""Child process for index_all_repos_resume — killed on parent timeout (no stuck daemon threads)."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _configure_child_logging() -> None:
    """Log only to file so the parent does not treat INFO lines as errors from capture_output."""
    log_file = ROOT / "logs" / "indexing_bulk.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s - %(levelname)s - %(message)s"
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _bulk_index_single.py <repo_folder_name> <base_path>", file=sys.stderr)
        return 2
    _configure_child_logging()
    repo_name, base_path = sys.argv[1], sys.argv[2]
    from scripts.index_all_repos_resume import index_repo_robust

    return 0 if index_repo_robust(repo_name, base_path) else 1


if __name__ == "__main__":
    raise SystemExit(main())
