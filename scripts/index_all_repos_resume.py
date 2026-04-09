#!/usr/bin/env python3
"""
Resume-capable bulk indexing of all repositories
Handles interruptions and continues from where it left off
"""

import sys
import os
import logging
import subprocess
from pathlib import Path
from typing import List, Set
import time
import json
import gc  # Garbage collection

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.index_one_repo import load_code_files, chunk_code
from src.ai.vector_db import VectorDB
from src.ai.vector_backend import (
    count_all_repo_chunks,
    indexed_repo_slugs,
    repo_collection_name,
    repo_collection_slug,
)
from src.ai.indexing_config import load_indexing_base_paths

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
    """Get list of already indexed repositories (Qdrant repo_* collections)."""
    try:
        indexed = indexed_repo_slugs()
        for repo_name in sorted(indexed):
            logger.info(f"Found indexed repo: {repo_name}")
        return indexed
    except Exception as e:
        logger.warning(f"Error checking indexed repos: {e}")
        return set()


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
        _emit_subprocess_reason("repo_path_missing")
        return False
    
    slug = repo_collection_slug(repo_name, base_path)
    collection = collection_name or repo_collection_name(repo_name, base_path)
    
    try:
        logger.info(f"📂 Loading code files from {repo_name}...")
        files = load_code_files(repo_path)
        
        if not files:
            logger.warning(f"No code files found in {repo_name}")
            _emit_subprocess_reason("no_matching_source_files")
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
            
            # Log progress every 10 files; always advance stall clock so huge single files don't false-timeout
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
                        "repo": slug,
                        "file": str(file_path),
                        "language": language,
                        "chunk": chunk_idx,
                        "total_chunks": len(chunks)
                    })
                    all_ids.append(f"{slug}_{file_path}_{chunk_idx}")
                
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
        _emit_subprocess_reason("exception")
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


