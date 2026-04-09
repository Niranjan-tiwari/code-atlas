"""
Data models for Code Atlas
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class RepoConfig:
    """Configuration for a repository"""
    name: str
    local_path: str
    gitlab_url: str
    source_branch: str = "main"
    component: str = ""
    description: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RepoConfig':
        """Create from dictionary"""
        return cls(**data)


@dataclass
class Task:
    """A task to perform on a repository"""
    repo_name: str
    task_id: str
    description: str
    files_to_modify: List[str]
    changes: Dict[str, str]  # file_path -> change_description
    code_changes: Optional[Dict[str, str]] = None  # file_path -> actual code changes/patches
    status: str = "pending"  # pending, in_progress, completed, failed
    branch_name: Optional[str] = None  # Custom branch name (if None, auto-generated)
    source_branch: Optional[str] = None  # Per-task source branch override (falls back to repo default)
    jira_id: Optional[str] = None  # Jira ticket ID (e.g., "PROJ-1234")
    continue_on_existing: bool = False  # Continue working on existing branch if it exists
    delete_branch_first: bool = False  # Delete branch before creating (if it exists)
    branch_only: bool = False  # If True, only create branch and push (skip code changes/commit)
    commit_message: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0  # Track retries/continuations
    
    def __post_init__(self):
        """Set default values"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if not self.commit_message:
            prefix = f"[{self.jira_id}] " if self.jira_id else ""
            self.commit_message = f"{prefix}feat: {self.description}"
        if self.code_changes is None:
            self.code_changes = {}
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Task':
        """Create from dictionary, ignoring unknown fields"""
        import inspect
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
