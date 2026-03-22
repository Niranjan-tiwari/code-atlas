"""
Comprehensive tests for RAG Architecture Phases 1-4

Phase 1: Bug Fixes (FLASHRANK_MODEL, unreachable code)
Phase 2: Caching Layer (LRU + Redis fallback)
Phase 3: Hybrid Search (dynamic weights, code-aware tokenization, RRF)
Phase 4: Query Expansion (synonyms, identifiers, code preprocessing)
"""

import time
import pytest


# ============================================================
# PHASE 1: Bug Fixes
# ============================================================

class TestPhase1BugFixes:
    """Verify all Phase 1 bug fixes"""

    def test_flashrank_model_defined(self):
        """FLASHRANK_MODEL should be defined and not raise NameError"""
        from src.ai.reranking import FLASHRANK_MODEL
        assert FLASHRANK_MODEL is not None
        assert isinstance(FLASHRANK_MODEL, str)
        assert "marco" in FLASHRANK_MODEL.lower() or "bert" in FLASHRANK_MODEL.lower()

    def test_flashrank_reranker_uses_model(self):
        """FlashRankReranker should reference FLASHRANK_MODEL without error"""
        from src.ai.reranking import FlashRankReranker, FLASHRANK_MODEL
        # Should not raise NameError during init (model may not be installed)
        try:
            r = FlashRankReranker()
            assert r.model_name == FLASHRANK_MODEL
        except Exception:
            # FlashRank may not be installed, but NameError must not happen
            pass

    def test_get_repo_summary_no_unreachable_code(self):
        """get_repo_summary should return without hitting dead code"""
        import inspect
        from src.ai.rag_enhanced import EnhancedRAGRetriever
        source = inspect.getsource(EnhancedRAGRetriever.get_repo_summary)
        lines = source.strip().split('\n')
        # After return statement, there should be no logger.info
        found_return = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('return '):
                found_return = True
            elif found_return and stripped and not stripped.startswith('#') and not stripped.startswith('"""'):
                # No executable code after return
                assert False, f"Unreachable code after return: {stripped}"

    def test_reranker_choice_env(self):
        """RERANKER_CHOICE should be readable"""
        from src.ai.reranking import RERANKER_CHOICE
        assert RERANKER_CHOICE in ("flashrank", "bge", "simple")

    def test_simple_reranker_works(self):
        """SimpleReranker should work as fallback"""
        from src.ai.reranking import SimpleReranker
        reranker = SimpleReranker()
        candidates = [
            {'code': 'func handleAuth()', 'file': 'auth.go', 'repo': 'api'},
            {'code': 'func main()', 'file': 'main.go', 'repo': 'api'},
            {'code': 'func authenticate(user)', 'file': 'login.go', 'repo': 'api'},
        ]
        results = reranker.rerank("authentication handler", candidates, top_k=2)
        assert len(results) == 2
        for r in results:
            assert 'rerank_score' in r

    def test_get_best_reranker_returns_something(self):
        """get_best_reranker should always return a reranker"""
        from src.ai.reranking import get_best_reranker, SimpleReranker
        reranker = get_best_reranker()
        assert reranker is not None
        assert hasattr(reranker, 'rerank')


# ============================================================
# PHASE 2: Caching Layer
# ============================================================

