#!/usr/bin/env python3
"""
Main entry point for Code Atlas
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.worker import ParallelRepoWorker
from src.core.models import RepoConfig, Task


def load_config(config_file: str = "config/config.json") -> dict:
    """Load main configuration"""
    config_path = Path(config_file)
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}


def load_repos(config_file: str = "config/repos_config.json") -> list:
    """Load repository configurations"""
    config_path = Path(config_file)
    if not config_path.exists():
        print(f"⚠️  Config file not found: {config_path}")
        print("💡 Create config/repos_config.json with your repository configurations")
        return []
    
    with open(config_path, 'r') as f:
        config = json.load(f)
        return config.get("repos", [])


def load_tasks(config_file: str = "config/tasks_config.json") -> list:
    """Load tasks from configuration"""
    config_path = Path(config_file)
    if not config_path.exists():
        return []
    
    with open(config_path, 'r') as f:
        config = json.load(f)
        return config.get("tasks", [])


def create_branches_only(worker: ParallelRepoWorker, task_prefix: str, remote: str = "origin"):
    """Create branches for all repos without making changes"""
    print("\n" + "="*80)
    print("🌿 CREATING BRANCHES (PARALLEL)")
    print("="*80 + "\n")
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create a simple task for each repo just to create branches
    for repo_name, repo in worker.repos.items():
        task = Task(
            repo_name=repo_name,
            task_id=f"{task_prefix}-{repo_name}",
            description=f"Create branch for {repo_name}",
            files_to_modify=[],
            changes={},
            commit_message=f"chore: create branch for parallel work on {repo_name}"
        )
        worker.add_task(task)
    
    # Execute branch creation in parallel
    results = worker.execute_parallel(max_workers=len(worker.repos), remote=remote)
    
    # Print summary
    print("\n" + "="*80)
    print("📊 BRANCH CREATION SUMMARY")
    print("="*80)
    
    for result in results:
        status_emoji = "✅" if result.get("status") == "completed" else "❌"
        print(f"{status_emoji} {result.get('repo', 'unknown')}: {result.get('branch', 'N/A')}")
        if result.get("error"):
            print(f"   Error: {result['error']}")
    
    return results


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description="Code Atlas")
    parser.add_argument(
        "--action",
        choices=["create-branches", "execute", "status", "interactive"],
        default="interactive",
        help="Action to perform"
    )
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to main config file"
    )
    parser.add_argument(
        "--repos-config",
        default="config/repos_config.json",
        help="Path to repos config file"
    )
    parser.add_argument(
        "--tasks-config",
        default="config/tasks_config.json",
        help="Path to tasks config file"
    )
    parser.add_argument(
        "--prefix",
        help="Task prefix for branch creation"
    )
    parser.add_argument(
        "--base-path",
        help="Base path for repositories"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Maximum parallel workers"
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    base_path = args.base_path or config.get("base_path", os.getcwd())
    max_workers = args.max_workers or config.get("max_workers", 5)
    
    # Initialize worker
    worker = ParallelRepoWorker(base_path=base_path, config_path=args.config)
    
    # Load repos
    print("📁 Loading repositories...")
    repos_data = load_repos(args.repos_config)
    
    if not repos_data:
        print("❌ No repositories configured. Please create config/repos_config.json")
        return 1
    
    for repo_data in repos_data:
        worker.add_repo(RepoConfig.from_dict(repo_data))
    
    print(f"✅ Loaded {len(worker.repos)} repositories\n")
    
    # Execute action
    if args.action == "create-branches":
        if not args.prefix:
            print("❌ --prefix required for create-branches action")
            return 1
        
        results = create_branches_only(worker, args.prefix, args.remote)
        worker.save_work_log()
        return 0
        
    elif args.action == "execute":
        tasks_data = load_tasks(args.tasks_config)
        if not tasks_data:
            print("❌ No tasks found. Please create config/tasks_config.json")
            return 1
        
        print(f"📋 Loading {len(tasks_data)} tasks...")
        for task_data in tasks_data:
            worker.add_task(Task.from_dict(task_data))
        
        print("\n🚀 Executing tasks in parallel...")
        results = worker.execute_parallel(max_workers=max_workers, remote=args.remote)
        worker.save_work_log()
        return 0
        
    elif args.action == "continue":
        # Continue mode: resume work on existing branches
        tasks_data = load_tasks(args.tasks_config)
        if not tasks_data:
            print("❌ No tasks found. Please create config/tasks_config.json")
            return 1
        
        print(f"📋 Loading {len(tasks_data)} tasks for continuation...")
        for task_data in tasks_data:
            # Force continue_on_existing for continue mode
            task_data["continue_on_existing"] = True
            worker.add_task(Task.from_dict(task_data))
        
        print("\n🔄 Continuing work on existing branches...")
        results = worker.execute_parallel(max_workers=max_workers, remote=args.remote)
        worker.save_work_log()
        return 0
        
    elif args.action == "status":
        worker.print_status()
        return 0
        
    elif args.action == "interactive":
        # Use full interactive CLI
        from cli import InteractiveCLI
        cli = InteractiveCLI(worker)
        cli.run()
        return 0
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
