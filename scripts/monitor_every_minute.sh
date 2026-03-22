#!/bin/bash
# Monitor indexing status every 1 minute

cd "$(dirname "$0")/.."

echo "🔍 Starting continuous monitoring (every 1 minute)..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
    clear
    echo "🔍 INDEXING STATUS CHECK - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================================"
    echo ""
    
    # Process status
    if pgrep -f "index_all_repos_resume" > /dev/null; then
        echo "✅ Process: RUNNING"
        ps aux | grep "index_all_repos_resume" | grep python | grep -v grep | awk '{print "   PID:", $2, "| CPU:", $3"%", "| MEM:", $4"%", "| TIME:", $10}'
    else
        echo "⚠️  Process: NOT RUNNING"
    fi
    
    echo ""
    echo "📊 Progress:"
    echo "--------------------------------------------------------------------------------"
    python3 scripts/check_indexing_status.py 2>&1 | grep -E "Progress|Total|Remaining|RUNNING|Indexed" | head -6
    
    echo ""
    echo "📝 Latest Activity (last 3 lines):"
    echo "--------------------------------------------------------------------------------"
    tail -3 logs/indexing_bulk.log 2>/dev/null || echo "   No log file"
    
    echo ""
    echo "💾 System Resources:"
    echo "--------------------------------------------------------------------------------"
    free -h | grep -E "Mem|Swap" | awk '{print "  "$0}'
    
    echo ""
    echo "📦 Vector DB Status:"
    echo "--------------------------------------------------------------------------------"
    python3 -c "
import chromadb
try:
    client = chromadb.PersistentClient(path='./data/vector_db')
    cols = [c for c in client.list_collections() if c.name.startswith('repo_')]
    indexed = len([c for c in cols if c.count() > 0])
    total_docs = sum(c.count() for c in cols)
    print(f'  Indexed: {indexed}/80 repos ({indexed/80*100:.1f}%)')
    print(f'  Total chunks: {total_docs:,}')
except Exception as e:
    print(f'  Error: {e}')
" 2>/dev/null
    
    echo ""
    echo "================================================================================"
    echo "⏰ Next check in 60 seconds... (Press Ctrl+C to stop)"
    
    sleep 60
done
