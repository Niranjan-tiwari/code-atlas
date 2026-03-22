"""
GitLab API integration for automatic Merge Request creation.

Supports creating MRs after branch push, with Jira ID tracking,
auto-assignment, and label management.

Requires:
  - GITLAB_TOKEN environment variable (Personal Access Token with api scope)
  - OR gitlab_token in config/config.json
"""

import os
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional
from pathlib import Path


logger = logging.getLogger("parallel_repo_worker.gitlab")


class GitLabAPI:
    """GitLab REST API client for Merge Request operations"""
    
    def __init__(self, token: str = None, base_url: str = None):
        """
        Initialize GitLab API client.
        
        Args:
            token: GitLab private token. Falls back to GITLAB_TOKEN env var or config.
            base_url: GitLab base URL (e.g., https://gitlab.com). Auto-detected from repo URL if not set.
        """
        self.token = token or self._load_token()
        self.base_url = base_url
        
        if not self.token:
            logger.warning(
                "No GitLab token found. Set GITLAB_TOKEN env var or add "
                "'gitlab_token' to config/config.json to enable MR creation."
            )
    
    def _load_token(self) -> Optional[str]:
        """Load GitLab token from env var or config file"""
        # Try environment variable first
        token = os.environ.get("GITLAB_TOKEN")
        if token:
            return token
        
        # Try config file
        config_path = Path("config/config.json")
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                return config.get("gitlab_token")
            except (json.JSONDecodeError, IOError):
                pass
        
        return None
    
    def _parse_gitlab_url(self, gitlab_url: str) -> tuple:
        """
        Parse a GitLab remote URL to extract base URL and project path.
        
        Supports:
          - https://gitlab.example.com/group/project.git
          - git@gitlab.example.com:group/project.git
          - ssh://git@gitlab.example.com/group/project.git
        
        Returns:
            (base_url, project_path) e.g., ("https://gitlab.example.com", "group/project")
        """
        project_path = ""
        base_url = self.base_url or ""
        
        if gitlab_url.startswith("git@"):
            # git@gitlab.example.com:group/subgroup/project.git
            parts = gitlab_url.split(":", 1)
            host = parts[0].replace("git@", "")
            project_path = parts[1].rstrip("/").removesuffix(".git")
            base_url = base_url or f"https://{host}"
        
        elif gitlab_url.startswith("ssh://"):
            # ssh://git@gitlab.example.com/group/project.git
            from urllib.parse import urlparse
            parsed = urlparse(gitlab_url)
            host = parsed.hostname
            project_path = parsed.path.lstrip("/").removesuffix(".git")
            base_url = base_url or f"https://{host}"
        
        elif gitlab_url.startswith("http"):
            # https://gitlab.example.com/group/project.git
            from urllib.parse import urlparse
            parsed = urlparse(gitlab_url)
            host = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port and parsed.port not in (80, 443):
                host += f":{parsed.port}"
            project_path = parsed.path.lstrip("/").removesuffix(".git")
            base_url = base_url or host
        
        return base_url, project_path
    
    def _api_request(self, base_url: str, endpoint: str, method: str = "GET",
                     data: Dict = None) -> Dict:
        """Make an authenticated API request to GitLab"""
        url = f"{base_url}/api/v4{endpoint}"
        
        headers = {
            "PRIVATE-TOKEN": self.token,
            "Content-Type": "application/json"
        }
        
        body = json.dumps(data).encode('utf-8') if data else None
        
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""
            logger.error(f"GitLab API error {e.code}: {error_body}")
            raise
        except urllib.error.URLError as e:
            logger.error(f"GitLab connection error: {e.reason}")
            raise
    
    def create_merge_request(
        self,
        gitlab_url: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        labels: str = "",
        assignee_id: int = None,
        remove_source_branch: bool = False
    ) -> Dict:
        """
        Create a Merge Request on GitLab.
        
        Args:
            gitlab_url: The repo's GitLab remote URL
            source_branch: Branch to merge from (the feature branch)
            target_branch: Branch to merge into (e.g., master, main)
            title: MR title
            description: MR description (markdown)
            labels: Comma-separated labels
            assignee_id: GitLab user ID to assign
            remove_source_branch: Remove source branch after merge
            
        Returns:
            Dict with status, url, iid, etc.
        """
        if not self.token:
            return {
                "status": "skipped",
                "reason": "No GitLab token configured. Set GITLAB_TOKEN env var."
            }
        
        base_url, project_path = self._parse_gitlab_url(gitlab_url)
        
        if not project_path:
            return {
                "status": "failed",
                "error": f"Could not parse project path from: {gitlab_url}"
            }
        
        # URL-encode project path for API
        encoded_project = urllib.parse.quote(project_path, safe="")
        
        # Build MR payload
        mr_data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": remove_source_branch
        }
        
        if labels:
            mr_data["labels"] = labels
        if assignee_id:
            mr_data["assignee_id"] = assignee_id
        
        try:
            result = self._api_request(
                base_url,
                f"/projects/{encoded_project}/merge_requests",
                method="POST",
                data=mr_data
            )
            
            mr_url = result.get("web_url", "")
            mr_iid = result.get("iid", "")
            
            logger.info(f"Created MR !{mr_iid}: {title} -> {mr_url}")
            
            return {
                "status": "success",
                "url": mr_url,
                "iid": mr_iid,
                "title": title,
                "source_branch": source_branch,
                "target_branch": target_branch
            }
            
        except urllib.error.HTTPError as e:
            error_msg = str(e)
            # Handle duplicate MR (409 conflict or specific message)
            if e.code == 409 or "already exists" in error_msg.lower():
                logger.info(f"MR already exists for {source_branch} -> {target_branch}")
                return {
                    "status": "exists",
                    "reason": f"MR already exists for {source_branch} -> {target_branch}"
                }
            return {
                "status": "failed",
                "error": f"HTTP {e.code}: {error_msg}"
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def get_project_id(self, gitlab_url: str) -> Optional[int]:
        """Get the numeric project ID from GitLab"""
        if not self.token:
            return None
        
        base_url, project_path = self._parse_gitlab_url(gitlab_url)
        encoded_project = urllib.parse.quote(project_path, safe="")
        
        try:
            result = self._api_request(base_url, f"/projects/{encoded_project}")
            return result.get("id")
        except Exception:
            return None
    
    def list_merge_requests(self, gitlab_url: str, state: str = "opened") -> list:
        """List MRs for a project"""
        if not self.token:
            return []
        
        base_url, project_path = self._parse_gitlab_url(gitlab_url)
        encoded_project = urllib.parse.quote(project_path, safe="")
        
        try:
            return self._api_request(
                base_url,
                f"/projects/{encoded_project}/merge_requests?state={state}"
            )
        except Exception:
            return []
