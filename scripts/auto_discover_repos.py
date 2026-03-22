#!/usr/bin/env python3
"""
Auto-discover repositories and update config
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.auto_discover import RepoDiscoverer

def main():
    base_path = "/path/to/your/repos"
    
    print("🔍 Auto-discovering repositories...")
    print(f"   Scanning: {base_path}")
    print()
    
    discoverer = RepoDiscoverer(base_path)
    repos = discoverer.discover_repos()
    
    if not repos:
        print("❌ No repositories found")
        return 1
    
    print(f"✅ Found {len(repos)} repositories:")
    for repo in repos:
        print(f"   - {repo['name']} (branch: {repo['source_branch']})")
    
    # Update repos_config.json
    config_path = Path(__file__).parent.parent / "config" / "repos_config.json"
    config_path.parent.mkdir(exist_ok=True)
    
    # Ensure all repos have default branch as master
    for repo in repos:
        if not repo.get("source_branch"):
            repo["source_branch"] = "master"
        elif repo["source_branch"] != "master":
            # Update to master if different
            print(f"   ⚠️  {repo['name']}: Changing branch from {repo['source_branch']} to master")
            repo["source_branch"] = "master"
    
    config = {
        "repos": repos
    }
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print()
    print(f"✅ Updated {config_path}")
    print(f"   Total repos: {len(repos)}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