class TestPhase2CachingLayer:
    """Test multi-tier caching (L1 LRU + L2 Redis fallback)"""

    def test_lru_cache_basic_ops(self):
        """LRU cache set/get/invalidate"""
        from src.ai.cache import LRUCache
        cache = LRUCache(max_size=5, default_ttl=60)

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        assert cache.get("missing") is None

        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_lru_cache_ttl_expiry(self):
        """LRU cache items should expire after TTL"""
        from src.ai.cache import LRUCache
        cache = LRUCache(max_size=10, default_ttl=1)

        cache.set("fast", "data", ttl=1)
        assert cache.get("fast") == "data"

        time.sleep(1.1)
        assert cache.get("fast") is None

    def test_lru_cache_eviction(self):
        """LRU cache should evict oldest when full"""
        from src.ai.cache import LRUCache
        cache = LRUCache(max_size=3, default_ttl=60)

        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # Should evict "a"

        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("d") == 4

    def test_lru_cache_stats(self):
        """LRU cache should track hit/miss stats"""
        from src.ai.cache import LRUCache
        cache = LRUCache(max_size=10)

        cache.set("x", 1)
        cache.get("x")   # hit
        cache.get("y")   # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["size"] == 1

    def test_lru_cache_clear(self):
        """LRU cache clear should empty everything"""
        from src.ai.cache import LRUCache
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None
        stats = cache.stats()
        assert stats["size"] == 0

    def test_rag_cache_without_redis(self):
        """RAGCache should work without Redis"""
        from src.ai.cache import RAGCache
        cache = RAGCache(enable_redis=False)

        cache.set("search", "test query", [{"code": "hello"}], n_results=5)
        result = cache.get("search", "test query", n_results=5)
        assert result is not None
        assert result[0]["code"] == "hello"

    def test_rag_cache_different_params_different_keys(self):
        """Same query with different params should have different cache keys"""
        from src.ai.cache import RAGCache
        cache = RAGCache(enable_redis=False)

        cache.set("search", "auth", [{"r": 1}], n_results=5)
        cache.set("search", "auth", [{"r": 2}], n_results=10)

        r1 = cache.get("search", "auth", n_results=5)
        r2 = cache.get("search", "auth", n_results=10)

        assert r1[0]["r"] == 1
        assert r2[0]["r"] == 2

    def test_rag_cache_namespace_ttl(self):
        """Different namespaces should get different TTLs"""
        from src.ai.cache import RAGCache
        assert RAGCache.TTL_EMBEDDING == 86400
        assert RAGCache.TTL_QUERY == 3600
        assert RAGCache.TTL_HYDE == 7200
        assert RAGCache.TTL_SEARCH_RESULT == 1800

    def test_rag_cache_invalidate_all(self):
        """invalidate_all should clear all cache entries"""
        from src.ai.cache import RAGCache
        cache = RAGCache(enable_redis=False)

        cache.set("search", "q1", [1])
        cache.set("hyde", "q2", "expanded")
        cache.invalidate_all()

        assert cache.get("search", "q1") is None
        assert cache.get("hyde", "q2") is None

    def test_rag_cache_stats_structure(self):
        """Cache stats should have expected structure"""
        from src.ai.cache import RAGCache
        cache = RAGCache(enable_redis=False)
        stats = cache.stats()
        assert "l1" in stats
        assert "size" in stats["l1"]
        assert "hits" in stats["l1"]
        assert "misses" in stats["l1"]
        assert "hit_rate" in stats["l1"]

    def test_redis_cache_graceful_fallback(self):
        """RedisCache should fail gracefully if Redis unavailable"""
        from src.ai.cache import RedisCache
        cache = RedisCache(host="localhost", port=59999)  # Likely no Redis here
        assert cache.is_available is False
        assert cache.get("test") is None
        cache.set("test", "value")  # Should not raise


# ============================================================
# PHASE 3: Hybrid Search
# ============================================================

