"""
Query Engine - Combines RAG retrieval with LLM generation
The core brain: retrieves relevant code from Vector DB, then asks LLM to answer
"""

import logging
import json
import time
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path
from dataclasses import dataclass, field

from .rag import RAGRetriever
from .rag_enhanced import EnhancedRAGRetriever
from .vector_backend import vector_db_path as default_vector_db_path
from .llm.manager import LLMManager
from .retrieval_router import classify_retrieval_intent, context_looks_weak
from .llm_response_cache import (
    CachedLLMPayload,
    LLMQueryCache,
    get_retriever_embed_fn,
    load_llm_query_cache_config,
)


SYSTEM_PROMPT = """You are an expert code assistant with deep knowledge of Go, Python, Java, and microservices architecture.

You are helping a developer understand and work with their codebase. You have access to actual code snippets from their repositories.

Rules:
1. ALWAYS base your answers on the provided code context. If the context doesn't contain relevant information, say so.
2. When referencing code, mention the specific repo and file it comes from.
3. Be precise and concise. Show relevant code snippets in your answers.
4. If asked to generate code, match the style and patterns from the existing codebase.
5. If you're unsure about something, say so rather than guessing.
6. For Go code, follow Go conventions (error handling patterns, naming, etc.).
7. Explain architectural decisions when relevant.

You are NOT allowed to:
- Make up function names, APIs, or imports that don't exist in the codebase
- Invent configuration values or environment variables
- Hallucinate package names or module paths"""


@dataclass
class QueryResult:
    """Result of a query to the engine"""
    answer: str
    sources: List[Dict]
    query: str
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    cost_estimate: float = 0.0
    latency_seconds: float = 0.0
    context_length: int = 0
    # Set when served from llm_response_cache (exact_l0 / exact_redis / semantic_pgvector)
    cache_hit: Optional[str] = None
    
    def format_answer(self) -> str:
        """Format the answer with sources for display"""
        output = []
        output.append(self.answer)
        
        if self.sources:
            output.append("\n\n📚 Sources:")
            for src in self.sources:
                relevance = src.get("relevance", 0)
                pct = f"{relevance*100:.0f}%" if relevance else "N/A"
                output.append(f"  [{src['index']}] {src['repo']}/{src['file']} ({src['language']}) - Relevance: {pct}")
        
        tail = f"\n⚡ {self.provider}/{self.model} | {self.tokens_used} tokens | ${self.cost_estimate:.6f} | {self.latency_seconds:.1f}s"
        if self.cache_hit:
            tail += f" | cache:{self.cache_hit}"
        output.append(tail)

        return "\n".join(output)


# Only "fast" forces expensive stages off regardless of ai_config enhanced_rag.
# "balanced" / "quality" use query_engine.enhanced_rag from JSON (defaults are conservative).
LATENCY_PRESET_FAST: Dict[str, object] = {
    "use_hyde": False,
    "use_deep_context": False,
    "use_reranking": False,
    "use_graphrag": False,
    "use_hybrid_search": True,
}


def _default_latency_bundle() -> Dict:
    return {
        "mode": "balanced",
        "progressive_retrieval": True,
        "progressive_initial_k": 3,
        "expand_relevance_threshold": 0.28,
        "query_classification": True,
    }


def _load_latency_bundle(llm_config_path: Optional[str]) -> Dict:
    bundle = _default_latency_bundle()
    if not llm_config_path or not Path(llm_config_path).is_file():
        return bundle
    try:
        with open(llm_config_path, encoding="utf-8") as f:
            data = json.load(f)
        lat = data.get("latency") or {}
        if isinstance(lat, dict):
            bundle.update(lat)
    except (OSError, json.JSONDecodeError):
        pass
    return bundle


