#!/bin/bash
# Start Code Atlas Daemon

DAEMON_SCRIPT="src/cli/daemon.py"
LOG_FILE="logs/daemon.log"
PID_FILE="logs/daemon.pid"

cd "$(dirname "$0")"

# Create logs directory
mkdir -p logs

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "⚠️  Daemon already running (PID: $OLD_PID)"
        echo "   Stop it first: ./stop_service.sh"
        exit 1
    fi
fi

# Start daemon
echo "🚀 Starting Code Atlas Daemon..."
nohup python3 -m src.cli.daemon > "$LOG_FILE" 2>&1 &
DAEMON_PID=$!

# Save PID
echo $DAEMON_PID > "$PID_FILE"

# Wait a moment and check if it's still running
sleep 2
if ps -p "$DAEMON_PID" > /dev/null 2>&1; then
    echo "✅ Daemon started successfully (PID: $DAEMON_PID)"
    echo "   Logs: $LOG_FILE"
    echo "   PID file: $PID_FILE"
    echo ""
    echo "To stop: ./stop_service.sh"
    echo "To view logs: tail -f $LOG_FILE"
else
    echo "❌ Daemon failed to start"
    echo "Check logs: cat $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
