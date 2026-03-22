"""
Cross-Repo Refactoring Engine: Rename functions, variables, or patterns
across multiple repos. Understands Go imports and references.
"""

import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("refactoring_engine")


def run_refactor(config: dict) -> dict:
    """
    Run a refactoring operation across repos.
    
    Config:
        base_path: Path to repos
        repos: List of repo names (or "all")
        type: "rename_function" | "rename_variable" | "rename_package" | "regex_replace"
        old_name: Current name
        new_name: New name
        file_pattern: File glob (default: "*.go")
        branch: Branch to create
        dry_run: If True, preview only
    """
    base_path = Path(config.get("base_path", "/path/to/your/repos"))
    repos = config.get("repos", [])
    refactor_type = config.get("type", "rename_function")
    old_name = config.get("old_name", "")
    new_name = config.get("new_name", "")
    file_pattern = config.get("file_pattern", "*.go")
    branch = config.get("branch", f"refactor/{old_name}-to-{new_name}")
    dry_run = config.get("dry_run", True)
    
    if not old_name or not new_name:
        return {"error": "Missing old_name or new_name"}
    
    # Build regex based on type
    if refactor_type == "rename_function":
        # Match function definition and calls
        pattern = rf'\b{re.escape(old_name)}\b'
        replacement = new_name
    elif refactor_type == "rename_variable":
        pattern = rf'\b{re.escape(old_name)}\b'
        replacement = new_name
    elif refactor_type == "rename_package":
        pattern = rf'"{re.escape(old_name)}"'
        replacement = f'"{new_name}"'
    elif refactor_type == "regex_replace":
        pattern = old_name  # Treat as raw regex
        replacement = new_name
    else:
        return {"error": f"Unknown type: {refactor_type}"}
    
    # Discover repos
    if not repos or repos == ["all"]:
        repos = [d.name for d in base_path.iterdir() if d.is_dir() and (d / ".git").exists()]
    
    def process_repo(repo_name):
        repo_path = base_path / repo_name
        if not repo_path.exists():
            return {"repo": repo_name, "status": "not_found"}
        
        changes = []
        for f in repo_path.rglob(file_pattern):
            if ".git" in str(f) or "vendor" in str(f):
                continue
            try:
                content = f.read_text()
                matches = re.findall(pattern, content)
                if matches:
                    rel_path = str(f.relative_to(repo_path))
                    changes.append({
                        "file": rel_path,
                        "occurrences": len(matches)
                    })
                    
                    if not dry_run:
                        new_content = re.sub(pattern, replacement, content)
                        f.write_text(new_content)
            except Exception:
                continue
        
        if not changes:
            return {"repo": repo_name, "status": "no_matches"}
        
        if not dry_run and changes:
            try:
                subprocess.run(["git", "checkout", "-b", branch], cwd=repo_path, capture_output=True)
                subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True)
                msg = f"refactor: rename {old_name} to {new_name}"
                subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, capture_output=True)
            except Exception as e:
                return {"repo": repo_name, "status": "error", "error": str(e)}
        
        total_occurrences = sum(c["occurrences"] for c in changes)
        return {
            "repo": repo_name,
            "status": "dry_run" if dry_run else "applied",
            "files_affected": len(changes),
            "total_occurrences": total_occurrences,
            "changes": changes
        }
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(process_repo, repos))
    
    affected = [r for r in results if r.get("status") in ("dry_run", "applied")]
    
    return {
        "refactor_type": refactor_type,
        "old_name": old_name,
        "new_name": new_name,
        "dry_run": dry_run,
        "total_repos": len(repos),
        "repos_affected": len(affected),
        "total_occurrences": sum(r.get("total_occurrences", 0) for r in results),
        "results": results
    }
