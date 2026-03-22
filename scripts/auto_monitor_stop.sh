#!/bin/bash
# Auto-monitor and stop when indexing completes (runs in background)

cd "$(dirname "$0")/.."

LOG_FILE="logs/monitor.log"

echo "🚀 Starting auto-monitor (background mode)"
echo "   Logs: $LOG_FILE"
echo "   Will stop service when indexing completes"
echo ""

# Run monitor in background
nohup bash scripts/monitor_and_stop_when_done.sh >> "$LOG_FILE" 2>&1 &
MONITOR_PID=$!

echo "✅ Monitor started (PID: $MONITOR_PID)"
echo ""
echo "📊 Check monitor logs:"
echo "   tail -f $LOG_FILE"
echo ""
echo "📊 Check indexing status:"
echo "   python3 scripts/check_indexing_status.py"
echo ""
echo "🛑 Stop monitor manually:"
echo "   kill $MONITOR_PID"
echo ""

# Save PID for reference
echo $MONITOR_PID > /tmp/indexing_monitor.pid
echo "Monitor PID saved to /tmp/indexing_monitor.pid"
