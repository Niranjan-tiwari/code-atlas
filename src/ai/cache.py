"""
Caching Layer for RAG Pipeline

Multi-tier cache:
1. LRU (in-memory) for hot queries - instant response
2. Redis for persistent cache across restarts - fast (1-5ms)
3. Embedding cache - avoid recomputing expensive embeddings

Cache invalidation:
- TTL-based expiry (default: 24 hours for embeddings, 1 hour for queries)
- Manual invalidation on re-index
- Key: hash of query + parameters
"""

import hashlib
import json
import logging
import time
from functools import lru_cache, wraps
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import OrderedDict
import threading

logger = logging.getLogger("rag_cache")


class LRUCache:
    """
    Thread-safe LRU cache with TTL support.
    Used as in-memory L1 cache for hot queries.
    """
    
    def __init__(self, max_size: int = 500, default_ttl: int = 3600):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._lock:
            ttl = ttl or self._default_ttl
            expiry = time.time() + ttl
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, expiry)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
    
    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def stats(self) -> Dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0
        }


class RedisCache:
    """
    Redis-backed L2 cache for persistent caching across restarts.
    Falls back gracefully if Redis is unavailable.
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        prefix: str = "rag:",
        default_ttl: int = 86400
    ):
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._client = None
        self._available = False
        self._hits = 0
        self._misses = 0
        
        try:
            import redis
            self._client = redis.Redis(
                host=host, port=port, db=db,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=False
            )
            self._client.ping()
            self._available = True
            logger.info(f"Redis cache connected: {host}:{port}/{db}")
        except ImportError:
            logger.info("Redis not installed (pip install redis). Using in-memory cache only.")
        except Exception as e:
            logger.info(f"Redis unavailable ({e}). Using in-memory cache only.")
    
    def get(self, key: str) -> Optional[Any]:
        if not self._available:
            return None
        try:
            full_key = f"{self._prefix}{key}"
            data = self._client.get(full_key)
            if data:
                self._hits += 1
                return json.loads(data)
            self._misses += 1
            return None
        except Exception as e:
            logger.debug(f"Redis get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        if not self._available:
            return
        try:
            full_key = f"{self._prefix}{key}"
            ttl = ttl or self._default_ttl
            data = json.dumps(value, default=str)
            self._client.setex(full_key, ttl, data)
        except Exception as e:
            logger.debug(f"Redis set error: {e}")
    
    def invalidate(self, key: str):
        if not self._available:
            return
        try:
            self._client.delete(f"{self._prefix}{key}")
        except Exception:
            pass
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching a pattern (e.g., 'emb:*')"""
        if not self._available:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = self._client.scan(
                    cursor, match=f"{self._prefix}{pattern}", count=100
                )
                if keys:
                    self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug(f"Redis invalidate_pattern error: {e}")
    
    def clear(self):
        if not self._available:
            return
        try:
            self.invalidate_pattern("*")
        except Exception:
            pass
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    def stats(self) -> Dict:
        total = self._hits + self._misses
        info = {
            "available": self._available,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0
        }
        if self._available:
            try:
                db_size = self._client.dbsize()
                info["db_size"] = db_size
            except Exception:
                pass
        return info


