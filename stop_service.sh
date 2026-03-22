#!/bin/bash
# Stop Code Atlas Service

SERVICE_NAME="code-atlas.service"

echo "🛑 Stopping Code Atlas Service..."
echo ""

# Check if service exists
if systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
    echo "Service found. Stopping..."
    sudo systemctl stop "$SERVICE_NAME"
    
    if [ $? -eq 0 ]; then
        echo "✅ Service stopped successfully"
    else
        echo "❌ Failed to stop service"
        exit 1
    fi
    
    # Show status
    echo ""
    echo "Service status:"
    sudo systemctl status "$SERVICE_NAME" --no-pager | head -10
else
    echo "⚠️  Service '$SERVICE_NAME' not found"
    echo ""
    echo "Checking for running processes..."
    
    # Check for daemon processes
    DAEMON_PIDS=$(pgrep -f "daemon.py|parallel.*worker" 2>/dev/null)
    
    if [ -n "$DAEMON_PIDS" ]; then
        echo "Found running processes: $DAEMON_PIDS"
        echo "Killing processes..."
        kill $DAEMON_PIDS
        echo "✅ Processes stopped"
    else
        echo "✅ No running processes found"
    fi
fi

echo ""
echo "Done!"
