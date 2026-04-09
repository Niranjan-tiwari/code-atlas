"""Tests for latency-oriented retrieval routing (no Qdrant)."""

from src.ai.retrieval_router import classify_retrieval_intent, context_looks_weak


def test_classify_semantic_question():
    assert classify_retrieval_intent("how does authentication work in this codebase?") == "semantic"


def test_classify_dependency():
    assert classify_retrieval_intent("dependency graph for redis imports") == "dependency"


def test_context_looks_weak():
    assert context_looks_weak([])
    assert context_looks_weak([{"relevance": 0.1}], min_best_relevance=0.28)
    assert not context_looks_weak([{"relevance": 0.5}], min_best_relevance=0.28)
