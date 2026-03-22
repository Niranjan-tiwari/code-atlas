"""
Cross-Encoder Reranking Module

After vector search returns top-k results, rerank them using a cross-encoder
that sees query + document together. Much more accurate than vector similarity alone.

Reranker options (priority order):
  1. FlashRank - Ultra-fast, ~4MB, CPU-friendly, no PyTorch (ms-marco-TinyBERT or MiniLM-L-12)
  2. BAAI/bge-reranker-v2-m3 - Best accuracy, needs sentence-transformers
  3. SimpleReranker - Keyword fallback when no model available
"""

import logging
import os
from typing import List, Dict, Optional

logger = logging.getLogger("reranker")

# RERANKER env: flashrank | bge | simple
RERANKER_CHOICE = os.environ.get("RERANKER", "flashrank")
FLASHRANK_MODEL = os.environ.get("FLASHRANK_MODEL", "ms-marco-TinyBERT-L-2-v2")


class FlashRankReranker:
    """
    FlashRank reranker - ultra-fast, ~4MB, runs on CPU without lag.
    Uses ms-marco-TinyBERT-L-2-v2 (default) or ms-marco-MiniLM-L-12-v2 (best).
    No PyTorch/Transformers required.
    """
    
    def __init__(self, model_name: str = None, max_length: int = 256):
        self.model_name = model_name or FLASHRANK_MODEL
        self.max_length = max_length  # Smaller = faster (query + doc truncated)
        self.ranker = None
        self._load()
    
    def _load(self):
        try:
            from flashrank import Ranker, RerankRequest
            self.Ranker = Ranker
            self.RerankRequest = RerankRequest
            self.ranker = Ranker(model_name=self.model_name, max_length=self.max_length)
            logger.info(f"FlashRank loaded: {self.model_name} (max_length={self.max_length})")
        except ImportError:
            logger.warning("FlashRank not installed. pip install flashrank")
            self.ranker = None
        except Exception as e:
            logger.warning(f"Could not load FlashRank: {e}")
            self.ranker = None
    
    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: Optional[int] = None
    ) -> List[Dict]:
        if not self.ranker or not candidates:
            for c in candidates:
                c['rerank_score'] = c.get('distance', 0.0) or 0.0
            return candidates[:top_k] if top_k else candidates
        
        try:
            passages = []
            for i, c in enumerate(candidates):
                text = c.get('code', '') or c.get('document', '')
                if len(text) > 1500:
                    text = text[:1500] + "..."
                passages.append({"id": i, "text": text})
            
            req = self.RerankRequest(query=query, passages=passages)
            results = self.ranker.rerank(req)
            
            # Build id -> score map
            score_map = {r["id"]: r["score"] for r in results}
            
            for i, c in enumerate(candidates):
                c['rerank_score'] = float(score_map.get(i, 0.0))
                if 'original_distance' not in c:
                    c['original_distance'] = c.get('distance')
            
            reranked = sorted(candidates, key=lambda x: x.get('rerank_score', 0.0), reverse=True)
            logger.info(f"FlashRank reranked {len(reranked)} candidates")
            return reranked[:top_k] if top_k else reranked
            
        except Exception as e:
            logger.error(f"FlashRank error: {e}")
            return candidates[:top_k] if top_k else candidates
    
    def is_available(self) -> bool:
        return self.ranker is not None


def get_best_reranker():
    """
    Get best available reranker.
    Priority: FlashRank > BAAI/bge-reranker > SimpleReranker
    Override with RERANKER=flashrank|bge|simple
    """
    choice = RERANKER_CHOICE.lower()
    
    if choice == "flashrank":
        r = FlashRankReranker()
        if r.is_available():
            return r
        logger.info("FlashRank not available, trying BGE reranker...")
    
    if choice in ("flashrank", "bge"):
        r = Reranker()
        if r.is_available():
            return r
        logger.info("BGE reranker not available, using SimpleReranker")
    
    return SimpleReranker()


