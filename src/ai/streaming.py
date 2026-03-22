"""
Streaming RAG Results via Server-Sent Events (SSE)

Instead of waiting for the entire pipeline to complete, stream results
as each stage finishes:
1. Immediate: vector results (fast)
2. Soon after: hybrid BM25+vector results
3. Then: reranked results
4. Then: graph context
5. Finally: LLM-generated answer

Uses SSE (Server-Sent Events) for HTTP streaming - works with any HTTP client.
"""

import json
import logging
import time
import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Any, Generator
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger("rag_streaming")


class StreamEventType(str, Enum):
    """Event types for SSE streaming"""
    SEARCH_START = "search_start"
    HYDE_COMPLETE = "hyde_complete"
    VECTOR_RESULTS = "vector_results"
    HYBRID_RESULTS = "hybrid_results"
    RERANKED_RESULTS = "reranked_results"
    GRAPH_CONTEXT = "graph_context"
    DEEP_CONTEXT = "deep_context"
    LLM_CHUNK = "llm_chunk"
    LLM_COMPLETE = "llm_complete"
    SEARCH_COMPLETE = "search_complete"
    ERROR = "error"
    CACHE_HIT = "cache_hit"


@dataclass
class StreamEvent:
    """A single streaming event"""
    event_type: StreamEventType
    data: Any = None
    stage: str = ""
    elapsed_ms: float = 0.0
    result_count: int = 0
    
    def to_sse(self) -> str:
        """Format as SSE event string"""
        payload = {
            "type": self.event_type.value,
            "stage": self.stage,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "result_count": self.result_count,
        }
        if self.data is not None:
            payload["data"] = self.data
        
        json_str = json.dumps(payload, default=str)
        return f"event: {self.event_type.value}\ndata: {json_str}\n\n"
    
    def to_dict(self) -> Dict:
        return {
            "type": self.event_type.value,
            "stage": self.stage,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "result_count": self.result_count,
            "data": self.data
        }


