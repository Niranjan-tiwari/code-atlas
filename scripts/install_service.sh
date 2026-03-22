#!/bin/bash
# Install systemd service for Code Atlas

set -e

SERVICE_NAME="code-atlas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
WORK_DIR="/path/to/code-atlas"
USER="YOUR_LINUX_USER"

echo "🔧 Installing Code Atlas service..."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

# Check if work directory exists
if [ ! -d "$WORK_DIR" ]; then
    echo "❌ Work directory not found: $WORK_DIR"
    exit 1
fi

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi

# Get Python path
PYTHON_PATH=$(which python3)

echo "📋 Configuration:"
echo "   Service Name: $SERVICE_NAME"
echo "   Work Directory: $WORK_DIR"
echo "   User: $USER"
echo "   Python: $PYTHON_PATH"
echo ""

# Create service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Code Atlas Daemon
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORK_DIR
ExecStart=$PYTHON_PATH -m src.cli.daemon
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment variables
Environment="PYTHONPATH=$WORK_DIR"
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service file created: $SERVICE_FILE"
echo ""

# Reload systemd
systemctl daemon-reload
echo "✅ Systemd daemon reloaded"
echo ""

# Enable service
systemctl enable $SERVICE_NAME
echo "✅ Service enabled (will start on boot)"
echo ""

# Start service
read -p "Start service now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl start $SERVICE_NAME
    echo "✅ Service started"
    echo ""
    echo "📊 Service Status:"
    systemctl status $SERVICE_NAME --no-pager -l
else
    echo "ℹ️  Service installed but not started. Start with:"
    echo "   sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "📋 Useful commands:"
echo "   sudo systemctl start $SERVICE_NAME      # Start service"
echo "   sudo systemctl stop $SERVICE_NAME       # Stop service"
echo "   sudo systemctl restart $SERVICE_NAME    # Restart service"
echo "   sudo systemctl status $SERVICE_NAME     # Check status"
echo "   sudo journalctl -u $SERVICE_NAME -f    # View logs"
echo "   sudo systemctl disable $SERVICE_NAME    # Disable auto-start"
