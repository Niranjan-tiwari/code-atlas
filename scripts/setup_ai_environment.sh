#!/bin/bash
# Setup AI environment for learning

echo "🚀 Setting up AI Learning Environment..."
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python version: $python_version"

# Create directories
echo "📁 Creating directories..."
mkdir -p data/qdrant_db
mkdir -p data/embeddings
mkdir -p data/memory
mkdir -p data/audit_logs
mkdir -p logs/ai
echo "✅ Directories created"

# Install AI dependencies
echo ""
echo "📦 Installing AI dependencies (latest versions)..."
pip install -r requirements-ai.txt

# Check installations
echo ""
echo "🔍 Checking installations..."
python3 -c "import langchain; print(f'✅ LangChain: {langchain.__version__}')" 2>/dev/null || echo "❌ LangChain not installed"
python3 -c "import qdrant_client; print('✅ qdrant-client OK')" 2>/dev/null || echo "❌ qdrant-client not installed"
python3 -c "import langsmith; print(f'✅ LangSmith: {langsmith.__version__}')" 2>/dev/null || echo "❌ LangSmith not installed"
python3 -c "import openai; print(f'✅ OpenAI: {openai.__version__}')" 2>/dev/null || echo "❌ OpenAI not installed"

echo ""
echo "🎯 Next steps:"
echo "1. Get LangSmith API key: https://smith.langchain.com (free)"
echo "2. Set environment variable: export LANGCHAIN_API_KEY='your-key'"
echo "3. Set OpenAI key: export OPENAI_API_KEY='your-key'"
echo "4. Index repos: PYTHONPATH=. python3 scripts/index_all_repos_resume.py"
