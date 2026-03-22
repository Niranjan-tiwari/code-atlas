"""
Deep Context: Architectural Summary for LLM

Before sending code snippets to LLM, generate an architectural summary
that explains how the snippets relate to each other. This gives the LLM
"deep context" - understanding the relationships, not just the code.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger("deep_context")


class DeepContextBuilder:
    """
    Builds architectural summaries from retrieved code snippets
    
    Strategy:
    1. Retrieve top 10 snippets via RAG
    2. Ask LLM to summarize architectural relationships
    3. Include summary + snippets in final prompt
    """
    
    def __init__(self, llm_manager=None):
        """
        Initialize deep context builder
        
        Args:
            llm_manager: LLMManager instance
        """
        self.llm_manager = llm_manager
    
    def build_architectural_summary(
        self,
        snippets: List[Dict],
        query: str
    ) -> str:
        """
        Generate architectural summary of code snippets
        
        Args:
            snippets: List of code snippet dicts with 'code', 'file', 'repo', etc.
            query: Original user query
            
        Returns:
            Architectural summary string
        """
        if not self.llm_manager or not snippets:
            return ""
        
        try:
            # Build context for summary
            context_parts = []
            context_parts.append(f"## User Query\n{query}\n")
            context_parts.append("## Retrieved Code Snippets\n")
            
            for i, snippet in enumerate(snippets[:10], 1):  # Limit to 10
                repo = snippet.get('repo', 'unknown')
                file = snippet.get('file', 'unknown')
                code = snippet.get('code', '')[:500]  # Truncate long code
                
                context_parts.append(f"### Snippet {i}: {repo}/{file}")
                context_parts.append(f"```\n{code}\n```\n")
            
            context = "\n".join(context_parts)
            
            # Generate summary
            prompt = self._build_summary_prompt(context, query)
            
            response = self.llm_manager.generate(
                prompt=prompt,
                temperature=0.3,  # Lower temperature for more factual summaries
                max_tokens=500
            )
            
            summary = response.content.strip()
            logger.info(f"Generated architectural summary: {len(summary)} chars")
            
            return summary
            
        except Exception as e:
            logger.warning(f"Architectural summary generation failed: {e}")
            return ""
    
    def _build_summary_prompt(self, context: str, query: str) -> str:
        """Build prompt for architectural summary"""
        return f"""Analyze these code snippets and explain their architectural relationships.

{context}

Provide a concise summary (2-3 sentences) explaining:
1. How these code snippets relate to each other
2. What architectural patterns or structures they represent
3. How they work together to solve the user's query: "{query}"

Focus on relationships, dependencies, and architectural patterns, not code details.

Summary:"""
    
    def build_deep_context_prompt(
        self,
        query: str,
        snippets: List[Dict],
        architectural_summary: Optional[str] = None
    ) -> str:
        """
        Build final prompt with deep context (summary + snippets)
        
        Args:
            query: User query
            snippets: Code snippets
            architectural_summary: Pre-generated summary (optional)
            
        Returns:
            Complete prompt with deep context
        """
        parts = []
        
        # Add architectural summary if available
        if architectural_summary:
            parts.append("## Architectural Context")
            parts.append(architectural_summary)
            parts.append("")
        
        # Add code snippets
        parts.append("## Relevant Code Snippets")
        for i, snippet in enumerate(snippets, 1):
            repo = snippet.get('repo', 'unknown')
            file = snippet.get('file', 'unknown')
            language = snippet.get('language', 'unknown')
            code = snippet.get('code', '')
            
            parts.append(f"### {i}. {repo}/{file} ({language})")
            parts.append(f"```{language}")
            parts.append(code)
            parts.append("```")
            parts.append("")
        
        # Add query
        parts.append("## Question")
        parts.append(query)
        
        return "\n".join(parts)


class DeepContextRAG:
    """
    Complete Deep Context RAG pipeline
    
    Combines:
    1. RAG retrieval
    2. Architectural summary generation
    3. Deep context prompt building
    """
    
    def __init__(self, rag_retriever, llm_manager):
        """
        Initialize Deep Context RAG
        
        Args:
            rag_retriever: RAGRetriever instance
            llm_manager: LLMManager instance
        """
        self.retriever = rag_retriever
        self.llm = llm_manager
        self.context_builder = DeepContextBuilder(llm_manager)
    
    def query_with_deep_context(
        self,
        query: str,
        n_snippets: int = 10,
        repo_filter: Optional[str] = None,
        generate_summary: bool = True
    ) -> Dict:
        """
        Query with deep architectural context
        
        Args:
            query: User query
            n_snippets: Number of snippets to retrieve
            repo_filter: Optional repo filter
            generate_summary: Whether to generate architectural summary
            
        Returns:
            Dict with:
            - snippets: Retrieved code snippets
            - architectural_summary: Generated summary
            - deep_context_prompt: Complete prompt for LLM
        """
        # Step 1: Retrieve snippets
        snippets = self.retriever.search_code(
            query=query,
            n_results=n_snippets,
            repo_filter=repo_filter
        )
        
        # Step 2: Generate architectural summary
        architectural_summary = ""
        if generate_summary and snippets:
            architectural_summary = self.context_builder.build_architectural_summary(
                snippets=snippets,
                query=query
            )
        
        # Step 3: Build deep context prompt
        deep_context_prompt = self.context_builder.build_deep_context_prompt(
            query=query,
            snippets=snippets,
            architectural_summary=architectural_summary if architectural_summary else None
        )
        
        return {
            'snippets': snippets,
            'architectural_summary': architectural_summary,
            'deep_context_prompt': deep_context_prompt,
            'n_snippets': len(snippets)
        }
