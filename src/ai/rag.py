"""
RAG (Retrieval-Augmented Generation) Pipeline - MAXIMUM SPEED

Performance:
1. UNIFIED collection: 1 query instead of 75 (~0.05s vs ~0.6s)
2. Pre-warmed embedding model (no cold-start)
3. Pre-computed query embedding (embed once)
4. Fallback to per-repo parallel search if unified not available
"""

import logging
import time
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import chromadb
from chromadb.config import Settings


class RAGRetriever:
    """Ultra-fast code retriever"""
    
    def __init__(self, persist_directory: str = "./data/vector_db"):
        self.persist_directory = persist_directory
        self.logger = logging.getLogger("rag_retriever")
        
        # ChromaDB client
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Embedding function: try Ollama bge-m3 (1024 dim) first, fall back to default (384 dim)
        self._emb_fn = None
        try:
            from src.ai.embeddings.ollama_embed import get_best_embedding_function
            self._emb_fn = get_best_embedding_function()
        except Exception:
            pass
        
        if self._emb_fn is None:
            self._emb_fn = chromadb.utils.embedding_functions.DefaultEmbeddingFunction()
        
        # Pre-warm
        try:
            self._emb_fn(["warmup"])
        except Exception:
            pass
        
        emb_name = getattr(self._emb_fn, 'model', 'default')
        self.logger.info(f"Embedding model: {emb_name}")
        
        # Try unified collection first (fastest path)
        self._unified = None
        try:
            uc = self.client.get_collection("unified_code")
            if uc.count() > 0:
                self._unified = uc
                self.logger.info(f"Using unified collection ({uc.count()} chunks)")
        except Exception:
            pass
        
        # Fallback: cache per-repo collections
        self._collections: Dict[str, object] = {}
        if not self._unified:
            for col in self.client.list_collections():
                if col.name.startswith("repo_"):
                    self._collections[col.name] = col
            self.logger.info(f"Using per-repo collections ({len(self._collections)} repos)")
        
        # Lazy cache
        self._repo_cache: Optional[List[Dict]] = None
    
    def get_available_repos(self) -> List[Dict]:
        """Get indexed repos from per-repo collections (accurate counts)"""
        if self._repo_cache is None:
            self._repo_cache = []
            # Always use per-repo collections for accurate listing
            for col_meta in self.client.list_collections():
                if not col_meta.name.startswith("repo_"):
                    continue
                try:
                    col = self.client.get_collection(col_meta.name)
                    count = col.count()
                    if count > 0:
                        self._repo_cache.append({
                            "name": col_meta.name.replace("repo_", ""),
                            "collection": col_meta.name,
                            "chunks": count
                        })
                except Exception:
                    pass
            self._repo_cache.sort(key=lambda x: x["name"])
        return self._repo_cache
    
    def search_code(
        self,
        query: str,
        n_results: int = 10,
        repo_filter: Optional[str] = None,
        language_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Ultra-fast search. Uses unified collection (1 query) when available.
        
        Speed: ~0.1s for 4000 chunks across 73 repos
        """
        query_lower = query.lower()
        query_keywords = set(query_lower.split())
        
        # Embed once
        query_emb = self._emb_fn([query])
        
        # Get raw results
        if self._unified:
            raw = self._search_unified(query_emb, n_results * 3, repo_filter, language_filter)
        else:
            raw = self._search_per_repo(query_emb, n_results, repo_filter, language_filter)
        
        # Keyword boost scoring
        for r in raw:
            dist = r.get("distance", 2.0) or 2.0
            boost = 0.0
            repo = r.get("repo", "").lower().replace("-", " ").replace("_", " ")
            fpath = r.get("file", "").lower()
            code = r.get("code", "").lower()
            for kw in query_keywords:
                if len(kw) >= 3:
                    if kw in repo: boost += 1.0
                    if kw in fpath: boost += 0.4
                    if kw in code: boost += 0.2
            r["hybrid_score"] = dist - boost
            r["keyword_boost"] = boost
        
        raw.sort(key=lambda x: x.get("hybrid_score", float("inf")))
        return raw[:n_results]
    
    def _search_unified(self, query_emb, n_results, repo_filter=None, language_filter=None):
        """Single query on unified collection — fastest path"""
        where = {}
        if repo_filter:
            where["repo"] = repo_filter
        if language_filter:
            where["language"] = language_filter.upper()
        
        try:
            results = self._unified.query(
                query_embeddings=query_emb,
                n_results=min(n_results, self._unified.count()),
                where=where if where else None
            )
        except Exception:
            # Retry without filters
            results = self._unified.query(
                query_embeddings=query_emb,
                n_results=min(n_results, self._unified.count())
            )
        
        return self._format_results(results, "unified_code")
    
    def _search_per_repo(self, query_emb, n_results, repo_filter=None, language_filter=None):
        """Parallel search across per-repo collections (fallback)"""
        if repo_filter:
            col = self._collections.get(f"repo_{repo_filter}")
            if col:
                return self._query_one(col, query_emb, n_results, language_filter)
            return []
        
        all_results = []
        cols = list(self._collections.values())
        per_col = min(n_results, 3)
        
        with ThreadPoolExecutor(max_workers=min(16, len(cols))) as ex:
            futs = {ex.submit(self._query_one, c, query_emb, per_col, language_filter): c for c in cols}
            for f in as_completed(futs):
                try:
                    all_results.extend(f.result())
                except Exception:
                    pass
        return all_results
    
    def _query_one(self, collection, query_emb, n_results, language_filter=None):
        """Query single collection with pre-computed embedding"""
        where = {"language": language_filter.upper()} if language_filter else None
        try:
            results = collection.query(query_embeddings=query_emb, n_results=n_results, where=where)
        except Exception:
            try:
                results = collection.query(query_embeddings=query_emb, n_results=n_results)
            except Exception:
                return []
        return self._format_results(results, collection.name)
    
    def _format_results(self, results, collection_name):
        """Format ChromaDB results into standard dicts"""
        formatted = []
        if results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                formatted.append({
                    "code": results["documents"][0][i],
                    "repo": meta.get("repo", collection_name.replace("repo_", "")),
                    "file": meta.get("file", "unknown"),
                    "language": meta.get("language", "unknown"),
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    "chunk_idx": meta.get("chunk", 0),
                    "total_chunks": meta.get("total_chunks", 1),
                    "collection": collection_name
                })
        return formatted
    
    def detect_repo_in_query(self, query: str) -> Optional[str]:
        """
        Auto-detect a repo name from a natural language query.
        Uses exact match first, then fuzzy matching with normalization.
        
        Examples:
            "explain whatsapp-es-reporting" → "whatsapp-es-reporting"
            "how does whatsapp_es_reporting work" → "whatsapp-es-reporting"
            "what does ProcessMessage do in rcs-sender" → "rcs-sender"
        """
        repos = self.get_available_repos()
        repo_names = [r["name"] for r in repos]
        if not repo_names:
            return None
        
        q_lower = query.lower().strip()
        
        # Normalize: replace underscores with hyphens for matching
        def norm(s):
            return s.lower().replace("_", "-").replace(" ", "-")
        
        q_norm = norm(q_lower)
        
        # 1. Exact match: check if any repo name appears in the query
        #    Sort by longest name first to prefer specific matches
        for name in sorted(repo_names, key=len, reverse=True):
            name_lower = name.lower()
            name_norm = norm(name)
            # Check both original and normalized forms in query
            if name_lower in q_lower or name_norm in q_norm:
                return name
        
        # 2. Token-based fuzzy match: split query into words, check combinations
        words = q_lower.replace("-", " ").replace("_", " ").split()
        # Build repo name lookup (normalized → original)
        repo_lookup = {norm(n): n for n in repo_names}
        
        # Try 1-4 word combinations (most repo names are 1-4 words)
        for window in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - window + 1):
                candidate = "-".join(words[i:i + window])
                if candidate in repo_lookup:
                    return repo_lookup[candidate]
        
        return None

    # Backward compat
    def _search_collection_fast(self, collection, query_emb, n_results, language_filter=None):
        return self._query_one(collection, query_emb, n_results, language_filter)
    
    def _search_collection(self, collection, query, n_results, language_filter=None):
        return self._query_one(collection, self._emb_fn([query]), n_results, language_filter)
    
    def build_context(self, query, n_results=5, repo_filter=None, max_context_length=8000):
        """Build context string for LLM"""
        results = self.search_code(query, n_results=n_results, repo_filter=repo_filter)
        if not results:
            return "", []
        parts, sources, total = [], [], 0
        for i, r in enumerate(results, 1):
            s = f"--- Source {i}: {r['repo']}/{r['file']} ({r['language']}) ---\n{r['code']}\n"
            if total + len(s) > max_context_length:
                break
            parts.append(s)
            sources.append({"index": i, "repo": r["repo"], "file": r["file"],
                            "language": r["language"], "relevance": 1 - (r.get("distance", 0) or 0)})
            total += len(s)
        return "\n".join(parts), sources
    
    def get_repo_summary(self, repo_name):
        """Get repo summary"""
        col = self._collections.get(f"repo_{repo_name}")
        if not col:
            return {"name": repo_name, "chunks": 0, "indexed": False}
        try:
            count = col.count()
            if count > 0:
                sample = col.peek(limit=min(count, 20))
                langs = {m.get("language") for m in (sample.get("metadatas") or []) if "language" in m}
                files = {m.get("file") for m in (sample.get("metadatas") or []) if "file" in m}
                return {"name": repo_name, "chunks": count, "languages": list(langs),
                        "sample_files": list(files)[:10], "indexed": True}
            return {"name": repo_name, "chunks": 0, "indexed": False}
        except Exception:
            return {"name": repo_name, "chunks": 0, "indexed": False}
