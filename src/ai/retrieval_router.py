"""
Latency-budget retrieval routing: cheap query classification before retrieval.

Maps natural-language / code queries to retrieval profiles so we avoid unnecessary
hybrid BM25 work, limit collection fan-out, and drive progressive expansion.
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from .hybrid_search import QueryClassifier

RetrievalIntent = Literal["keyword", "semantic", "hybrid", "dependency"]


_DEPENDENCY_HINTS = re.compile(
    r"\b(import\s+graph|call\s+graph|dependency|dependencies|who\s+calls|"
    r"transitive|package\s+graph|module\s+graph)\b",
    re.IGNORECASE,
)


def classify_retrieval_intent(query: str) -> RetrievalIntent:
    """
    Heuristic intent (no LLM). Used to pick vector-heavy vs keyword-heavy vs hybrid
    retrieval and to skip optional stages.
    """
    q = (query or "").strip()
    if not q:
        return "hybrid"
    if _DEPENDENCY_HINTS.search(q):
        return "dependency"
    bm25_w, vec_w = QueryClassifier.classify(q)
    if vec_w >= 0.72:
        return "semantic"
    if bm25_w >= 0.48:
        return "keyword"
    return "hybrid"


def context_looks_weak(
    sources: List[dict],
    *,
    min_sources: int = 1,
    min_best_relevance: float = 0.28,
) -> bool:
    """
    True if we should run a second, wider retrieval pass (progressive retrieval).

    Relevance is whatever build_context attached (typically 1 - distance for cosine-like).
    """
    if not sources or len(sources) < min_sources:
        return True
    best = 0.0
    for s in sources:
        r = s.get("relevance")
        if r is None:
            continue
        try:
            best = max(best, float(r))
        except (TypeError, ValueError):
            continue
    return best < min_best_relevance
