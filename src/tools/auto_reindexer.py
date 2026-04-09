"""
Auto-Reindex: Re-index a repo when code changes (webhook or manual).
Supports GitLab webhook payload or direct repo path.
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("auto_reindexer")

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


def reindex_repo(repo_path: str, vector_db_path: str = "./data/qdrant_db") -> dict:
    """Re-index a single repo into the vector DB"""
    t = time.time()
    repo_path = Path(repo_path)
    
    if not repo_path.exists():
        return {"error": f"Path not found: {repo_path}", "success": False}
    
    repo_name = repo_path.name
    logger.info(f"Re-indexing {repo_name}...")
    
    try:
        base_path = str(repo_path.parent)
        timeout_sec = int(os.environ.get("INDEX_REPO_TIMEOUT_SEC", "3600"))
        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_ROOT
        result = subprocess.run(
            [
                sys.executable,
                f"{PROJECT_ROOT}/scripts/index_one_repo.py",
                "--repo",
                repo_name,
                "--base-path",
                base_path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec or None,
            cwd=PROJECT_ROOT,
            env=env,
        )
        
        elapsed = time.time() - t
        
        if result.returncode == 0:
            # Rebuild unified collection
            try:
                rebuild_unified(vector_db_path)
            except Exception as e:
                logger.warning(f"Unified rebuild failed: {e}")
            
            return {
                "success": True,
                "repo": repo_path.name,
                "time_seconds": round(elapsed, 2),
                "output": result.stdout[-500:] if result.stdout else ""
            }
        else:
            return {
                "success": False,
                "repo": repo_path.name,
                "error": result.stderr[-500:] if result.stderr else "Unknown error"
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "repo": repo_path.name,
            "error": f"Timeout ({timeout_sec}s)",
        }
    except Exception as e:
        return {"success": False, "repo": repo_path.name, "error": str(e)}


def rebuild_unified(vector_db_path: str = "./data/qdrant_db"):
    """Rebuild the unified collection after re-indexing"""
    subprocess.run(
        [sys.executable, f"{PROJECT_ROOT}/scripts/build_unified_index.py"],
        capture_output=True, timeout=60, cwd=PROJECT_ROOT
    )


def handle_gitlab_webhook(payload: dict) -> dict:
    """Handle GitLab push webhook - extract repo path and re-index"""
    from src.ai.indexing_config import load_indexing_base_paths

    project = payload.get("project", {})
    repo_name = project.get("name", "")
    _ = project.get("git_http_url", "") or project.get("git_ssh_url", "")

    base_paths = []
    if os.environ.get("REPOS_BASE_PATH"):
        base_paths.append(os.environ.get("REPOS_BASE_PATH"))
    base_paths.extend(load_indexing_base_paths())

    seen = set()
    for base in base_paths:
        if not base or base in seen:
            continue
        seen.add(base)
        repo_path = Path(base).expanduser() / repo_name
        if repo_path.is_dir() and (repo_path / ".git").exists():
            return reindex_repo(str(repo_path))

    return {"success": False, "error": f"Repo {repo_name} not found under indexing base_paths (clone locally first)"}
