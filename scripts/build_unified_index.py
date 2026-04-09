#!/usr/bin/env python3
"""
Build unified_code from all repo_* Qdrant collections (one collection = one fast query).

  python scripts/build_unified_index.py

Storage: QDRANT_PATH or ./data/qdrant_db
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    from src.ai.qdrant_rag_support import rebuild_unified_collection
    from src.ai.vector_backend import vector_db_path

    print("=" * 60)
    print("  Building unified_code (Qdrant)")
    print("  Storage:", vector_db_path())
    print("=" * 60)
    rebuild_unified_collection(verbose=True)
    print("=" * 60)


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"\n  Done in {time.time()-t:.1f}s")
