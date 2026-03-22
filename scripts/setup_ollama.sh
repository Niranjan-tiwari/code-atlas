#!/bin/bash
# Quick setup script for Ollama

echo "🚀 Setting up Ollama for Local LLM..."
echo ""

# Check if Ollama is installed
if command -v ollama &> /dev/null; then
    echo "✅ Ollama is installed"
    ollama --version
else
    echo "📦 Installing Ollama..."
    echo "   Visit: https://ollama.ai"
    echo "   Or run: curl -fsSL https://ollama.ai/install.sh | sh"
    echo ""
    read -p "Press Enter after installing Ollama..."
fi

# Start Ollama server (if not running)
echo ""
echo "🔍 Checking if Ollama server is running..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama server is running"
else
    echo "⚠️  Ollama server not running"
    echo "   Starting Ollama server..."
    ollama serve &
    sleep 3
    echo "✅ Ollama server started"
fi

# Check available models
echo ""
echo "📋 Available models:"
ollama list 2>/dev/null || echo "   No models pulled yet"

# Recommend pulling codellama
echo ""
echo "💡 Recommended: Pull a code model"
echo "   Run: ollama pull codellama"
echo ""
read -p "Pull codellama now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📥 Pulling codellama (this may take a few minutes)..."
    ollama pull codellama
    echo "✅ codellama ready!"
fi

# Test Ollama
echo ""
echo "🧪 Testing Ollama..."
if ollama list | grep -q codellama; then
    echo "✅ codellama is available"
    echo ""
    echo "Test query:"
    ollama run codellama "Write a Go function to handle errors" --verbose 2>&1 | head -20
else
    echo "⚠️  codellama not found"
    echo "   Pull it with: ollama pull codellama"
fi

echo ""
echo "✅ Ollama setup complete!"
echo ""
echo "💡 Usage:"
echo "   python3 scripts/query_code.py"
echo "   # Will automatically use Ollama if no API keys are set"