class RAGCache:
    """
    Multi-tier cache for RAG pipeline.
    
    L1: In-memory LRU (fastest, limited size)
    L2: Redis (persistent, larger capacity)
    
    Cache types:
    - embedding: Cached embeddings (TTL: 24h)
    - query: Cached search results (TTL: 1h)
    - hyde: Cached HyDE expansions (TTL: 2h)
    - rerank: Cached reranking scores (TTL: 1h)
    """
    
    # TTL defaults in seconds
    TTL_EMBEDDING = 86400     # 24 hours
    TTL_QUERY = 3600          # 1 hour
    TTL_HYDE = 7200           # 2 hours
    TTL_RERANK = 3600         # 1 hour
    TTL_SEARCH_RESULT = 1800  # 30 minutes
    
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        l1_max_size: int = 500,
        enable_redis: bool = True
    ):
        self.l1 = LRUCache(max_size=l1_max_size, default_ttl=self.TTL_QUERY)
        self.l2 = RedisCache(
            host=redis_host, port=redis_port, db=redis_db
        ) if enable_redis else None
        
        logger.info(
            f"RAG Cache initialized: L1={l1_max_size} slots, "
            f"L2/Redis={'connected' if self.l2 and self.l2.is_available else 'disabled'}"
        )
    
    @staticmethod
    def _make_key(namespace: str, query: str, **kwargs) -> str:
        """Generate deterministic cache key from query + params"""
        key_data = {"q": query}
        key_data.update(sorted(kwargs.items()))
        raw = json.dumps(key_data, sort_keys=True, default=str)
        hash_val = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{namespace}:{hash_val}"
    
    def get(self, namespace: str, query: str, **kwargs) -> Optional[Any]:
        """
        Get from cache (L1 first, then L2).
        Returns None on miss.
        """
        key = self._make_key(namespace, query, **kwargs)
        
        # L1 check
        result = self.l1.get(key)
        if result is not None:
            logger.debug(f"L1 cache hit: {namespace}")
            return result
        
        # L2 check
        if self.l2 and self.l2.is_available:
            result = self.l2.get(key)
            if result is not None:
                logger.debug(f"L2 cache hit: {namespace}")
                # Promote to L1
                self.l1.set(key, result)
                return result
        
        return None
    
    def set(
        self,
        namespace: str,
        query: str,
        value: Any,
        ttl: Optional[int] = None,
        **kwargs
    ):
        """Set in both L1 and L2 caches"""
        key = self._make_key(namespace, query, **kwargs)
        
        # Determine TTL by namespace
        if ttl is None:
            ttl_map = {
                "embedding": self.TTL_EMBEDDING,
                "query": self.TTL_QUERY,
                "hyde": self.TTL_HYDE,
                "rerank": self.TTL_RERANK,
                "search": self.TTL_SEARCH_RESULT,
            }
            ttl = ttl_map.get(namespace, self.TTL_QUERY)
        
        self.l1.set(key, value, ttl)
        if self.l2 and self.l2.is_available:
            self.l2.set(key, value, ttl)
    
    def invalidate_namespace(self, namespace: str):
        """Invalidate all cached items in a namespace"""
        self.l1.clear()
        if self.l2 and self.l2.is_available:
            self.l2.invalidate_pattern(f"{namespace}:*")
        logger.info(f"Cache invalidated: {namespace}")
    
    def invalidate_all(self):
        """Clear all caches (e.g., on re-index)"""
        self.l1.clear()
        if self.l2 and self.l2.is_available:
            self.l2.clear()
        logger.info("All caches cleared")
    
    def stats(self) -> Dict:
        """Get cache statistics"""
        stats = {
            "l1": self.l1.stats(),
        }
        if self.l2:
            stats["l2_redis"] = self.l2.stats()
        return stats


def cached_search(cache: RAGCache, namespace: str = "search"):
    """
    Decorator to cache search function results.
    
    Usage:
        @cached_search(rag_cache, "search")
        def search_code(query, n_results=10, **kwargs):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self_or_query, *args, **kwargs):
            # Handle both bound methods and plain functions
            if hasattr(self_or_query, '__class__') and not isinstance(self_or_query, str):
                instance = self_or_query
                query = args[0] if args else kwargs.get('query', '')
                extra_kwargs = kwargs
            else:
                instance = None
                query = self_or_query
                extra_kwargs = kwargs
            
            # Build cache params
            cache_params = {
                k: v for k, v in extra_kwargs.items()
                if k in ('n_results', 'repo_filter', 'language_filter', 'language')
            }
            
            # Check cache
            cached = cache.get(namespace, query, **cache_params)
            if cached is not None:
                logger.debug(f"Cache hit for {namespace}: {query[:50]}...")
                return cached
            
            # Execute and cache
            if instance is not None:
                result = func(instance, *args, **kwargs)
            else:
                result = func(self_or_query, *args, **kwargs)
            
            if result:
                cache.set(namespace, query, result, **cache_params)
            
            return result
        
        return wrapper
    return decorator


# Global cache instance (lazy-initialized)
_global_cache: Optional[RAGCache] = None
_cache_lock = threading.Lock()


def get_rag_cache(
    redis_host: str = "localhost",
    redis_port: int = 6379,
    enable_redis: bool = True
) -> RAGCache:
    """Get or create the global RAG cache instance"""
    global _global_cache
    with _cache_lock:
        if _global_cache is None:
            _global_cache = RAGCache(
                redis_host=redis_host,
                redis_port=redis_port,
                enable_redis=enable_redis
            )
        return _global_cache
