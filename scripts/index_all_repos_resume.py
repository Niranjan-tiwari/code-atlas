#!/usr/bin/env python3
"""
Resume-capable bulk indexing of all repositories
Handles interruptions and continues from where it left off
"""

import sys
import os
import logging
from pathlib import Path
from typing import List, Set
import time
import json
import gc  # Garbage collection
import psutil  # System monitoring
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import threading

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.index_one_repo import load_code_files, chunk_code
from src.ai.vector_db import VectorDB
import chromadb

# Setup logging
log_file = Path("logs/indexing_bulk.log")
log_file.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='a'),  # Append mode
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("index_all_repos_resume")


def get_indexed_repos() -> Set[str]:
    """Get list of already indexed repositories"""
    indexed = set()
    try:
        client = chromadb.PersistentClient(path='./data/vector_db')
        collections = client.list_collections()
        
        for collection in collections:
            name = collection.name
            if name.startswith('repo_'):
                repo_name = name.replace('repo_', '')
                # Check if collection has documents
                if collection.count() > 0:
                    indexed.add(repo_name)
                    logger.info(f"Found indexed repo: {repo_name} ({collection.count()} docs)")
    except Exception as e:
        logger.warning(f"Error checking indexed repos: {e}")
    
    return indexed


def discover_repos(base_path: str) -> List[str]:
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
        if git_dir.exists():
            repos.append(item.name)
    
    return sorted(repos)


def index_repo_robust(repo_name: str, base_path: str, collection_name: str = None):
    """Robust indexing with error handling and progress tracking"""
    repo_path = Path(base_path) / repo_name
    
    if not repo_path.exists():
        logger.error(f"Repository not found: {repo_path}")
        return False
    
    collection = collection_name or f"repo_{repo_name}"
    
    try:
        logger.info(f"📂 Loading code files from {repo_name}...")
        files = load_code_files(repo_path)
        
        if not files:
            logger.warning(f"No code files found in {repo_name}")
            return False
        
        # Group by language
        lang_counts = {}
        for _, _, lang in files:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        
        logger.info(f"✅ Found {len(files)} code files in {repo_name}")
        for lang, count in lang_counts.items():
            logger.info(f"   - {lang.upper()}: {count} files")
        
        # Initialize vector DB
        db = VectorDB(collection_name=collection)
        
        # Process files in batches (reduced for memory efficiency)
        batch_size = 25  # Smaller batches to prevent memory issues
        all_documents = []
        all_metadatas = []
        all_ids = []
        
        total_chunks = 0
        files_processed = 0
        last_log_time = time.time()
        
        for file_idx, (file_path, content, language) in enumerate(files, 1):
            # Check for timeout (if no progress for 5 minutes, skip repo)
            current_time = time.time()
            if current_time - last_log_time > 300:  # 5 minutes timeout
                logger.error(f"⏱️  TIMEOUT: {repo_name} stuck for >5 minutes, skipping...")
                logger.error(f"   Last processed: file {files_processed}/{len(files)}")
                # Note: Will be added to skip list by caller
                return False
            
            # Log progress every 10 files
            if file_idx % 10 == 0:
                logger.info(f"   📄 Processing file {file_idx}/{len(files)}...")
                last_log_time = time.time()
            
            try:
                chunks = chunk_code(content, language=language)
                total_chunks += len(chunks)
                files_processed += 1
                
                for chunk_idx, chunk in enumerate(chunks):
                    all_documents.append(chunk)
                    all_metadatas.append({
                        "repo": repo_name,
                        "file": str(file_path),
                        "language": language,
                        "chunk": chunk_idx,
                        "total_chunks": len(chunks)
                    })
                    all_ids.append(f"{repo_name}_{file_path}_{chunk_idx}")
                
                # Add in batches to avoid memory issues
                if len(all_documents) >= batch_size:
                    try:
                        batch_start = time.time()
                        db.add_documents(all_documents, all_metadatas, all_ids)
                        batch_time = time.time() - batch_start
                        logger.info(f"   ✅ Added batch: {len(all_documents)} chunks ({files_processed}/{len(files)} files) in {batch_time:.1f}s")
                        last_log_time = time.time()
                        
                        all_documents = []
                        all_metadatas = []
                        all_ids = []
                        
                        # Force GC after each batch
                        gc.collect()
                        
                        # Small delay to prevent CPU saturation
                        time.sleep(0.1)
                    except Exception as e:
                        logger.error(f"   ❌ Error adding batch: {e}")
                        # Continue with next batch
                        all_documents = []
                        all_metadatas = []
                        all_ids = []
                        gc.collect()
                        last_log_time = time.time()
                
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                continue
        
        # Add remaining documents
        if all_documents:
            try:
                logger.info(f"   📦 Adding final batch: {len(all_documents)} chunks...")
                final_batch_start = time.time()
                db.add_documents(all_documents, all_metadatas, all_ids)
                final_batch_time = time.time() - final_batch_start
                logger.info(f"   ✅ Added final batch: {len(all_documents)} chunks in {final_batch_time:.1f}s")
                # Clear and GC
                all_documents = []
                all_metadatas = []
                all_ids = []
                gc.collect()
            except Exception as e:
                logger.error(f"   ❌ Error adding final batch: {e}")
                gc.collect()
        
        # Get collection info with timeout protection
        try:
            logger.info(f"   📊 Getting collection info for {repo_name}...")
            info_start = time.time()
            info = db.get_collection_info()
            info_time = time.time() - info_start
            logger.info(f"✅ {repo_name}: {info['count']} total chunks indexed ({files_processed}/{len(files)} files) [info retrieved in {info_time:.1f}s]")
        except Exception as e:
            logger.error(f"   ⚠️  Error getting collection info: {e}, but indexing completed")
            info = {'count': 'unknown'}
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error indexing {repo_name}: {e}", exc_info=True)
        return False


