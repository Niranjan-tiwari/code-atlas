#!/bin/bash
# Real-time indexing progress monitor (Qdrant)

cd "$(dirname "$0")/.." || exit 1

clear
echo "🔍 INDEXING PROGRESS MONITOR"
echo "============================"
echo ""
echo "Press Ctrl+C to exit"
echo ""

while true; do
    clear
    echo "🔍 INDEXING PROGRESS MONITOR - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================================"
    echo ""

    if pgrep -f "index_all_repos_resume" > /dev/null; then
        echo "✅ Status: RUNNING"
        echo ""
        ps aux | grep "index_all_repos_resume" | grep python | grep -v grep | awk '{print "  PID:", $2, "| CPU:", $3"%", "| MEM:", $4"%"}'
    else
        echo "⚠️  Status: NOT RUNNING"
    fi

    echo ""
    echo "📊 Collections Status:"
    echo "--------------------------------------------------------------------------------"
    PYTHONPATH=. python3 -c "
from qdrant_client import QdrantClient
from src.ai.vector_backend import vector_db_path
client = QdrantClient(path=vector_db_path())
cols = [c for c in client.get_collections().collections if c.name.startswith('repo_')]
total_docs = sum(client.count(c.name, exact=True).count for c in cols)
indexed = len([c for c in cols if client.count(c.name, exact=True).count > 0])
print(f'  Total Repos Indexed: {indexed}/80')
print(f'  Total Chunks: {total_docs}')
print(f'  Progress: {indexed/80*100:.1f}%')
" 2>/dev/null || echo "  Error checking collections"

    echo ""
    echo "📝 Latest Log Entries:"
    echo "--------------------------------------------------------------------------------"
    tail -15 logs/indexing_bulk.log 2>/dev/null | tail -10 || echo "  No log file found"

    echo ""
    echo "Refreshing in 10 seconds... (Ctrl+C to exit)"
    sleep 10
done
