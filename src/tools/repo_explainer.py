"""
Repo Explainer: Explain functions, logic flow, or entire repos using RAG + LLM.
Supports end-to-end architecture explanations and optional Mermaid diagram generation.
"""

import logging
import os
from typing import Dict, Optional, List

logger = logging.getLogger("repo_explainer")


REPO_ARCHITECTURE_SYSTEM = """You are an expert software architect helping a developer understand a codebase.

Your job is to provide CLEAR, ACCURATE, and COMPREHENSIVE explanations based ONLY on the provided code context.

For REPO-LEVEL / ARCHITECTURE questions ("how does X repo work", "explain the flow"):
1. Identify entry points (main, init, handlers)
2. Trace the data/logic flow through the key components
3. Explain the purpose of each major piece
4. Describe how components interact
5. Be specific - reference actual file names, function names from the code

For FUNCTION-LEVEL questions ("what does function X do", "explain this logic"):
1. Explain the purpose in plain language
2. Describe inputs, outputs, and side effects
3. Explain the control flow / logic step by step
4. Note any dependencies or called functions

For DIAGRAM requests:
- Generate a Mermaid diagram (flowchart or sequence diagram) that shows the architecture or flow
- Use correct Mermaid syntax. Common patterns:
  flowchart TD / flowchart LR
  subgraph for components
  A --> B for flow
  sequenceDiagram for request/response flows
- Place the diagram in a ```mermaid ... ``` code block so it can be rendered
- Keep diagrams concise but informative

ALWAYS base your answer on the provided code. If the context is insufficient, say so.
Do NOT hallucinate - only reference code that was actually provided."""


def explain(
    retriever,
    question: str,
    repo_filter: Optional[str] = None,
    n_context: int = 15,
    include_diagram: bool = False,
    max_tokens: int = 2048,
) -> Dict:
    """
    Explain code, a function, logic flow, or entire repo using RAG + LLM.
    
    Args:
        retriever: RAGRetriever instance
        question: What to explain (e.g. "how payment_service works", "what does ProcessMessage do")
        repo_filter: Limit to specific repo
        n_context: Number of code chunks to retrieve (more for repo-level)
        include_diagram: Ask LLM to generate Mermaid architecture diagram
        max_tokens: Max LLM response tokens
        
    Returns:
        dict with keys: explanation, diagram (if generated), sources, model, error
    """
    result = {
        "explanation": "",
        "diagram": None,
        "sources": [],
        "model": "",
        "provider": "",
        "error": None,
    }
    
    # Detect if this is repo-level (needs more context, architecture focus)
    q_lower = question.lower()
    is_repo_level = any(
        phrase in q_lower
        for phrase in ["how ", "how does", "works", "architecture", "flow", "end to end", "explain the"]
    )
    
    if is_repo_level and n_context < 12:
        n_context = 15
    
    # Build enhanced prompt for diagram request
    user_prompt = question
    if include_diagram:
        user_prompt = f"""{question}

IMPORTANT: Include a Mermaid architecture/flow diagram in your response.
Use a ```mermaid ... ``` code block. Show:
- Main components and their relationships
- Data/request flow
- Entry points and key functions
Keep the diagram readable (max 15-20 nodes)."""
    
    # Retrieve context
    try:
        context, sources = retriever.build_context(
            query=question,
            n_results=n_context,
            repo_filter=repo_filter,
            max_context_length=6000,  # Balanced for local LLM speed
        )
    except Exception as e:
        result["error"] = str(e)
        return result
    
    if not context:
        result["error"] = "No relevant code found. Try a different question or check if the repo is indexed."
        return result
    
    # Build full prompt
    prompt_parts = [
        "## Code Context from Codebase",
        context,
        "",
        "## Question",
        user_prompt,
    ]
    
    if repo_filter:
        prompt_parts.insert(0, f"## Repository: {repo_filter}\n")
    
    prompt = "\n".join(prompt_parts)
    
    # Call LLM
    try:
        if os.environ.get("SKIP_LLM"):
            raise RuntimeError("LLM disabled (SKIP_LLM=1)")
        
        from src.ai.llm.manager import LLMManager
        llm = LLMManager()
        
        if not llm.get_available_providers():
            result["error"] = "No LLM provider available. Set OPENAI_API_KEY, or run `ollama serve` and `ollama pull codellama`"
            return result
        
        response = llm.generate(
            prompt=prompt,
            system_prompt=REPO_ARCHITECTURE_SYSTEM,
            temperature=0.2,  # Lower for accurate explanations
            max_tokens=max_tokens,
        )
        
        result["explanation"] = response.content
        result["model"] = response.model
        result["provider"] = response.provider
        result["sources"] = [
            {"repo": s["repo"], "file": s["file"]}
            for s in sources
        ]
        
        # Extract Mermaid diagram if present
        if "```mermaid" in response.content:
            try:
                start = response.content.index("```mermaid") + len("```mermaid")
                end = response.content.index("```", start)
                result["diagram"] = response.content[start:end].strip()
            except ValueError:
                pass
        
    except Exception as e:
        result["error"] = str(e)
    
    return result
