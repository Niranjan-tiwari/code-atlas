"""
Embedding Function for ChromaDB using BAAI/bge-m3.

Uses sentence-transformers library directly (not Ollama HTTP) for speed.
Falls back to Ollama if sentence-transformers fails.

bge-m3 vs default (all-MiniLM-L6-v2):
  - 1024 dims vs 384 dims   = 2.7x more semantic precision
  - 8K token context vs 512  = full functions, no truncation
  - Code + multilingual aware
  - ~0.27s/text on CPU (one-time indexing cost)

Setup:
  pip install sentence-transformers  # already installed via chromadb
  # Model auto-downloads on first use (~1.2 GB)
"""

import logging
import os
from typing import List, Optional
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

logger = logging.getLogger("embeddings")

# Model choices (pick via EMBED_MODEL env var)
MODELS = {
    "bge-m3": {"name": "BAAI/bge-m3", "dims": 1024},
    "bge-small": {"name": "BAAI/bge-small-en-v1.5", "dims": 384},
    "nomic": {"name": "nomic-ai/nomic-embed-text-v1.5", "dims": 768},
    "default": {"name": "all-MiniLM-L6-v2", "dims": 384},
}

DEFAULT_MODEL = os.environ.get("EMBED_MODEL", "bge-small")


class SentenceTransformerEmbedding(EmbeddingFunction):
    """ChromaDB-compatible embedding using sentence-transformers (local, fast)"""
    
    def __init__(self, model_key: str = DEFAULT_MODEL):
        self.model_key = model_key
        self.model_info = MODELS.get(model_key, MODELS["bge-m3"])
        self.model_name = self.model_info["name"]
        self.dims = self.model_info["dims"]
        self.model = None  # Lazy load
        self._loaded = False
    
    def _load(self):
        if self._loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}...")
            
            # Trust remote code needed for some models
            kwargs = {}
            if "nomic" in self.model_name:
                kwargs["trust_remote_code"] = True
            
            self.model = SentenceTransformer(self.model_name, **kwargs)
            self._loaded = True
            logger.info(f"Loaded {self.model_name} ({self.dims} dims)")
        except Exception as e:
            logger.error(f"Failed to load {self.model_name}: {e}")
            raise
    
    def __call__(self, input: Documents) -> Embeddings:
        """Embed documents using sentence-transformers"""
        if not input:
            return []
        
        self._load()
        
        try:
            embeddings = self.model.encode(
                input, 
                batch_size=64,
                show_progress_bar=False,
                normalize_embeddings=True  # Cosine similarity ready
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [[0.0] * self.dims] * len(input)


class OllamaEmbeddingFunction(EmbeddingFunction):
    """ChromaDB-compatible embedding using Ollama HTTP (slower, but works with any Ollama model)"""
    
    def __init__(self, model: str = "bge-m3", base_url: str = "http://localhost:11434"):
        import requests
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._requests = requests
        self._available = None
    
    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            resp = self._requests.get(f"{self.base_url}/api/tags", timeout=3)
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            self._available = any(self.model in m for m in models)
            return self._available
        except Exception:
            self._available = False
            return False
    
    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        
        embeddings = []
        batch_size = 8
        for i in range(0, len(input), batch_size):
            batch = input[i:i + batch_size]
            try:
                resp = self._requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=300
                )
                resp.raise_for_status()
                embeddings.extend(resp.json().get("embeddings", []))
            except Exception as e:
                logger.error(f"Ollama embed error: {e}")
                dim = len(embeddings[0]) if embeddings else 1024
                embeddings.extend([[0.0] * dim] * len(batch))
        
        return embeddings


def get_best_embedding_function() -> Optional[EmbeddingFunction]:
    """
    Get the best available embedding function.
    Priority: sentence-transformers (bge-small default) > Ollama bge-m3 > ChromaDB default
    Default: bge-small (384 dims) - matches reindex and unified collection.
    """
    model_key = os.environ.get("EMBED_MODEL", "bge-small")
    
    # 1. Try sentence-transformers (fastest)
    try:
        emb = SentenceTransformerEmbedding(model_key)
        emb._load()  # Verify it works
        logger.info(f"Using sentence-transformers: {emb.model_name} ({emb.dims} dims)")
        return emb
    except Exception as e:
        logger.warning(f"sentence-transformers not available: {e}")
    
    # 2. Try Ollama (slower but works)
    try:
        ollama = OllamaEmbeddingFunction()
        if ollama.is_available():
            logger.info("Using Ollama bge-m3 embeddings")
            return ollama
    except Exception:
        pass
    
    # 3. Fall back to ChromaDB default
    logger.info("Using ChromaDB default embeddings (all-MiniLM-L6-v2, 384 dims)")
    return None
