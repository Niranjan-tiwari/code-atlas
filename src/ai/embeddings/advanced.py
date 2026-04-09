"""
Advanced Embedding Models for Code

Supports:
- jina-embeddings-v2-base-code (768 dim, 8k context, code-specific)
- CodeBERT (Microsoft)
- OpenAI text-embedding-3-small (1536 dim)
- Local sentence-transformers (MiniLM fallback)
"""

import logging
from typing import List, Optional, Union
import numpy as np

from ..llm.env_keys import OPENAI, from_env

logger = logging.getLogger("advanced_embeddings")


class AdvancedEmbeddingModel:
    """
    Advanced embedding model wrapper supporting multiple providers
    """
    
    def __init__(self, model_name: str = "jina-code"):
        """
        Initialize embedding model
        
        Args:
            model_name: One of:
                - "jina-code": jina-embeddings-v2-base-code (best for code)
                - "codebert": microsoft/codebert-base
                - "openai": text-embedding-3-small
                - "local": sentence-transformers all-MiniLM-L6-v2 (fallback)
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.dimensions = 384  # Default
        self._load_model()
    
    def _load_model(self):
        """Load the embedding model"""
        if self.model_name == "jina-code":
            self._load_jina()
        elif self.model_name == "codebert":
            self._load_codebert()
        elif self.model_name == "openai":
            self._load_openai()
        else:
            self._load_local_minilm()

    def _load_local_minilm(self):
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading all-MiniLM-L6-v2 (local fallback)...")
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
            self.dimensions = 384
            logger.info("✅ Local embeddings (384 dim)")
        except Exception as e:
            logger.warning("sentence-transformers not available for local fallback: %s", e)
            self.model = None

    def _load_jina(self):
        """Load Jina embeddings v2 base code"""
        try:
            from sentence_transformers import SentenceTransformer
            
            logger.info("Loading jina-embeddings-v2-base-code...")
            self.model = SentenceTransformer('jinaai/jina-embeddings-v2-base-code')
            self.dimensions = 768
            logger.info("✅ Jina code embeddings loaded (768 dim)")
            
        except ImportError:
            logger.warning("sentence-transformers not installed for Jina embeddings")
            self.model = None
        except Exception as e:
            logger.warning(f"Could not load Jina embeddings: {e}")
            self.model = None
    
    def _load_codebert(self):
        """Load CodeBERT embeddings"""
        try:
            from transformers import AutoModel, AutoTokenizer
            import torch
            
            logger.info("Loading microsoft/codebert-base...")
            self.tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
            self.model = AutoModel.from_pretrained("microsoft/codebert-base")
            self.dimensions = 768
            logger.info("✅ CodeBERT loaded (768 dim)")
            
        except ImportError:
            logger.warning("transformers/torch not installed for CodeBERT")
            self.model = None
        except Exception as e:
            logger.warning(f"Could not load CodeBERT: {e}")
            self.model = None
    
    def _load_openai(self):
        """Load OpenAI embeddings"""
        try:
            import openai
            
            api_key = from_env(OPENAI)
            if not api_key:
                logger.warning("%s not set, cannot use OpenAI embeddings", OPENAI)
                self.model = None
                return
            
            self.model = "openai"  # Marker
            self.dimensions = 1536
            logger.info("✅ OpenAI embeddings ready (1536 dim)")
            
        except ImportError:
            logger.warning("openai package not installed")
            self.model = None
    
    def embed(self, texts: Union[str, List[str]]) -> Union[np.ndarray, List[np.ndarray]]:
        """
        Generate embeddings for text(s)
        
        Args:
            texts: Single string or list of strings
            
        Returns:
            numpy array(s) of embeddings
        """
        if not self.model:
            raise RuntimeError(f"Embedding model {self.model_name} not available")
        
        is_single = isinstance(texts, str)
        if is_single:
            texts = [texts]
        
        if self.model_name == "jina-code":
            embeddings = self.model.encode(texts, convert_to_numpy=True)
        elif self.model_name == "codebert":
            embeddings = self._embed_codebert(texts)
        elif self.model_name == "openai":
            embeddings = self._embed_openai(texts)
        else:
            raise RuntimeError(f"Unknown model: {self.model_name}")
        
        return embeddings[0] if is_single else embeddings
    
    def _embed_codebert(self, texts: List[str]) -> List[np.ndarray]:
        """Embed using CodeBERT"""
        import torch
        
        embeddings = []
        for text in texts:
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True
            )
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                # Use CLS token embedding
                embedding = outputs.last_hidden_state[:, 0, :].squeeze().numpy()
                embeddings.append(embedding)
        
        return embeddings
    
    def _embed_openai(self, texts: List[str]) -> List[np.ndarray]:
        """Embed using OpenAI API"""
        import openai
        
        embeddings = []
        for text in texts:
            response = openai.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            embeddings.append(np.array(response.data[0].embedding))
        
        return embeddings
    
    def get_dimensions(self) -> int:
        """Get embedding dimensions"""
        return self.dimensions
    
    def is_available(self) -> bool:
        """Check if model is available"""
        return self.model is not None


def get_embedding_model(model_name: Optional[str] = None) -> AdvancedEmbeddingModel:
    """
    Factory function to get embedding model
    
    Args:
        model_name: Model name or None for auto-detection
        
    Returns:
        AdvancedEmbeddingModel instance
    """
    if model_name:
        return AdvancedEmbeddingModel(model_name)
    
    # Auto-detect: try jina-code first, then fallback
    for name in ["jina-code", "codebert", "openai", "local"]:
        model = AdvancedEmbeddingModel(name)
        if model.is_available():
            return model

    return AdvancedEmbeddingModel("local")
