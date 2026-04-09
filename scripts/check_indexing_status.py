#!/usr/bin/env python3
"""
Check indexing status and show progress (Qdrant).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_indexing_status():
    from qdrant_client import QdrantClient

    from src.ai.vector_backend import vector_db_path

    print("=" * 80)
    print("📊 INDEXING STATUS CHECK (Qdrant)")
    print("=" * 80)
    print()
    print(f"📂 Storage: {vector_db_path()}")
    print()

    import subprocess

    try:
        result = subprocess.run(
            ["pgrep", "-f", "index_all_repos_resume"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            print(f"✅ Indexing process is RUNNING (PIDs: {', '.join(pids)})")
        else:
            print("⚠️  No indexing process found")
    except Exception as e:
        print(f"⚠️  Could not check process: {e}")

    print()

    repo_collections = []
    try:
        p = Path(vector_db_path())
        if not p.exists():
            print("⚠️  Qdrant directory does not exist yet — run indexing first.")
        else:
            client = QdrantClient(path=str(p))
            for c in client.get_collections().collections:
                if c.name.startswith("repo_"):
                    n = client.count(c.name, exact=True).count
                    repo_collections.append((c.name, n))

            print(f"📁 Total Repo Collections: {len(repo_collections)}")
            print()

            if repo_collections:
                print("📊 Collections:")
                print("-" * 80)
                total_docs = 0
                for name, count in sorted(repo_collections, key=lambda x: x[0]):
                    total_docs += count
                    repo_name = name.replace("repo_", "")
                    print(f"  ✅ {repo_name:40s} {count:6d} chunks")
                print("-" * 80)
                print(f"  📊 TOTAL: {total_docs:46d} chunks")
                print()
            else:
                print("⚠️  No repo collections found yet")
                print()

        expected_repos = 80
        indexed_repos = len(repo_collections)
        remaining = expected_repos - indexed_repos
        print(
            f"📈 Progress: {indexed_repos}/{expected_repos} repos indexed "
            f"({indexed_repos/expected_repos*100:.1f}%)"
        )
        if remaining > 0:
            print(f"⏳ Remaining: {remaining} repos")
        print()

    except Exception as e:
        print(f"❌ Error checking collections: {e}")
        import traceback

        traceback.print_exc()
        repo_collections = []

    log_file = Path("logs/indexing_bulk.log")
    if log_file.exists():
        print("📝 Latest Log Entries:")
        print("-" * 80)
        try:
            with open(log_file, "r") as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    print(f"  {line.rstrip()}")
        except Exception as e:
            print(f"  ⚠️  Could not read log: {e}")
    else:
        print("⚠️  Log file not found")

    print()
    print("=" * 80)

    expected_repos = 80
    if repo_collections and len(repo_collections) >= expected_repos:
        print("✅ INDEXING COMPLETE!")
        print()
        print("🚀 Next: python3 scripts/query_code.py --stats")
    else:
        print("⏳ Indexing in progress...")
        print()
        print("💡 Monitor: tail -f logs/indexing_bulk.log")
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