def load_skip_list() -> Set[str]:
    """Load list of repos to skip"""
    skip_list = set()
    skip_file = Path(__file__).parent.parent / "config" / "skip_repos.json"
    
    if skip_file.exists():
        try:
            with open(skip_file, 'r') as f:
                config = json.load(f)
                for repo_info in config.get("skipped_repos", []):
                    skip_list.add(repo_info["repo_name"])
                    logger.info(f"⏭️  Skipping repo: {repo_info['repo_name']} - {repo_info.get('reason', 'Unknown')}")
        except Exception as e:
            logger.warning(f"Error loading skip list: {e}")
    
    return skip_list


def add_to_skip_list(repo_name: str, reason: str, files_count: int = None, language: str = None, error: str = None):
    """Add a repo to the skip list with details"""
    skip_file = Path(__file__).parent.parent / "config" / "skip_repos.json"
    
    # Load existing skip list
    config = {"skipped_repos": [], "notes": []}
    if skip_file.exists():
        try:
            with open(skip_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            logger.warning(f"Error loading skip list: {e}")
    
    # Check if repo already in list
    existing_repos = {r["repo_name"] for r in config.get("skipped_repos", [])}
    if repo_name in existing_repos:
        logger.info(f"⏭️  {repo_name} already in skip list")
        return
    
    # Add new skipped repo entry
    skip_entry = {
        "repo_name": repo_name,
        "reason": reason,
        "skipped_at": time.strftime("%Y-%m-%d %H:%M"),
        "status": "pending",
        "note": f"Auto-added during indexing. {error if error else ''}"
    }
    
    if files_count:
        skip_entry["files_count"] = files_count
    if language:
        skip_entry["language"] = language
    
    config.setdefault("skipped_repos", []).append(skip_entry)
    
    # Save updated skip list
    try:
        skip_file.parent.mkdir(parents=True, exist_ok=True)
        with open(skip_file, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"📝 Added {repo_name} to skip list: {reason}")
    except Exception as e:
        logger.error(f"Error saving skip list: {e}")


def index_all_repos_resume():
    """Index all repos with resume capability"""
    paths = [
        "/path/to/your/repos",
        "/path/to/your/repos-alt"
    ]
    
    logger.info("=" * 80)
    logger.info("🚀 Starting Resume-Capable Bulk Indexing")
    logger.info("=" * 80)
    
    # Get already indexed repos
    indexed_repos = get_indexed_repos()
    logger.info(f"📊 Already indexed: {len(indexed_repos)} repos")
    
    # Load skip list
    skip_list = load_skip_list()
    if skip_list:
        logger.info(f"⏭️  Skipping {len(skip_list)} repos: {', '.join(sorted(skip_list))}")
    
    # Discover all repos
    all_repos = []
    for base_path in paths:
        if not Path(base_path).exists():
            logger.warning(f"Path does not exist: {base_path}")
            continue
        
        logger.info(f"🔍 Discovering repos in {base_path}...")
        repos = discover_repos(base_path)
        logger.info(f"✅ Found {len(repos)} repos in {base_path}")
        
        for repo in repos:
            all_repos.append((repo, base_path))
    
    # Filter out already indexed repos and skipped repos
    repos_to_index = [
        (repo, path) for repo, path in all_repos 
        if repo not in indexed_repos and repo not in skip_list
    ]
    
    logger.info(f"📊 Total repos: {len(all_repos)}")
    logger.info(f"📊 Already indexed: {len(indexed_repos)}")
    logger.info(f"📊 Skipped: {len(skip_list)}")
    logger.info(f"📊 Remaining to index: {len(repos_to_index)}")
    logger.info("=" * 80)
    
    if not repos_to_index:
        logger.info("✅ All repositories already indexed!")
        return
    
    successful = 0
    failed = 0
    start_time = time.time()
    
    for i, (repo_name, base_path) in enumerate(repos_to_index, 1):
        logger.info(f"\n[{i}/{len(repos_to_index)}] Processing: {repo_name}")
        logger.info(f"   Path: {base_path}")
        logger.info("-" * 80)
        
        # Check if repo is too large (heuristic: >200 files)
        try:
            files = load_code_files(Path(base_path) / repo_name)
            if len(files) > 200:
                logger.warning(f"⚠️  {repo_name} has {len(files)} files - may cause issues")
                logger.warning(f"   Consider adding to skip list if it causes problems")
        except:
            pass
        
        repo_start = time.time()
        
        # Use threading timeout to prevent stuck repos (5 minutes max)
        success = False
        result_container = {'success': False, 'error': None}
        
        def run_indexing():
            try:
                result_container['success'] = index_repo_robust(repo_name, base_path)
            except Exception as e:
                result_container['error'] = str(e)
                result_container['success'] = False
        
        # Run with 5 minute timeout per repo
        indexing_thread = threading.Thread(target=run_indexing, daemon=True)
        indexing_thread.start()
        indexing_thread.join(timeout=300)  # 5 minutes timeout
        
        repo_time = time.time() - repo_start
        
        # Check if thread is still alive (timed out)
        if indexing_thread.is_alive():
            logger.error(f"⏱️  TIMEOUT: {repo_name} exceeded 5 minute timeout, skipping...")
            logger.error(f"   Time taken: {repo_time/60:.1f} minutes")
            logger.error(f"   Skipping and continuing to next repo...")
            success = False
        else:
            success = result_container['success']
            if result_container['error']:
                logger.error(f"❌ Error: {result_container['error']}")
        
        # If repo took too long (>5 minutes), mark as failed
        if repo_time > 300:  # 5 minutes
            logger.warning(f"⚠️  {repo_name} took {repo_time/60:.1f} minutes - very slow")
            if not success:
                logger.warning(f"   Marking as failed and continuing...")
        
        # Force GC after each repo to free memory
        gc.collect()
        
        # Longer delay between repos to prevent system overload
        time.sleep(2)
        
        if success:
            successful += 1
            logger.info(f"✅ {repo_name} completed in {repo_time:.1f}s")
        else:
            failed += 1
            logger.error(f"❌ {repo_name} failed after {repo_time:.1f}s")
        
        # Progress update
        elapsed = time.time() - start_time
        avg_time = elapsed / i if i > 0 else 0
        remaining = len(repos_to_index) - i
        eta = avg_time * remaining if avg_time > 0 else 0
        
        logger.info(f"📊 Progress: {i}/{len(repos_to_index)} | "
                   f"Success: {successful} | Failed: {failed} | "
                   f"ETA: {eta/60:.1f} minutes")
    
    total_time = time.time() - start_time
    
    logger.info("\n" + "=" * 80)
    logger.info("📊 INDEXING SUMMARY")
    logger.info("=" * 80)
    logger.info(f"✅ Successful: {successful}")
    logger.info(f"❌ Failed: {failed}")
    logger.info(f"⏭️  Skipped: {len(skip_list)}")
    logger.info(f"📁 Total processed: {len(repos_to_index)}")
    logger.info(f"⏱️  Total time: {total_time/60:.1f} minutes")
    
    if skip_list:
        logger.info("")
        logger.info("📝 Skipped repos (process separately):")
        for repo in sorted(skip_list):
            logger.info(f"   - {repo}")
    
    # Final status
    try:
        client = chromadb.PersistentClient(path='./data/vector_db')
        collections = client.list_collections()
        total_docs = sum(c.count() for c in collections if c.name.startswith('repo_'))
        logger.info(f"📊 Total documents in vector DB: {total_docs}")
    except Exception as e:
        logger.warning(f"Error getting final count: {e}")
    
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        logger.info("🚀 Starting resume-capable bulk indexing...")
        index_all_repos_resume()
        logger.info("\n✅ Bulk indexing completed!")
    except KeyboardInterrupt:
        logger.info("\n⚠️  Indexing interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
