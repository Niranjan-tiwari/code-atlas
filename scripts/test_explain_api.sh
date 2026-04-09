#!/bin/bash
# Test the explain API - use with: bash scripts/test_explain_api.sh
set -e
cd "$(dirname "$0")/.."

echo "1. Ensure API is running: python3 scripts/start_api.py"
echo "2. This script will test /health and /api/explain"
echo ""

echo "Testing /health..."
HEALTH=$(curl -s http://localhost:8765/health 2>/dev/null || echo '{"error":"Connection refused"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

if echo "$HEALTH" | grep -q "Connection refused\|error"; then
    echo ""
    echo "❌ API not running. Start it first:"
    echo "   python3 scripts/start_api.py"
    exit 1
fi

echo ""
echo "Testing /api/explain (this may take 60-90s if LLM is slow)..."
echo "Use: curl --max-time 120 -X POST http://localhost:8765/api/explain -H 'Content-Type: application/json' -d '{\"query\":\"how payment_service works\",\"repo\":\"payment-service\"}'"
echo ""

RESULT=$(curl -s --max-time 120 -X POST http://localhost:8765/api/explain \
  -H "Content-Type: application/json" \
  -d '{"query": "what does main do", "repo": "payment-service"}' 2>/dev/null || echo '{"error":"Request failed or timed out"}')

echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"

if echo "$RESULT" | grep -q '"explanation"'; then
    echo ""
    echo "✅ Explain API working!"
elif echo "$RESULT" | grep -q '"error"'; then
    echo ""
    echo "❌ Error from explain. Check:"
    echo "   - Ollama: ollama serve && ollama pull codellama"
    echo "   - Or set OPENAI_API_KEY / GEMINI_API_KEY"
fi
