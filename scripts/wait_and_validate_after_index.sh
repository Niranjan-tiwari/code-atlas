#!/usr/bin/env bash
# After bulk indexing finishes: build unified_code, run pytest + test_all_features, log everything.
# Intended for overnight runs (detach from terminal):
#   nohup ./scripts/wait_and_validate_after_index.sh &
#   setsid -f ./scripts/wait_and_validate_after_index.sh </dev/null >/dev/null 2>&1
#
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="$ROOT/logs/nightly_validate.log"

exec >>"$LOG" 2>&1

echo "================================================================================"
echo "nightly validate started $(date -Iseconds)"
echo "ROOT=$ROOT"
echo "================================================================================"

wait_for_indexers() {
  while true; do
    # Broad patterns (match argv with or without "scripts/" prefix)
    if pgrep -af "index_all_repos_resume" 2>/dev/null | grep -v pgrep | grep -q python; then
      echo "$(date -Iseconds) waiting: index_all_repos_resume still running"
      sleep 90
      continue
    fi
    if pgrep -af "_bulk_index_single" 2>/dev/null | grep -v pgrep | grep -q python; then
      echo "$(date -Iseconds) waiting: _bulk_index_single still running"
      sleep 30
      continue
    fi
    break
  done
  echo "$(date -Iseconds) no bulk indexer processes found — proceeding"
}

wait_for_indexers

export PYTHONPATH="$ROOT"
# Qdrant local DB must be free before we open it again
sleep 5

BUILD_EC=0

echo ""
echo "=== verify_setup.sh (deps / layout) ==="
if [[ -x scripts/verify_setup.sh ]]; then
  ./scripts/verify_setup.sh || echo "(verify_setup had warnings)"
else
  chmod +x scripts/verify_setup.sh 2>/dev/null && ./scripts/verify_setup.sh || true
fi

echo ""
echo "=== build_unified_index.py (required for duplication tests) ==="
python3 scripts/build_unified_index.py || BUILD_EC=$?

echo ""
echo "=== indexing_healthcheck.py ==="
python3 scripts/indexing_healthcheck.py || true

echo ""
echo "=== pytest (unit / workflow) ==="
PYTEST_EC=0
python3 -m pytest tests/ -q \
  --ignore=tests/test_ollama_search.py \
  --ignore=tests/test_fast_search.py \
  --tb=short || PYTEST_EC=$?

echo ""
echo "=== test_all_features.py (needs Qdrant + optional unified) ==="
FEAT_EC=0
python3 scripts/test_all_features.py || FEAT_EC=$?

echo ""
echo "=== query_code.py --stats ==="
python3 scripts/query_code.py --stats || true

echo ""
echo "================================================================================"
echo "nightly validate finished $(date -Iseconds)"
echo "build_unified exit=$BUILD_EC  pytest exit=$PYTEST_EC  test_all_features exit=$FEAT_EC"
echo "Full log: $LOG"
echo "================================================================================"

exit $(( BUILD_EC != 0 || PYTEST_EC != 0 || FEAT_EC != 0 ))
