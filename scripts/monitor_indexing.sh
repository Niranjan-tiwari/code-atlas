#!/bin/bash
# Monitor indexing progress (Qdrant)

echo "📊 Indexing Monitor"
echo "==================="

cd "$(dirname "$0")/.." || exit 1

# Check if process is running
if pgrep -f "index_all_repos_resume" > /dev/null; then
    echo "✅ Indexing process is RUNNING"
    ps aux | grep "index_all_repos_resume" | grep python | grep -v grep | awk '{print "  PID:", $2, "CPU:", $3"%", "MEM:", $4"%"}'
else
    echo "⚠️  No indexing process found"
fi

echo ""
echo "📁 Collections in Vector DB (Qdrant):"
PYTHONPATH=. python3 -c "
from qdrant_client import QdrantClient
from src.ai.vector_backend import vector_db_path
p = vector_db_path()
client = QdrantClient(path=p)
cols = [c for c in client.get_collections().collections if c.name.startswith('repo_')]
print(f'  Total repo collections: {len(cols)}')
total = sum(client.count(c.name, exact=True).count for c in cols)
print(f'  Total documents: {total}')
"

echo ""
echo "🩺 Health check (processes + Qdrant + log age):"
PYTHONPATH=. python3 scripts/indexing_healthcheck.py 2>/dev/null || true

echo ""
echo "📝 Latest log entries:"
tail -10 logs/indexing_bulk.log 2>/dev/null || echo "  No log file found"
