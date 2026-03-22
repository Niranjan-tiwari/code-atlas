#!/usr/bin/env python3
"""
Index remaining repos one-by-one using subprocess isolation.
Each repo runs in a SEPARATE PROCESS so it can be truly killed on timeout.
This solves the memory thrashing problem.
"""

import sys
import os
import subprocess
import time
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/indexing_bulk.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("index_remaining")

TIMEOUT_SECONDS = 180  # 3 minutes per repo (hard kill)
VECTOR_DB_PATH = "./data/vector_db"

# Single-repo indexing script (run as subprocess)
SINGLE_REPO_SCRIPT = '''
import sys, os, gc, time, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, "{project_root}")

from scripts.index_one_repo import load_code_files, chunk_code
from src.ai.vector_db import VectorDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("single_repo")

repo_name = "{repo_name}"
base_path = "{base_path}"
repo_path = Path(base_path) / repo_name

logger.info(f"Loading files from {{repo_name}}...")
files = load_code_files(repo_path)
if not files:
    logger.warning(f"No files found in {{repo_name}}")
    sys.exit(1)

logger.info(f"Found {{len(files)}} files in {{repo_name}}")

db = VectorDB(collection_name=f"repo_{{repo_name}}")
batch_size = 15  # Very small batches
all_docs, all_meta, all_ids = [], [], []
total_chunks = 0

for idx, (file_path, content, language) in enumerate(files, 1):
    try:
        chunks = chunk_code(content, language=language)
        total_chunks += len(chunks)
        for ci, chunk in enumerate(chunks):
            all_docs.append(chunk)
            all_meta.append({{"repo": repo_name, "file": str(file_path), "language": language, "chunk": ci, "total_chunks": len(chunks)}})
            all_ids.append(f"{{repo_name}}_{{file_path}}_{{ci}}")
        
        if len(all_docs) >= batch_size:
            db.add_documents(all_docs, all_meta, all_ids)
            logger.info(f"  Batch: {{len(all_docs)}} chunks ({{idx}}/{{len(files)}} files)")
            all_docs, all_meta, all_ids = [], [], []
            gc.collect()
            time.sleep(0.05)
    except Exception as e:
        logger.error(f"Error processing {{file_path}}: {{e}}")
        continue

if all_docs:
    db.add_documents(all_docs, all_meta, all_ids)
    logger.info(f"  Final batch: {{len(all_docs)}} chunks")

info = db.get_collection_info()
logger.info(f"Done: {{repo_name}} - {{info['count']}} chunks indexed")
'''


def get_indexed_repos():
    """Get already indexed repos"""
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=VECTOR_DB_PATH, settings=Settings(anonymized_telemetry=False))
    indexed = set()
    for col in client.list_collections():
        if col.name.startswith("repo_") and col.count() > 0:
            indexed.add(col.name.replace("repo_", ""))
    return indexed


def get_skip_list():
    """Get repos to skip"""
    skip = set()
    try:
        data = json.load(open("config/skip_repos.json"))
        skip = {r["repo_name"] for r in data.get("skipped_repos", [])}
    except:
        pass
    return skip


def discover_remaining():
    """Find repos that still need indexing"""
    indexed = get_indexed_repos()
    skip = get_skip_list()
    
    all_repos = []
    for base_path in ["/path/to/your/repos", "/path/to/your/repos-alt"]:
        p = Path(base_path)
        if not p.exists():
            continue
        for item in sorted(p.iterdir()):
            if item.is_dir() and (item / ".git").exists():
                name = item.name
                if name not in indexed and name not in skip:
                    all_repos.append((name, base_path))
    
    return all_repos, indexed, skip


