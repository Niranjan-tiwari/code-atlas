#!/bin/bash
# Monitor indexing and stop service when complete

cd "$(dirname "$0")/.."

echo "🔍 Starting Indexing Monitor"
echo "============================"
echo ""
echo "Will monitor until indexing completes, then stop service"
echo "Press Ctrl+C to stop monitoring early"
echo ""

# Function to check indexing status
check_status() {
    python3 scripts/check_indexing_status.py 2>&1 | head -30
}

# Function to check if indexing is complete
is_complete() {
    local status=$(python3 scripts/check_indexing_status.py 2>&1 | grep -E "Progress:|Total repos indexed")
    local progress=$(echo "$status" | grep "Progress:" | grep -oE "[0-9]+/80" | cut -d'/' -f1)
    local total=$(echo "$status" | grep "Progress:" | grep -oE "[0-9]+/80" | cut -d'/' -f2)
    
    if [ -z "$progress" ] || [ -z "$total" ]; then
        echo "0"
        return
    fi
    
    if [ "$progress" -ge "$total" ]; then
        echo "1"
    else
        echo "0"
    fi
}

# Function to check if indexing process is running
is_running() {
    if pgrep -f "index_all_repos_resume" > /dev/null; then
        echo "1"
    else
        echo "0"
    fi
}

# Function to stop service
stop_service() {
    echo ""
    echo "🛑 Stopping service..."
    
    # Stop daemon service if exists
    if [ -f "./scripts/stop_service.sh" ]; then
        ./scripts/stop_service.sh 2>/dev/null
    fi
    
    # Stop any daemon processes
    pkill -f "daemon.py" 2>/dev/null
    pkill -f "src.cli.daemon" 2>/dev/null
    
    # Wait a moment
    sleep 2
    
    # Verify stopped
    if ! pgrep -f "daemon.py" > /dev/null; then
        echo "✅ Service stopped"
    else
        echo "⚠️  Some processes may still be running"
    fi
}

# Main monitoring loop
iteration=0
while true; do
    clear
    echo "🔍 INDEXING MONITOR - Iteration $iteration"
    echo "=========================================="
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # Check if indexing process is running
    if [ "$(is_running)" = "1" ]; then
        echo "✅ Indexing process: RUNNING"
    else
        echo "⚠️  Indexing process: NOT RUNNING"
    fi
    
    echo ""
    
    # Show status
    check_status
    
    echo ""
    echo "=========================================="
    
    # Check if complete
    if [ "$(is_complete)" = "1" ]; then
        echo ""
        echo "🎉 INDEXING COMPLETE!"
        echo ""
        echo "Waiting 10 seconds for final operations..."
        sleep 10
        
        # Final status check
        echo ""
        echo "📊 Final Status:"
        check_status
        
        # Stop service
        stop_service
        
        echo ""
        echo "✅ All done! Indexing complete and service stopped."
        exit 0
    fi
    
    # Check if process stopped but not complete
    if [ "$(is_running)" = "0" ] && [ "$(is_complete)" = "0" ]; then
        echo ""
        echo "⚠️  Indexing process stopped but not complete!"
        echo "   Checking if it crashed or finished..."
        sleep 5
        
        # Check again
        if [ "$(is_running)" = "0" ]; then
            echo "   Process still not running. May have crashed."
            echo "   Check logs: tail -50 logs/indexing_bulk.log"
            echo ""
            echo "   To restart: bash scripts/restart_indexing.sh"
        fi
    fi
    
    echo ""
    echo "Refreshing in 30 seconds... (Ctrl+C to stop)"
    sleep 30
    iteration=$((iteration + 1))
done
