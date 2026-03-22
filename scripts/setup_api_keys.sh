#!/bin/bash
# Setup API keys for LLM providers
# You only need at least ONE of these

echo "🔧 Setup API Keys for Code Intelligence"
echo "========================================"
echo ""
echo "You need at least ONE API key to use the LLM features."
echo "The system will use whichever providers are available."
echo ""

# Check current keys
echo "📋 Current Status:"
if [ -n "$OPENAI_API_KEY" ]; then
    echo "  ✅ OpenAI: Configured"
else
    echo "  ❌ OpenAI: Not set"
fi

if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "  ✅ Anthropic (Claude): Configured"
else
    echo "  ❌ Anthropic (Claude): Not set"
fi

if [ -n "$GEMINI_API_KEY" ]; then
    echo "  ✅ Google Gemini: Configured"
else
    echo "  ❌ Google Gemini: Not set"
fi

echo ""
echo "📝 To set API keys, add to your ~/.bashrc or ~/.zshrc:"
echo ""
echo "  # OpenAI (GPT-4, GPT-4o)"
echo "  export OPENAI_API_KEY=sk-..."
echo ""
echo "  # Anthropic (Claude)"
echo "  export ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "  # Google Gemini"
echo "  export GEMINI_API_KEY=AI..."
echo ""
echo "Then run: source ~/.bashrc"
echo ""
echo "🚀 Quick start: You can use the system without LLM keys for search-only mode:"
echo "  python3 scripts/query_code.py --search 'your query'"
echo ""
