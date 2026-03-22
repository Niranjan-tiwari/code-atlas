#!/bin/bash
# Setup script for Advanced RAG features

echo "🚀 Setting up Advanced RAG Dependencies..."
echo ""

# Install Python dependencies
echo "📦 Installing Python packages..."
pip install tree-sitter sentence-transformers

# Build tree-sitter languages
echo ""
echo "🌳 Building tree-sitter languages..."
echo "This may take a few minutes..."

# Create build directory
mkdir -p build/tree-sitter-languages
cd build/tree-sitter-languages

# Clone tree-sitter language repositories
echo "  Cloning tree-sitter-go..."
git clone https://github.com/tree-sitter/tree-sitter-go.git 2>/dev/null || echo "  Already cloned"

echo "  Cloning tree-sitter-python..."
git clone https://github.com/tree-sitter/tree-sitter-python.git 2>/dev/null || echo "  Already cloned"

echo "  Cloning tree-sitter-javascript..."
git clone https://github.com/tree-sitter/tree-sitter-javascript.git 2>/dev/null || echo "  Already cloned"

echo "  Cloning tree-sitter-java..."
git clone https://github.com/tree-sitter/tree-sitter-java.git 2>/dev/null || echo "  Already cloned"

# Build languages (requires tree-sitter CLI)
echo ""
echo "  Building language parsers..."
python3 << 'PYTHON'
from tree_sitter import Language

try:
    Language.build_library(
        'build/my-languages.so',
        [
            'build/tree-sitter-languages/tree-sitter-go',
            'build/tree-sitter-languages/tree-sitter-python',
            'build/tree-sitter-languages/tree-sitter-javascript',
            'build/tree-sitter-languages/tree-sitter-java',
        ]
    )
    print("✅ Language parsers built successfully")
except Exception as e:
    print(f"⚠️  Could not build parsers: {e}")
    print("   You can use regex-based chunking as fallback")
PYTHON

cd ../..

echo ""
echo "✅ Advanced RAG setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Test AST chunking: python3 -c 'from src.ai.chunking import ASTChunker; print(\"OK\")'"
echo "2. Test reranking: python3 -c 'from src.ai.reranking import Reranker; print(\"OK\")'"
echo "3. Test HyDE: python3 -c 'from src.ai.hyde import HyDEExpander; print(\"OK\")'"
echo ""
echo "💡 Note: Some features require LLM API keys:"
echo "   - HyDE: Needs OPENAI_API_KEY or ANTHROPIC_API_KEY"
echo "   - Deep Context: Needs LLM for architectural summaries"
