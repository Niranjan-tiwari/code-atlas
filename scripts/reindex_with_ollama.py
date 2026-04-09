#!/usr/bin/env python3
"""
Re-index all repos using BAAI/bge-small or bge-m3 embeddings.

Uses sentence-transformers directly (faster than Ollama HTTP).

Features:
  - Parallel processing (ProcessPoolExecutor, 75% of CPU cores)
  - Incremental reindexing (SHA-256 file hashing, skip unchanged files)
  - AST-based chunking (functions/classes) with line-based fallback

Full reindex:
  python3 scripts/reindex_with_ollama.py

Resume after interruption (skips already-indexed repos):
  python3 scripts/reindex_with_ollama.py --resume

Incremental (skip unchanged files within repos):
  python3 scripts/reindex_with_ollama.py --resume --incremental

Parallel workers (default: 75% of cores):
  python3 scripts/reindex_with_ollama.py --workers 8

Scan paths: config/indexing_paths.json, REPOS_BASE_PATH, or:
  python3 scripts/reindex_with_ollama.py --paths /path/a,/path/b

Override model: EMBED_MODEL=bge-small python3 scripts/reindex_with_ollama.py
"""

import sys
import os
import time
import shutil
import hashlib
import json as _json
import multiprocessing as mp
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

STATE_DIR = "./data/reindex_state"

# Force flush on all prints
import builtins
_orig_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)

# Module-level for worker initializer
_worker_emb_fn = None
_worker_model_key = None


def _worker_init(model_key: str):
    """Initialize embedding model in worker process (called once per worker)"""
    global _worker_emb_fn, _worker_model_key
    _worker_model_key = model_key
    from src.ai.embeddings.ollama_embed import SentenceTransformerEmbedding
    _worker_emb_fn = SentenceTransformerEmbedding(model_key)
    _worker_emb_fn._load()


