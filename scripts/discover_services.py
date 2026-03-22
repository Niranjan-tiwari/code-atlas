#!/usr/bin/env python3
"""
Auto-discover systemd services and map to repositories
"""

import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.auto_discover import ServiceDiscoverer, RepoDiscoverer

def main():
    systemd_path = "/etc/systemd/system"
    base_path = "/path/to/your/repos"
    
    print("🔍 Auto-discovering systemd services...")
    print(f"   Scanning: {systemd_path}")
    print()
    
    # Discover services
    service_discoverer = ServiceDiscoverer(systemd_path)
    services = service_discoverer.discover_services()
    
    if not services:
        print("❌ No services found")
        return 1
    
    print(f"✅ Found {len(services)} services:")
    for service in services[:10]:  # Show first 10
        print(f"   - {service['service_name']}")
        if service.get('working_directory'):
            print(f"     WorkingDir: {service['working_directory']}")
    
    if len(services) > 10:
        print(f"   ... and {len(services) - 10} more")
    
    # Discover repos
    print()
    print("🔍 Discovering repositories...")
    repo_discoverer = RepoDiscoverer(base_path)
    repos = repo_discoverer.discover_repos()
    
    # Map services to repos
    print()
    print("🔗 Mapping services to repositories...")
    mapping = service_discoverer.map_services_to_repos(repos, services, base_path)
    
    if mapping:
        print(f"✅ Mapped {len(mapping)} services:")
        for service_name, repo_name in list(mapping.items())[:10]:
            print(f"   - {service_name} → {repo_name}")
    else:
        print("⚠️  No mappings found")
    
    # Save mapping
    mapping_path = Path(__file__).parent.parent / "config" / "services_mapping.json"
    mapping_path.parent.mkdir(exist_ok=True)
    
    with open(mapping_path, 'w') as f:
        json.dump({
            "services": services,
            "mapping": mapping
        }, f, indent=2)
    
    print()
    print(f"✅ Saved mapping to {mapping_path}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