def index_one_repo(repo_name: str, base_path: str) -> bool:
    """Index a single repo in a subprocess with hard timeout"""
    project_root = str(Path(__file__).parent.parent)
    
    script = SINGLE_REPO_SCRIPT.format(
        project_root=project_root,
        repo_name=repo_name,
        base_path=base_path
    )
    
    # Write temp script
    tmp_script = f"/tmp/index_{repo_name}.py"
    with open(tmp_script, "w") as f:
        f.write(script)
    
    try:
        # Run in subprocess with HARD timeout
        result = subprocess.run(
            [sys.executable, tmp_script],
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            cwd=project_root
        )
        
        # Log output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"  [{repo_name}] {line}")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-3:]:
                if "ERROR" in line or "Error" in line:
                    logger.error(f"  [{repo_name}] {line}")
        
        success = result.returncode == 0
        if success:
            logger.info(f"✅ {repo_name}: indexed successfully")
        else:
            logger.error(f"❌ {repo_name}: failed (exit code {result.returncode})")
        
        return success
        
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️  TIMEOUT: {repo_name} exceeded {TIMEOUT_SECONDS}s - KILLED")
        # Add to skip list
        add_to_skip_list(repo_name, f"Timeout after {TIMEOUT_SECONDS}s")
        return False
    except Exception as e:
        logger.error(f"❌ {repo_name}: error - {e}")
        return False
    finally:
        # Cleanup
        try:
            os.remove(tmp_script)
        except:
            pass


def add_to_skip_list(repo_name: str, reason: str):
    """Add repo to skip list"""
    skip_file = Path("config/skip_repos.json")
    config = {"skipped_repos": [], "notes": []}
    if skip_file.exists():
        try:
            config = json.load(open(skip_file))
        except:
            pass
    
    existing = {r["repo_name"] for r in config.get("skipped_repos", [])}
    if repo_name in existing:
        return
    
    config.setdefault("skipped_repos", []).append({
        "repo_name": repo_name,
        "reason": reason,
        "skipped_at": time.strftime("%Y-%m-%d %H:%M"),
        "status": "pending",
        "note": "Auto-added: subprocess timeout"
    })
    
    with open(skip_file, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"📝 Added {repo_name} to skip list")


def main():
    logger.info("=" * 80)
    logger.info("🚀 Indexing Remaining Repos (Subprocess Isolation)")
    logger.info("=" * 80)
    
    remaining, indexed, skip = discover_remaining()
    
    logger.info(f"📊 Already indexed: {len(indexed)}")
    logger.info(f"⏭️  Skipped: {len(skip)}")
    logger.info(f"⏳ Remaining: {len(remaining)}")
    logger.info(f"⏱️  Timeout per repo: {TIMEOUT_SECONDS}s")
    logger.info("")
    
    if not remaining:
        logger.info("✅ All repos already indexed!")
        return
    
    successful = 0
    failed = 0
    start_time = time.time()
    
    for i, (repo_name, base_path) in enumerate(remaining, 1):
        logger.info(f"\n[{i}/{len(remaining)}] Processing: {repo_name}")
        logger.info(f"   Path: {base_path}")
        logger.info("-" * 60)
        
        repo_start = time.time()
        success = index_one_repo(repo_name, base_path)
        repo_time = time.time() - repo_start
        
        if success:
            successful += 1
            logger.info(f"✅ {repo_name} done in {repo_time:.1f}s")
        else:
            failed += 1
            logger.error(f"❌ {repo_name} failed after {repo_time:.1f}s")
        
        # Brief pause between repos
        time.sleep(1)
        
        # Progress
        elapsed = time.time() - start_time
        logger.info(f"📊 Progress: {i}/{len(remaining)} | ✅ {successful} | ❌ {failed} | ⏱️ {elapsed/60:.1f}min")
    
    total_time = time.time() - start_time
    
    logger.info("\n" + "=" * 80)
    logger.info("📊 INDEXING COMPLETE")
    logger.info("=" * 80)
    logger.info(f"✅ Successful: {successful}")
    logger.info(f"❌ Failed: {failed}")
    logger.info(f"⏱️  Total time: {total_time/60:.1f} minutes")
    
    # Final count
    final_indexed = get_indexed_repos()
    logger.info(f"📦 Total indexed repos: {len(final_indexed)}")


if __name__ == "__main__":
    main()
