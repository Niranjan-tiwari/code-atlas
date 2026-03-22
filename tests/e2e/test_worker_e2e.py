import os
import shutil
import tempfile
import pytest
import subprocess
from pathlib import Path
from src.core.worker import ParallelRepoWorker
from src.core.models import RepoConfig, Task

class TestWorkerE2E:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        # Create a temporary directory for our "remote" and "local" repos
        self.test_dir = tempfile.mkdtemp()
        self.remote_dir = os.path.join(self.test_dir, "remote_repo.git")
        self.local_dir = os.path.join(self.test_dir, "local_workspace")
        self.repo_name = "test-repo"
        self.local_repo_path = os.path.join(self.local_dir, self.repo_name)

        # 1. Initialize "remote" bare repo
        os.makedirs(self.remote_dir)
        subprocess.run(["git", "init", "--bare"], cwd=self.remote_dir, check=True)

        # 2. Prepare workspace and clone repo
        os.makedirs(self.local_dir)
        subprocess.run(["git", "clone", self.remote_dir, self.repo_name], cwd=self.local_dir, check=True)

        # 3. Create initial commit in local repo and push to remote
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.local_repo_path, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.local_repo_path, check=True)
        
        readme_path = os.path.join(self.local_repo_path, "README.md")
        with open(readme_path, "w") as f:
            f.write("# Test Repo")
        
        subprocess.run(["git", "add", "."], cwd=self.local_repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.local_repo_path, check=True)
        subprocess.run(["git", "push", "origin", "master"], cwd=self.local_repo_path, check=True)

        yield

        # Cleanup
        shutil.rmtree(self.test_dir)

    def test_simple_task_execution(self):
        """Test creating a branch, adding a file, committing, and pushing"""
        
        # Initialize worker with local workspace as base path
        worker = ParallelRepoWorker(base_path=self.local_dir)
        
        # Configure repo in worker
        repo_config = RepoConfig(
            name=self.repo_name,
            local_path=self.repo_name,
            gitlab_url=self.remote_dir, # Use local path as remote URL
            source_branch="master"
        )
        worker.add_repo(repo_config)

        # Define task
        task = Task(
            task_id="test-task-1",
            repo_name=self.repo_name,
            description="Add test file",
            branch_name="feature/test-file",
            source_branch="master",
            files_to_modify=["test_file.txt"],
            changes={"test_file.txt": "Add test file content"},
            code_changes={
                "test_file.txt": "This is a test file contents."
            },
            commit_message="Add test file"
        )

        # Execute task
        result = worker.execute_task(task)

        # Verify execution result
        assert result["status"] == "completed"
        
        # Verify file creation locally
        new_file_path = os.path.join(self.local_repo_path, "test_file.txt")
        assert os.path.exists(new_file_path)
        with open(new_file_path, "r") as f:
            content = f.read()
            assert content == "This is a test file contents."

        # Verify branch creation and push on "remote"
        # check if branch exists in remote
        result = subprocess.run(
            ["git", "branch", "--list", "feature/test-file"], 
            cwd=self.remote_dir, 
            capture_output=True, 
            text=True
        )
        assert "feature/test-file" in result.stdout

    def test_branch_update_existing(self):
        """Test updating an existing branch"""
        
        # Setup: Create the branch first
        subprocess.run(["git", "checkout", "-b", "feature/update-test"], cwd=self.local_repo_path, check=True)
        subprocess.run(["git", "push", "origin", "feature/update-test"], cwd=self.local_repo_path, check=True)
        subprocess.run(["git", "checkout", "master"], cwd=self.local_repo_path, check=True)

        # Initialize worker
        worker = ParallelRepoWorker(base_path=self.local_dir)
        repo_config = RepoConfig(
            name=self.repo_name,
            local_path=self.repo_name,
            gitlab_url=self.remote_dir,
            source_branch="master"
        )
        worker.add_repo(repo_config)

        # Task to update existing branch
        task = Task(
            task_id="test-task-2",
            repo_name=self.repo_name,
            description="Update existing branch",
            branch_name="feature/update-test",
            continue_on_existing=True,
            files_to_modify=["update.txt"],
            changes={"update.txt": "Add update file"},
            code_changes={
                "update.txt": "Updated content"
            },
            commit_message="Update feature branch"
        )

        result = worker.execute_task(task)
        
        assert result["status"] == "completed"
        
        # Verify file exists
        update_file_path = os.path.join(self.local_repo_path, "update.txt")
        assert os.path.exists(update_file_path)

