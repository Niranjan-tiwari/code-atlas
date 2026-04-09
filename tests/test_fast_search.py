import sys
import os
import logging

import pytest

# Add project root to path
project_root = os.path.abspath(os.path.join(os.getcwd(), '.'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_fast_search")

from src.ai.llm.manager import LLMManager
from src.ai.rag_enhanced import EnhancedRAGRetriever
from tests.qdrant_helpers import skip_if_embedded_qdrant_locked


@pytest.mark.integration
def test_fast_search():
    """Test search for 'reporting' WITHOUT slow LLM features (HyDE/DeepContext)"""
    skip_if_embedded_qdrant_locked("./data/qdrant_db")
    print("\n🔍 INITIALIZING FAST SEARCH TEST")
    print("=" * 50)

    # 1. Initialize LLM Manager
    llm = LLMManager()

    # 2. Initialize RAG (Disable heavy LLM usage)
    print("\n2. Initializing Enhanced RAG (Fast Mode)...")
    rag = EnhancedRAGRetriever(
        vector_db_path="./data/qdrant_db",
        llm_manager=llm,
        use_hyde=False,          # DISABLE HyDE for speed
        use_deep_context=False,  # DISABLE Deep Context for speed
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

    print(f"\n✅ Found {len(results)} results (Fast Mode):")
    print("-" * 50)
    for i, res in enumerate(results, 1):
        print(f"{i}. {res.get('repo')}/{res.get('file')}")
        print(f"   Score: {res.get('hybrid_score', 0):.4f}")
        print(f"   Snippet: {res.get('code', '')[:100]}...")
        print("-" * 50)

if __name__ == "__main__":
    test_fast_search()
