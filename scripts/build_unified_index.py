#!/usr/bin/env python3
"""
Build a UNIFIED ChromaDB collection from all per-repo collections.

Why: Searching 1 collection = 1 query (~0.05s)
     Searching 75 collections = 75 queries (~0.6s even with parallel)

This merges all per-repo collections into one "unified_code" collection
with repo/file metadata preserved for filtering.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.config import Settings


def build_unified():
    print("=" * 60)
    print("  Building Unified Code Collection")
    print("=" * 60)
    
    client = chromadb.PersistentClient(
        path="./data/vector_db",
        settings=Settings(anonymized_telemetry=False)
    )
    
    # Delete old unified collection if exists
    try:
        client.delete_collection("unified_code")
        print("  Deleted old unified_code collection")
    except Exception:
        pass
    
    # Create new unified collection
    unified = client.create_collection(
        name="unified_code",
        metadata={"description": "All code chunks from all repos in one collection"}
    )
    
    # Gather all repo collections
    cols = client.list_collections()
    repo_cols = [c for c in cols if c.name.startswith("repo_")]
    
    print(f"\n  Found {len(repo_cols)} repo collections")
    
    total_docs = 0
    total_repos = 0
    
    for i, col in enumerate(repo_cols):
        repo_name = col.name.replace("repo_", "")
        count = col.count()
        
        if count == 0:
            continue
        
        # Get ALL documents from this collection
        try:
            data = col.get(
                include=["documents", "metadatas", "embeddings"]
            )
        except Exception as e:
            print(f"  ⚠️  Error reading {repo_name}: {e}")
            continue
        
        if not data["documents"]:
            continue
        
        # Add to unified collection with unique IDs
        ids = [f"{repo_name}__{j}" for j in range(len(data["documents"]))]
        
        # Ensure all metadata has repo field
        metadatas = []
        for j, meta in enumerate(data["metadatas"] or [{}] * len(data["documents"])):
            m = dict(meta) if meta else {}
            m["repo"] = repo_name
            metadatas.append(m)
        
        # Add in batches (ChromaDB limit)
        batch_size = 500
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            batch_ids = ids[start:end]
            batch_docs = data["documents"][start:end]
            batch_meta = metadatas[start:end]
            batch_emb = data["embeddings"][start:end] if data.get("embeddings") is not None else None
            
            if batch_emb is not None:
                unified.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_meta,
                    embeddings=batch_emb
                )
            else:
                unified.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_meta
                )
        
        total_docs += len(ids)
        total_repos += 1
        
        if (i + 1) % 10 == 0 or i == len(repo_cols) - 1:
            print(f"  [{i+1}/{len(repo_cols)}] {total_docs} chunks from {total_repos} repos")
    
    print(f"\n  ✅ Unified collection: {unified.count()} chunks from {total_repos} repos")
    print("=" * 60)


if __name__ == "__main__":
    t = time.time()
    build_unified()
    print(f"\n  Done in {time.time()-t:.1f}s")
