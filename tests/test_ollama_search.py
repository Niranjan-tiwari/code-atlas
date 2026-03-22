import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = os.path.abspath(os.path.join(os.getcwd(), '.'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_ollama_search")

from src.ai.llm.manager import LLMManager
from src.ai.rag_enhanced import EnhancedRAGRetriever

def test_search_reporting():
    """Test search for 'reporting' with Ollama summarization"""
    print("\n🔍 INITIALIZING SEARCH TEST")
    print("="*50)

    # 1. Initialize LLM Manager (will auto-detect Ollama)
    print("\n1. Initializing AI Engine...")
    llm = LLMManager()
    
    # Check if Ollama is available
    if "ollama" not in llm.providers:
        print("❌ Ollama not found! Please run 'ollama serve' and 'ollama pull codellama'")
        return
    
    print(f"✅ AI Engine Ready. Providers: {list(llm.providers.keys())}")

    # 2. Initialize RAG
    print("\n2. Initializing Enhanced RAG...")
    rag = EnhancedRAGRetriever(
        vector_db_path="./data/vector_db",
        llm_manager=llm,
        use_hyde=True,     # Use Ollama for HyDE
        use_reranking=True,
        use_graphrag=True
    )
    
    # 3. Perform Search
    query = "reporting"
    print(f"\n3. Searching for: '{query}'")
    
    results = rag.search_code(query, n_results=5)
    
    if not results:
        print("❌ No results found. Index might be empty.")
        return

    print(f"\n✅ Found {len(results)} results:")
    for i, res in enumerate(results, 1):
        print(f"  {i}. {res.get('repo')}/{res.get('file')} (Score: {res.get('hybrid_score', 0):.4f})")
    
    # 4. Generate Summary with Ollama
    print("\n4. Generating Architectural Summary with Ollama...")
    
    try:
        context_data = rag.build_context_with_deep_summary(query, n_results=5)
        summary = context_data.get('architectural_summary')
        
        print("\n📋 ARCHITECTURAL SUMMARY:")
        print("-" * 50)
        print(summary)
        print("-" * 50)
        
    except Exception as e:
        print(f"❌ Error generating summary: {e}")

if __name__ == "__main__":
    test_search_reporting()
