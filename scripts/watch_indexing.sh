#!/bin/bash
# Real-time indexing progress monitor

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
    
    # Check if process is running
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
    python3 -c "
import chromadb
client = chromadb.PersistentClient(path='./data/vector_db')
collections = client.list_collections()
repo_collections = [c for c in collections if c.name.startswith('repo_')]
total_docs = sum(c.count() for c in repo_collections)
print(f'  Total Repos Indexed: {len(repo_collections)}/80')
print(f'  Total Chunks: {total_docs}')
print(f'  Progress: {len(repo_collections)/80*100:.1f}%')
" 2>/dev/null || echo "  Error checking collections"
    
    echo ""
    echo "📝 Latest Log Entries:"
    echo "--------------------------------------------------------------------------------"
    tail -15 logs/indexing_bulk.log 2>/dev/null | tail -10 || echo "  No log file found"
    
    echo ""
    echo "================================================================================"
    echo "Refreshing in 5 seconds... (Ctrl+C to exit)"
    sleep 5
done
