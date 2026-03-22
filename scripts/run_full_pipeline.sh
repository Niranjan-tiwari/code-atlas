#!/bin/bash
# Full pipeline: Reindex with bge-small → Build unified → Run end-to-end tests
set -e
cd "$(dirname "$0")/.."

echo "=============================================="
echo "  1. Full reindex with bge-small embeddings"
echo "=============================================="
python3 scripts/reindex_with_ollama.py \
  --skip-file config/skip_repos.json \
  --timeout 600

echo ""
echo "=============================================="
echo "  2. Build unified collection (if not done)"
echo "=============================================="
python3 scripts/build_unified_index.py

echo ""
echo "=============================================="
echo "  3. Run end-to-end tests"
echo "=============================================="
python3 scripts/test_all_features.py

echo ""
echo "=============================================="
echo "  Pipeline complete!"
echo "=============================================="