def _subprocess_indexing_env(project_root: Path) -> dict:
    """Quieter Hugging Face / tokenizers; same PYTHONPATH."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    env["ATLAS_INDEX_SUBPROCESS_CHILD"] = "1"
    env.setdefault("TRANSFORMERS_VERBOSITY", "error")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    return env


def _emit_subprocess_reason(reason: str) -> None:
    """One-line stderr for parent to classify failures (child only)."""
    if os.environ.get("ATLAS_INDEX_SUBPROCESS_CHILD"):
        print(f"ATLAS_INDEX_REASON={reason}", file=sys.stderr, flush=True)


def _format_subprocess_failure(repo_name: str, returncode: int, stderr: str, stdout: str) -> str:
    """Avoid logging megabytes of captured INFO as ERROR; classify empty repos."""
    blob = (stderr or "") + "\n" + (stdout or "")
    for line in (stderr or "").splitlines():
        if line.strip().startswith("ATLAS_INDEX_REASON="):
            code = line.split("=", 1)[-1].strip()
            if code == "no_matching_source_files":
                return "no indexable files (go/py/js/ts/java) — add skip_repos or extend load_code_files"
            if code == "repo_path_missing":
                return "repository path missing"
            if code == "exception":
                return "exception during indexing (see logs/indexing_bulk.log)"
            return f"child reported: {code}"
    if "No code files found" in blob:
        return f"no indexable files (go/py/js/ts/java) — add skip_repos or extend load_code_files"
    # Real errors often on stderr; keep last non-empty lines
    lines = [ln.strip() for ln in blob.splitlines() if ln.strip() and " - INFO - " not in ln]
    tail = "\n".join(lines[-12:]) if lines else ""
    return tail[-1500:].strip() or f"exit {returncode}"


def _warm_shared_embeddings() -> None:
    """Load embedding model once before in-process bulk loop."""
    try:
        from src.ai.embeddings.ollama_embed import get_best_embedding_function

        fn = get_best_embedding_function()
        if fn:
            fn(["__index_warmup__"])
            logger.info("✅ Embedding model warmed (singleton; reused for each repo in this process)")
    except Exception as e:
        logger.warning(f"Warmup skipped: {e}")


def _run_one_repo_subprocess(
    repo_name: str,
    base_path: str,
    repo_timeout_sec: int,
    project_root: Path,
) -> tuple[bool, str]:
    """Run indexing in a child process; on timeout the child is killed (unlike daemon threads)."""
    helper = project_root / "scripts" / "_bulk_index_single.py"
    env = _subprocess_indexing_env(project_root)
    try:
        proc = subprocess.run(
            [sys.executable, str(helper), repo_name, base_path],
            cwd=str(project_root),
            env=env,
            timeout=repo_timeout_sec if repo_timeout_sec > 0 else None,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True, ""
        detail = _format_subprocess_failure(
            repo_name, proc.returncode, proc.stderr or "", proc.stdout or ""
        )
        return False, detail
    except subprocess.TimeoutExpired:
        return False, f"timeout after {repo_timeout_sec}s (process killed)"


def index_all_repos_resume(
    paths: list[str] | None = None,
    *,
    repo_timeout_sec: int | None = None,
    use_subprocess: bool = True,
    build_unified: bool = False,
):
    """Index all repos with resume capability."""
    project_root = Path(__file__).resolve().parent.parent
    if repo_timeout_sec is None:
        repo_timeout_sec = int(os.environ.get("INDEX_REPO_TIMEOUT_SEC", "3600"))
    paths = paths if paths is not None else load_indexing_base_paths()
    if not paths:
        logger.error(
            "No base paths: create config/indexing_paths.json from "
            "config/indexing_paths.json.example or set CODE_ATLAS_INDEX_PATHS"
        )
        return
    
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
    
    # Filter: skip by folder name (skip_list) or by full collection slug (indexed)
    repos_to_index = []
    for repo, path in all_repos:
        if repo in skip_list:
            continue
        if repo_collection_slug(repo, path) in indexed_repos:
            continue
        repos_to_index.append((repo, path))
    
    logger.info(f"📊 Total repos: {len(all_repos)}")
    logger.info(f"📊 Already indexed: {len(indexed_repos)}")
    logger.info(f"📊 Skipped: {len(skip_list)}")
    logger.info(f"📊 Remaining to index: {len(repos_to_index)}")
    logger.info("=" * 80)
    
    if not repos_to_index:
        logger.info("✅ All repositories already indexed!")
        return

    if not use_subprocess:
        logger.info("⚡ In-process mode: one embedding model for all repos (faster; use subprocess if a repo hangs)")
        _warm_shared_embeddings()

    successful = 0
    failed = 0
    skipped_no_code = 0
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
        err_detail = ""
        if use_subprocess:
            success, err_detail = _run_one_repo_subprocess(
                repo_name, base_path, repo_timeout_sec, project_root
            )
            if err_detail:
                if "no indexable files" in err_detail:
                    logger.warning(f"⏭️  {repo_name}: {err_detail[:300]}")
                else:
                    logger.error(f"❌ {repo_name}: {err_detail[:800]}")
        else:
            try:
                success = index_repo_robust(repo_name, base_path)
            except Exception as e:
                logger.error(f"❌ {repo_name}: {e}")
                success = False

        repo_time = time.time() - repo_start
        if repo_time > 600 and not success:
            logger.warning(f"⚠️  {repo_name} ran {repo_time/60:.1f} min then failed or timed out — continuing")
        
        # Force GC after each repo to free memory
        gc.collect()
        
        # Longer delay between repos to prevent system overload
        time.sleep(2)
        
        if success:
            successful += 1
            logger.info(f"✅ {repo_name} completed in {repo_time:.1f}s")
        else:
            if use_subprocess and err_detail and "no indexable files" in err_detail:
                skipped_no_code += 1
                logger.warning(f"⏭️  {repo_name}: no matching source files after {repo_time:.1f}s")
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
    logger.info(f"⏭️  No matching source files: {skipped_no_code}")
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
        total_docs = count_all_repo_chunks()
        logger.info(f"📊 Total documents in vector DB: {total_docs}")
    except Exception as e:
        logger.warning(f"Error getting final count: {e}")
    
    logger.info("=" * 80)

    if build_unified:
        logger.info("🔧 Building unified_code collection...")
        try:
            from src.ai.qdrant_rag_support import rebuild_unified_collection
            from src.ai.vector_backend import vector_db_path

            n = rebuild_unified_collection(vector_db_path(), verbose=True)
            logger.info(f"✅ unified_code: {n} points")
        except Exception as e:
            logger.error(f"❌ unified_code build failed: {e}", exc_info=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Bulk index Git repos into Qdrant")
    ap.add_argument(
        "--paths",
        type=str,
        default="",
        help="Comma-separated base directories (overrides config / env)",
    )
    ap.add_argument(
        "--repo-timeout",
        type=int,
        default=None,
        help="Seconds per repo (0 = no limit). Default: INDEX_REPO_TIMEOUT_SEC or 3600",
    )
    ap.add_argument(
        "--no-subprocess",
        action="store_true",
        help="Index in-process: load embedding model once (fast). Env: INDEX_BULK_IN_PROCESS=1. "
        "Default is subprocess per repo (survives hangs via timeout).",
    )
    ap.add_argument(
        "--build-unified",
        action="store_true",
        help="After all repos, merge repo_* into unified_code",
    )
    args = ap.parse_args()
    override = [p.strip() for p in args.paths.split(",") if p.strip()] or None
    in_process = args.no_subprocess or os.environ.get("INDEX_BULK_IN_PROCESS", "").lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        logger.info("🚀 Starting resume-capable bulk indexing...")
        index_all_repos_resume(
            paths=override,
            repo_timeout_sec=args.repo_timeout,
            use_subprocess=not in_process,
            build_unified=args.build_unified,
        )
        logger.info("\n✅ Bulk indexing completed!")
    except KeyboardInterrupt:
        logger.info("\n⚠️  Indexing interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
