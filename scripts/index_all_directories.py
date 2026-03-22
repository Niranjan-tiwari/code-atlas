#!/usr/bin/env python3
"""
Index all repositories from multiple base directories
Runs autonomously, indexes all Go repos
"""

import sys
import os
import json
import time
import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.index_one_repo import load_code_files, chunk_code, chunk_go_code
from src.ai.vector_db import VectorDB

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/indexing.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("index_all")


def discover_repos(base_path: str) -> List[Dict]:
    """Discover all Git repositories in base path"""
    repos = []
    base = Path(base_path)
    
    if not base.exists():
        logger.warning(f"Base path does not exist: {base_path}")
        return repos
    
    for item in base.iterdir():
        if not item.is_dir():
            continue
        
        # Check if it's a Git repository
        git_dir = item / ".git"
        if not git_dir.exists():
            continue
        
        repos.append({
            "name": item.name,
            "path": str(item),
            "base_path": base_path
        })
    
    return repos


def index_repo_autonomous(repo_info: Dict, vector_db: VectorDB) -> Dict:
    """Index a single repository autonomously"""
    repo_name = repo_info["name"]
    repo_path = Path(repo_info["path"])
    
    logger.info(f"📂 Indexing: {repo_name}")
    
    try:
        # Load code files
        files = load_code_files(repo_path)
        
        if not files:
            logger.warning(f"⚠️  No code files found in {repo_name}")
            return {"status": "skipped", "reason": "no_files"}
        
        # Group by language
        lang_counts = {}
        for _, _, lang in files:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        
        logger.info(f"   Found {len(files)} files: {lang_counts}")
        
        # Process files
        all_documents = []
        all_metadatas = []
        all_ids = []
        
        for file_path, content, language in files:
            # Split into chunks
            chunks = chunk_code(content, language=language)
            
            for chunk_idx, chunk in enumerate(chunks):
                all_documents.append(chunk)
                all_metadatas.append({
                    "repo": repo_name,
                    "file": file_path,
                    "language": language,
                    "chunk": chunk_idx,
                    "total_chunks": len(chunks),
                    "base_path": repo_info["base_path"]
                })
                all_ids.append(f"{repo_info['base_path']}_{repo_name}_{file_path}_{chunk_idx}")
        
        logger.info(f"   Created {len(all_documents)} chunks")
        
        # Add to vector DB in batches (to avoid memory issues)
        batch_size = 100
        for i in range(0, len(all_documents), batch_size):
            batch_docs = all_documents[i:i+batch_size]
            batch_meta = all_metadatas[i:i+batch_size]
            batch_ids = all_ids[i:i+batch_size]
            
            vector_db.add_documents(batch_docs, batch_meta, batch_ids)
            logger.debug(f"   Added batch {i//batch_size + 1}/{(len(all_documents)-1)//batch_size + 1}")
        
        logger.info(f"✅ {repo_name}: {len(all_documents)} chunks indexed")
        
        return {
            "status": "success",
            "files": len(files),
            "chunks": len(all_documents),
            "languages": lang_counts
        }
    
    except Exception as e:
        logger.error(f"❌ {repo_name} failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


def index_all_directories(
    base_paths: List[str],
    collection_name: str = "all_repos",
    limit: int = None
):
    """Index all repositories from multiple base directories"""
    logger.info("=" * 80)
    logger.info("🚀 Starting Autonomous Indexing")
    logger.info(f"📁 Base paths: {base_paths}")
    logger.info(f"🗄️  Collection: {collection_name}")
    logger.info("=" * 80)
    
    # Initialize vector DB
    vector_db = VectorDB(collection_name=collection_name)
    
    # Discover all repos
    all_repos = []
    for base_path in base_paths:
        logger.info(f"\n🔍 Discovering repos in: {base_path}")
        repos = discover_repos(base_path)
        logger.info(f"   Found {len(repos)} repositories")
        all_repos.extend(repos)
    
    if limit:
        all_repos = all_repos[:limit]
    
    logger.info(f"\n📊 Total repositories to index: {len(all_repos)}")
    
    # Index each repo
    results = {
        "started_at": datetime.now().isoformat(),
        "total_repos": len(all_repos),
        "successful": [],
        "failed": [],
        "skipped": []
    }
    
    for i, repo_info in enumerate(all_repos, 1):
        logger.info(f"\n[{i}/{len(all_repos)}] Processing: {repo_info['name']}")
        logger.info("-" * 60)
        
        result = index_repo_autonomous(repo_info, vector_db)
        
        if result["status"] == "success":
            results["successful"].append({
                "repo": repo_info["name"],
                "path": repo_info["path"],
                **result
            })
        elif result["status"] == "skipped":
            results["skipped"].append({
                "repo": repo_info["name"],
                "path": repo_info["path"],
                **result
            })
        else:
            results["failed"].append({
                "repo": repo_info["name"],
                "path": repo_info["path"],
                **result
            })
        
        # Small delay to avoid overwhelming system
        time.sleep(0.5)
    
    # Final summary
    results["completed_at"] = datetime.now().isoformat()
    results["summary"] = {
        "total": len(all_repos),
        "successful": len(results["successful"]),
        "failed": len(results["failed"]),
        "skipped": len(results["skipped"])
    }
    
    # Collection info
    info = vector_db.get_collection_info()
    results["vector_db"] = {
        "collection": info["name"],
        "total_documents": info["count"]
    }
    
    # Save results
    results_file = Path("logs/indexing_results.json")
    results_file.parent.mkdir(exist_ok=True)
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("📊 INDEXING SUMMARY")
    logger.info("=" * 80)
    logger.info(f"✅ Successful: {results['summary']['successful']}")
    logger.info(f"❌ Failed: {results['summary']['failed']}")
    logger.info(f"⚠️  Skipped: {results['summary']['skipped']}")
    logger.info(f"📁 Total: {results['summary']['total']}")
    logger.info(f"🗄️  Vector DB: {info['name']}")
    logger.info(f"📊 Total Documents: {info['count']}")
    logger.info(f"💾 Results saved to: {results_file}")
    logger.info("=" * 80)
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Index all repositories from multiple directories")
    parser.add_argument(
        "--base-paths",
        nargs="+",
        default=[
            "/path/to/your/repos",
            "/path/to/your/repos-alt"
        ],
        help="Base paths to scan"
    )
    parser.add_argument(
        "--collection",
        default="all_repos",
        help="Vector DB collection name"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of repos (for testing)"
    )
    
    args = parser.parse_args()
    
    try:
        results = index_all_directories(
            base_paths=args.base_paths,
            collection_name=args.collection,
            limit=args.limit
        )
        
        # Exit with error code if failures
        if results["summary"]["failed"] > 0:
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
