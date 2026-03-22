#!/bin/bash
# Monitor indexing progress

echo "📊 Indexing Monitor"
echo "==================="

# Check if process is running
if pgrep -f "index_all_repos_resume" > /dev/null; then
    echo "✅ Indexing process is RUNNING"
    ps aux | grep "index_all_repos_resume" | grep python | grep -v grep | awk '{print "  PID:", $2, "CPU:", $3"%", "MEM:", $4"%"}'
else
    echo "⚠️  No indexing process found"
fi

echo ""
echo "📁 Collections in Vector DB:"
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='./data/vector_db')
collections = client.list_collections()
repo_collections = [c for c in collections if c.name.startswith('repo_')]
print(f'  Total repo collections: {len(repo_collections)}')
total_docs = sum(c.count() for c in repo_collections)
print(f'  Total documents: {total_docs}')
"

echo ""
echo "📝 Latest log entries:"
tail -10 logs/indexing_bulk.log 2>/dev/null || echo "  No log file found"
