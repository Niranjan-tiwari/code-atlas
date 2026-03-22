#!/usr/bin/env python3
"""
Interactive CLI for Code Atlas
Supports multi-agent workflows and interactive task management
"""

import sys
import os
import json
import readline
from pathlib import Path
from typing import List, Dict, Optional
import argparse

# Enable arrow keys, history, and line editing in interactive input()
readline.parse_and_bind('"\e[A": history-search-backward')
readline.parse_and_bind('"\e[B": history-search-forward')
readline.parse_and_bind('set editing-mode emacs')

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.worker import ParallelRepoWorker
from src.core.models import RepoConfig, Task


class InteractiveCLI:
    """Interactive CLI interface"""
    
    def __init__(self, worker: ParallelRepoWorker):
        self.worker = worker
        self.running = True
    
    def print_header(self):
        """Print CLI header"""
        print("\n" + "="*80)
        print(" " * 25 + "PARALLEL REPO WORKER")
        print(" " * 20 + "Multi-Agent CLI Interface")
        print("="*80)
    
    def print_menu(self):
        """Print main menu"""
        print("\n📋 MAIN MENU")
        print("-" * 80)
        print("1.  📁 Manage Repositories")
        print("2.  📝 Manage Tasks")
        print("3.  🚀 Execute Tasks (Parallel)")
        print("4.  🔄 Continue Work on Existing Branches")
        print("5.  🌿 Create Branches Only")
        print("6.  📊 View Status")
        print("7.  📜 View Work Log")
        print("8.  ⚙️  Configuration")
        print("9.  🤖 Multi-Agent Mode")
        print("10. ❌ Exit")
        print("-" * 80)
    
    def manage_repos(self):
        """Manage repositories"""
        while True:
            print("\n📁 REPOSITORY MANAGEMENT")
            print("-" * 80)
            print("1. List repositories")
            print("2. Add repository")
            print("3. Remove repository")
            print("4. Test repository access")
            print("5. Back to main menu")
            
            choice = input("\nEnter choice (1-5): ").strip()
            
            if choice == "1":
                self.worker.print_status()
            elif choice == "2":
                self.add_repo_interactive()
            elif choice == "3":
                self.remove_repo_interactive()
            elif choice == "4":
                self.test_repo_access()
            elif choice == "5":
                break
            else:
                print("❌ Invalid choice")
    
    def add_repo_interactive(self):
        """Add repository interactively"""
        print("\n➕ ADD REPOSITORY")
        print("-" * 80)
        
        name = input("Repository name: ").strip()
        local_path = input("Local path (relative to base): ").strip()
        gitlab_url = input("GitLab URL: ").strip()
        source_branch = input("Source branch (default: main): ").strip() or "main"
        component = input("Component name (optional): ").strip()
        description = input("Description (optional): ").strip()
        
        repo = RepoConfig(
            name=name,
            local_path=local_path,
            gitlab_url=gitlab_url,
            source_branch=source_branch,
            component=component,
            description=description
        )
        
        self.worker.add_repo(repo)
        print(f"✅ Repository '{name}' added!")
        
        save = input("\nSave to config? (y/n): ").strip().lower()
        if save == 'y':
            self.save_repos_config()
    
    def remove_repo_interactive(self):
        """Remove repository interactively"""
        print("\n➖ REMOVE REPOSITORY")
        print("-" * 80)
        
        if not self.worker.repos:
            print("❌ No repositories configured")
            return
        
        print("\nAvailable repositories:")
        for i, name in enumerate(self.worker.repos.keys(), 1):
            print(f"  {i}. {name}")
        
        choice = input("\nEnter repository name to remove: ").strip()
        
        if choice in self.worker.repos:
            del self.worker.repos[choice]
            print(f"✅ Repository '{choice}' removed!")
            self.save_repos_config()
        else:
            print(f"❌ Repository '{choice}' not found")
    
    def test_repo_access(self):
        """Test repository access"""
        print("\n🔍 TEST REPOSITORY ACCESS")
        print("-" * 80)
        
        if not self.worker.repos:
            print("❌ No repositories configured")
            return
        
        print("\nAvailable repositories:")
        for i, name in enumerate(self.worker.repos.keys(), 1):
            print(f"  {i}. {name}")
        
        choice = input("\nEnter repository name to test: ").strip()
        
        if choice not in self.worker.repos:
            print(f"❌ Repository '{choice}' not found")
            return
        
        repo = self.worker.repos[choice]
        repo_path = os.path.join(self.worker.base_path, repo.local_path)
        
        print(f"\nTesting: {repo.name}")
        print(f"Path: {repo_path}")
        
        if not os.path.exists(repo_path):
            print("❌ Path does not exist")
            return
        
        # Test git access
        import subprocess
        try:
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print("✅ Git repository accessible")
                print(f"Remotes:\n{result.stdout}")
            else:
                print("❌ Git repository not accessible")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def manage_tasks(self):
        """Manage tasks"""
        while True:
            print("\n📝 TASK MANAGEMENT")
            print("-" * 80)
            print("1. List tasks")
            print("2. Add task")
            print("3. Remove task")
            print("4. Edit task")
            print("5. Load tasks from config")
            print("6. Save tasks to config")
            print("7. Back to main menu")
            
            choice = input("\nEnter choice (1-7): ").strip()
            
            if choice == "1":
                self.list_tasks()
            elif choice == "2":
                self.add_task_interactive()
            elif choice == "3":
                self.remove_task_interactive()
            elif choice == "4":
                self.edit_task_interactive()
            elif choice == "5":
                self.load_tasks_from_config()
            elif choice == "6":
                self.save_tasks_config()
            elif choice == "7":
                break
            else:
                print("❌ Invalid choice")
    
    def add_task_interactive(self):
        """Add task interactively"""
        print("\n➕ ADD TASK")
        print("-" * 80)
        
        if not self.worker.repos:
            print("❌ No repositories configured. Add repositories first.")
            return
        
        print("\nAvailable repositories:")
        for i, name in enumerate(self.worker.repos.keys(), 1):
            print(f"  {i}. {name}")
        
        repo_name = input("\nRepository name: ").strip()
        if repo_name not in self.worker.repos:
            print(f"❌ Repository '{repo_name}' not found")
            return
        
        task_id = input("Task ID: ").strip()
        description = input("Description: ").strip()
        
        print("\nBranch Configuration:")
        branch_name = input("Branch name (leave empty for auto-generated): ").strip() or None
        continue_existing = input("Continue on existing branch? (y/n): ").strip().lower() == 'y'
        
        print("\nFiles to modify (comma-separated):")
        files_input = input("Files: ").strip()
        files_to_modify = [f.strip() for f in files_input.split(",") if f.strip()]
        
        print("\nCode Changes (optional):")
        print("Enter file paths and code (type 'done' when finished):")
        code_changes = {}
        while True:
            file_path = input("File path (or 'done'): ").strip()
            if file_path.lower() == 'done':
                break
            print("Enter code (end with 'END' on new line):")
            code_lines = []
            while True:
                line = input()
                if line.strip() == 'END':
                    break
                code_lines.append(line)
            code_changes[file_path] = '\n'.join(code_lines)
        
        commit_message = input("Commit message (or press Enter for default): ").strip()
        
        task = Task(
            repo_name=repo_name,
            task_id=task_id,
            description=description,
            files_to_modify=files_to_modify,
            changes={},
            code_changes=code_changes if code_changes else None,
            branch_name=branch_name,
            continue_on_existing=continue_existing,
            commit_message=commit_message or None
        )
        
        self.worker.add_task(task)
        print(f"✅ Task '{task_id}' added!")
    
    def list_tasks(self):
        """List all tasks"""
        if not self.worker.tasks:
            print("\n❌ No tasks configured")
            return
        
        print("\n📋 TASKS")
        print("-" * 80)
        for i, task in enumerate(self.worker.tasks, 1):
            status_emoji = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "failed": "❌"
            }.get(task.status, "❓")
            
            print(f"\n{i}. {status_emoji} {task.task_id} ({task.repo_name})")
            print(f"   Description: {task.description}")
            if task.branch_name:
                print(f"   Branch: {task.branch_name}")
            print(f"   Continue on existing: {task.continue_on_existing}")
            if task.files_to_modify:
                print(f"   Files: {', '.join(task.files_to_modify)}")
    
    def remove_task_interactive(self):
        """Remove task interactively"""
        if not self.worker.tasks:
            print("\n❌ No tasks configured")
            return
        
        self.list_tasks()
        task_id = input("\nEnter task ID to remove: ").strip()
        
        self.worker.tasks = [t for t in self.worker.tasks if t.task_id != task_id]
        print(f"✅ Task '{task_id}' removed!")
    
    def edit_task_interactive(self):
        """Edit task interactively"""
        if not self.worker.tasks:
            print("\n❌ No tasks configured")
            return
        
        self.list_tasks()
        task_id = input("\nEnter task ID to edit: ").strip()
        
        task = next((t for t in self.worker.tasks if t.task_id == task_id), None)
        if not task:
            print(f"❌ Task '{task_id}' not found")
            return
        
        print(f"\nEditing task: {task_id}")
        print("(Press Enter to keep current value)")
        
        new_desc = input(f"Description [{task.description}]: ").strip()
        if new_desc:
            task.description = new_desc
        
        new_branch = input(f"Branch name [{task.branch_name or 'auto'}]: ").strip()
        if new_branch:
            task.branch_name = new_branch
        
        print(f"✅ Task '{task_id}' updated!")
    
    def load_tasks_from_config(self):
        """Load tasks from config file"""
        config_file = "config/tasks_config.json"
        if not Path(config_file).exists():
            print(f"❌ Config file not found: {config_file}")
            return
        
        with open(config_file, 'r') as f:
            config = json.load(f)
            tasks_data = config.get("tasks", [])
        
        if not tasks_data:
            print("❌ No tasks in config file")
            return
        
        print(f"\n📋 Loading {len(tasks_data)} tasks from config...")
        for task_data in tasks_data:
            self.worker.add_task(Task.from_dict(task_data))
        
        print("✅ Tasks loaded!")
    
    def save_tasks_config(self):
        """Save tasks to config file"""
        config_file = Path("config/tasks_config.json")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        config = {
            "tasks": [task.to_dict() for task in self.worker.tasks]
        }
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Tasks saved to {config_file}")
    
    def save_repos_config(self):
        """Save repositories to config file"""
        config_file = Path("config/repos_config.json")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        config = {
            "repos": [repo.to_dict() for repo in self.worker.repos.values()]
        }
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Repositories saved to {config_file}")
    
    def execute_tasks(self):
        """Execute tasks"""
        if not self.worker.tasks:
            print("\n❌ No tasks configured")
            return
        
        print(f"\n🚀 EXECUTING {len(self.worker.tasks)} TASKS")
        print("-" * 80)
        
        max_workers = input("Max parallel workers (default: 5): ").strip()
        max_workers = int(max_workers) if max_workers.isdigit() else 5
        
        confirm = input(f"\nExecute {len(self.worker.tasks)} tasks with {max_workers} workers? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Cancelled")
            return
        
        results = self.worker.execute_parallel(max_workers=max_workers)
        self.worker.save_work_log()
        
        print("\n📊 EXECUTION SUMMARY")
        print("-" * 80)
        for result in results:
            status_emoji = {
                "completed": "✅",
                "in_progress": "🔄",
                "failed": "❌"
            }.get(result.get("status"), "❓")
            print(f"{status_emoji} {result.get('repo', 'unknown')}: {result.get('status', 'unknown')}")
            if result.get("error"):
                print(f"   Error: {result['error']}")
    
    def continue_work(self):
        """Continue work on existing branches"""
        if not self.worker.tasks:
            print("\n❌ No tasks configured")
            return
        
        print("\n🔄 CONTINUE WORK ON EXISTING BRANCHES")
        print("-" * 80)
        print("This will force continue_on_existing=true for all tasks")
        
        confirm = input("\nContinue? (y/n): ").strip().lower()
        if confirm != 'y':
            return
        
        # Force continue mode
        for task in self.worker.tasks:
            task.continue_on_existing = True
        
        max_workers = input("Max parallel workers (default: 5): ").strip()
        max_workers = int(max_workers) if max_workers.isdigit() else 5
        
        results = self.worker.execute_parallel(max_workers=max_workers)
        self.worker.save_work_log()
        
        print("\n✅ Continue work completed!")
    
    def create_branches_only(self):
        """Create branches only"""
        if not self.worker.repos:
            print("\n❌ No repositories configured")
            return
        
        print("\n🌿 CREATE BRANCHES ONLY")
        print("-" * 80)
        
        prefix = input("Branch prefix (default: parallel-work): ").strip() or "parallel-work"
        
        # Create tasks for all repos
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for repo_name, repo in self.worker.repos.items():
            task = Task(
                repo_name=repo_name,
                task_id=f"{prefix}-{repo_name}",
                description=f"Create branch for {repo_name}",
                files_to_modify=[],
                changes={},
                commit_message=f"chore: create branch for parallel work on {repo_name}"
            )
            self.worker.add_task(task)
        
        max_workers = input("Max parallel workers (default: 5): ").strip()
        max_workers = int(max_workers) if max_workers.isdigit() else 5
        
        results = self.worker.execute_parallel(max_workers=max_workers)
        self.worker.save_work_log()
        
        print("\n✅ Branches created!")
    
    def view_status(self):
        """View status"""
        self.worker.print_status()
    
    def view_work_log(self):
        """View work log"""
        log_file = Path("logs/work_log.json")
        if not log_file.exists():
            print("\n❌ No work log found")
            return
        
        with open(log_file, 'r') as f:
            log_data = json.load(f)
        
        print("\n📜 WORK LOG")
        print("-" * 80)
        print(f"Timestamp: {log_data.get('timestamp', 'N/A')}")
        print(f"\nRepositories: {len(log_data.get('repos', {}))}")
        print(f"Tasks: {len(log_data.get('tasks', []))}")
        print(f"Results: {len(log_data.get('results', []))}")
        
        if log_data.get('results'):
            print("\n📊 Results:")
            for result in log_data['results']:
                status_emoji = {
                    "completed": "✅",
                    "in_progress": "🔄",
                    "failed": "❌"
                }.get(result.get("status"), "❓")
                print(f"{status_emoji} {result.get('repo', 'unknown')}: {result.get('branch', 'N/A')}")
    
    def multi_agent_mode(self):
        """Multi-agent mode"""
        print("\n🤖 MULTI-AGENT MODE")
        print("-" * 80)
        print("This mode allows multiple agents/instances to work in parallel")
        print("Each agent can work on different repositories or tasks")
        print("\nFeatures:")
        print("  • Agent ID assignment")
        print("  • Task distribution")
        print("  • Parallel execution")
        print("  • Result aggregation")
        
        num_agents = input("\nNumber of agents (default: 2): ").strip()
        num_agents = int(num_agents) if num_agents.isdigit() else 2
        
        print(f"\n🚀 Starting {num_agents} agents...")
        print("(This is a simulation - in production, agents would run separately)")
        
        # Distribute tasks across agents
        tasks_per_agent = len(self.worker.tasks) // num_agents
        for agent_id in range(num_agents):
            start_idx = agent_id * tasks_per_agent
            end_idx = start_idx + tasks_per_agent if agent_id < num_agents - 1 else len(self.worker.tasks)
            agent_tasks = self.worker.tasks[start_idx:end_idx]
            
            print(f"\nAgent {agent_id + 1}: {len(agent_tasks)} tasks")
            for task in agent_tasks:
                print(f"  • {task.task_id} ({task.repo_name})")
        
        print("\n💡 In production, each agent would:")
        print("  1. Load its assigned tasks")
        print("  2. Execute in parallel")
        print("  3. Report results to central log")
    
    def run(self):
        """Run interactive CLI"""
        self.print_header()
        
        while self.running:
            self.print_menu()
            choice = input("\nEnter choice (1-10): ").strip()
            
            try:
                if choice == "1":
                    self.manage_repos()
                elif choice == "2":
                    self.manage_tasks()
                elif choice == "3":
                    self.execute_tasks()
                elif choice == "4":
                    self.continue_work()
                elif choice == "5":
                    self.create_branches_only()
                elif choice == "6":
                    self.view_status()
                elif choice == "7":
                    self.view_work_log()
                elif choice == "8":
                    print("\n⚙️  Configuration")
                    print("Edit config files manually:")
                    print("  • config/config.json")
                    print("  • config/repos_config.json")
                    print("  • config/tasks_config.json")
                elif choice == "9":
                    self.multi_agent_mode()
                elif choice == "10":
                    print("\n👋 Goodbye!")
                    self.running = False
                else:
                    print("❌ Invalid choice")
            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted by user")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Code Atlas - Interactive CLI")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to main config file"
    )
    parser.add_argument(
        "--base-path",
        help="Base path for repositories (overrides config)"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = {}
    if Path(args.config).exists():
        with open(args.config, 'r') as f:
            config = json.load(f)
    
    base_path = args.base_path or config.get("base_path", os.getcwd())
    
    # Initialize worker
    worker = ParallelRepoWorker(base_path=base_path, config_path=args.config)
    
    # Load repos if config exists
    repos_config = Path("config/repos_config.json")
    if repos_config.exists():
        with open(repos_config, 'r') as f:
            repos_data = json.load(f).get("repos", [])
            for repo_data in repos_data:
                worker.add_repo(RepoConfig.from_dict(repo_data))
    
    # Start interactive CLI
    cli = InteractiveCLI(worker)
    cli.run()


if __name__ == "__main__":
    main()
