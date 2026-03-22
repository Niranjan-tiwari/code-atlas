#!/bin/bash
# Restart indexing with optimizations

cd "$(dirname "$0")/.."

echo "🔄 Restarting Indexing Process..."
echo ""

# Kill any existing processes
echo "Stopping any existing indexing processes..."
pkill -f "index_all_repos_resume" 2>/dev/null
sleep 2

# Check if killed
if pgrep -f "index_all_repos_resume" > /dev/null; then
    echo "⚠️  Force killing remaining processes..."
    pkill -9 -f "index_all_repos_resume" 2>/dev/null
    sleep 1
fi

# Start new process
echo "Starting optimized indexing..."
nohup python3 scripts/index_all_repos_resume.py >> logs/indexing_bulk.log 2>&1 &
PID=$!

sleep 3

# Verify it's running
if ps -p $PID > /dev/null 2>&1; then
    echo "✅ Indexing started successfully!"
    echo "   PID: $PID"
    echo ""
    echo "📊 Monitor progress:"
    echo "   tail -f logs/indexing_bulk.log"
    echo "   bash scripts/watch_indexing.sh"
    echo "   python3 scripts/check_indexing_status.py"
else
    echo "❌ Failed to start indexing process"
    echo "   Check logs/indexing_bulk.log for errors"
fi
