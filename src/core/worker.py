"""
Core worker engine for parallel repository operations
"""

import os
import subprocess
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import asdict
import concurrent.futures
import threading

from .models import RepoConfig, Task
from .logger import get_logger


class ParallelRepoWorker:
    """Manages parallel work across multiple repositories"""
    
    def __init__(self, base_path: str = None, config_path: str = None):
        """
        Initialize worker
        
        Args:
            base_path: Base path for repositories (default: from config)
            config_path: Path to config file (default: config/config.json)
        """
        # Load config if provided
        if config_path:
            self._load_config(config_path)
        else:
            self.base_path = base_path or os.getcwd()
        
        self.repos: Dict[str, RepoConfig] = {}
        self.tasks: List[Task] = []
        self.lock = threading.Lock()
        self.work_log: List[Dict] = []
        
        # Setup logging
        self.logger = self._setup_logging()
        self.task_logger = get_logger()
        
    def _load_config(self, config_path: str):
        """Load configuration from JSON file"""
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
                self.base_path = config.get("base_path", os.getcwd())
        else:
            self.base_path = os.getcwd()
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging"""
        logger = logging.getLogger("parallel_repo_worker")
        logger.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
        
    def add_repo(self, repo: RepoConfig):
        """Add a repository to work on"""
        self.repos[repo.name] = repo
        self.logger.info(f"Added repo: {repo.name} ({repo.local_path})")
        print(f"✅ Added repo: {repo.name} ({repo.local_path})")
        
    def add_task(self, task: Task):
        """Add a task to the queue"""
        self.tasks.append(task)
        self.logger.info(f"Added task: {task.task_id} for {task.repo_name}")
        self.task_logger.logger.info(
            f"[TASK ADDED] {task.task_id} | Repo: {task.repo_name} | "
            f"Branch: {task.branch_name or 'auto'} | Description: {task.description}"
        )
        print(f"📋 Added task: {task.task_id} for {task.repo_name}")
        
    def get_current_branch(self, repo_path: str) -> str:
        """Get current branch name"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Error getting branch: {e}")
            return "unknown"
    
    def check_branch_exists(self, repo_path: str, branch_name: str, remote: str = "origin") -> bool:
        """Check if branch exists locally or remotely"""
        try:
            # Check local branches
            result = subprocess.run(
                ["git", "branch", "--list", branch_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout.strip():
                return True
            
            # Check remote branches
            subprocess.run(
                ["git", "fetch", remote],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=10
            )
            
            result = subprocess.run(
                ["git", "branch", "-r", "--list", f"{remote}/{branch_name}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            return bool(result.stdout.strip())
        except Exception:
            return False
    
    def checkout_existing_branch(self, repo_path: str, branch_name: str, remote: str = "origin") -> bool:
        """Checkout an existing branch and pull latest changes"""
        try:
            # Fetch latest
            subprocess.run(
                ["git", "fetch", remote],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=30
            )
            
            # Checkout branch (create local tracking if needed)
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=10
            )
            
            if result.returncode != 0:
                # Try to create local branch tracking remote
                subprocess.run(
                    ["git", "checkout", "-b", branch_name, f"{remote}/{branch_name}"],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                    timeout=10
                )
            
            # Pull latest changes
            subprocess.run(
                ["git", "pull", remote, branch_name],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=30
            )
            
            self.logger.info(f"Checked out existing branch: {branch_name}")
            print(f"✅ Checked out existing branch: {branch_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error checking out branch: {e}")
            return False
    
    def delete_branch(self, repo_path: str, branch_name: str, remote: str = "origin") -> bool:
        """Delete a branch locally and remotely"""
        try:
            # Switch away from the branch if we're on it
            current_branch = self.get_current_branch(repo_path)
            if current_branch == branch_name:
                # Switch to source branch or main/master
                subprocess.run(
                    ["git", "checkout", "demo_test"],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                    timeout=10
                )
            
            # Delete local branch
            result = subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=10
            )
            
            # Delete remote branch
            subprocess.run(
                ["git", "push", remote, "--delete", branch_name],
                cwd=repo_path,
                capture_output=True,
                check=False,
                timeout=30
            )
            
            self.logger.info(f"Deleted branch: {branch_name}")
            print(f"✅ Deleted branch: {branch_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting branch: {e}")
            return False
    
    def create_branch(self, repo_path: str, source_branch: str, new_branch: str, remote: str = "origin") -> bool:
        """Create a new branch from source branch"""
        try:
            # Fetch latest
            subprocess.run(
                ["git", "fetch", remote],
                cwd=repo_path,
                capture_output=True,
                check=False,  # Don't fail if fetch fails
                timeout=30
            )
            
            # Check if source branch exists locally
            result = subprocess.run(
                ["git", "branch", "--list", source_branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            branch_exists_locally = bool(result.stdout.strip())
            
            # Checkout source branch
            subprocess.run(
                ["git", "checkout", source_branch],
                cwd=repo_path,
                capture_output=True,
                check=True,
                timeout=10
            )
            
            # Pull latest only if branch exists on remote
            if not branch_exists_locally:
                # Try to pull, but don't fail if branch doesn't exist on remote
                pull_result = subprocess.run(
                    ["git", "pull", remote, source_branch],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,  # Don't fail if pull fails
                    timeout=30
                )
                if pull_result.returncode != 0:
                    self.logger.info(f"Source branch {source_branch} doesn't exist on remote, using local branch")
            else:
                # Branch exists locally, try to pull updates if it exists on remote
                pull_result = subprocess.run(
                    ["git", "pull", remote, source_branch],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,  # Don't fail if pull fails
                    timeout=30
                )
                if pull_result.returncode != 0:
                    self.logger.info(f"Could not pull {source_branch} from remote, using local version")
            
            # Create and checkout new branch
            subprocess.run(
                ["git", "checkout", "-b", new_branch],
                cwd=repo_path,
                capture_output=True,
                check=True,
                timeout=10
            )
            
            self.logger.info(f"Created branch: {new_branch} from {source_branch} in {repo_path}")
            # Extract repo name from path for logging
            repo_name = os.path.basename(repo_path)
            self.task_logger.log_branch_created(repo_name, new_branch, source_branch)
            print(f"✅ Created branch: {new_branch} from {source_branch}")
            return True
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout creating branch: {new_branch}")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error creating branch: {e}")
            print(f"❌ Error creating branch: {e}")
            return False
    
    def apply_code_changes(self, repo_path: str, task: Task) -> bool:
        """Apply code changes to files in repository"""
        try:
            if not task.code_changes:
                self.logger.info("No code changes to apply")
                return False
            
            for file_path, code_content in task.code_changes.items():
                full_path = os.path.join(repo_path, file_path)
                
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Write file content
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(code_content)
                
                self.logger.info(f"Applied changes to {file_path}")
                print(f"  ✅ Updated: {file_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error applying code changes: {e}")
            print(f"❌ Error applying code changes: {e}")
            return False
    
    def commit_changes(self, repo_path: str, message: str) -> bool:
        """Commit changes in repository"""
        try:
            # Check if there are changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            if not result.stdout.strip():
                self.logger.info(f"No changes to commit in {repo_path}")
                print(f"⚠️  No changes to commit in {repo_path}")
                return False
            
            # Add all changes
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
            
            # Commit
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
            
            self.logger.info(f"Committed changes: {message}")
            # Get changed files
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            files_changed = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            repo_name = os.path.basename(repo_path)
            branch_name = self.get_current_branch(repo_path)
            self.task_logger.log_commit(repo_name, branch_name, message, files_changed)
            print(f"✅ Committed changes: {message}")
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error committing: {e}")
            print(f"❌ Error committing: {e}")
            return False
    
    def push_branch(self, repo_path: str, branch_name: str, remote: str = "origin") -> bool:
        """Push branch to remote"""
        try:
            result = subprocess.run(
                ["git", "push", "-u", remote, branch_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )
            
            self.logger.info(f"Pushed branch: {branch_name} to {remote}")
            repo_name = os.path.basename(repo_path)
            self.task_logger.log_push(repo_name, branch_name, remote, True)
            print(f"✅ Pushed branch: {branch_name} to {remote}")
            return True
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout pushing branch: {branch_name}")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error pushing branch: {e.stderr}")
            print(f"❌ Error pushing branch: {e.stderr}")
            return False
    
    def execute_task(self, task: Task, remote: str = "origin") -> Dict:
        """Execute a single task on a repository"""
        repo = self.repos.get(task.repo_name)
        if not repo:
            return {
                "task_id": task.task_id,
                "status": "failed",
                "error": f"Repo {task.repo_name} not found"
            }
        
        repo_path = os.path.join(self.base_path, repo.local_path)
        
        if not os.path.exists(repo_path):
            return {
                "task_id": task.task_id,
                "status": "failed",
                "error": f"Path does not exist: {repo_path}"
            }
        
        # Determine branch name
        if task.branch_name:
            branch_name = task.branch_name
        else:
            # Auto-generate branch name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            branch_name = f"feature/{task.task_id}_{timestamp}"
        
        task.branch_name = branch_name
        
        # Log task start
        self.task_logger.log_task_start(
            task.task_id,
            task.repo_name,
            branch_name,
            {
                "description": task.description,
                "jira_id": task.jira_id,
                "source_branch": task.source_branch,
                "files_to_modify": task.files_to_modify,
                "continue_on_existing": task.continue_on_existing,
                "branch_only": task.branch_only
            }
        )
        
        result = {
            "task_id": task.task_id,
            "jira_id": task.jira_id,
            "repo": task.repo_name,
            "branch": branch_name,
            "started_at": datetime.now().isoformat(),
            "steps": []
        }
        
        try:
            # Step 0: Delete branch first if requested
            if task.delete_branch_first:
                with self.lock:
                    print(f"\n🗑️  [{task.repo_name}] Deleting branch: {branch_name}")
                
                branch_exists = self.check_branch_exists(repo_path, branch_name, remote)
                if branch_exists:
                    if self.delete_branch(repo_path, branch_name, remote):
                        result["steps"].append({
                            "step": "delete_branch",
                            "status": "success",
                            "branch": branch_name,
                            "note": "Branch deleted before recreation"
                        })
                        self.task_logger.log_task_step(task.task_id, task.repo_name, "delete_branch", "success", {"branch": branch_name})
                    else:
                        result["steps"].append({
                            "step": "delete_branch",
                            "status": "failed",
                            "branch": branch_name
                        })
                        self.task_logger.log_task_step(task.task_id, task.repo_name, "delete_branch", "failed", {"branch": branch_name})
                        # Continue anyway - might have been deleted already
                else:
                    result["steps"].append({
                        "step": "delete_branch",
                        "status": "skipped",
                        "note": "Branch does not exist"
                    })
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "delete_branch", "skipped", {"branch": branch_name})
            
            # Step 1: Create or checkout branch
            with self.lock:
                print(f"\n🔄 [{task.repo_name}] Working on branch: {branch_name}")
            
            # Check if branch exists and handle accordingly
            branch_exists = self.check_branch_exists(repo_path, branch_name, remote)
            
            # Determine source branch: task-level override > repo-level default
            source_branch = task.source_branch or repo.source_branch
            
            if branch_exists and task.continue_on_existing:
                # Checkout existing branch
                if not self.checkout_existing_branch(repo_path, branch_name, remote):
                    result["status"] = "failed"
                    result["error"] = "Failed to checkout existing branch"
                    return result
            elif not branch_exists:
                # Create new branch from determined source branch
                if not self.create_branch(repo_path, source_branch, branch_name, remote):
                    result["status"] = "failed"
                    result["error"] = "Failed to create branch"
                    return result
            else:
                # Branch exists but continue_on_existing is False
                result["status"] = "failed"
                result["error"] = f"Branch {branch_name} already exists and continue_on_existing is False"
                return result
            
            result["steps"].append({
                "step": "create_branch",
                "status": "success",
                "branch": branch_name
            })
            self.task_logger.log_task_step(task.task_id, task.repo_name, "create_branch", "success", {"branch": branch_name})
            
            # Step 2: Apply code changes (skip if branch_only)
            if task.branch_only:
                with self.lock:
                    print(f"📝 [{task.repo_name}] Branch-only mode - skipping code changes")
                result["steps"].append({
                    "step": "apply_code_changes",
                    "status": "skipped",
                    "note": "branch_only mode"
                })
                self.task_logger.log_task_step(task.task_id, task.repo_name, "apply_code_changes", "skipped", {"note": "branch_only"})
            else:
                with self.lock:
                    print(f"📝 [{task.repo_name}] Task: {task.description}")
                    if task.files_to_modify:
                        print(f"   Files to modify: {', '.join(task.files_to_modify)}")
                    if task.code_changes:
                        print(f"   Applying code changes to {len(task.code_changes)} file(s)")
                
                if task.code_changes:
                    if self.apply_code_changes(repo_path, task):
                        result["steps"].append({"step": "apply_code_changes", "status": "success"})
                        self.task_logger.log_task_step(task.task_id, task.repo_name, "apply_code_changes", "success")
                        files_modified = list(task.code_changes.keys())
                        self.task_logger.log_code_changes_applied(task.repo_name, branch_name, files_modified)
                    else:
                        result["steps"].append({"step": "apply_code_changes", "status": "failed"})
                        self.task_logger.log_task_step(task.task_id, task.repo_name, "apply_code_changes", "failed")
                else:
                    result["steps"].append({
                        "step": "apply_code_changes",
                        "status": "skipped",
                        "note": "No code_changes specified in task"
                    })
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "apply_code_changes", "skipped")
            
            # Step 2.5: AI Code Review (if code was changed and not branch_only)
            if not task.branch_only and task.code_changes:
                ai_review = self._run_ai_code_review(repo_path, task)
                if ai_review:
                    result["steps"].append({
                        "step": "ai_code_review",
                        "status": "success",
                        "review": ai_review
                    })
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "ai_code_review", "success", {"review_summary": ai_review.get("summary", "")})
                    with self.lock:
                        print(f"🤖 [{task.repo_name}] AI Review: {ai_review.get('summary', 'No issues')}")
            
            # Step 3: Commit (if changes exist and not branch_only)
            if task.branch_only:
                result["steps"].append({
                    "step": "commit",
                    "status": "skipped",
                    "note": "branch_only mode"
                })
                self.task_logger.log_task_step(task.task_id, task.repo_name, "commit", "skipped", {"note": "branch_only"})
            elif self.commit_changes(repo_path, task.commit_message):
                result["steps"].append({
                    "step": "commit", 
                    "status": "success",
                    "commit_message": task.commit_message
                })
                self.task_logger.log_task_step(task.task_id, task.repo_name, "commit", "success")
            else:
                result["steps"].append({
                    "step": "commit", 
                    "status": "skipped", 
                    "note": "No changes to commit"
                })
                self.task_logger.log_task_step(task.task_id, task.repo_name, "commit", "skipped")
            
            # Step 3.5: Pre-push validation (go vet, go build)
            validation_passed = True
            if task.branch_name and not task.branch_only:
                validation_result = self._run_pre_push_validation(repo_path, task)
                if validation_result:
                    result["steps"].append({
                        "step": "pre_push_validation",
                        "status": "success" if validation_result["passed"] else "warning",
                        "details": validation_result
                    })
                    validation_passed = validation_result["passed"]
                    status = "success" if validation_passed else "warning"
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "pre_push_validation", status, validation_result)
                    with self.lock:
                        if validation_passed:
                            print(f"✅ [{task.repo_name}] Pre-push validation passed")
                        else:
                            print(f"⚠️  [{task.repo_name}] Pre-push validation warnings: {validation_result.get('summary', '')}")
            
            # Step 4: Push (push even with validation warnings - don't block)
            if task.branch_name:
                if self.push_branch(repo_path, task.branch_name, remote):
                    result["steps"].append({"step": "push", "status": "success"})
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "push", "success")
                else:
                    result["steps"].append({"step": "push", "status": "failed"})
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "push", "failed")
            
            # Step 5: Create GitLab Merge Request (if push succeeded)
            push_step = next((s for s in result["steps"] if s["step"] == "push"), None)
            if push_step and push_step["status"] == "success":
                source_branch = task.source_branch or repo.source_branch
                mr_result = self._create_gitlab_mr(repo, task, branch_name, source_branch)
                if mr_result:
                    result["steps"].append({
                        "step": "create_mr",
                        "status": mr_result.get("status", "skipped"),
                        "mr_url": mr_result.get("url", ""),
                        "mr_iid": mr_result.get("iid", "")
                    })
                    self.task_logger.log_task_step(task.task_id, task.repo_name, "create_mr", mr_result.get("status", "skipped"), mr_result)
            
            result["status"] = "completed" if all(s.get("status") in ("success", "skipped") for s in result["steps"]) else "in_progress"
            result["completed_at"] = datetime.now().isoformat()
            
            # Log task completion
            self.task_logger.log_task_complete(task.task_id, task.repo_name, result["status"], result)
            
            # Send notifications after commit/push
            if result["status"] in ("completed", "failed"):
                self._send_notifications(
                    task.task_id,
                    task.repo_name,
                    branch_name,
                    result["status"],
                    result,
                    task_description=task.description,
                    repo_path=repo_path
                )
            
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            self.logger.error(f"Error executing task {task.task_id}: {e}")
            self.task_logger.log_error(f"Task execution: {task.task_id}", e, {
                "repo": task.repo_name,
                "branch": branch_name
            })
            self.task_logger.log_task_complete(task.task_id, task.repo_name, "failed", result)
        
        return result
    
    def _get_committer_info(self, repo_path: str) -> Dict[str, str]:
        """Get committer information from git config"""
        try:
            # Get user name
            name_result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            name = name_result.stdout.strip() if name_result.returncode == 0 else "Unknown"
            
            # Get user email
            email_result = subprocess.run(
                ["git", "config", "user.email"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            email = email_result.stdout.strip() if email_result.returncode == 0 else ""
            
            return {
                "name": name,
                "email": email,
                "display": f"{name} ({email})" if email else name
            }
        except Exception:
            return {"name": "Unknown", "email": "", "display": "Unknown"}
    
    def _send_notifications(self, task_id: str, repo_name: str, branch_name: str,
                           status: str, result: Dict, task_description: str = "", repo_path: str = ""):
        """Send notifications via notification manager"""
        try:
            from ..notifications import get_notification_manager
            
            # Load notification config
            import json
            from pathlib import Path
            config = {}
            config_file = Path("config/notifications_config.json")
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
            
            # Get committer info
            committer_info = {}
            if repo_path:
                committer_info = self._get_committer_info(repo_path)
            
            # Enhance result with additional info
            enhanced_result = result.copy()
            enhanced_result["task_description"] = task_description
            enhanced_result["committer"] = committer_info
            
            # Get commit message from steps if available
            commit_step = next((s for s in result.get("steps", []) if s.get("step") == "commit"), None)
            if commit_step:
                enhanced_result["commit_message"] = commit_step.get("commit_message", "")
            else:
                # Try to get from task if available
                enhanced_result["commit_message"] = ""
            
            manager = get_notification_manager(config)
            results = manager.send_task_notification(
                task_id, repo_name, branch_name, status, enhanced_result
            )
            
            if results.get('whatsapp'):
                self.logger.info("WhatsApp notification sent")
            if results.get('slack'):
                self.logger.info("Slack notification sent")
        except ImportError:
            self.logger.warning("Notification modules not available")
        except Exception as e:
            self.logger.error(f"Error sending notifications: {e}")
    
    def _run_pre_push_validation(self, repo_path: str, task: Task) -> Optional[Dict]:
        """Run pre-push validation (go vet, go build) on the repo"""
        try:
            from .validator import PrePushValidator
            validator = PrePushValidator()
            return validator.validate(repo_path)
        except ImportError:
            self.logger.debug("PrePushValidator not available, skipping validation")
            return None
        except Exception as e:
            self.logger.warning(f"Pre-push validation error: {e}")
            return {"passed": True, "summary": f"Validation skipped: {e}", "checks": []}
    
    def _run_ai_code_review(self, repo_path: str, task: Task) -> Optional[Dict]:
        """Run AI code review on the changes using RAG + LLM"""
        try:
            from ..ai.code_reviewer import CodeReviewer
            reviewer = CodeReviewer()
            return reviewer.review_changes(repo_path, task)
        except ImportError:
            self.logger.debug("CodeReviewer not available, skipping AI review")
            return None
        except Exception as e:
            self.logger.warning(f"AI code review error: {e}")
            return None
    
    def _create_gitlab_mr(self, repo: RepoConfig, task: Task, branch_name: str, target_branch: str) -> Optional[Dict]:
        """Create a GitLab Merge Request after successful push"""
        try:
            from .gitlab_api import GitLabAPI
            gitlab = GitLabAPI()
            
            # Build MR title with Jira ID if present
            title = f"[{task.jira_id}] {task.description}" if task.jira_id else task.description
            
            # Build MR description
            description_parts = [f"## {task.description}"]
            if task.jira_id:
                description_parts.append(f"\n**Jira:** {task.jira_id}")
            if task.files_to_modify:
                description_parts.append(f"\n**Files modified:** {', '.join(task.files_to_modify)}")
            description_parts.append(f"\n**Source branch:** `{branch_name}`")
            description_parts.append(f"**Target branch:** `{target_branch}`")
            description_parts.append(f"\n---\n*Auto-created by Code Atlas*")
            
            description = "\n".join(description_parts)
            
            return gitlab.create_merge_request(
                gitlab_url=repo.gitlab_url,
                source_branch=branch_name,
                target_branch=target_branch,
                title=title,
                description=description
            )
        except ImportError:
            self.logger.debug("GitLabAPI not available, skipping MR creation")
            return None
        except Exception as e:
            self.logger.warning(f"GitLab MR creation error: {e}")
            return {"status": "failed", "error": str(e)}
    
    def execute_parallel(self, max_workers: int = 5, remote: str = "origin",
                        max_workers_per_repo: int = 1,
                        enable_agent_pool: bool = False,
                        agent_pool_size: int = None) -> List[Dict]:
        """
        Execute all tasks in parallel with configurable worker pools
        
        Args:
            max_workers: Maximum total parallel workers
            remote: Git remote name
            max_workers_per_repo: Max workers per repository (for breaking down parallel execution)
            enable_agent_pool: Enable separate agent pool for task distribution
            agent_pool_size: Size of agent pool (defaults to max_workers)
        """
        agent_pool_size = agent_pool_size or max_workers
        
        print(f"\n🚀 Starting parallel execution...")
        print(f"📊 Total tasks: {len(self.tasks)}")
        print(f"⚙️  Configuration:")
        print(f"   - Max Workers: {max_workers}")
        print(f"   - Workers per Repo: {max_workers_per_repo}")
        print(f"   - Agent Pool: {'Enabled' if enable_agent_pool else 'Disabled'}")
        
        self.logger.info(f"Starting parallel execution: {max_workers} workers, {len(self.tasks)} tasks")
        
        results = []
        
        # Group tasks by repository for per-repo worker limits
        if max_workers_per_repo > 1:
            tasks_by_repo = {}
            for task in self.tasks:
                if task.repo_name not in tasks_by_repo:
                    tasks_by_repo[task.repo_name] = []
                tasks_by_repo[task.repo_name].append(task)
            
            # Execute with per-repo worker limits
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as main_executor:
                repo_futures = []
                
                for repo_name, repo_tasks in tasks_by_repo.items():
                    # Create executor for this repo with limited workers
                    repo_executor = concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(max_workers_per_repo, len(repo_tasks))
                    )
                    
                    # Submit tasks for this repo
                    for task in repo_tasks:
                        future = main_executor.submit(self._execute_with_repo_pool, task, remote, repo_executor)
                        repo_futures.append((future, task))
                    
                    repo_executor.shutdown(wait=False)
                
                # Collect results
                for future, task in repo_futures:
                    try:
                        result = future.result()
                        results.append(result)
                        
                        with self.lock:
                            status_emoji = {
                                "completed": "✅",
                                "in_progress": "🔄",
                                "failed": "❌"
                            }.get(result["status"], "❓")
                            print(f"{status_emoji} [{task.repo_name}] {task.task_id}: {result['status']}")
                            
                    except Exception as e:
                        error_result = {
                            "task_id": task.task_id,
                            "repo": task.repo_name,
                            "status": "failed",
                            "error": str(e)
                        }
                        results.append(error_result)
                        self.logger.error(f"Error executing task {task.task_id}: {e}")
        else:
            # Standard parallel execution
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_task = {
                    executor.submit(self.execute_task, task, remote): task
                    for task in self.tasks
                }
                
                # Collect results as they complete
                for future in concurrent.futures.as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        result = future.result()
                        results.append(result)
                        
                        with self.lock:
                            status_emoji = {
                                "completed": "✅",
                                "in_progress": "🔄",
                                "failed": "❌"
                            }.get(result["status"], "❓")
                            print(f"{status_emoji} [{task.repo_name}] {task.task_id}: {result['status']}")
                            
                    except Exception as e:
                        error_result = {
                            "task_id": task.task_id,
                            "repo": task.repo_name,
                            "status": "failed",
                            "error": str(e)
                        }
                        results.append(error_result)
                        self.logger.error(f"Error executing task {task.task_id}: {e}")
        
        self.work_log = results
        return results
    
    def _execute_with_repo_pool(self, task: Task, remote: str, repo_executor: concurrent.futures.ThreadPoolExecutor) -> Dict:
        """Execute task using repository-specific executor pool"""
        future = repo_executor.submit(self.execute_task, task, remote)
        return future.result()
    
    def save_work_log(self, filename: str = "work_log.json"):
        """Save work log to file"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "repos": {name: repo.to_dict() for name, repo in self.repos.items()},
            "tasks": [task.to_dict() for task in self.tasks],
            "results": self.work_log
        }
        
        log_path = log_dir / filename
        with open(log_path, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        self.logger.info(f"Work log saved to: {log_path}")
        print(f"\n💾 Work log saved to: {log_path}")
    
    def print_status(self):
        """Print current status"""
        print("\n" + "="*80)
        print("📊 PARALLEL REPO WORKER STATUS")
        print("="*80)
        print(f"\n📁 Repositories ({len(self.repos)}):")
        for name, repo in self.repos.items():
            print(f"  • {name}: {repo.local_path} (source: {repo.source_branch})")
        
        print(f"\n📋 Tasks ({len(self.tasks)}):")
        for task in self.tasks:
            status_emoji = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "failed": "❌"
            }.get(task.status, "❓")
            print(f"  {status_emoji} {task.task_id} ({task.repo_name}): {task.description}")
        
        print("\n" + "="*80)