class QueryEngine:
    """
    Main query engine - ties RAG retrieval and LLM generation together
    
    Flow:
    1. User asks a question
    2. RAG retriever finds relevant code from Vector DB
    3. Code context + question are sent to LLM
    4. LLM generates answer grounded in actual code
    5. Answer is returned with source references
    """
    
    def __init__(
        self,
        vector_db_path: Optional[str] = None,
        llm_config_path: Optional[str] = None,
        system_prompt: Optional[str] = None,
        use_enhanced_rag: bool = False,
        enhanced_rag_config: Optional[Dict] = None,
        latency_mode: Optional[str] = None,
        latency_overrides: Optional[Dict] = None,
        retriever: Optional[Union[RAGRetriever, EnhancedRAGRetriever]] = None,
    ):
        self.logger = logging.getLogger("query_engine")

        if vector_db_path is None:
            vector_db_path = default_vector_db_path()

        if llm_config_path is None:
            _cfg = Path(__file__).resolve().parent.parent.parent / "config" / "ai_config.json"
            if _cfg.is_file():
                llm_config_path = str(_cfg)

        self.latency_bundle = _load_latency_bundle(llm_config_path)
        if latency_mode:
            self.latency_bundle["mode"] = latency_mode
        if latency_overrides:
            self.latency_bundle.update(latency_overrides)
        self.logger.info(
            f"⏱️ Latency mode: {self.latency_bundle.get('mode')} "
            f"(progressive={self.latency_bundle.get('progressive_retrieval')})"
        )

        # Initialize LLM manager first (needed for enhanced RAG)
        self.llm = LLMManager(config_path=llm_config_path)
        self.logger.info("✅ LLM manager initialized")

        # Reuse an existing retriever (e.g. API server) to avoid a second embedded Qdrant client
        if retriever is not None:
            self.retriever = retriever
            self.is_enhanced = isinstance(retriever, EnhancedRAGRetriever)
            self.logger.info(
                "✅ Using injected RAG retriever (shared vector store handle)"
            )
            self.system_prompt = system_prompt or SYSTEM_PROMPT
            self.history: List[Dict] = []
            self._shutdown_done = False
            self._retriever_owned = False
            self._llm_query_cache = LLMQueryCache(
                load_llm_query_cache_config(llm_config_path)
            )
            return

        # Initialize RAG retriever (enhanced or basic)
        if use_enhanced_rag:
            try:
                mode = self.latency_bundle.get("mode", "balanced")
                merged = dict(enhanced_rag_config or {})
                if mode == "fast":
                    merged.update(LATENCY_PRESET_FAST)

                use_hyde = merged.get("use_hyde", False)
                use_deep_context = merged.get("use_deep_context", False)
                use_reranking = merged.get("use_reranking", False)
                use_graphrag = merged.get("use_graphrag", False)
                use_hybrid = merged.get("use_hybrid_search", True)

                self.retriever = EnhancedRAGRetriever(
                    vector_db_path=vector_db_path,
                    llm_manager=self.llm,
                    use_hyde=use_hyde,
                    use_reranking=use_reranking,
                    use_graphrag=use_graphrag,
                    use_deep_context=use_deep_context,
                    use_hybrid_search=use_hybrid,
                )
                self.logger.info(
                    f"✅ Enhanced RAG initialized "
                    f"(HyDE={use_hyde}, Rerank={use_reranking}, "
                    f"Graph={use_graphrag}, Deep={use_deep_context}, Hybrid={use_hybrid})"
                )
                self.is_enhanced = True
            except Exception as e:
                self.logger.warning(
                    f"Enhanced RAG failed to initialize: {e}, falling back to basic RAG"
                )
                self.retriever = RAGRetriever(persist_directory=vector_db_path)
                self.is_enhanced = False
        else:
            self.retriever = RAGRetriever(persist_directory=vector_db_path)
            self.is_enhanced = False
            self.logger.info("✅ Basic RAG retriever initialized")

        # System prompt
        self.system_prompt = system_prompt or SYSTEM_PROMPT

        # Query history for context
        self.history: List[Dict] = []
        self._shutdown_done: bool = False
        self._retriever_owned = True

        # LLM answer cache (Redis exact + optional pgvector semantic + in-process LRU)
        self._llm_query_cache = LLMQueryCache(load_llm_query_cache_config(llm_config_path))

    def shutdown(self) -> None:
        """Close vector DB handles so embedded Qdrant lock is released promptly."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        if not getattr(self, "_retriever_owned", True):
            return
        try:
            closer = getattr(self.retriever, "close", None)
            if callable(closer):
                closer()
        except Exception as exc:
            self.logger.debug("shutdown: retriever close failed: %s", exc)

    def _skip_deep_context_path(self) -> bool:
        if self.latency_bundle.get("mode") == "fast":
            return True
        if not self.is_enhanced:
            return True
        return not getattr(self.retriever, "use_deep_context", False)

    def _build_context_core(
        self,
        question: str,
        n_results: int,
        repo_filter: Optional[str],
        max_context_length: int,
        retrieval_intent: Optional[str],
        fast_fanout: bool,
        skip_deep: bool,
    ) -> Tuple[str, List[Dict]]:
        if (
            self.is_enhanced
            and not skip_deep
            and getattr(self.retriever, "use_deep_context", False)
        ):
            data = self.retriever.build_context_with_deep_summary(
                query=question,
                n_results=n_results,
                repo_filter=repo_filter,
                language="go",
                retrieval_intent=retrieval_intent,
                fast_fanout=fast_fanout,
            )
            return data["context"], data["sources"]
        if self.is_enhanced:
            return self.retriever.build_context(
                question,
                n_results=n_results,
                repo_filter=repo_filter,
                max_context_length=max_context_length,
                retrieval_intent=retrieval_intent,
                fast_fanout=fast_fanout,
            )
        return self.retriever.build_context(
            question,
            n_results=n_results,
            repo_filter=repo_filter,
            max_context_length=max_context_length,
            retrieval_intent=retrieval_intent,
            fast_fanout=fast_fanout,
        )

    def _retrieve_context(
        self,
        question: str,
        n_context: int,
        repo_filter: Optional[str],
        max_context_length: int = 6000,
    ) -> Tuple[str, List[Dict]]:
        lb = self.latency_bundle
        intent = (
            classify_retrieval_intent(question)
            if lb.get("query_classification", True)
            else None
        )
        fast_fanout = lb.get("mode") == "fast"
        initial_k = max(1, int(lb.get("progressive_initial_k", 3)))
        thresh = float(lb.get("expand_relevance_threshold", 0.28))
        progressive = lb.get("progressive_retrieval", True) and lb.get("mode") != "quality"

        if progressive and n_context > initial_k:
            ctx, src = self._build_context_core(
                question,
                min(initial_k, n_context),
                repo_filter,
                max_context_length,
                intent,
                fast_fanout,
                skip_deep=True,
            )
            if context_looks_weak(src, min_best_relevance=thresh):
                return self._build_context_core(
                    question,
                    n_context,
                    repo_filter,
                    max_context_length,
                    intent,
                    fast_fanout,
                    skip_deep=self._skip_deep_context_path(),
                )
            return ctx, src

        return self._build_context_core(
            question,
            n_context,
            repo_filter,
            max_context_length,
            intent,
            fast_fanout,
            skip_deep=self._skip_deep_context_path(),
        )
    
    def query(
        self,
        question: str,
        repo_filter: Optional[str] = None,
        n_context: int = 5,
        provider: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4000,
        include_history: bool = True
    ) -> QueryResult:
        """
        Ask a question about the codebase
        
        Args:
            question: Natural language question
            repo_filter: Limit search to specific repo
            n_context: Number of code snippets to retrieve
            provider: Specific LLM provider to use
            temperature: LLM creativity (lower = more precise)
            max_tokens: Max response tokens
            include_history: Include conversation history for context
        
        Returns:
            QueryResult with answer and sources
        """
        start_time = time.time()

        # LLM response cache (skip when multi-turn history changes the prompt)
        if (
            not include_history
            and self._llm_query_cache
            and self._llm_query_cache.enabled
        ):
            emb_fn = get_retriever_embed_fn(self.retriever)
            cached = self._llm_query_cache.try_get(
                question,
                repo_filter,
                n_context,
                provider,
                temperature,
                emb_fn,
            )
            if cached is not None:
                layer, payload = cached
                latency = time.time() - start_time
                self.logger.info("LLM cache hit (%s) in %.3fs", layer, latency)
                return QueryResult(
                    answer=payload.answer,
                    sources=payload.sources,
                    query=question,
                    provider=payload.provider,
                    model=payload.model,
                    tokens_used=payload.tokens_used,
                    cost_estimate=payload.cost_estimate,
                    latency_seconds=latency,
                    context_length=payload.context_length,
                    cache_hit=layer,
                )

        # Step 1: Retrieve relevant code from Vector DB (latency-budget routing)
        self.logger.info(f"🔍 Retrieving context for: {question[:80]}...")
        try:
            context, sources = self._retrieve_context(
                question, n_context, repo_filter, max_context_length=6000
            )
        except Exception as e:
            self.logger.warning(f"Retrieval failed: {e}, retrying basic build_context")
            context, sources = self.retriever.build_context(
                question,
                n_results=n_context,
                repo_filter=repo_filter,
                max_context_length=6000,
            )
        
        if not context:
            self.logger.warning("⚠️  No relevant code found in Vector DB")
            context = "(No relevant code found in the indexed repositories)"
        
        # Step 2: Build the prompt with context
        prompt = self._build_prompt(question, context, repo_filter, include_history)
        
        # Step 3: Generate response from LLM
        self.logger.info(f"🤖 Generating answer ({len(prompt)} chars prompt)...")
        response = self.llm.generate(
            prompt=prompt,
            system_prompt=self.system_prompt,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        latency = time.time() - start_time
        
        # Step 4: Build result
        result = QueryResult(
            answer=response.content,
            sources=sources,
            query=question,
            provider=response.provider,
            model=response.model,
            tokens_used=response.tokens_used,
            cost_estimate=response.cost_estimate,
            latency_seconds=latency,
            context_length=len(context)
        )
        
        # Save to history (multi-turn CLI / dedicated session only)
        if include_history:
            self.history.append({
                "question": question,
                "answer": response.content[:200] + "...",
                "sources_count": len(sources),
                "provider": response.provider
            })

        # Write-through LLM answer cache
        if (
            not include_history
            and self._llm_query_cache
            and self._llm_query_cache.enabled
        ):
            emb_fn = get_retriever_embed_fn(self.retriever)
            self._llm_query_cache.store(
                question,
                repo_filter,
                n_context,
                provider,
                temperature,
                CachedLLMPayload(
                    answer=result.answer,
                    sources=result.sources,
                    provider=result.provider,
                    model=result.model,
                    tokens_used=result.tokens_used,
                    cost_estimate=result.cost_estimate,
                    context_length=result.context_length,
                    query=question,
                ),
                emb_fn,
            )

        self.logger.info(f"✅ Answer generated in {latency:.1f}s")
        
        return result
    
    def search_only(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language_filter: Optional[str] = None,
        language: str = "go"
    ) -> List[Dict]:
        """
        Search code without LLM - just RAG retrieval
        Useful for finding code snippets directly
        
        Uses enhanced RAG if available (HyDE, reranking, etc.)
        """
        intent = (
            classify_retrieval_intent(query)
            if self.latency_bundle.get("query_classification", True)
            else None
        )
        fast_fanout = self.latency_bundle.get("mode") == "fast"
        if self.is_enhanced and hasattr(self.retriever, "search_code"):
            return self.retriever.search_code(
                query=query,
                n_results=n_results,
                repo_filter=repo_filter,
                language_filter=language_filter,
                language=language,
                retrieval_intent=intent,
                fast_fanout=fast_fanout,
            )
        return self.retriever.search_code(
            query=query,
            n_results=n_results,
            repo_filter=repo_filter,
            language_filter=language_filter,
            retrieval_intent=intent,
            fast_fanout=fast_fanout,
        )
    
    def list_repos(self) -> List[Dict]:
        """List all indexed repositories"""
        return self.retriever.get_available_repos()
    
    def get_repo_info(self, repo_name: str) -> Dict:
        """Get detailed info about a specific repo"""
        return self.retriever.get_repo_summary(repo_name)
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        repos = self.retriever.get_available_repos()
        llm_stats = self.llm.get_usage_stats()
        
        return {
            "repos_indexed": len(repos),
            "total_chunks": sum(r["chunks"] for r in repos),
            "queries_answered": len(self.history),
            "llm": llm_stats
        }
    
    def _build_prompt(
        self,
        question: str,
        context: str,
        repo_filter: Optional[str],
        include_history: bool
    ) -> str:
        """Build the full prompt with context and history"""
        parts = []
        
        # Add conversation history (last 3 exchanges)
        if include_history and self.history:
            recent = self.history[-3:]
            parts.append("## Previous Questions")
            for h in recent:
                parts.append(f"Q: {h['question']}")
                parts.append(f"A: {h['answer']}")
            parts.append("")
        
        # Add repo filter note
        if repo_filter:
            parts.append(f"## Repository Context: {repo_filter}")
            parts.append(f"Focus your answer on the `{repo_filter}` repository.")
            parts.append("")
        
        # Add code context
        parts.append("## Relevant Code from the Codebase")
        parts.append(context)
        parts.append("")
        
        # Add the question
        parts.append("## Question")
        parts.append(question)
        
        return "\n".join(parts)
