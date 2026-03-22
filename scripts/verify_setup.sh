#!/usr/bin/env bash
# Verify Code Atlas install (structure, deps, smoke import, optional pytest).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "🔍 Verifying Code Atlas setup..."
echo ""

ERRORS=0

if command -v python3 &>/dev/null; then
  echo "✅ Python: $(python3 --version)"
else
  echo "❌ python3 not found"
  ERRORS=$((ERRORS + 1))
fi

if command -v git &>/dev/null; then
  echo "✅ Git: $(git --version)"
else
  echo "❌ git not found"
  ERRORS=$((ERRORS + 1))
fi

mkdir -p logs data

for dir in src config scripts; do
  if [[ -d "$dir" ]]; then
    echo "✅ Directory: $dir/"
  else
    echo "❌ Missing directory: $dir/"
    ERRORS=$((ERRORS + 1))
  fi
done

for f in src/core/worker.py src/cli/daemon.py scripts/start_api.py scripts/query_code.py; do
  if [[ -f "$f" ]]; then
    echo "✅ File: $f"
  else
    echo "❌ Missing file: $f"
    ERRORS=$((ERRORS + 1))
  fi
done

if [[ -f config/config.json ]]; then
  echo "✅ Local config: config/config.json"
else
  echo "⚠️  config/config.json missing — copy from config/config.json.example"
fi

echo ""
echo "🧪 Smoke import (package layout)..."
if PYTHONPATH="$ROOT" python3 -c "from src.core.worker import ParallelRepoWorker; print('✅ ParallelRepoWorker import OK')"; then
  :
else
  echo "❌ Import failed (set PYTHONPATH=$ROOT or run from repo root)"
  ERRORS=$((ERRORS + 1))
fi

echo ""
echo "🧪 Optional: chromadb (after pip install -r requirements-ai.txt)..."
if PYTHONPATH="$ROOT" python3 -c "import chromadb; print('✅ chromadb OK')" 2>/dev/null; then
  :
else
  echo "⚠️  chromadb not importable — install requirements-ai.txt for RAG/indexing"
fi

echo ""
echo "🧪 Fast unit tests (no Ollama required)..."
if PYTHONPATH="$ROOT" python3 -m pytest tests/test_workflows.py tests/test_impact_analyzer.py -q --tb=no 2>/dev/null; then
  echo "✅ Core workflow / impact tests passed"
else
  echo "⚠️  pytest failed or not installed (pip install -r requirements.txt)"
fi

echo ""
if [[ "$ERRORS" -eq 0 ]]; then
  echo "✅ Structure check passed. Next:"
  echo "   pip install -r requirements.txt && pip install -r requirements-ai.txt"
  echo "   cp config/config.json.example config/config.json   # edit paths"
  echo "   ./scripts/verify_setup.sh"
  echo "   PYTHONPATH=. python3 -m pytest tests/ -q --ignore=tests/test_ollama_search.py --ignore=tests/test_fast_search.py"
else
  echo "❌ Found $ERRORS error(s)."
  exit 1
fi
