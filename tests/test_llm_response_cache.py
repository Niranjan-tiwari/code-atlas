"""Tests for LLM response cache (exact + semantic scaffolding)."""

import pytest


def test_normalize_question():
    from src.ai.llm_response_cache import normalize_question

    assert normalize_question("  Hello   World\n") == "hello world"
    assert normalize_question("") == ""


def test_exact_key_stable():
    from src.ai.llm_response_cache import cache_key_parts, exact_key_hash

    a = cache_key_parts("How does auth work?", None, 5, None, 0.3)
    b = cache_key_parts("  how does auth work?  ", None, 5, None, 0.3)
    assert exact_key_hash(a) == exact_key_hash(b)


def test_param_hash_excludes_question():
    from src.ai.llm_response_cache import cache_key_parts, exact_key_hash, param_hash_only

    p1 = cache_key_parts("q1", "repo-a", 5, "openai", 0.3)
    p2 = cache_key_parts("q2", "repo-a", 5, "openai", 0.3)
    assert exact_key_hash(p1) != exact_key_hash(p2)
    assert param_hash_only(p1) == param_hash_only(p2)


def test_llm_query_cache_l0_roundtrip():
    from src.ai.llm_response_cache import LLMQueryCache, CachedLLMPayload

    c = LLMQueryCache(
        {
            "enabled": True,
            "ttl_seconds": 3600,
            "l1_max_size": 50,
            "redis": {"enabled": False},
            "semantic": {"enabled": False},
        }
    )
    assert c.enabled
    emb = lambda texts: [[0.1, 0.2] for _ in texts]  # noqa: E731
    miss = c.try_get("What is X?", None, 5, None, 0.3, emb)
    assert miss is None

    payload = CachedLLMPayload(
        answer="A",
        sources=[],
        provider="p",
        model="m",
        tokens_used=1,
        cost_estimate=0.0,
        context_length=0,
        query="What is X?",
    )
    c.store("What is X?", None, 5, None, 0.3, payload, emb)
    hit = c.try_get("What is X?", None, 5, None, 0.3, emb)
    assert hit is not None
    layer, got = hit
    assert layer == "exact_l0"
    assert got.answer == "A"


def test_load_llm_query_cache_config_missing_file():
    from src.ai.llm_response_cache import load_llm_query_cache_config

    cfg = load_llm_query_cache_config("/nonexistent/ai_config.json")
    assert cfg["enabled"] is False
