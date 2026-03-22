"""
Security layer for Code Atlas
Input validation, sanitization, rate limiting, and access control
"""

import re
import time
import hashlib
import logging
from typing import Dict, Optional, List
from collections import defaultdict
from datetime import datetime, timedelta


class SecurityManager:
    """Security and validation manager"""
    
    def __init__(self):
        self.logger = logging.getLogger("security")
        self.rate_limits: Dict[str, List[float]] = defaultdict(list)
        self.blocked_ips: Dict[str, datetime] = {}
        self.allowed_branches: Optional[List[str]] = None
        self.blocked_branches: List[str] = ["main", "master", "production", "prod"]
        
    def validate_branch_name(self, branch_name: str) -> tuple[bool, Optional[str]]:
        """
        Validate branch name
        
        Returns:
            (is_valid, error_message)
        """
        if not branch_name:
            return False, "Branch name cannot be empty"
        
        if len(branch_name) > 255:
            return False, "Branch name too long (max 255 characters)"
        
        # Git branch name rules
        if branch_name.startswith('.') or branch_name.endswith('.'):
            return False, "Branch name cannot start or end with '.'"
        
        if '..' in branch_name or '~' in branch_name or '^' in branch_name or ':' in branch_name:
            return False, "Branch name contains invalid characters"
        
        # Check for blocked branches
        if branch_name.lower() in [b.lower() for b in self.blocked_branches]:
            return False, f"Branch '{branch_name}' is protected and cannot be modified"
        
        # Check for allowed branches if configured
        if self.allowed_branches and branch_name not in self.allowed_branches:
            return False, f"Branch '{branch_name}' is not in allowed list"
        
        return True, None
    
    def validate_repo_name(self, repo_name: str) -> tuple[bool, Optional[str]]:
        """Validate repository name"""
        if not repo_name:
            return False, "Repository name cannot be empty"
        
        if len(repo_name) > 100:
            return False, "Repository name too long"
        
        # Only allow alphanumeric, dash, underscore
        if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
            return False, "Repository name contains invalid characters"
        
        return True, None
    
    def validate_file_path(self, file_path: str) -> tuple[bool, Optional[str]]:
        """Validate file path to prevent directory traversal"""
        if not file_path:
            return False, "File path cannot be empty"
        
        # Prevent directory traversal
        if '..' in file_path or file_path.startswith('/'):
            return False, "Invalid file path"
        
        # Prevent absolute paths
        if file_path.startswith('/') or '\\' in file_path:
            return False, "File path must be relative"
        
        # Check for dangerous patterns
        dangerous_patterns = ['/.git/', '/.env', '/passwd', '/shadow']
        if any(pattern in file_path.lower() for pattern in dangerous_patterns):
            return False, "File path contains dangerous pattern"
        
        return True, None
    
    def sanitize_commit_message(self, message: str) -> str:
        """Sanitize commit message"""
        if not message:
            return "chore: automated commit"
        
        # Remove control characters
        message = ''.join(char for char in message if ord(char) >= 32 or char == '\n')
        
        # Limit length
        if len(message) > 500:
            message = message[:497] + "..."
        
        return message.strip()
    
    def check_rate_limit(self, identifier: str, max_requests: int = 10, window_seconds: int = 60) -> tuple[bool, Optional[str]]:
        """
        Check rate limit
        
        Args:
            identifier: Unique identifier (IP, user, etc.)
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds
        
        Returns:
            (allowed, error_message)
        """
        now = time.time()
        
        # Clean old entries
        self.rate_limits[identifier] = [
            req_time for req_time in self.rate_limits[identifier]
            if now - req_time < window_seconds
        ]
        
        # Check limit
        if len(self.rate_limits[identifier]) >= max_requests:
            return False, f"Rate limit exceeded: {max_requests} requests per {window_seconds} seconds"
        
        # Add current request
        self.rate_limits[identifier].append(now)
        
        return True, None
    
    def validate_task(self, task_data: Dict) -> tuple[bool, Optional[str]]:
        """Validate task data"""
        # Validate repo name
        repo_name = task_data.get("repo_name", "")
        is_valid, error = self.validate_repo_name(repo_name)
        if not is_valid:
            return False, f"Invalid repo name: {error}"
        
        # Validate branch name
        branch_name = task_data.get("branch_name")
        if branch_name:
            is_valid, error = self.validate_branch_name(branch_name)
            if not is_valid:
                return False, f"Invalid branch name: {error}"
        
        # Validate file paths
        files_to_modify = task_data.get("files_to_modify", [])
        code_changes = task_data.get("code_changes", {})
        
        all_files = set(files_to_modify) | set(code_changes.keys())
        for file_path in all_files:
            is_valid, error = self.validate_file_path(file_path)
            if not is_valid:
                return False, f"Invalid file path '{file_path}': {error}"
        
        # Validate code changes size
        total_size = sum(len(str(content)) for content in code_changes.values())
        if total_size > 10 * 1024 * 1024:  # 10MB limit
            return False, "Total code changes exceed 10MB limit"
        
        return True, None
    
    def hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data for logging"""
        return hashlib.sha256(data.encode()).hexdigest()[:16]


class AccessControl:
    """Access control and authentication"""
    
    def __init__(self, api_keys: Optional[List[str]] = None):
        self.api_keys = set(api_keys or [])
        self.logger = logging.getLogger("access_control")
    
    def validate_api_key(self, api_key: str) -> bool:
        """Validate API key"""
        if not self.api_keys:
            # If no keys configured, allow all (development mode)
            return True
        
        return api_key in self.api_keys
    
    def require_auth(self, api_key: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Check if request is authenticated"""
        if not api_key:
            return False, "API key required"
        
        if not self.validate_api_key(api_key):
            return False, "Invalid API key"
        
        return True, None
