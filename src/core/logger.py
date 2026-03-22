"""
Enhanced logging module for Code Atlas
Provides structured logging for tasks, repos, and operations
"""

import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import asdict


class TaskLogger:
    """Structured logger for tasks and repositories"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Setup main logger
        self.logger = self._setup_logger()
        
        # Task execution log file
        self.task_log_file = self.log_dir / "task_executions.jsonl"
        self.repo_log_file = self.log_dir / "repo_operations.jsonl"
        
    def _setup_logger(self) -> logging.Logger:
        """Setup main application logger"""
        logger = logging.getLogger("parallel_repo_worker")
        logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        logger.handlers.clear()
        
        # File handler for detailed logs
        file_handler = logging.FileHandler(self.log_dir / "worker.log")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def log_repo_operation(self, operation: str, repo_name: str, details: Dict):
        """Log repository operation"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "repo_name": repo_name,
            "details": details
        }
        
        # Write to JSONL file
        with open(self.repo_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Also log to main logger
        self.logger.info(f"[REPO] {operation} - {repo_name}: {json.dumps(details)}")
    
    def log_task_start(self, task_id: str, repo_name: str, branch_name: str, task_details: Dict):
        """Log task start"""
        jira_id = task_details.get("jira_id", "")
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "task_start",
            "task_id": task_id,
            "jira_id": jira_id,
            "repo_name": repo_name,
            "branch_name": branch_name,
            "task_details": task_details
        }
        
        with open(self.task_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        jira_str = f" | Jira: {jira_id}" if jira_id else ""
        self.logger.info(
            f"[TASK START] {task_id}{jira_str} | Repo: {repo_name} | Branch: {branch_name}"
        )
    
    def log_task_step(self, task_id: str, repo_name: str, step: str, status: str, details: Optional[Dict] = None):
        """Log task step"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "task_step",
            "task_id": task_id,
            "repo_name": repo_name,
            "step": step,
            "status": status,
            "details": details or {}
        }
        
        with open(self.task_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        status_emoji = {
            "success": "✅",
            "failed": "❌",
            "skipped": "⏭️",
            "pending": "⏳"
        }.get(status, "❓")
        
        self.logger.info(
            f"[TASK STEP] {task_id} | {step} | {status_emoji} {status}"
        )
        if details:
            self.logger.debug(f"  Details: {json.dumps(details)}")
    
    def log_task_complete(self, task_id: str, repo_name: str, status: str, result: Dict):
        """Log task completion"""
        jira_id = result.get("jira_id", "")
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "task_complete",
            "task_id": task_id,
            "jira_id": jira_id,
            "repo_name": repo_name,
            "status": status,
            "result": result
        }
        
        with open(self.task_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "in_progress": "🔄"
        }.get(status, "❓")
        
        jira_str = f" | Jira: {jira_id}" if jira_id else ""
        self.logger.info(
            f"[TASK COMPLETE] {task_id}{jira_str} | Repo: {repo_name} | Status: {status_emoji} {status}"
        )
        
        if result.get("error"):
            self.logger.error(f"  Error: {result['error']}")
        
        if result.get("steps"):
            for step in result["steps"]:
                step_status = step.get("status", "unknown")
                step_name = step.get("step", "unknown")
                self.logger.debug(f"  Step: {step_name} - {step_status}")
    
    def log_repo_added(self, repo_name: str, repo_config: Dict):
        """Log repository addition"""
        self.log_repo_operation("repo_added", repo_name, repo_config)
    
    def log_branch_created(self, repo_name: str, branch_name: str, source_branch: str):
        """Log branch creation"""
        self.log_repo_operation("branch_created", repo_name, {
            "branch_name": branch_name,
            "source_branch": source_branch
        })
    
    def log_branch_checkout(self, repo_name: str, branch_name: str, existed: bool):
        """Log branch checkout"""
        self.log_repo_operation("branch_checkout", repo_name, {
            "branch_name": branch_name,
            "existed": existed
        })
    
    def log_commit(self, repo_name: str, branch_name: str, commit_message: str, files_changed: List[str]):
        """Log commit"""
        self.log_repo_operation("commit", repo_name, {
            "branch_name": branch_name,
            "commit_message": commit_message,
            "files_changed": files_changed
        })
    
    def log_push(self, repo_name: str, branch_name: str, remote: str, success: bool, error: Optional[str] = None):
        """Log push operation"""
        self.log_repo_operation("push", repo_name, {
            "branch_name": branch_name,
            "remote": remote,
            "success": success,
            "error": error
        })
    
    def log_code_changes_applied(self, repo_name: str, branch_name: str, files_modified: List[str]):
        """Log code changes application"""
        self.log_repo_operation("code_changes_applied", repo_name, {
            "branch_name": branch_name,
            "files_modified": files_modified
        })
    
    def log_error(self, context: str, error: Exception, details: Optional[Dict] = None):
        """Log error with context"""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "details": details or {}
        }
        
        self.logger.error(
            f"[ERROR] {context}: {type(error).__name__} - {str(error)}",
            exc_info=True
        )
        
        # Also log to task log
        with open(self.task_log_file, 'a') as f:
            f.write(json.dumps(error_entry) + '\n')
    
    def get_task_history(self, task_id: Optional[str] = None, repo_name: Optional[str] = None) -> List[Dict]:
        """Get task execution history"""
        if not self.task_log_file.exists():
            return []
        
        history = []
        with open(self.task_log_file, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if task_id and entry.get("task_id") != task_id:
                        continue
                    if repo_name and entry.get("repo_name") != repo_name:
                        continue
                    history.append(entry)
                except json.JSONDecodeError:
                    continue
        
        return history
    
    def get_repo_operations(self, repo_name: Optional[str] = None) -> List[Dict]:
        """Get repository operations history"""
        if not self.repo_log_file.exists():
            return []
        
        operations = []
        with open(self.repo_log_file, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if repo_name and entry.get("repo_name") != repo_name:
                        continue
                    operations.append(entry)
                except json.JSONDecodeError:
                    continue
        
        return operations


# Global logger instance
_task_logger: Optional[TaskLogger] = None


def get_logger() -> TaskLogger:
    """Get or create global logger instance"""
    global _task_logger
    if _task_logger is None:
        _task_logger = TaskLogger()
    return _task_logger
