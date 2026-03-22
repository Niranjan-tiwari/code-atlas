"""
Hybrid Search: BM25 + Vector Search

Combines:
1. BM25 (keyword-based, fast, exact matches)
2. Vector Search (semantic, understands meaning)

Best of both worlds: exact keyword matches + semantic understanding

Improvements over basic hybrid:
- Code-aware tokenization (camelCase, snake_case splitting)
- Dynamic weight tuning based on query type
- Reciprocal Rank Fusion (RRF) as alternative combining strategy
- Score normalization with min-max scaling
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
import math

logger = logging.getLogger("hybrid_search")

# Code-specific stop words to filter out
CODE_STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'this', 'that', 'these', 'those', 'it', 'its', 'my', 'your', 'our',
    'var', 'let', 'const', 'nil', 'null', 'none', 'true', 'false',
}


class BM25:
    """
    BM25 (Best Matching 25) keyword search algorithm
    
    Enhanced with code-aware tokenization:
    - Splits camelCase and snake_case identifiers
    - Handles code-specific patterns (imports, function names)
    - Filters stop words for better precision
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: List[str] = []
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0.0
        self._doc_lens: List[int] = []
    
    def index(self, documents: List[str]):
        """Index documents for BM25 search"""
        self.documents = documents
        self.doc_freqs = []
        self._doc_lens = []
        
        for doc in documents:
            terms = self._tokenize(doc)
            term_freq = {}
            for term in terms:
                term_freq[term] = term_freq.get(term, 0) + 1
            self.doc_freqs.append(term_freq)
            self._doc_lens.append(len(terms))
        
        self.avg_doc_len = sum(self._doc_lens) / len(self._doc_lens) if self._doc_lens else 0
        
        doc_count = len(documents)
        term_doc_freq: Dict[str, int] = {}
        for term_freq in self.doc_freqs:
            for term in term_freq:
                term_doc_freq[term] = term_doc_freq.get(term, 0) + 1
        
        for term, df in term_doc_freq.items():
            # Robertson-Sparck Jones IDF variant: always positive, even for
            # terms appearing in >50% of docs (important for small corpora)
            self.idf[term] = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Code-aware tokenization:
        - Split camelCase: getUserName -> get, user, name
        - Split snake_case: get_user_name -> get, user, name
        - Keep alphanumeric tokens
        - Filter stop words
        """
        # Split camelCase before lowering
        camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        camel_split = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', camel_split)
        
        # Split snake_case by replacing underscores with spaces
        underscore_split = text.replace('_', ' ')
        
        # Combine all forms: original lowered + camelCase split + underscore split
        combined = f"{text.lower()} {camel_split.lower()} {underscore_split.lower()}"
        tokens = re.findall(r'\b[a-z][a-z0-9]{1,}\b', combined)
        
        # Filter stop words and very short tokens
        return [t for t in tokens if t not in CODE_STOP_WORDS and len(t) > 1]
    
    def score(self, query: str, doc_idx: int) -> float:
        """Calculate BM25 score for query against document"""
        if doc_idx >= len(self.documents):
            return 0.0
        
        query_terms = self._tokenize(query)
        doc_freq = self.doc_freqs[doc_idx]
        doc_len = self._doc_lens[doc_idx]
        
        score = 0.0
        for term in query_terms:
            if term not in self.idf:
                continue
            tf = doc_freq.get(term, 0)
            if tf == 0:
                continue
            
            idf = self.idf[term]
            numerator = idf * tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / max(self.avg_doc_len, 1)))
            score += numerator / denominator
        
        return score
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """Search documents and return top-k results as (doc_idx, score) tuples"""
        scores = []
        for i in range(len(self.documents)):
            score = self.score(query, i)
            if score > 0:
                scores.append((i, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class QueryClassifier:
    """
    Classifies query type to dynamically adjust BM25/Vector weights.
    
    Query types:
    - keyword_heavy: "getUserById function", "import redis" -> more BM25
    - semantic_heavy: "how does authentication work?" -> more vector
    - balanced: "find database connection error handling" -> equal weights
    """
    
    # Patterns that suggest keyword-heavy queries (checked case-insensitive)
    KEYWORD_PATTERNS = [
        r'\b(function|func|def|class|struct|interface|type)\s+\w+',
        r'\b(import|from|require|include)\s+',
        r'\b(get|set|create|delete|update|find|search)\w*\b',
        r'\w+_\w+',           # snake_case
        r'\.\w+\(',           # method calls
        r'\"[^\"]+\"',        # quoted strings
    ]
    
    # Case-sensitive patterns (camelCase detection must respect case)
    KEYWORD_PATTERNS_CS = [
        r'[A-Z][a-z]+[A-Z]',  # camelCase (e.g., getUserById)
    ]
    
    # Patterns that suggest semantic/conceptual queries
    SEMANTIC_PATTERNS = [
        r'\b(how|what|why|where|when|explain|describe)\b',
        r'\b(works|implemented|designed|architecture|flow|logic)\b',
        r'\b(best practice|pattern|approach|strategy)\b',
        r'\b(similar|related|like|equivalent)\b',
    ]
    
    @classmethod
    def classify(cls, query: str) -> Tuple[float, float]:
        """
        Classify query and return (bm25_weight, vector_weight).
        
        Returns:
            Tuple of (bm25_weight, vector_weight) that sum to 1.0
        """
        query_lower = query.lower()
        
        keyword_score = sum(
            1 for pattern in cls.KEYWORD_PATTERNS
            if re.search(pattern, query, re.IGNORECASE)
        ) + sum(
            1 for pattern in cls.KEYWORD_PATTERNS_CS
            if re.search(pattern, query)
        )
        semantic_score = sum(
            1 for pattern in cls.SEMANTIC_PATTERNS
            if re.search(pattern, query_lower)
        )
        
        # Short queries with specific identifiers are keyword-heavy
        words = query.split()
        if len(words) <= 3 and keyword_score > 0:
            keyword_score += 2
        
        # Long natural language queries are semantic-heavy
        if len(words) > 6 and semantic_score > 0:
            semantic_score += 2
        
        total = keyword_score + semantic_score
        if total == 0:
            return 0.3, 0.7  # Default: favor vector search
        
        keyword_ratio = keyword_score / total
        
        # Scale: keyword_ratio=1.0 -> (0.6, 0.4), keyword_ratio=0.0 -> (0.2, 0.8)
        bm25_weight = 0.2 + (keyword_ratio * 0.4)
        vector_weight = 1.0 - bm25_weight
        
        return round(bm25_weight, 2), round(vector_weight, 2)


class HybridSearcher:
    """
    Combines BM25 (keyword) and Vector Search (semantic).
    
    Improvements:
    - Dynamic weight tuning based on query classification
    - Reciprocal Rank Fusion (RRF) as alternative combining strategy
    - Min-max score normalization
    """
    
    def __init__(self, vector_search_func, documents: List[str], metadata: List[Dict]):
        self.vector_search = vector_search_func
        self.documents = documents
        self.metadata = metadata
        self.bm25 = BM25()
        self.bm25.index(documents)
        self.classifier = QueryClassifier()
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        use_rrf: bool = False,
        auto_weight: bool = True
    ) -> List[Dict]:
        """
        Hybrid search combining BM25 and vector search.
        
        Args:
            query: Search query
            top_k: Number of results
            bm25_weight: Weight for BM25 (None = auto-detect)
            vector_weight: Weight for vector (None = auto-detect)
            use_rrf: Use Reciprocal Rank Fusion instead of score combination
            auto_weight: Automatically adjust weights based on query type
        """
        # Dynamic weight tuning
        if auto_weight and bm25_weight is None:
            bm25_weight, vector_weight = self.classifier.classify(query)
            logger.info(f"Auto weights: BM25={bm25_weight}, Vector={vector_weight}")
        else:
            bm25_weight = bm25_weight or 0.3
            vector_weight = vector_weight or 0.7
        
        # BM25 search
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        
        # Vector search
        vector_results = self.vector_search(query, top_k=top_k * 2)
        
        if use_rrf:
            return self._combine_rrf(bm25_results, vector_results, top_k)
        
        return self._combine_weighted(
            bm25_results, vector_results, bm25_weight, vector_weight, top_k
        )
    
    def _combine_weighted(
        self,
        bm25_results: List[Tuple],
        vector_results: List[Dict],
        bm25_weight: float,
        vector_weight: float,
        top_k: int
    ) -> List[Dict]:
        """Weighted score combination with min-max normalization"""
        combined_scores: Dict[int, Dict] = {}
        
        # Normalize BM25 scores to [0, 1]
        if bm25_results:
            bm25_scores = [s for _, s in bm25_results]
            min_bm25 = min(bm25_scores)
            max_bm25 = max(bm25_scores)
            range_bm25 = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1.0
            
            for doc_idx, score in bm25_results:
                normalized = (score - min_bm25) / range_bm25
                combined_scores[doc_idx] = {
                    'bm25_score': normalized,
                    'vector_score': 0.0,
                    'hybrid_score': normalized * bm25_weight
                }
        
        # Normalize vector scores
        if vector_results:
            for result in vector_results:
                doc_idx = self._find_doc_idx(result)
                if doc_idx is None:
                    continue
                
                distance = result.get('distance', 2.0) or 2.0
                similarity = 1.0 / (1.0 + distance)
                
                if doc_idx in combined_scores:
                    combined_scores[doc_idx]['vector_score'] = similarity
                    combined_scores[doc_idx]['hybrid_score'] += similarity * vector_weight
                else:
                    combined_scores[doc_idx] = {
                        'bm25_score': 0.0,
                        'vector_score': similarity,
                        'hybrid_score': similarity * vector_weight
                    }
        
        sorted_results = sorted(
            combined_scores.items(),
            key=lambda x: x[1]['hybrid_score'],
            reverse=True
        )
        
        results = []
        for doc_idx, scores in sorted_results[:top_k]:
            result = {
                'code': self.documents[doc_idx],
                'metadata': self.metadata[doc_idx] if doc_idx < len(self.metadata) else {},
                'bm25_score': scores['bm25_score'],
                'vector_score': scores['vector_score'],
                'hybrid_score': scores['hybrid_score']
            }
            if doc_idx < len(self.metadata):
                result.update(self.metadata[doc_idx])
            results.append(result)
        
        logger.info(
            f"Hybrid search (weighted): BM25={bm25_weight}, Vector={vector_weight}, "
            f"Found {len(results)} results"
        )
        return results
    
    def _combine_rrf(
        self,
        bm25_results: List[Tuple],
        vector_results: List[Dict],
        top_k: int,
        k: int = 60
    ) -> List[Dict]:
        """
        Reciprocal Rank Fusion (RRF) combining.
        
        RRF score = sum(1 / (k + rank_i)) across all ranking lists.
        k=60 is the standard constant from the original RRF paper.
        More robust than weighted combination when score distributions differ.
        """
        rrf_scores: Dict[int, float] = {}
        
        # BM25 ranks
        for rank, (doc_idx, _) in enumerate(bm25_results):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + 1.0 / (k + rank + 1)
        
        # Vector ranks
        for rank, result in enumerate(vector_results):
            doc_idx = self._find_doc_idx(result)
            if doc_idx is not None:
                rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + 1.0 / (k + rank + 1)
        
        sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for doc_idx, rrf_score in sorted_results[:top_k]:
            result = {
                'code': self.documents[doc_idx],
                'metadata': self.metadata[doc_idx] if doc_idx < len(self.metadata) else {},
                'hybrid_score': rrf_score,
                'rrf_score': rrf_score
            }
            if doc_idx < len(self.metadata):
                result.update(self.metadata[doc_idx])
            results.append(result)
        
        logger.info(f"Hybrid search (RRF): Found {len(results)} results")
        return results
    
    def _find_doc_idx(self, vector_result: Dict) -> Optional[int]:
        """Find document index from vector search result"""
        result_code = vector_result.get('code', '') or vector_result.get('document', '')
        for i, doc in enumerate(self.documents):
            if doc == result_code or doc[:100] == result_code[:100]:
                return i
        return None
