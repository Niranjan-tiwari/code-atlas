"""
Code Duplication Finder: Uses embedding similarity to find duplicate/similar
code across repositories.

"This function in repo A is 92% similar to one in repo B"
"""

import logging
import time
from typing import List, Dict, Optional

logger = logging.getLogger("duplication_finder")


def find_duplicates(
    retriever,
    repo_filter: Optional[str] = None,
    threshold: float = 0.15,
    max_results: int = 20
) -> dict:
    """
    Find similar/duplicate code across repos using embedding distance.
    
    Args:
        retriever: RAGRetriever instance
        repo_filter: Optional repo to check for duplicates
        threshold: Max distance to consider as duplicate (lower = more similar)
        max_results: Max duplicate pairs to return
    """
    t = time.time()
    
    if not retriever._unified:
        return {"error": "Unified collection required. Run: python3 scripts/build_unified_index.py"}
    
    collection = retriever._unified
    total = collection.count()
    
    # Sample chunks to check for duplicates
    sample_size = min(100, total)
    
    try:
        sample = collection.peek(limit=sample_size)
    except Exception as e:
        return {"error": f"Failed to peek collection: {e}"}
    
    docs = sample.get("documents") or []
    metas = sample.get("metadatas") or []
    
    if len(docs) == 0:
        return {"error": "No documents found in collection", "duplicates": [], "count": 0}
    
    # Get embeddings - handle numpy arrays carefully
    raw_embeddings = sample.get("embeddings")
    has_embeddings = raw_embeddings is not None
    if has_embeddings:
        try:
            has_embeddings = len(raw_embeddings) > 0
        except Exception:
            has_embeddings = False
    
    if not has_embeddings:
        return {"error": "No embeddings available", "duplicates": [], "count": 0}
    
    duplicates = []
    seen = set()
    
    # For each chunk, find similar chunks
    num_items = min(sample_size, len(docs))
    
    for i in range(num_items):
        if len(duplicates) >= max_results:
            break
        
        try:
            emb = [raw_embeddings[i].tolist() if hasattr(raw_embeddings[i], 'tolist') else list(raw_embeddings[i])]
        except Exception:
            continue
        
        meta_i = metas[i] if i < len(metas) else {}
        repo_i = meta_i.get("repo", "?") if meta_i else "?"
        file_i = meta_i.get("file", "?") if meta_i else "?"
        
        if repo_filter and repo_i != repo_filter:
            continue
        
        # Find similar
        try:
            results = collection.query(
                query_embeddings=emb,
                n_results=5
            )
        except Exception:
            continue
        
        dists = results.get("distances", [[]])[0] if results.get("distances") else []
        result_metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        result_docs = results.get("documents", [[]])[0] if results.get("documents") else []
        
        for j in range(len(dists)):
            dist = dists[j]
            meta_j = result_metas[j] if j < len(result_metas) else {}
            repo_j = meta_j.get("repo", "?") if meta_j else "?"
            file_j = meta_j.get("file", "?") if meta_j else "?"
            
            # Skip self-matches and same-file matches
            if repo_i == repo_j and file_i == file_j:
                continue
            
            # Skip if distance above threshold
            if dist > threshold:
                continue
            
            # Skip already seen pairs
            pair_key = tuple(sorted([f"{repo_i}/{file_i}", f"{repo_j}/{file_j}"]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            
            similarity = round((1 - dist) * 100, 1)
            doc_j = result_docs[j] if j < len(result_docs) else ""
            
            duplicates.append({
                "similarity": similarity,
                "file_a": f"{repo_i}/{file_i}",
                "file_b": f"{repo_j}/{file_j}",
                "distance": round(dist, 4),
                "preview_a": (docs[i] or "")[:100] if i < len(docs) else "",
                "preview_b": (doc_j or "")[:100]
            })
            
            if len(duplicates) >= max_results:
                break
    
    # Sort by similarity (highest first)
    duplicates.sort(key=lambda x: x["similarity"], reverse=True)
    
    return {
        "duplicates": duplicates[:max_results],
        "count": len(duplicates),
        "threshold": threshold,
        "scanned_chunks": num_items,
        "time_ms": round((time.time() - t) * 1000)
    }
