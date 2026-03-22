#!/usr/bin/env python3
"""
Test Vector DB functionality
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai.vector_db import VectorDB, test_vector_db

if __name__ == "__main__":
    print("🚀 Testing Vector DB Setup...")
    print("=" * 60)
    
    try:
        test_vector_db()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