class StreamingRAGSearch:
    """
    Streaming wrapper around EnhancedRAGRetriever.
    
    Yields results incrementally as each pipeline stage completes.
    Can be used with:
    - SSE endpoints (HTTP streaming)
    - WebSockets
    - Synchronous generators
    """
    
    def __init__(self, enhanced_retriever):
        """
        Args:
            enhanced_retriever: EnhancedRAGRetriever instance
        """
        self.retriever = enhanced_retriever
    
    def stream_search(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        language: str = "go"
    ) -> Generator[StreamEvent, None, None]:
        """
        Stream search results as each pipeline stage completes.
        
        Yields StreamEvent objects that can be converted to SSE format.
        """
        start_time = time.time()
        
        def elapsed():
            return (time.time() - start_time) * 1000
        
        # Emit search start
        yield StreamEvent(
            event_type=StreamEventType.SEARCH_START,
            stage="start",
            data={"query": query, "n_results": n_results}
        )
        
        # Check cache
        cache_params = {
            "n_results": n_results,
            "repo_filter": repo_filter or "",
            "language_filter": language_filter or "",
            "language": language
        }
        if self.retriever.cache:
            cached = self.retriever.cache.get("search", query, **cache_params)
            if cached is not None:
                yield StreamEvent(
                    event_type=StreamEventType.CACHE_HIT,
                    stage="cache",
                    data=self._summarize_results(cached),
                    elapsed_ms=elapsed(),
                    result_count=len(cached)
                )
                yield StreamEvent(
                    event_type=StreamEventType.SEARCH_COMPLETE,
                    stage="complete",
                    data=cached,
                    elapsed_ms=elapsed(),
                    result_count=len(cached)
                )
                return
        
        # Step 1: HyDE expansion
        expanded_query = query
        if self.retriever.use_hyde and self.retriever.hyde:
            hyde_cached = None
            if self.retriever.cache:
                hyde_cached = self.retriever.cache.get("hyde", query, language=language)
            
            if hyde_cached:
                expanded_query = hyde_cached
            else:
                expanded_query = self.retriever.hyde.expand_for_search(query, language)
                if self.retriever.cache and expanded_query != query:
                    self.retriever.cache.set("hyde", query, expanded_query, language=language)
            
            yield StreamEvent(
                event_type=StreamEventType.HYDE_COMPLETE,
                stage="hyde",
                data={"expanded_length": len(expanded_query)},
                elapsed_ms=elapsed()
            )
        
        # Step 2: Vector search
        initial_k = n_results * 3 if self.retriever.use_reranking else n_results
        vector_results = self.retriever.base_retriever.search_code(
            query=expanded_query,
            n_results=initial_k,
            repo_filter=repo_filter,
            language_filter=language_filter
        )
        
        if not vector_results:
            yield StreamEvent(
                event_type=StreamEventType.SEARCH_COMPLETE,
                stage="complete",
                data=[],
                elapsed_ms=elapsed(),
                result_count=0
            )
            return
        
        # Stream vector results immediately
        yield StreamEvent(
            event_type=StreamEventType.VECTOR_RESULTS,
            stage="vector_search",
            data=self._summarize_results(vector_results[:n_results]),
            elapsed_ms=elapsed(),
            result_count=len(vector_results)
        )
        
        # Step 3: Hybrid search
        if self.retriever.use_hybrid_search and vector_results:
            try:
                from .hybrid_search import BM25, QueryClassifier
                
                bm25_weight, vector_weight = QueryClassifier.classify(query)
                documents = [
                    r.get('code', '') or r.get('document', '')
                    for r in vector_results
                ]
                
                bm25 = BM25()
                bm25.index(documents)
                bm25_results = bm25.search(expanded_query, top_k=min(initial_k, len(documents)))
                
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
                
                vector_results = sorted(
                    combined, key=lambda x: x.get('hybrid_score', 0), reverse=True
                )
                
                yield StreamEvent(
                    event_type=StreamEventType.HYBRID_RESULTS,
                    stage="hybrid_search",
                    data={
                        "bm25_weight": bm25_weight,
                        "vector_weight": vector_weight,
                        "results": self._summarize_results(vector_results[:n_results])
                    },
                    elapsed_ms=elapsed(),
                    result_count=len(vector_results)
                )
            except Exception as e:
                yield StreamEvent(
                    event_type=StreamEventType.ERROR,
                    stage="hybrid_search",
                    data={"error": str(e)},
                    elapsed_ms=elapsed()
                )
        
        # Step 4: Reranking
        if self.retriever.use_reranking and self.retriever.reranker:
            vector_results = self.retriever.reranker.rerank(
                query, vector_results, top_k=n_results * 2
            )
            
            yield StreamEvent(
                event_type=StreamEventType.RERANKED_RESULTS,
                stage="reranking",
                data=self._summarize_results(vector_results[:n_results]),
                elapsed_ms=elapsed(),
                result_count=len(vector_results)
            )
        
        # Step 5: GraphRAG
        if self.retriever.use_graphrag and self.retriever.graphrag:
            vector_results = self.retriever.graphrag.multi_hop_retrieve(
                vector_results, hops=1, max_additional=5
            )
            
            yield StreamEvent(
                event_type=StreamEventType.GRAPH_CONTEXT,
                stage="graphrag",
                data={"total_results": len(vector_results)},
                elapsed_ms=elapsed(),
                result_count=len(vector_results)
            )
        
        # Final results
        final_results = vector_results[:n_results]
        
        # Cache results
        if self.retriever.cache and final_results:
            self.retriever.cache.set("search", query, final_results, **cache_params)
        
        yield StreamEvent(
            event_type=StreamEventType.SEARCH_COMPLETE,
            stage="complete",
            data=final_results,
            elapsed_ms=elapsed(),
            result_count=len(final_results)
        )
    
    def _summarize_results(self, results: List[Dict], max_code_len: int = 200) -> List[Dict]:
        """Summarize results for streaming (truncate code previews)"""
        summarized = []
        for r in results:
            summarized.append({
                "repo": r.get("repo", ""),
                "file": r.get("file", ""),
                "language": r.get("language", ""),
                "score": round(
                    r.get("rerank_score", r.get("hybrid_score", r.get("distance", 0.0))) or 0.0,
                    4
                ),
                "code_preview": (r.get("code", "") or "")[:max_code_len]
            })
        return summarized


def generate_sse_response(events: Generator[StreamEvent, None, None]) -> Generator[str, None, None]:
    """
    Convert StreamEvent generator to SSE string generator.
    Use with HTTP streaming response.
    
    Example (with Flask):
        @app.route('/api/stream-search')
        def stream_search():
            events = streaming_rag.stream_search(query)
            return Response(
                generate_sse_response(events),
                mimetype='text/event-stream'
            )
    """
    for event in events:
        yield event.to_sse()
