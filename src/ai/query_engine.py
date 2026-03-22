"""
Query Engine - Combines RAG retrieval with LLM generation
The core brain: retrieves relevant code from Vector DB, then asks LLM to answer
"""

import logging
import json
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

from .rag import RAGRetriever
from .rag_enhanced import EnhancedRAGRetriever
from .llm.manager import LLMManager


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
        
        output.append(f"\n⚡ {self.provider}/{self.model} | {self.tokens_used} tokens | ${self.cost_estimate:.6f} | {self.latency_seconds:.1f}s")
        
        return "\n".join(output)


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
        vector_db_path: str = "./data/vector_db",
        llm_config_path: Optional[str] = None,
        system_prompt: Optional[str] = None,
        use_enhanced_rag: bool = False,
        enhanced_rag_config: Optional[Dict] = None
    ):
        self.logger = logging.getLogger("query_engine")
        
        # Initialize LLM manager first (needed for enhanced RAG)
        self.llm = LLMManager(config_path=llm_config_path)
        self.logger.info("✅ LLM manager initialized")
        
        # Initialize RAG retriever (enhanced or basic)
        if use_enhanced_rag:
            try:
                config = enhanced_rag_config or {}
                
                # Auto-detect: disable LLM-dependent features if no providers
                has_llm = bool(self.llm.get_available_providers())
                use_hyde = config.get("use_hyde", has_llm)  # Needs LLM
                use_deep_context = config.get("use_deep_context", has_llm)  # Needs LLM
                use_reranking = config.get("use_reranking", False)  # Needs sentence-transformers
                use_graphrag = config.get("use_graphrag", False)  # Adds overhead, disable by default
                use_hybrid = config.get("use_hybrid_search", False)  # Base RAG already has hybrid
                
                self.retriever = EnhancedRAGRetriever(
                    vector_db_path=vector_db_path,
                    llm_manager=self.llm,
                    use_hyde=use_hyde,
                    use_reranking=use_reranking,
                    use_graphrag=use_graphrag,
                    use_deep_context=use_deep_context,
                    use_hybrid_search=use_hybrid
                )
                self.logger.info(
                    f"✅ Enhanced RAG initialized "
                    f"(HyDE={use_hyde}, Rerank={use_reranking}, "
                    f"Graph={use_graphrag}, Deep={use_deep_context})"
                )
                self.is_enhanced = True
            except Exception as e:
                self.logger.warning(f"Enhanced RAG failed to initialize: {e}, falling back to basic RAG")
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
        
        # Step 1: Retrieve relevant code from Vector DB
        self.logger.info(f"🔍 Retrieving context for: {question[:80]}...")
        
        # Use enhanced RAG if available
        if self.is_enhanced and hasattr(self.retriever, 'build_context_with_deep_summary'):
            try:
                context_data = self.retriever.build_context_with_deep_summary(
                    query=question,
                    n_results=n_context,
                    repo_filter=repo_filter,
                    language="go"  # Default, could be detected from repo
                )
                context = context_data.get('context', '')
                sources = context_data.get('sources', [])
                architectural_summary = context_data.get('architectural_summary', '')
                
                if architectural_summary:
                    self.logger.info(f"📊 Generated architectural summary: {len(architectural_summary)} chars")
            except Exception as e:
                self.logger.warning(f"Enhanced context building failed: {e}, using basic retrieval")
                context, sources = self.retriever.build_context(
                    query=question,
                    n_results=n_context,
                    repo_filter=repo_filter,
                    max_context_length=6000
                )
        else:
            # Basic RAG retrieval
            context, sources = self.retriever.build_context(
                query=question,
                n_results=n_context,
                repo_filter=repo_filter,
                max_context_length=6000
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
        
        # Save to history
        self.history.append({
            "question": question,
            "answer": response.content[:200] + "...",
            "sources_count": len(sources),
            "provider": response.provider
        })
        
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
        if self.is_enhanced and hasattr(self.retriever, 'search_code'):
            # Enhanced RAG search with all optimizations
            return self.retriever.search_code(
                query=query,
                n_results=n_results,
                repo_filter=repo_filter,
                language_filter=language_filter,
                language=language
            )
        else:
            # Basic RAG search
            return self.retriever.search_code(
                query=query,
                n_results=n_results,
                repo_filter=repo_filter,
                language_filter=language_filter
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
