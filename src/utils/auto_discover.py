"""
Auto-discover repositories and services
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional


class RepoDiscoverer:
    """Auto-discover Git repositories"""
    
    def __init__(self, base_path: str, default_branch: str = None):
        """
        Args:
            base_path: Base directory containing git repos
            default_branch: Force this as the default branch for all repos
                           under this base_path (overrides git detection).
                           Set per workspace in config base_paths_config.
        """
        self.base_path = base_path
        self.forced_default_branch = default_branch
        self.logger = logging.getLogger("repo_discoverer")
    
    def discover_repos(self) -> List[Dict]:
        """Discover all Git repositories in base path"""
        repos = []
        
        if not os.path.exists(self.base_path):
            self.logger.warning(f"Base path does not exist: {self.base_path}")
            return repos
        
        # Scan directories
        for item in os.listdir(self.base_path):
            item_path = os.path.join(self.base_path, item)
            
            if not os.path.isdir(item_path):
                continue
            
            # Check if it's a Git repository
            git_dir = os.path.join(item_path, ".git")
            if not os.path.exists(git_dir):
                continue
            
            # Use forced default branch if set, otherwise detect from git
            if self.forced_default_branch:
                default_branch = self.forced_default_branch
            else:
                default_branch = self._get_default_branch(item_path)
            
            # Get GitLab URL if available
            gitlab_url = self._get_gitlab_url(item_path)
            
            repo_config = {
                "name": item,
                "local_path": item,
                "gitlab_url": gitlab_url or f"https://gitlab.com/org/{item}.git",
                "source_branch": default_branch,
                "component": self._detect_component(item),
                "description": f"Auto-discovered repository: {item}"
            }
            
            repos.append(repo_config)
            self.logger.info(f"Discovered repo: {item} (branch: {default_branch})")
        
        return repos
    
    def _get_default_branch(self, repo_path: str) -> str:
        """Get default branch (master/main)"""
        try:
            # Try to get default branch from remote
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                ref = result.stdout.strip()
                if '/origin/' in ref:
                    return ref.split('/origin/')[-1]
            
            # Check for master
            if os.path.exists(os.path.join(repo_path, ".git", "refs", "heads", "master")):
                return "master"
            
            # Check for main
            if os.path.exists(os.path.join(repo_path, ".git", "refs", "heads", "main")):
                return "main"
            
            # Default to master
            return "master"
        except Exception as e:
            self.logger.debug(f"Error getting default branch for {repo_path}: {e}")
            return "master"
    
    def _get_gitlab_url(self, repo_path: str) -> Optional[str]:
        """Get GitLab URL from git remote"""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        
        return None
    
    def _detect_component(self, repo_name: str) -> str:
        """Detect component type from repo name"""
        name_lower = repo_name.lower()
        
        if "webhook" in name_lower:
            return "webhooks"
        elif "api" in name_lower:
            return "api"
        elif "service" in name_lower:
            return "service"
        else:
            return "other"


class ServiceDiscoverer:
    """Auto-discover systemd services and map to repos"""
    
    def __init__(self, systemd_path: str = "/etc/systemd/system"):
        self.systemd_path = systemd_path
        self.logger = logging.getLogger("service_discoverer")
    
    def discover_services(self) -> List[Dict]:
        """Discover systemd services"""
        services = []
        
        if not os.path.exists(self.systemd_path):
            self.logger.warning(f"Systemd path does not exist: {self.systemd_path}")
            return services
        
        # Scan .service files
        for file in os.listdir(self.systemd_path):
            if not file.endswith('.service'):
                continue
            
            file_path = os.path.join(self.systemd_path, file)
            service_info = self._parse_service_file(file_path)
            
            if service_info:
                services.append(service_info)
        
        return services
    
    def _parse_service_file(self, file_path: str) -> Optional[Dict]:
        """Parse systemd service file"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            service_name = os.path.basename(file_path).replace('.service', '')
            
            # Extract WorkingDirectory
            working_dir = None
            for line in content.split('\n'):
                if line.startswith('WorkingDirectory='):
                    working_dir = line.split('=', 1)[1].strip()
                    break
            
            # Extract ExecStart to find repo
            exec_start = None
            for line in content.split('\n'):
                if line.startswith('ExecStart='):
                    exec_start = line.split('=', 1)[1].strip()
                    break
            
            return {
                "service_name": service_name,
                "file_path": file_path,
                "working_directory": working_dir,
                "exec_start": exec_start
            }
        except Exception as e:
            self.logger.debug(f"Error parsing service file {file_path}: {e}")
            return None
    
    def map_services_to_repos(self, repos: List[Dict], services: List[Dict], base_path: str = "") -> Dict[str, str]:
        """Map systemd services to repositories"""
        mapping = {}
        
        for service in services:
            working_dir = service.get("working_directory", "")
            exec_start = service.get("exec_start", "")
            
            # Try to match by working directory
            for repo in repos:
                repo_name = repo.get("name", "")
                repo_local_path = repo.get("local_path", repo_name)
                
                # Build full repo path
                if base_path:
                    repo_path = os.path.join(base_path, repo_local_path)
                else:
                    repo_path = repo_local_path
                
                # Check if working directory contains repo path
                if working_dir and repo_path and repo_path in working_dir:
                    mapping[service["service_name"]] = repo_name
                    break
                
                # Also check if repo name appears in working directory
                if working_dir and repo_name in working_dir:
                    mapping[service["service_name"]] = repo_name
                    break
            
            # Try to match by service name
            if service["service_name"] not in mapping:
                service_name_lower = service["service_name"].lower()
                for repo in repos:
                    repo_name = repo.get("name", "")
                    if repo_name.lower() in service_name_lower or service_name_lower in repo_name.lower():
                        mapping[service["service_name"]] = repo_name
                        break
        
        return mapping
