#!/usr/bin/env python3
"""
Check indexing status and show progress
"""

import sys
from pathlib import Path
import chromadb
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

def check_indexing_status():
    """Check current indexing status"""
    
    print("=" * 80)
    print("📊 INDEXING STATUS CHECK")
    print("=" * 80)
    print()
    
    # Check if process is running
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "index_all_repos_resume"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            print(f"✅ Indexing process is RUNNING (PIDs: {', '.join(pids)})")
        else:
            print("⚠️  No indexing process found")
    except Exception as e:
        print(f"⚠️  Could not check process: {e}")
    
    print()
    
    # Check vector DB collections
    try:
        client = chromadb.PersistentClient(path='./data/vector_db')
        collections = client.list_collections()
        
        repo_collections = [c for c in collections if c.name.startswith('repo_')]
        
        print(f"📁 Total Repo Collections: {len(repo_collections)}")
        print()
        
        if repo_collections:
            print("📊 Collections:")
            print("-" * 80)
            
            total_docs = 0
            for collection in sorted(repo_collections, key=lambda x: x.name):
                count = collection.count()
                total_docs += count
                repo_name = collection.name.replace('repo_', '')
                print(f"  ✅ {repo_name:40s} {count:6d} chunks")
            
            print("-" * 80)
            print(f"  📊 TOTAL: {total_docs:46d} chunks")
            print()
        else:
            print("⚠️  No repo collections found yet")
            print()
        
        # Expected repos
        expected_repos = 80  # 32 + 48
        indexed_repos = len(repo_collections)
        remaining = expected_repos - indexed_repos
        
        print(f"📈 Progress: {indexed_repos}/{expected_repos} repos indexed ({indexed_repos/expected_repos*100:.1f}%)")
        if remaining > 0:
            print(f"⏳ Remaining: {remaining} repos")
        
        print()
        
    except Exception as e:
        print(f"❌ Error checking collections: {e}")
        import traceback
        traceback.print_exc()
    
    # Check log file
    log_file = Path("logs/indexing_bulk.log")
    if log_file.exists():
        print("📝 Latest Log Entries:")
        print("-" * 80)
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Show last 10 lines
                for line in lines[-10:]:
                    print(f"  {line.rstrip()}")
        except Exception as e:
            print(f"  ⚠️  Could not read log: {e}")
    else:
        print("⚠️  Log file not found")
    
    print()
    print("=" * 80)
    
    # Check if indexing is complete
    if repo_collections and len(repo_collections) >= expected_repos:
        print("✅ INDEXING COMPLETE!")
        print()
        print("🚀 Next Steps:")
        print("  1. Review NEXT_STEPS.md for implementation plan")
        print("  2. Start building RAG pipeline (Phase 1)")
        print("  3. Test code search: python3 scripts/query_code.py 'your query'")
    else:
        print("⏳ Indexing in progress...")
        print()
        print("💡 Monitor progress:")
        print("  tail -f logs/indexing_bulk.log")
        print("  bash scripts/monitor_indexing.sh")
    
    print("=" * 80)


if __name__ == "__main__":
    try:
        check_indexing_status()
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
