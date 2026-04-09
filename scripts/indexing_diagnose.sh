#!/usr/bin/env bash
# Quick checks when bulk indexing looks "stuck": processes, log freshness, Qdrant.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${CODE_ATLAS_INDEX_LOG:-$ROOT/logs/indexing_bulk.log}"

echo "=== Code Atlas indexing diagnose ==="
echo "Project: $ROOT"
echo ""

echo "--- Processes (index_all_repos_resume / _bulk_index_single / python bulk) ---"
pgrep -af "index_all_repos_resume|_bulk_index_single" 2>/dev/null || echo "(none)"
echo ""

if [[ -f "$LOG" ]]; then
  echo "--- Log: $LOG ---"
  stat -c "mtime: %y  size: %s bytes" "$LOG" 2>/dev/null || stat -f "mtime: %Sm  size: %z bytes" "$LOG" 2>/dev/null || ls -la "$LOG"
  echo "Last 8 lines:"
  tail -n 8 "$LOG"
else
  echo "--- Log not found: $LOG ---"
fi
echo ""

if command -v curl >/dev/null 2>&1; then
  QDRANT="${QDRANT_URL:-http://localhost:6333}"
  echo "--- Qdrant ($QDRANT) ---"
  if curl -sfS --max-time 3 "$QDRANT/collections" >/dev/null; then
    echo "OK: collections endpoint reachable"
  else
    echo "WARN: cannot reach $QDRANT/collections (is Qdrant up?)"
  fi
else
  echo "--- curl not installed; skip Qdrant probe ---"
fi
echo ""

echo "Why it can look stuck (not always a deadlock):"
echo "  - Subprocess mode reloads the embedding model per repo (slow between repos)."
echo "  - Large Go repos: many files → long embedding batches; log may pause on one repo."
echo "  - HF rate limits / first download: set HF_TOKEN in .env if you see hub warnings."
echo "  - Qdrant single-writer: another process holding the DB lock blocks upserts."
echo ""
echo "Resume: re-run the same command; finished repos are skipped (collection already has points)."
echo "Faster: INDEX_BULK_IN_PROCESS=1 python scripts/index_all_repos_resume.py --no-subprocess"
echo "Strict health: python scripts/indexing_healthcheck.py --strict"
