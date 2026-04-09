"""
HTTP API package. Primary surface: ``search_api`` (RAG + dashboard), started via ``scripts/start_api.py``.
"""

from .search_api import SearchAPIHandler, start_search_api

__all__ = ["SearchAPIHandler", "start_search_api"]
