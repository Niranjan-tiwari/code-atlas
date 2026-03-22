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


def reindex_repo(repo_path: str, vector_db_path: str = "./data/vector_db") -> dict:
    """Re-index a single repo into the vector DB"""
    t = time.time()
    repo_path = Path(repo_path)
    
    if not repo_path.exists():
        return {"error": f"Path not found: {repo_path}", "success": False}
    
    repo_name = repo_path.name
    logger.info(f"Re-indexing {repo_name}...")
    
    try:
        # Use the existing index script
        result = subprocess.run(
            [sys.executable, f"{PROJECT_ROOT}/scripts/index_one_repo.py", str(repo_path)],
            capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT
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
                "repo": repo_name,
                "time_seconds": round(elapsed, 2),
                "output": result.stdout[-500:] if result.stdout else ""
            }
        else:
            return {
                "success": False,
                "repo": repo_name,
                "error": result.stderr[-500:] if result.stderr else "Unknown error"
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "repo": repo_name, "error": "Timeout (120s)"}
    except Exception as e:
        return {"success": False, "repo": repo_name, "error": str(e)}


def rebuild_unified(vector_db_path: str = "./data/vector_db"):
    """Rebuild the unified collection after re-indexing"""
    subprocess.run(
        [sys.executable, f"{PROJECT_ROOT}/scripts/build_unified_index.py"],
        capture_output=True, timeout=60, cwd=PROJECT_ROOT
    )


def handle_gitlab_webhook(payload: dict) -> dict:
    """Handle GitLab push webhook - extract repo path and re-index"""
    project = payload.get("project", {})
    repo_name = project.get("name", "")
    repo_url = project.get("git_http_url", "") or project.get("git_ssh_url", "")
    
    # Try to find the repo locally
    base_paths = [
        os.environ.get("REPOS_BASE_PATH", ""),
        "/path/to/your/repos",
        "/path/to/your/projects",
    ]
    
    for base in base_paths:
        if not base:
            continue
        repo_path = Path(base) / repo_name
        if repo_path.exists():
            return reindex_repo(str(repo_path))
    
    return {"success": False, "error": f"Repo {repo_name} not found locally"}
