#!/bin/bash
# Quick run script for Code Atlas

set -e

echo "🚀 Code Atlas"
echo "========================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Check if setup is needed
if [ ! -f "config/repos_config.json" ]; then
    echo "⚠️  Configuration files not found. Running setup..."
    ./setup.sh
fi

# Run interactive CLI
python3 src/cli.py "$@"
