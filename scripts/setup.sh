#!/bin/bash
# Setup script for Code Atlas

set -e

echo "🚀 Setting up Code Atlas..."

# Create necessary directories
mkdir -p logs
mkdir -p config

# Copy example configs if they don't exist
if [ ! -f config/repos_config.json ]; then
    echo "📋 Creating repos_config.json from example..."
    cp config/repos_config.json.example config/repos_config.json
    echo "⚠️  Please edit config/repos_config.json with your repository paths"
fi

if [ ! -f config/tasks_config.json ]; then
    echo "📋 Creating tasks_config.json from example..."
    cp config/tasks_config.json.example config/tasks_config.json
    echo "⚠️  Please edit config/tasks_config.json with your tasks"
fi

# Make scripts executable
chmod +x src/main.py

# Check Python version
python3 --version || {
    echo "❌ Python 3 is required"
    exit 1
}

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit config/repos_config.json with your repository configurations"
echo "2. Edit config/config.json with your base path"
echo "3. Run: python3 src/main.py --action status"
