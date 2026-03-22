#!/usr/bin/env python3
"""
Demo: Enhanced RAG End-to-End

Shows the complete pipeline:
1. Index a repo with AST chunking
2. Search with enhanced RAG (HyDE, reranking, hybrid search)
3. Query with deep context (architectural summaries)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai.query_engine import QueryEngine
from src.ai.rag_enhanced import EnhancedRAGRetriever
from src.ai.llm.manager import LLMManager


def main():
    print("\n" + "="*70)
    print("  🚀 Enhanced RAG End-to-End Demo")
    print("="*70)
    
    # Initialize QueryEngine (automatically uses Enhanced RAG)
    print("\n1️⃣  Initializing QueryEngine with Enhanced RAG...")
    engine = QueryEngine(
        vector_db_path="./data/vector_db",
        use_enhanced_rag=True
    )
    
    print(f"   ✅ Enhanced RAG: {engine.is_enhanced}")
    
    # List repos
    repos = engine.list_repos()
    print(f"\n2️⃣  Found {len(repos)} indexed repositories")
    if repos:
        print("   Sample repos:")
        for repo in repos[:5]:
            print(f"      - {repo['name']} ({repo['chunks']} chunks)")
    
    # Test search-only (no LLM needed)
    print("\n3️⃣  Testing Enhanced Search (HyDE + Reranking + Hybrid)...")
    query = "logging"
    results = engine.search_only(query, n_results=5, language="go")
    
    print(f"   ✅ Found {len(results)} results")
    for i, result in enumerate(results[:3], 1):
        repo = result.get('repo', 'unknown')
        file = result.get('file', 'unknown')
        score = (
            result.get('rerank_score') or 
            result.get('hybrid_score') or 
            result.get('distance', 0)
        )
        print(f"      {i}. {repo}/{file} - Score: {score:.4f}")
    
    # Test full query (requires LLM)
    if engine.llm.get_available_providers():
        print("\n4️⃣  Testing Full Query with Deep Context...")
        print("   (This uses architectural summaries + LLM)")
        
        try:
            result = engine.query(
                "How does error handling work in the codebase?",
                n_context=5,
                max_tokens=500
            )
            
            print(f"\n   ✅ Answer Generated:")
            print(f"   {'─'*60}")
            print(f"   {result.answer[:300]}...")
            print(f"   {'─'*60}")
            print(f"\n   📊 Stats:")
            print(f"      Sources: {len(result.sources)}")
            print(f"      Provider: {result.provider}/{result.model}")
            print(f"      Tokens: {result.tokens_used}")
            print(f"      Cost: ${result.cost_estimate:.6f}")
            print(f"      Latency: {result.latency_seconds:.1f}s")
            
        except Exception as e:
            print(f"   ⚠️  Query failed: {e}")
            print("   (This is OK - may need API key or more indexed repos)")
    else:
        print("\n4️⃣  Full Query Test (Skipped - No LLM API keys)")
        print("   Set API keys to test:")
        print("      export OPENAI_API_KEY=sk-...")
        print("      export ANTHROPIC_API_KEY=sk-ant-...")
        print("      export GEMINI_API_KEY=AI...")
    
    # Show stats
    print("\n5️⃣  System Statistics:")
    stats = engine.get_stats()
    print(f"   Repos indexed: {stats['repos_indexed']}")
    print(f"   Total chunks: {stats['total_chunks']}")
    print(f"   Queries answered: {stats['queries_answered']}")
    
    print("\n" + "="*70)
    print("  ✅ Demo Complete!")
    print("="*70)
    print("\n💡 Next steps:")
    print("   1. Index more repos: python3 scripts/index_one_repo.py")
    print("   2. Set LLM API keys for full query testing")
    print("   3. Install sentence-transformers for reranking: pip install sentence-transformers")
    print("   4. Build tree-sitter languages: ./scripts/setup_advanced_rag.sh")


if __name__ == "__main__":
    main()