class Reranker:
    """
    Cross-encoder reranker (BAAI/bge-reranker-v2-m3) via sentence-transformers.
    Best accuracy, requires PyTorch. Use FlashRankReranker for CPU speed.
    """
    
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        """
        Initialize reranker
        
        Args:
            model_name: HuggingFace model name for reranking
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self._load_model()
    
    def _load_model(self):
        """Load reranking model"""
        try:
            from sentence_transformers import CrossEncoder
            
            logger.info(f"Loading reranker model: {self.model_name}")
            self.model = CrossEncoder(self.model_name, max_length=512)
            logger.info("✅ Reranker model loaded")
            
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            logger.warning("Reranking will be disabled")
            self.model = None
            
        except Exception as e:
            logger.warning(f"Could not load reranker model: {e}")
            logger.warning("Falling back to no reranking")
            self.model = None
    
    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: Optional[int] = None
    ) -> List[Dict]:
        """
        Rerank search results using cross-encoder
        
        Args:
            query: Search query
            candidates: List of candidate dicts with 'code' and other fields
            top_k: Return top k results (None = return all)
            
        Returns:
            Reranked list of candidates with 'rerank_score' added
        """
        if not self.model or not candidates:
            # No reranking available, return as-is
            for candidate in candidates:
                candidate['rerank_score'] = candidate.get('distance', 0.0) or 0.0
            return candidates[:top_k] if top_k else candidates
        
        try:
            # Prepare query-document pairs
            pairs = []
            for candidate in candidates:
                code = candidate.get('code', '') or candidate.get('document', '')
                # Truncate code if too long (model has max_length)
                if len(code) > 2000:
                    code = code[:2000] + "..."
                pairs.append([query, code])
            
            # Score pairs
            logger.debug(f"Reranking {len(pairs)} candidates...")
            scores = self.model.predict(pairs)
            
            # Add scores to candidates
            for i, candidate in enumerate(candidates):
                candidate['rerank_score'] = float(scores[i])
                # Keep original distance for reference
                if 'original_distance' not in candidate:
                    candidate['original_distance'] = candidate.get('distance')
            
            # Sort by rerank score (higher = more relevant)
            reranked = sorted(
                candidates,
                key=lambda x: x.get('rerank_score', 0.0),
                reverse=True
            )
            
            logger.info(
                f"Reranked {len(reranked)} candidates. "
                f"Top score: {reranked[0].get('rerank_score', 0):.4f}"
            )
            
            return reranked[:top_k] if top_k else reranked
            
        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            # Return original order on error
            return candidates[:top_k] if top_k else candidates
    
    def is_available(self) -> bool:
        """Check if reranking is available"""
        return self.model is not None


class SimpleReranker:
    """
    Simple reranker using keyword matching (fallback when model unavailable)
    
    Scores based on:
    - Exact keyword matches
    - TF-IDF similarity
    - Code structure matches
    """
    
    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: Optional[int] = None
    ) -> List[Dict]:
        """Simple keyword-based reranking"""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for candidate in candidates:
            code = (candidate.get('code', '') or candidate.get('document', '')).lower()
            file_path = candidate.get('file', '').lower()
            repo_name = candidate.get('repo', '').lower()
            
            score = 0.0
            
            # Exact keyword matches in code
            for word in query_words:
                if len(word) >= 3:
                    if word in code:
                        score += 1.0
                    if word in file_path:
                        score += 2.0  # File path match is stronger
                    if word in repo_name:
                        score += 3.0  # Repo name match is strongest
            
            # Normalize score
            candidate['rerank_score'] = score / max(len(query_words), 1)
        
        # Sort by score
        reranked = sorted(
            candidates,
            key=lambda x: x.get('rerank_score', 0.0),
            reverse=True
        )
        
        return reranked[:top_k] if top_k else reranked
