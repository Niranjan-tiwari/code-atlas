"""
Enhanced RAG Retriever with All Advanced Features

Integrates:
- AST-based chunking
- Parent-child indexing
- HyDE query expansion
- Hybrid search (BM25 + Vector)
- Cross-encoder reranking
- GraphRAG multi-hop retrieval
- Deep context architectural summaries
- Multi-tier caching (L1 LRU + L2 Redis)
"""

import logging
import time
from typing import List, Dict, Optional

from .rag import RAGRetriever
from .hyde import HyDEExpander, QueryExpander
from .reranking import get_best_reranker, Reranker, SimpleReranker
from .graphrag import GraphRAGRetriever, CodeGraph
from .hybrid_search import HybridSearcher, BM25, QueryClassifier
from .deep_context import DeepContextBuilder
from .cache import RAGCache, get_rag_cache
from .code_preprocessor import CodePreprocessor

logger = logging.getLogger("rag_enhanced")


class EnhancedRAGRetriever:
    """
    Advanced RAG retriever with all optimizations
    
    Pipeline:
    1. HyDE: Expand query with hypothetical code
    2. Hybrid Search: BM25 + Vector search
    3. Reranking: Cross-encoder rerank
    4. GraphRAG: Multi-hop retrieval
    5. Deep Context: Architectural summary
    """
    
    def __init__(
        self,
        vector_db_path: str = "./data/vector_db",
        llm_manager=None,
        use_hyde: bool = True,
        use_reranking: bool = True,
        use_graphrag: bool = True,
        use_deep_context: bool = True,
        use_hybrid_search: bool = True,
        enable_cache: bool = True,
        redis_host: str = "localhost",
        redis_port: int = 6379
    ):
        """
        Initialize enhanced RAG retriever
        
        Args:
            vector_db_path: Path to ChromaDB
            llm_manager: LLMManager for HyDE and deep context
            use_hyde: Enable HyDE query expansion
            use_reranking: Enable cross-encoder reranking
            use_graphrag: Enable GraphRAG multi-hop
            use_deep_context: Enable architectural summaries
            use_hybrid_search: Enable BM25 + Vector hybrid
            enable_cache: Enable multi-tier caching
            redis_host: Redis host for L2 cache
            redis_port: Redis port for L2 cache
        """
        # Base RAG retriever
        self.base_retriever = RAGRetriever(persist_directory=vector_db_path)
        
        # Advanced components
        self.llm_manager = llm_manager
        self.use_hyde = use_hyde and llm_manager
        self.use_reranking = use_reranking
        self.use_graphrag = use_graphrag
        self.use_deep_context = use_deep_context and llm_manager
        self.use_hybrid_search = use_hybrid_search
        
        # Initialize components
        self.hyde = HyDEExpander(llm_manager) if self.use_hyde else None
        self.reranker = get_best_reranker() if self.use_reranking else None
        if not self.reranker:
            self.reranker = SimpleReranker()
        
        self.graph = CodeGraph()  # Will be populated during indexing
        self.graphrag = GraphRAGRetriever(self.graph) if self.use_graphrag else None
        self.deep_context = DeepContextBuilder(llm_manager) if self.use_deep_context else None
        
        # Multi-tier cache (L1: LRU in-memory, L2: Redis)
        self.cache = get_rag_cache(
            redis_host=redis_host,
            redis_port=redis_port,
            enable_redis=enable_cache
        ) if enable_cache else None
        
        logger.info(
            f"Enhanced RAG initialized: "
            f"HyDE={self.use_hyde}, Reranking={self.use_reranking}, "
            f"GraphRAG={self.use_graphrag}, DeepContext={self.use_deep_context}, "
            f"HybridSearch={self.use_hybrid_search}, Cache={enable_cache}"
        )
    
    def get_available_repos(self):
        """Delegate to base retriever"""
        return self.base_retriever.get_available_repos()
    
    def get_repo_summary(self, repo_name: str):
        """Delegate to base retriever"""
        return self.base_retriever.get_repo_summary(repo_name)
    
    def invalidate_cache(self):
        """Invalidate all caches (call after re-indexing)"""
        if self.cache:
            self.cache.invalidate_all()
            logger.info("All RAG caches invalidated")
    
    def get_cache_stats(self) -> Dict:
        """Get cache hit/miss statistics"""
        if self.cache:
            return self.cache.stats()
        return {"enabled": False}
    
    def search_code(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        language: str = "go"
    ) -> List[Dict]:
        """
        Advanced code search with all optimizations
        
        Args:
            query: Search query
            n_results: Number of results
            repo_filter: Filter to specific repo
            language_filter: Filter by language
            language: Target language for HyDE expansion
            
        Returns:
            List of enhanced results
        """
        search_start = time.time()
        
        # Check cache first
        cache_params = {
            "n_results": n_results,
            "repo_filter": repo_filter or "",
            "language_filter": language_filter or "",
            "language": language
        }
        if self.cache:
            cached = self.cache.get("search", query, **cache_params)
            if cached is not None:
                elapsed = (time.time() - search_start) * 1000
                logger.info(f"Cache hit for query: {query[:50]}... ({elapsed:.1f}ms)")
                return cached
        
        # Step 1a: Query expansion (always active - synonyms + identifiers)
        expanded_query = QueryExpander.expand_with_synonyms(query)
        expanded_query = QueryExpander.normalize_code_terms(expanded_query)
        
        # Code-aware query preprocessing (split identifiers, normalize naming)
        preprocessed = CodePreprocessor.preprocess_query(expanded_query)
        if preprocessed != expanded_query:
            expanded_query = preprocessed
            logger.info("Applied code-aware query preprocessing")
        
        # Extract code identifiers and add them to the query
        identifiers = QueryExpander.extract_code_identifiers(query)
        if identifiers:
            expanded_query = f"{expanded_query} {' '.join(identifiers)}"
            logger.info(f"Extracted {len(identifiers)} code identifiers from query")
        
        # Step 1b: HyDE expansion (if LLM enabled, with its own cache)
        if self.use_hyde and self.hyde:
            hyde_cached = None
            if self.cache:
                hyde_cached = self.cache.get("hyde", query, language=language)
            if hyde_cached:
                expanded_query = hyde_cached
                logger.info("HyDE cache hit")
            else:
                logger.info("Expanding query with HyDE...")
                expanded_query = self.hyde.expand_for_search(query, language)
                if self.cache and expanded_query != query:
                    self.cache.set("hyde", query, expanded_query, language=language)
        
        # Step 2: Initial vector search (get more candidates for reranking)
        initial_k = n_results * 3 if self.use_reranking else n_results
        vector_results = self.base_retriever.search_code(
            query=expanded_query,
            n_results=initial_k,
            repo_filter=repo_filter,
            language_filter=language_filter
        )
        
        if not vector_results:
            logger.warning("No results from vector search")
            return []
        
        # Step 3: Hybrid search (BM25 + Vector) with dynamic weight tuning
        if self.use_hybrid_search and len(vector_results) > 0:
            try:
                # Dynamic weight tuning based on query type
                bm25_weight, vector_weight = QueryClassifier.classify(query)
                logger.info(
                    f"Hybrid search: auto-weights BM25={bm25_weight}, "
                    f"Vector={vector_weight}"
                )
                
                documents = [r.get('code', '') or r.get('document', '') for r in vector_results]
                
                bm25 = BM25()
                bm25.index(documents)
                bm25_results = bm25.search(expanded_query, top_k=min(initial_k, len(documents)))
                
                # Build score maps for min-max normalization
                bm25_score_map = {idx: score for idx, score in bm25_results}
                bm25_scores = [s for _, s in bm25_results] if bm25_results else [0]
                min_bm25 = min(bm25_scores)
                max_bm25 = max(bm25_scores)
                range_bm25 = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1.0
                
                combined = []
                for i, result in enumerate(vector_results):
                    result = result.copy()
                    vector_score = 1.0 / (1.0 + (result.get('distance', 2.0) or 2.0))
                    
                    raw_bm25 = bm25_score_map.get(i, 0.0)
                    norm_bm25 = (raw_bm25 - min_bm25) / range_bm25 if raw_bm25 > 0 else 0.0
                    
                    result['bm25_score'] = norm_bm25
                    result['vector_score'] = vector_score
                    result['hybrid_score'] = (norm_bm25 * bm25_weight) + (vector_score * vector_weight)
                    combined.append(result)
                
                vector_results = sorted(combined, key=lambda x: x.get('hybrid_score', 0), reverse=True)
                logger.info(f"Hybrid search: combined {len(vector_results)} results")
            except Exception as e:
                logger.warning(f"Hybrid search failed: {e}, using vector results only")
        
        # Step 4: Reranking (if enabled)
        if self.use_reranking and self.reranker:
            logger.info(f"🔍 Reranking {len(vector_results)} candidates...")
            vector_results = self.reranker.rerank(query, vector_results, top_k=n_results * 2)
        
        # Step 5: GraphRAG multi-hop (if enabled)
        if self.use_graphrag and self.graphrag:
            logger.info("🔍 Performing multi-hop GraphRAG retrieval...")
            vector_results = self.graphrag.multi_hop_retrieve(
                vector_results,
                hops=1,
                max_additional=5
            )
        
        # Step 6: Return top-k
        final_results = vector_results[:n_results]
        
        elapsed = (time.time() - search_start) * 1000
        logger.info(
            f"Enhanced search complete: {len(final_results)} results "
            f"(from {len(vector_results)} candidates, {elapsed:.1f}ms)"
        )
        
        # Cache the results
        if self.cache and final_results:
            self.cache.set("search", query, final_results, **cache_params)
        
        return final_results
    
    def build_context_with_deep_summary(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language: str = "go"
    ) -> Dict:
        """
        Build context with architectural summary
        
        Returns:
            Dict with:
            - context: Code context string
            - sources: Source references
            - architectural_summary: Generated summary
            - deep_context_prompt: Complete prompt
        """
        # Search with all optimizations
        snippets = self.search_code(
            query=query,
            n_results=n_results,
            repo_filter=repo_filter,
            language=language
        )
        
        # Generate architectural summary
        architectural_summary = ""
        if self.use_deep_context and self.deep_context:
            architectural_summary = self.deep_context.build_architectural_summary(
                snippets=snippets,
                query=query
            )
        
        # Build context string
        context_parts = []
        if architectural_summary:
            context_parts.append("## Architectural Context")
            context_parts.append(architectural_summary)
            context_parts.append("")
        
        context_parts.append("## Relevant Code")
        sources = []
        for i, snippet in enumerate(snippets, 1):
            repo = snippet.get('repo', 'unknown')
            file = snippet.get('file', 'unknown')
            language = snippet.get('language', 'unknown')
            code = snippet.get('code', '')
            
            context_parts.append(f"--- Source {i}: {repo}/{file} ({language}) ---")
            context_parts.append(code)
            context_parts.append("")
            
            sources.append({
                'index': i,
                'repo': repo,
                'file': file,
                'language': language,
                'relevance': snippet.get('rerank_score', snippet.get('hybrid_score', 0.0))
            })
        
        context = "\n".join(context_parts)
        
        # Build deep context prompt
        deep_context_prompt = ""
        if self.use_deep_context and self.deep_context:
            deep_context_prompt = self.deep_context.build_deep_context_prompt(
                query=query,
                snippets=snippets,
                architectural_summary=architectural_summary if architectural_summary else None
            )
        
        return {
            'context': context,
            'sources': sources,
            'architectural_summary': architectural_summary,
            'deep_context_prompt': deep_context_prompt,
            'n_snippets': len(snippets)
        }
