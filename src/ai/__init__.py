"""
AI components for Code Atlas
Vector DB, RAG, LLM integration, Query Engine

Heavy deps (qdrant-client, sentence-transformers) load when you import RAGRetriever / QueryEngine,
so ``from src.ai.llm.manager import LLMManager`` works with just ``openai`` etc.
"""

__version__ = "1.0.0"

__all__ = ["RAGRetriever", "QueryEngine"]


def __getattr__(name: str):
    if name == "RAGRetriever":
        from .rag import RAGRetriever

        return RAGRetriever
    if name == "QueryEngine":
        from .query_engine import QueryEngine

        return QueryEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
