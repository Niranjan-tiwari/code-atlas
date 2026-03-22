"""
Migration Automator: Define a pattern replacement rule and apply it
across multiple repos in parallel. Creates branches, applies changes, commits.
"""

import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("migration_automator")


def run_migration(config: dict) -> dict:
    """
    Run a migration across repos.
    
    Config:
        base_path: Path to repos directory
        repos: List of repo names (or "all")
        find: Regex pattern to find
        replace: Replacement string
        file_pattern: Glob pattern for files (e.g., "*.go")
        branch: Branch name to create
        commit_message: Commit message
        dry_run: If True, preview only
    """
    base_path = Path(config.get("base_path", "/path/to/your/repos"))
    repos = config.get("repos", [])
    find_pattern = config.get("find", "")
    replace_str = config.get("replace", "")
    file_pattern = config.get("file_pattern", "*.go")
    branch = config.get("branch", "migration/auto")
    commit_msg = config.get("commit_message", "chore: automated migration")
    dry_run = config.get("dry_run", True)
    
    if not find_pattern:
        return {"error": "Missing 'find' pattern"}
    
    # Discover repos
    if not repos or repos == ["all"]:
        repos = [d.name for d in base_path.iterdir() if d.is_dir() and (d / ".git").exists()]
    
    results = []
    
    def process_repo(repo_name):
        repo_path = base_path / repo_name
        if not repo_path.exists():
            return {"repo": repo_name, "status": "not_found"}
        
        # Find matching files
        matches = []
        for f in repo_path.rglob(file_pattern):
            if ".git" in str(f) or "vendor" in str(f) or "node_modules" in str(f):
                continue
            try:
                content = f.read_text()
                found = re.findall(find_pattern, content)
                if found:
                    matches.append({
                        "file": str(f.relative_to(repo_path)),
                        "matches": len(found),
                        "preview": found[:3]
                    })
            except Exception:
                continue
        
        if not matches:
            return {"repo": repo_name, "status": "no_matches", "files_checked": 0}
        
        if dry_run:
            return {
                "repo": repo_name, "status": "dry_run",
                "matches": matches, "total_matches": sum(m["matches"] for m in matches)
            }
        
        # Apply migration
        try:
            # Create branch
            subprocess.run(["git", "checkout", "-b", branch], cwd=repo_path, capture_output=True)
            
            # Apply replacements
            changed_files = 0
            for match in matches:
                fpath = repo_path / match["file"]
                content = fpath.read_text()
                new_content = re.sub(find_pattern, replace_str, content)
                if new_content != content:
                    fpath.write_text(new_content)
                    changed_files += 1
            
            # Commit
            subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, capture_output=True)
            
            return {
                "repo": repo_name, "status": "applied",
                "branch": branch, "files_changed": changed_files
            }
        except Exception as e:
            return {"repo": repo_name, "status": "error", "error": str(e)}
    
    # Process repos in parallel
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(process_repo, repos))
    
    applied = [r for r in results if r.get("status") == "applied"]
    matched = [r for r in results if r.get("status") in ("applied", "dry_run")]
    
    return {
        "total_repos": len(repos),
        "repos_with_matches": len(matched),
        "repos_applied": len(applied),
        "dry_run": dry_run,
        "results": results
    }
