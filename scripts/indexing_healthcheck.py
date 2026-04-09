#!/usr/bin/env python3
"""
Validate bulk indexing health: processes, log freshness, Qdrant counts.

  PYTHONPATH=. python3 scripts/indexing_healthcheck.py
  PYTHONPATH=. python3 scripts/indexing_healthcheck.py --strict   # exit 1 if log stale while workers run

Environment:
  INDEX_HEALTH_STALE_MINUTES  default 20  (log silence threshold)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pgrep(pattern: str) -> list[str]:
    try:
        r = subprocess.run(
            ["pgrep", "-af", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return []
        out = [ln for ln in r.stdout.strip().split("\n") if ln.strip()]
        return [ln for ln in out if "pgrep" not in ln]
    except (OSError, subprocess.TimeoutExpired):
        return []


def _last_log_timestamp(log_path: Path) -> datetime | None:
    if not log_path.is_file():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")
    for line in reversed(lines[-400:]):
        m = pat.match(line)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Indexing health check")
    ap.add_argument("--strict", action="store_true", help="Exit 1 if log stale while indexer runs")
    args = ap.parse_args()

    os.chdir(ROOT)
    stale_min = int(os.environ.get("INDEX_HEALTH_STALE_MINUTES", "20"))

    bulk = _pgrep("index_all_repos_resume")
    child = _pgrep("_bulk_index_single")

    log_path = ROOT / "logs" / "indexing_bulk.log"
    last_ts = _last_log_timestamp(log_path)
    now = datetime.now()
    stale = False
    if last_ts:
        age_min = (now - last_ts).total_seconds() / 60.0
        stale = age_min > stale_min
        print(f"Last log line ~ {last_ts} ({age_min:.1f} min ago)")
    else:
        print("No parsable timestamp in logs/indexing_bulk.log")
        stale = True

    print()
    if bulk:
        print(f"✅ index_all_repos_resume running ({len(bulk)} match(es))")
        for ln in bulk[:3]:
            print(f"   {ln[:120]}")
    else:
        print("ℹ️  index_all_repos_resume not running")

    if child:
        print(f"✅ _bulk_index_single child running ({len(child)} match(es))")
        for ln in child[:3]:
            print(f"   {ln[:120]}")
    else:
        print("ℹ️  _bulk_index_single not running")

    print()
    sys.path.insert(0, str(ROOT))
    p = str(ROOT / "data" / "qdrant_db")
    try:
        from qdrant_client import QdrantClient

        from src.ai.vector_backend import vector_db_path

        p = vector_db_path()
        if Path(p).exists():
            client = QdrantClient(path=p)
            cols = [c.name for c in client.get_collections().collections if c.name.startswith("repo_")]
            total = sum(client.count(n, exact=True).count for n in cols)
            print(f"Qdrant {p}: {len(cols)} repo_* collections, {total} points")
        else:
            print(f"Qdrant path missing yet: {p}")
    except Exception as e:
        err = str(e).lower()
        if "already accessed" in err:
            print(
                f"Qdrant {p}: stats skipped (indexer holds the local DB lock — normal while bulk index runs)"
            )
        else:
            print(f"Qdrant stats skipped: {e}")

    print()
    print("Tail log:")
    if log_path.is_file():
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
        for line in tail:
            print(f"  {line}")
    else:
        print("  (no log file)")

    if args.strict and (bulk or child) and stale:
        print("\n❌ STRICT: log looks stale while indexer processes are running — possible stuck run.")
        print("   Fix: wait longer, or kill child PID, or use INDEX_BULK_IN_PROCESS=1 for in-process mode.")
        return 1

    if stale and (bulk or child):
        print(f"\n⚠️  Log older than {stale_min} min with workers running — verify with tail -f logs/indexing_bulk.log")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