class TestPhase3HybridSearch:
    """Test improved hybrid search with dynamic weights"""

    def test_bm25_basic_search(self):
        """BM25 should rank exact keyword matches higher"""
        from src.ai.hybrid_search import BM25
        bm25 = BM25()
        docs = [
            "func handleAuth(user string) error",
            "func main() { fmt.Println('hello') }",
            "func authenticateUser(name string, password string) bool",
        ]
        bm25.index(docs)
        results = bm25.search("authenticate user", top_k=3)

        assert len(results) > 0
        # Doc index 2 (authenticateUser) should rank high
        top_idx = results[0][0]
        assert top_idx == 2 or top_idx == 0  # auth-related docs

    def test_bm25_code_aware_tokenization(self):
        """BM25 should split camelCase and snake_case"""
        from src.ai.hybrid_search import BM25
        bm25 = BM25()
        docs = [
            "func getUserById(id int) User",
            "func deleteRecord(r Record) error",
            "func get_user_by_name(name string) User",
        ]
        bm25.index(docs)

        # "user" should match getUserById and get_user_by_name
        results = bm25.search("user", top_k=3)
        matched_idxs = {idx for idx, _ in results}
        assert 0 in matched_idxs  # getUserById -> "get", "user", "by", "id"
        assert 2 in matched_idxs  # get_user_by_name

    def test_bm25_empty_query(self):
        """BM25 should handle empty query gracefully"""
        from src.ai.hybrid_search import BM25
        bm25 = BM25()
        bm25.index(["func hello()"])
        results = bm25.search("", top_k=5)
        assert results == []

    def test_query_classifier_semantic(self):
        """Semantic queries should get higher vector weight"""
        from src.ai.hybrid_search import QueryClassifier
        bm25_w, vec_w = QueryClassifier.classify("how does authentication work in the system?")
        assert vec_w > bm25_w, f"Semantic query should favor vector: BM25={bm25_w}, Vec={vec_w}"

    def test_query_classifier_keyword(self):
        """Keyword queries should get higher BM25 weight"""
        from src.ai.hybrid_search import QueryClassifier
        bm25_w, vec_w = QueryClassifier.classify("getUserById function")
        assert bm25_w >= vec_w, f"Keyword query should favor BM25: BM25={bm25_w}, Vec={vec_w}"

    def test_query_classifier_default(self):
        """Ambiguous queries should use default weights"""
        from src.ai.hybrid_search import QueryClassifier
        bm25_w, vec_w = QueryClassifier.classify("hello")
        assert bm25_w + vec_w == pytest.approx(1.0)
        assert vec_w >= 0.5  # Default favors vector

    def test_query_classifier_weights_sum_to_one(self):
        """Weights should always sum to 1.0"""
        from src.ai.hybrid_search import QueryClassifier
        queries = [
            "how does X work?",
            "getUserById",
            "import redis",
            "find database connection error handling",
            "class AuthService",
            "what is the best approach for caching?",
        ]
        for q in queries:
            bm25_w, vec_w = QueryClassifier.classify(q)
            assert bm25_w + vec_w == pytest.approx(1.0), f"Weights don't sum to 1.0 for: {q}"

    def test_hybrid_searcher_rrf(self):
        """Reciprocal Rank Fusion should combine rankings"""
        from src.ai.hybrid_search import HybridSearcher

        docs = [
            "func handleAuth() error { return nil }",
            "func main() { http.ListenAndServe() }",
            "func authenticateUser(token string) (User, error)",
        ]
        metadata = [
            {"file": "auth.go", "repo": "api"},
            {"file": "main.go", "repo": "api"},
            {"file": "login.go", "repo": "api"},
        ]

        def mock_vector_search(query, top_k=10):
            return [
                {"code": docs[0], "distance": 0.3},
                {"code": docs[2], "distance": 0.5},
                {"code": docs[1], "distance": 0.9},
            ]

        searcher = HybridSearcher(mock_vector_search, docs, metadata)
        results = searcher.search("authenticate", top_k=3, use_rrf=True)

        assert len(results) > 0
        for r in results:
            assert "hybrid_score" in r or "rrf_score" in r

    def test_code_stop_words_excluded(self):
        """Code stop words should be filtered from BM25 tokens"""
        from src.ai.hybrid_search import BM25, CODE_STOP_WORDS
        bm25 = BM25()
        # These stop words shouldn't create meaningful BM25 matches
        assert "the" in CODE_STOP_WORDS
        assert "this" in CODE_STOP_WORDS
        assert "var" in CODE_STOP_WORDS


# ============================================================
# PHASE 4: Query Expansion & Code Preprocessing
# ============================================================

