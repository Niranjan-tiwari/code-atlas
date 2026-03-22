#!/bin/bash
# Cleanup old files after refactoring

echo "🧹 Cleaning up old files..."

cd "$(dirname "$0")"

# Remove old files from src/ (now in subdirectories)
rm -f src/worker.py src/models.py src/logger.py src/utils.py
rm -f src/cli.py src/daemon.py src/main.py
rm -f src/slack_notifier.py src/whatsapp_direct.py src/whatsapp_simple.py src/notifications.py

# Remove redundant markdown files (now in docs/)
# Keep only essential ones in root
rm -f QUICK_WHATSAPP_SETUP.md README_SETUP.md

echo "✅ Cleanup complete!"
echo ""
echo "Old files removed. New structure:"
echo "  - Core modules: src/core/"
echo "  - Notifications: src/notifications/"
echo "  - CLI: src/cli/"
echo "  - Scripts: scripts/"
echo "  - Tests: tests/"
echo "  - Docs: docs/"
