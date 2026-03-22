"""
Cross-Repo Dependency Scanner: Scans all repos for Go modules,
Python packages, and identifies outdated/common dependencies.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger("dependency_scanner")


def scan_repo(repo_path: str) -> dict:
    """Scan a single repo for dependencies"""
    repo_path = Path(repo_path)
    repo_name = repo_path.name
    deps = {"go": [], "python": [], "node": []}
    
    # Go: go.mod
    go_mod = repo_path / "go.mod"
    if go_mod.exists():
        deps["go"] = _parse_go_mod(go_mod)
    
    # Python: requirements.txt
    for req_file in ["requirements.txt", "requirements-ai.txt"]:
        req_path = repo_path / req_file
        if req_path.exists():
            deps["python"].extend(_parse_requirements(req_path))
    
    # Node: package.json
    pkg_json = repo_path / "package.json"
    if pkg_json.exists():
        deps["node"] = _parse_package_json(pkg_json)
    
    total = sum(len(v) for v in deps.values())
    lang = "go" if deps["go"] else ("python" if deps["python"] else ("node" if deps["node"] else "unknown"))
    
    return {
        "repo": repo_name,
        "language": lang,
        "total_deps": total,
        "dependencies": deps
    }


def scan_all(base_path: str = None) -> dict:
    """Scan all repos under a base path"""
    paths_to_scan = []
    
    if base_path and Path(base_path).exists():
        paths_to_scan.append(base_path)
    else:
        # Default paths
        for p in ["/path/to/your/repos", "/path/to/your/projects"]:
            if Path(p).exists():
                paths_to_scan.append(p)
    
    all_repos = []
    dep_usage = defaultdict(list)  # dep_name -> [repos using it]
    
    for base in paths_to_scan:
        base = Path(base)
        for item in sorted(base.iterdir()):
            if item.is_dir() and (item / ".git").exists():
                result = scan_repo(str(item))
                if result["total_deps"] > 0:
                    all_repos.append(result)
                    # Track cross-repo usage
                    for lang, deps in result["dependencies"].items():
                        for dep in deps:
                            dep_name = dep.get("name", dep.get("module", ""))
                            if dep_name:
                                dep_usage[dep_name].append(result["repo"])
    
    # Find most common deps
    common_deps = sorted(
        [{"name": k, "used_by": v, "count": len(v)} for k, v in dep_usage.items()],
        key=lambda x: x["count"], reverse=True
    )[:30]
    
    return {
        "repos_scanned": len(all_repos),
        "repos": all_repos,
        "most_common_deps": common_deps,
        "total_unique_deps": len(dep_usage)
    }


def _parse_go_mod(path: Path) -> list:
    """Parse go.mod file"""
    deps = []
    in_require = False
    try:
        content = path.read_text()
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("require ("):
                in_require = True
                continue
            if line == ")":
                in_require = False
                continue
            if in_require and line and not line.startswith("//"):
                parts = line.split()
                if len(parts) >= 2:
                    deps.append({"module": parts[0], "version": parts[1]})
            elif line.startswith("require ") and "(" not in line:
                parts = line.replace("require ", "").split()
                if len(parts) >= 2:
                    deps.append({"module": parts[0], "version": parts[1]})
    except Exception as e:
        logger.debug(f"Error parsing {path}: {e}")
    return deps


def _parse_requirements(path: Path) -> list:
    """Parse requirements.txt"""
    deps = []
    try:
        for line in path.read_text().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                match = re.match(r'^([a-zA-Z0-9_-]+)\s*([><=!~]+\s*[\d.]+)?', line)
                if match:
                    deps.append({"name": match.group(1), "version": (match.group(2) or "").strip()})
    except Exception:
        pass
    return deps


def _parse_package_json(path: Path) -> list:
    """Parse package.json"""
    deps = []
    try:
        data = json.loads(path.read_text())
        for section in ["dependencies", "devDependencies"]:
            for name, version in data.get(section, {}).items():
                deps.append({"name": name, "version": version})
    except Exception:
        pass
    return deps