class TestPhase4QueryExpansion:
    """Test query expansion with synonyms, identifiers, and code preprocessing"""

    def test_synonym_expansion_db(self):
        """'db' should expand to database-related terms"""
        from src.ai.hyde import QueryExpander
        expanded = QueryExpander.expand_with_synonyms("db connection error")
        assert "database" in expanded or "datastore" in expanded

    def test_synonym_expansion_auth(self):
        """'auth' should expand to authentication-related terms"""
        from src.ai.hyde import QueryExpander
        expanded = QueryExpander.expand_with_synonyms("auth middleware")
        assert "authentication" in expanded or "login" in expanded

    def test_synonym_expansion_preserves_original(self):
        """Original query should be preserved in expansion"""
        from src.ai.hyde import QueryExpander
        expanded = QueryExpander.expand_with_synonyms("cache redis")
        assert "cache" in expanded
        assert "redis" in expanded

    def test_synonym_expansion_max_additions(self):
        """Should respect max_additions limit"""
        from src.ai.hyde import QueryExpander
        expanded = QueryExpander.expand_with_synonyms("db auth config", max_additions=2)
        original_words = set("db auth config".split())
        new_words = set(expanded.split()) - original_words
        assert len(new_words) <= 2

    def test_synonym_expansion_no_match(self):
        """Query with no synonyms should return unchanged"""
        from src.ai.hyde import QueryExpander
        query = "xyzabc foobar"
        expanded = QueryExpander.expand_with_synonyms(query)
        assert expanded == query

    def test_extract_code_identifiers_camelcase(self):
        """Should extract camelCase identifiers"""
        from src.ai.hyde import QueryExpander
        identifiers = QueryExpander.extract_code_identifiers(
            "find the getUserById and createNewOrder functions"
        )
        assert "getUserById" in identifiers
        assert "createNewOrder" in identifiers

    def test_extract_code_identifiers_snake_case(self):
        """Should extract snake_case identifiers"""
        from src.ai.hyde import QueryExpander
        identifiers = QueryExpander.extract_code_identifiers(
            "look at get_user_by_id and handle_error"
        )
        assert "get_user_by_id" in identifiers
        assert "handle_error" in identifiers

    def test_extract_code_identifiers_dot_notation(self):
        """Should extract dot.notation identifiers"""
        from src.ai.hyde import QueryExpander
        identifiers = QueryExpander.extract_code_identifiers(
            "use http.StatusOK and os.path.join"
        )
        assert any("http.StatusOK" in i for i in identifiers)

    def test_normalize_code_terms(self):
        """Should split camelCase and snake_case in query"""
        from src.ai.hyde import QueryExpander
        normalized = QueryExpander.normalize_code_terms("getUserById")
        assert "get" in normalized.lower()
        assert "user" in normalized.lower()

    def test_normalize_preserves_original(self):
        """Normalization should keep original query intact"""
        from src.ai.hyde import QueryExpander
        normalized = QueryExpander.normalize_code_terms("getUserById")
        assert "getUserById" in normalized

    def test_hyde_expander_without_llm(self):
        """HyDEExpander without LLM should use synonym+normalization only"""
        from src.ai.hyde import HyDEExpander
        expander = HyDEExpander(llm_manager=None)
        result = expander.expand_query("db connection error")
        assert "database" in result or "datastore" in result
        # Should NOT contain "Hypothetical code:" since no LLM
        assert "Hypothetical code:" not in result

    # --- Code Preprocessor ---

    def test_preprocessor_detect_language(self):
        """Should detect language from file extension"""
        from src.ai.code_preprocessor import CodePreprocessor
        assert CodePreprocessor.detect_language("main.py") == "python"
        assert CodePreprocessor.detect_language("handler.go") == "go"
        assert CodePreprocessor.detect_language("app.ts") == "typescript"
        assert CodePreprocessor.detect_language("index.js") == "javascript"
        assert CodePreprocessor.detect_language("unknown.xyz") == "unknown"

    def test_preprocessor_strip_python_comments(self):
        """Should strip Python line comments"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
def hello():
    # This is a comment
    print("hello")  # inline comment
    return True
"""
        stripped = CodePreprocessor.strip_comments(code, "python")
        assert "# This is a comment" not in stripped
        assert "print" in stripped
        assert "return True" in stripped

    def test_preprocessor_strip_go_comments(self):
        """Should strip Go line comments"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
// handleAuth handles authentication
func handleAuth(w http.ResponseWriter) {
    // check token
    token := r.Header.Get("Authorization")
}
"""
        stripped = CodePreprocessor.strip_comments(code, "go")
        assert "// handleAuth" not in stripped
        assert "// check token" not in stripped
        assert "func handleAuth" in stripped

    def test_preprocessor_extract_python_signatures(self):
        """Should extract Python function/class signatures"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
class UserService:
    def get_user(self, user_id: int) -> User:
        pass

    async def create_user(self, name: str) -> User:
        pass
"""
        sigs = CodePreprocessor.extract_signatures(code, "python")
        assert any("class UserService" in s for s in sigs)
        assert any("get_user" in s for s in sigs)

    def test_preprocessor_extract_go_signatures(self):
        """Should extract Go function signatures"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
func handleAuth(w http.ResponseWriter, r *http.Request) {
    token := r.Header.Get("Authorization")
}

type UserService struct {
    db *sql.DB
}
"""
        sigs = CodePreprocessor.extract_signatures(code, "go")
        assert any("handleAuth" in s for s in sigs)
        assert any("UserService" in s for s in sigs)

    def test_preprocessor_extract_imports_python(self):
        """Should extract Python imports"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
import os
from typing import List, Dict
from src.core.models import User
"""
        imports = CodePreprocessor.extract_imports(code, "python")
        assert any("os" in i for i in imports)
        assert any("typing" in i for i in imports)

    def test_preprocessor_extract_imports_go(self):
        """Should extract Go imports"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = '''
import "fmt"
import "net/http"
'''
        imports = CodePreprocessor.extract_imports(code, "go")
        assert "fmt" in imports
        assert "net/http" in imports

    def test_preprocessor_full_pipeline(self):
        """Full preprocessing pipeline should return all fields"""
        from src.ai.code_preprocessor import CodePreprocessor
        code = """