def _file_hash(content: str) -> str:
    """SHA-256 hash of file content for incremental indexing"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_state(repo_name: str, state_dir: Path) -> dict:
    """Load file hash state for a repo"""
    state_path = state_dir / f"{repo_name}.json"
    if state_path.exists():
        try:
            return _json.loads(state_path.read_text())
        except Exception:
            return {}
    return {}


def _save_state(repo_name: str, state_dir: Path, state: dict):
    """Save file hash state for a repo"""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{repo_name}.json"
    state_path.write_text(_json.dumps(state, sort_keys=True))


def _chunk_with_ast_or_fallback(
    content: str, language: str, file_path: str, repo_name: str
) -> tuple[list[str], list[dict], list[str]]:
    """
    Chunk code using AST (parent-child) when possible, else line/function-based.
    Returns (docs, metas, ids).
    """
    from scripts.index_one_repo import chunk_code
    from src.ai.chunking import ParentChildIndexer

    doc_id = [0]  # Mutable for closure

    def next_id():
        doc_id[0] += 1
        return doc_id[0] - 1

    all_docs = []
    all_metas = []
    all_ids = []

    try:
        indexer = ParentChildIndexer()
        pc_chunks = indexer.create_parent_child_chunks(
            content=content, language=language, file_path=file_path, repo_name=repo_name
        )
        if pc_chunks and len(pc_chunks) > 0:
            for pc in pc_chunks:
                # Child chunk (for precise search)
                all_docs.append(pc.child_code)
                meta = dict(pc.child_metadata)
                meta["language"] = meta.get("language", language).upper()
                all_metas.append(meta)
                all_ids.append(f"{repo_name}_{file_path}_child_{next_id()}")
                # Parent chunk (for context)
                all_docs.append(pc.parent_code)
                meta = dict(pc.parent_metadata)
                meta["language"] = meta.get("language", language).upper()
                all_metas.append(meta)
                all_ids.append(f"{repo_name}_{file_path}_parent_{next_id()}")
            return (all_docs, all_metas, all_ids)
    except Exception:
        pass

    # Fallback: line/function-based chunking
    chunks = chunk_code(content, language=language)
    for chunk_idx, chunk in enumerate(chunks):
        all_docs.append(chunk)
        all_metas.append({
            "repo": repo_name, "file": file_path, "language": language.upper(),
            "chunk": chunk_idx, "total_chunks": len(chunks),
        })
        all_ids.append(f"{repo_name}_{file_path}_{chunk_idx}_{next_id()}")
    return (all_docs, all_metas, all_ids)


def _index_repo_worker(args: tuple) -> dict:
    """
    Worker: process one repo (load files, chunk, embed).
    Returns dict with repo_name, ids, embeddings, metadatas, documents,
    chunk_count, file_count, skipped_files, new_state, error.
    """
    (
        repo_path_str,
        model_key,
        skip_repos,
        already_indexed,
        resume,
        incremental,
        state_dir_str,
        timeout_sec,
        max_chunks,
    ) = args

    result = {
        "repo_name": "",
        "ids": [],
        "embeddings": [],
        "metadatas": [],
        "documents": [],
        "chunk_count": 0,
        "file_count": 0,
        "skipped_files": 0,
        "files_modified": [],  # for incremental: files we actually processed
        "new_state": {},
        "error": None,
    }

    repo_path = Path(repo_path_str)
    repo_folder = repo_path.name
    parent_name = repo_path.parent.name
    repo_slug = f"{parent_name}_{repo_folder}".replace(".", "_")
    result["repo_name"] = repo_slug

    if repo_folder in skip_repos:
        result["error"] = "skip_list"
        return result
    if resume and repo_slug in already_indexed:
        result["error"] = "already_indexed"
        return result

    # Timeout (Unix)
    def _timeout_handler(signum, frame):
        raise TimeoutError("Indexing timed out")

    try:
        if timeout_sec and hasattr(__import__("signal").signal, "__call__"):
            import signal
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_sec)

        from scripts.index_one_repo import load_code_files

        state_dir = Path(state_dir_str)
        state = _load_state(repo_slug, state_dir) if incremental else {}

        files = load_code_files(repo_path)
        if not files:
            result["error"] = "no_files"
            return result

        all_docs = []
        all_metas = []
        all_ids = []
        new_state = {}

        for file_path, content, language in files:
            fhash = _file_hash(content)
            if incremental and state.get(file_path) == fhash:
                result["skipped_files"] += 1
                new_state[file_path] = fhash
                continue

            result["files_modified"].append(file_path)
            docs, metas, ids = _chunk_with_ast_or_fallback(
                content, language, file_path, repo_slug
            )
            base = len(all_docs)
            all_docs.extend(docs)
            all_metas.extend(metas)
            all_ids.extend(ids)
            new_state[file_path] = fhash

        if max_chunks and len(all_docs) > max_chunks:
            result["error"] = f"too_large:{len(all_docs)}"
            return result

        if not all_docs:
            result["error"] = "no_chunks"
            result["new_state"] = new_state
            return result

        # Embed in batches
        global _worker_emb_fn
        if _worker_emb_fn is None:
            _worker_init(model_key)
        emb_fn = _worker_emb_fn

        batch_size = 200
        all_embeddings = []
        for start in range(0, len(all_docs), batch_size):
            end = min(start + batch_size, len(all_docs))
            batch = all_docs[start:end]
            embs = emb_fn(batch)
            all_embeddings.extend(embs)

        result["ids"] = all_ids
        result["embeddings"] = all_embeddings
        result["metadatas"] = all_metas
        result["documents"] = all_docs
        result["chunk_count"] = len(all_docs)
        result["file_count"] = len(files)
        result["new_state"] = new_state

        if timeout_sec:
            try:
                import signal as _s
                if hasattr(_s, "SIGALRM"):
                    _s.alarm(0)
            except Exception:
                pass

    except TimeoutError:
        try:
            import signal as _s
            if hasattr(_s, "SIGALRM"):
                _s.alarm(0)
        except Exception:
            pass
        result["error"] = "timeout"
    except Exception as e:
        try:
            import signal as _s
            if hasattr(_s, "SIGALRM"):
                _s.alarm(0)
        except Exception:
            pass
        result["error"] = str(e)[:120]

    return result


def main():
    import argparse

    from qdrant_client import QdrantClient

    from src.ai.qdrant_rag_support import (
        delete_points_by_files,
        ensure_qdrant_collection,
        qdrant_upsert_points,
        rebuild_unified_collection,
    )
    from src.ai.indexing_config import load_indexing_base_paths
    from src.ai.vector_backend import indexed_repo_slugs, vector_db_path

    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Skip already-indexed repos")
    parser.add_argument("--incremental", action="store_true", help="Skip unchanged files (use with --resume)")
    parser.add_argument("--workers", type=int, default=None, help="Parallel workers (default: 75%% of CPU cores)")
    parser.add_argument("--timeout", type=int, default=600, help="Per-repo timeout seconds (0=no limit)")
    parser.add_argument("--skip-repos", type=str, default="", help="Comma-separated repo names to skip")
    parser.add_argument("--skip-file", type=str, default="", help="JSON file with repo names to skip")
    parser.add_argument("--max-chunks", type=int, default=0, help="Skip repo if more chunks than this")
    parser.add_argument("--paths", type=str, default=None, help="Comma-separated base paths to scan")
    args = parser.parse_args()

    resume = args.resume
    incremental = args.incremental
    timeout_sec = args.timeout
    max_chunks = args.max_chunks

    num_workers = args.workers
    if num_workers is None:
        import psutil
        try:
            mem_gb = psutil.virtual_memory().total / (1024**3)
        except Exception:
            mem_gb = 16
        # 2 workers for <=16GB, scale up for more RAM
        if mem_gb <= 16:
            num_workers = 2
        else:
            num_workers = max(2, int(mp.cpu_count() * 0.75))
    num_workers = max(1, min(num_workers, mp.cpu_count() or 4))

    # Build skip set
    skip_repos = set()
    if args.skip_repos:
        skip_repos.update(r.strip() for r in args.skip_repos.split(",") if r.strip())
    if args.skip_file:
        p = Path(args.skip_file)
        if p.exists():
            try:
                data = _json.loads(p.read_text())
                if isinstance(data, dict) and "repos" in data:
                    skip_repos.update(data["repos"])
                elif isinstance(data, dict) and "skipped_repos" in data:
                    skip_repos.update(r.get("repo_name", "") for r in data["skipped_repos"] if isinstance(r, dict))
                elif isinstance(data, list):
                    skip_repos.update(str(r) for r in data)
            except Exception as e:
                print(f"  Warning: could not read skip file: {e}")

    model_key = os.environ.get("EMBED_MODEL", "bge-small")
    state_dir = Path(STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  Re-indexing with model: {model_key}")
    print(f"  Workers: {num_workers} (parallel)")
    if resume:
        print("  Mode: RESUME (skip already-indexed repos)")
    if incremental:
        print("  Mode: INCREMENTAL (skip unchanged files)")
    if skip_repos:
        print(f"  Skipping {len(skip_repos)} repos")
    if timeout_sec:
        print(f"  Per-repo timeout: {timeout_sec}s")
    if max_chunks:
        print(f"  Max chunks per repo: {max_chunks}")
    print("=" * 60)

    # Load model in main process (for unified build)
    print("\n  Loading embedding model...")
    t = time.time()
    from src.ai.embeddings.ollama_embed import SentenceTransformerEmbedding
    emb_fn = SentenceTransformerEmbedding(model_key)
    emb_fn._load()
    print(f"  OK: {emb_fn.model_name} ({emb_fn.dims} dims) in {time.time()-t:.1f}s\n")

    vp = vector_db_path()
    print(f"  Vector DB path: {vp}\n")

    # Backup/wipe DB if not resuming
    if not resume and Path(vp).exists():
        backup_path = f"{vp}_backup_{int(time.time())}"
        print(f"  Backing up DB to {backup_path}...")
        shutil.copytree(vp, backup_path)
        shutil.rmtree(vp)

    # Discover repos (same folder name under different roots is allowed)
    base_paths_str = (args.paths or os.environ.get("REPOS_BASE_PATH") or "").strip()
    if base_paths_str:
        sep = "," if "," in base_paths_str else ":"
        base_paths = [p.strip() for p in base_paths_str.split(sep) if p.strip()]
    else:
        base_paths = load_indexing_base_paths()
    if not base_paths:
        print("  No scan paths: use --paths, REPOS_BASE_PATH, or config/indexing_paths.json")
        sys.exit(1)

    repos = []
    seen_resolved = set()
    for bp in base_paths:
        base = Path(bp)
        if not base.exists():
            print(f"  Warning: {bp} does not exist")
            continue
        for item in sorted(base.iterdir()):
            if not item.is_dir() or not (item / ".git").exists():
                continue
            key = str(item.resolve())
            if key in seen_resolved:
                continue
            seen_resolved.add(key)
            repos.append(item)

    print(f"  Found {len(repos)} repos\n")
    if not repos:
        print("  No repos found!")
        sys.exit(1)

    # Already indexed (for --resume)
    already_indexed = set()
    if resume and Path(vp).exists():
        try:
            already_indexed = indexed_repo_slugs()
        except Exception:
            pass
        if already_indexed:
            print(f"  Resuming: {len(already_indexed)} repos already indexed, will skip\n")

    # Prepare worker args
    worker_args = [
        (
            str(rp),
            model_key,
            skip_repos,
            already_indexed,
            resume,
            incremental,
            str(state_dir),
            timeout_sec,
            max_chunks,
        )
        for rp in repos
    ]

    # Run workers (main process writes Qdrant)
    Path(vp).mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=vp)
    total_chunks = 0
    indexed_repos = 0
    failed_repos = 0
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=num_workers, initializer=_worker_init, initargs=(model_key,)) as executor:
        future_to_repo = {executor.submit(_index_repo_worker, a): a[0] for a in worker_args}
        done = 0
        for future in as_completed(future_to_repo, timeout=(len(repos) * (timeout_sec or 900)) + 60):
            try:
                res = future.result(timeout=10)
            except Exception as e:
                done += 1
                failed_repos += 1
                repo_str = future_to_repo.get(future, "?")
                print(f"  [{done}/{len(repos)}] {Path(repo_str).name}: FAILED - {e}")
                continue

            done += 1
            rname = res["repo_name"]
            err = res.get("error")

            if err == "skip_list":
                print(f"  [{done}/{len(repos)}] {rname}: in skip list")
                continue
            if err == "already_indexed":
                print(f"  [{done}/{len(repos)}] {rname}: already indexed, skipping")
                continue
            if err == "no_files":
                print(f"  [{done}/{len(repos)}] {rname}: no code files")
                continue
            if err == "no_chunks":
                print(f"  [{done}/{len(repos)}] {rname}: no chunks (all skipped)")
                continue
            if err and str(err).startswith("too_large:"):
                print(f"  [{done}/{len(repos)}] {rname}: too many chunks, skipping")
                failed_repos += 1
                continue
            if err == "timeout":
                print(f"  [{done}/{len(repos)}] {rname}: TIMEOUT")
                failed_repos += 1
                continue
            if err:
                print(f"  [{done}/{len(repos)}] {rname}: ERROR - {err}")
                failed_repos += 1
                continue

            # Write to Qdrant
            try:
                col_name = f"repo_{rname}"
                ids = res["ids"]
                metas = res["metadatas"]
                docs = res["documents"]
                embs = res["embeddings"]
                files_modified = res.get("files_modified", [])
                dim = len(embs[0]) if embs else emb_fn.dims

                if incremental and files_modified:
                    if client.collection_exists(col_name):
                        delete_points_by_files(client, col_name, files_modified)
                    ensure_qdrant_collection(client, col_name, dim)
                else:
                    if client.collection_exists(col_name):
                        client.delete_collection(collection_name=col_name)
                    ensure_qdrant_collection(client, col_name, dim)

                if ids:
                    qdrant_upsert_points(client, col_name, docs, embs, metas, ids)

                total_chunks += res["chunk_count"]
                indexed_repos += 1
                skip_str = f", {res['skipped_files']} files skipped (unchanged)" if res.get("skipped_files") else ""
                print(f"  [{done}/{len(repos)}] {rname}: {res['file_count']} files, {res['chunk_count']} chunks{skip_str}")

                # Save incremental state
                if incremental and res.get("new_state"):
                    _save_state(rname, state_dir, res["new_state"])

            except Exception as e:
                print(f"  [{done}/{len(repos)}] {rname}: DB write failed - {e}")
                failed_repos += 1

    total_time = time.time() - t_start
    print(f"\n  Indexed {indexed_repos} repos, {total_chunks} chunks in {total_time:.0f}s")
    if failed_repos:
        print(f"  Skipped {failed_repos} repos (errors/timeout)")

    print(f"\n  Building unified collection...")
    try:
        ucount = rebuild_unified_collection(vp, verbose=False)
        print(f"  Unified: {ucount} chunks")
    except Exception as e:
        print(f"  Warning: unified build failed: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Re-indexing complete!")
    print(f"  Model: {emb_fn.model_name} ({emb_fn.dims} dims)")
    print(f"  Repos: {indexed_repos}" + (f" ({failed_repos} failed)" if failed_repos else ""))
    print(f"  Chunks: {total_chunks}")
    print(f"  Time: {total_time:.0f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