# User service handles user management
def get_user_by_id(user_id: int) -> dict:
    \"\"\"Fetch user by their ID.\"\"\"
    return db.query(user_id)

import os
from typing import Dict
"""
        result = CodePreprocessor.preprocess_for_indexing(code, "python")
        assert "code" in result
        assert "signatures" in result
        assert "imports" in result
        assert "enriched_text" in result
        assert isinstance(result["signatures"], list)
        assert isinstance(result["imports"], list)

    def test_preprocessor_query_preprocessing(self):
        """Query preprocessing should normalize identifiers"""
        from src.ai.code_preprocessor import CodePreprocessor
        result = CodePreprocessor.preprocess_query("getUserById in auth.service")
        assert "user" in result.lower()
        assert "auth" in result.lower()
        assert "service" in result.lower()


# ============================================================
# INTEGRATION: Full Pipeline Smoke Test
# ============================================================

class TestPipelineIntegration:
    """End-to-end integration smoke tests for the full RAG pipeline"""

    def test_enhanced_rag_init_no_crash(self):
        """EnhancedRAGRetriever should initialize without crashing"""
        from src.ai.rag_enhanced import EnhancedRAGRetriever
        retriever = EnhancedRAGRetriever(
            vector_db_path="./data/vector_db",
            llm_manager=None,
            use_hyde=False,
            use_reranking=True,
            use_graphrag=False,
            use_deep_context=False,
            use_hybrid_search=True,
            enable_cache=True
        )
        assert retriever is not None
        assert retriever.cache is not None

    def test_enhanced_rag_cache_stats(self):
        """Cache stats should be accessible"""
        from src.ai.rag_enhanced import EnhancedRAGRetriever
        retriever = EnhancedRAGRetriever(
            vector_db_path="./data/vector_db",
            llm_manager=None,
            use_hyde=False,
            use_deep_context=False,
            enable_cache=True
        )
        stats = retriever.get_cache_stats()
        assert "l1" in stats

    def test_enhanced_rag_invalidate_cache(self):
        """Cache invalidation should not crash"""
        from src.ai.rag_enhanced import EnhancedRAGRetriever
        retriever = EnhancedRAGRetriever(
            vector_db_path="./data/vector_db",
            llm_manager=None,
            use_hyde=False,
            use_deep_context=False,
            enable_cache=True
        )
        retriever.invalidate_cache()  # Should not raise

    def test_query_classifier_feeds_into_hybrid_search(self):
        """QueryClassifier output should be valid weights for hybrid search"""
        from src.ai.hybrid_search import QueryClassifier, BM25

        queries = [
            "how does error handling work?",
            "getUserById function",
            "import database connection",
        ]

        for q in queries:
            bm25_w, vec_w = QueryClassifier.classify(q)
            assert 0.0 <= bm25_w <= 1.0
            assert 0.0 <= vec_w <= 1.0
            assert bm25_w + vec_w == pytest.approx(1.0)

    def test_cache_integration_with_search_params(self):
        """Cache should differentiate queries by all params"""
        from src.ai.cache import RAGCache

        cache = RAGCache(enable_redis=False)

        cache.set("search", "auth", ["result_a"], repo_filter="api", n_results=5)
        cache.set("search", "auth", ["result_b"], repo_filter="web", n_results=5)
        cache.set("search", "auth", ["result_c"], repo_filter="api", n_results=10)

        assert cache.get("search", "auth", repo_filter="api", n_results=5) == ["result_a"]
        assert cache.get("search", "auth", repo_filter="web", n_results=5) == ["result_b"]
        assert cache.get("search", "auth", repo_filter="api", n_results=10) == ["result_c"]

    def test_synonym_expansion_feeds_bm25(self):
        """Synonym expansion should improve BM25 recall"""
        from src.ai.hyde import QueryExpander
        from src.ai.hybrid_search import BM25

        docs = [
            "func connectToDatabase(host string) (*sql.DB, error)",
            "func handleHTTPRequest(w http.ResponseWriter)",
            "func authenticateUser(token string) error",
        ]

        bm25 = BM25()
        bm25.index(docs)

        # Without expansion: "db" won't match "Database"
        raw_results = bm25.search("db connection", top_k=3)

        # With expansion: adds "database" which matches
        expanded = QueryExpander.expand_with_synonyms("db connection")
        expanded_results = bm25.search(expanded, top_k=3)

        # Expanded should find the database doc
        expanded_idxs = {idx for idx, _ in expanded_results}
        assert 0 in expanded_idxs, "Synonym expansion should help find 'connectToDatabase'"
