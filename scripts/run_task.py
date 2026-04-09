#!/usr/bin/env python3
"""
Parallel Multi-Repo Task Runner

Submit a single task across multiple repositories and execute in parallel.
Supports CLI arguments, JSON task files, and interactive mode.

Usage:
  # CLI mode - create branches across 5 repos
  python3 scripts/run_task.py \
    --repos service-alpha,service-beta,service-gamma \
    --jira PROJ-1234 \
    --description "Add health check endpoint" \
    --source master \
    --branch feature/PROJ-1234-health-check \
    --base-path /path/to/your/repos \
    --branch-only

  # JSON mode - load task from file
  python3 scripts/run_task.py --from-json tasks/my_task.json

  # Interactive mode
  python3 scripts/run_task.py --interactive

  # Dry run (preview without executing)
  python3 scripts/run_task.py --from-json tasks/my_task.json --dry-run

  # Multiple base paths
  python3 scripts/run_task.py \
    --repos service-alpha,service-gamma \
    --jira PROJ-1234 \
    --description "Fix logging" \
    --source master \
    --branch feature/PROJ-1234-logging \
    --base-path /path/to/your/repos \
    --base-path /path/to/your/repos-alt
"""

import sys
import os
import json
import argparse
import time
import readline
from pathlib import Path
from datetime import datetime

# Enable arrow keys, history, and line editing in interactive input()
readline.parse_and_bind('"\e[A": history-search-backward')
readline.parse_and_bind('"\e[B": history-search-forward')
readline.parse_and_bind('set editing-mode emacs')

# Add project root to path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from src.core.models import RepoConfig, Task
from src.core.worker import ParallelRepoWorker
from src.utils.auto_discover import RepoDiscoverer


# =============================================================================
# Auto-Discovery Helper
# =============================================================================

def load_base_paths_config() -> dict:
    """
    Load base_paths_config from config/config.json.
    Returns dict mapping path -> default_branch.
    
    Each workspace directory can set default_branch in config/config.json
    (base_paths_config).
    """
    branch_rules = {}
    config_path = Path(project_root) / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            for entry in config.get("base_paths_config", []):
                path = os.path.expanduser(entry.get("path", ""))
                branch = entry.get("default_branch", "")
                if path and branch:
                    branch_rules[path] = branch
        except (json.JSONDecodeError, IOError):
            pass
    return branch_rules


def discover_all_repos(base_paths: list) -> dict:
    """
    Discover all Git repos across multiple base paths.
    Returns dict mapping repo_name -> {base_path, local_path, gitlab_url, source_branch}
    
    Applies default_branch from base_paths_config for each base path.
    """
    all_repos = {}
    branch_rules = load_base_paths_config()
    
    for bp in base_paths:
        bp = os.path.expanduser(bp)
        if not os.path.exists(bp):
            print(f"  ⚠️  Base path does not exist: {bp}")
            continue
        
        # Look up forced default branch for this base path
        forced_branch = branch_rules.get(bp)
        if forced_branch:
            print(f"  📏 Rule: {os.path.basename(bp)} -> branch from '{forced_branch}'")
        
        discoverer = RepoDiscoverer(bp, default_branch=forced_branch)
        found = discoverer.discover_repos()
        
        for repo_info in found:
            name = repo_info["name"]
            all_repos[name] = {
                "base_path": bp,
                "local_path": repo_info.get("local_path", name),
                "gitlab_url": repo_info.get("gitlab_url", ""),
                "source_branch": repo_info.get("source_branch", "master"),
                "component": repo_info.get("component", "")
            }
    
    return all_repos


# =============================================================================
# Task Loading
# =============================================================================

def load_task_from_json(json_path: str) -> dict:
    """Load a multi-repo task definition from a JSON file"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    required = ["repos"]
    for field in required:
        if field not in data:
            raise ValueError(f"Missing required field in task JSON: '{field}'")
    
    return data


def build_tasks_from_args(args, discovered_repos: dict) -> list:
    """Build Task objects from CLI arguments or JSON data"""
    tasks = []
    repo_names = args.get("repos", [])
    
    if not repo_names:
        print("❌ No repositories specified")
        return []
    
    jira_id = args.get("jira_id", "") or args.get("jira", "")
    description = args.get("description", "Task")
    source_branch = args.get("source_branch", "") or args.get("source", "")
    branch_name = args.get("branch_name", "") or args.get("branch", "")
    branch_only = args.get("branch_only", False)
    delete_branch_first = args.get("delete_branch_first", False)
    
    # Per-repo task overrides (from JSON mode)
    per_repo_tasks = {}
    if "tasks" in args:
        for t in args["tasks"]:
            repo = t.get("repo", "")
            if repo:
                per_repo_tasks[repo] = t
    
    for repo_name in repo_names:
        repo_name = repo_name.strip()
        if not repo_name:
            continue
        
        # Find repo in discovered repos
        if repo_name not in discovered_repos:
            print(f"  ⚠️  Repo '{repo_name}' not found in any base path. Skipping.")
            continue
        
        repo_info = discovered_repos[repo_name]
        
        # Get per-repo overrides
        repo_override = per_repo_tasks.get(repo_name, {})
        
        # Build task ID
        task_id = f"{jira_id}_{repo_name}" if jira_id else f"task_{repo_name}_{int(time.time())}"
        
        # Determine source branch: per-repo override > global > repo default
        task_source = (
            repo_override.get("source_branch") or
            source_branch or
            repo_info.get("source_branch", "master")
        )
        
        # Build the Task
        task = Task(
            repo_name=repo_name,
            task_id=task_id,
            description=repo_override.get("description", description),
            files_to_modify=repo_override.get("files_to_modify", []),
            changes=repo_override.get("changes", {}),
            code_changes=repo_override.get("code_changes"),
            branch_name=branch_name,
            source_branch=task_source,
            jira_id=jira_id,
            branch_only=branch_only,
            delete_branch_first=delete_branch_first,
            commit_message=repo_override.get("commit_message")
        )
        
        tasks.append((task, repo_info))
    
    return tasks


# =============================================================================
# Interactive Mode
# =============================================================================

def interactive_mode(base_paths: list) -> dict:
    """Collect task parameters interactively"""
    print("\n" + "=" * 60)
    print("  🚀 Parallel Multi-Repo Task Runner - Interactive Mode")
    print("=" * 60)
    
    # Discover repos
    print("\n📂 Discovering repositories...")
    discovered = discover_all_repos(base_paths)
    
    if not discovered:
        print("❌ No repositories found. Check your base paths.")
        sys.exit(1)
    
    print(f"   Found {len(discovered)} repos across {len(base_paths)} base path(s)\n")
    
    # List available repos
    print("Available repositories:")
    repo_list = sorted(discovered.keys())
    for i, name in enumerate(repo_list, 1):
        info = discovered[name]
        print(f"  {i:3d}. {name} (branch: {info['source_branch']})")
    
    # Get repo selection
    print("\n📋 Enter repo names (comma-separated) or numbers:")
    print("   Example: service-alpha,service-beta,service-gamma")
    print("   Example: 1,5,12")
    selection = input("   > ").strip()
    
    # Parse selection (numbers or names)
    selected_repos = []
    for item in selection.split(","):
        item = item.strip()
        if item.isdigit():
            idx = int(item) - 1
            if 0 <= idx < len(repo_list):
                selected_repos.append(repo_list[idx])
            else:
                print(f"   ⚠️  Invalid number: {item}")
        else:
            selected_repos.append(item)
    
    if not selected_repos:
        print("❌ No repos selected")
        sys.exit(1)
    
    print(f"\n   Selected: {', '.join(selected_repos)}")
    
    # Get Jira ID
    jira_id = input("\n🎫 Jira ID (e.g., PROJ-1234, or press Enter to skip): ").strip()
    
    # Get description
    description = input("\n📝 Task description: ").strip() or "Parallel task"
    
    # Get source branch
    default_source = discovered[selected_repos[0]].get("source_branch", "master")
    source_branch = input(f"\n🌿 Source branch (default: {default_source}): ").strip() or default_source
    
    # Get new branch name
    if jira_id:
        default_branch = f"feature/{jira_id}-{description.lower().replace(' ', '-')[:30]}"
    else:
        default_branch = f"feature/{description.lower().replace(' ', '-')[:40]}"
    branch_name = input(f"\n🌱 New branch name (default: {default_branch}): ").strip() or default_branch
    
    # Branch only?
    branch_only_str = input("\n🔀 Branch-only mode? (just create branch, no code changes) [Y/n]: ").strip().lower()
    branch_only = branch_only_str != "n"
    
    return {
        "repos": selected_repos,
        "jira_id": jira_id,
        "description": description,
        "source_branch": source_branch,
        "branch_name": branch_name,
        "branch_only": branch_only,
        "delete_branch_first": False
    }


# =============================================================================
# Execution
# =============================================================================

def print_task_summary(tasks: list, dry_run: bool = False):
    """Print a summary table of tasks before execution"""
    mode = "DRY RUN" if dry_run else "EXECUTION PLAN"
    
    print(f"\n{'=' * 70}")
    print(f"  📋 {mode}")
    print(f"{'=' * 70}")
    
    if not tasks:
        print("  No tasks to execute.")
        return
    
    first_task = tasks[0][0]
    print(f"  Jira:        {first_task.jira_id or 'N/A'}")
    print(f"  Description: {first_task.description}")
    print(f"  Branch:      {first_task.branch_name}")
    print(f"  Mode:        {'Branch-only' if first_task.branch_only else 'Full workflow'}")
    print(f"  Repos:       {len(tasks)}")
    print(f"{'─' * 70}")
    print(f"  {'#':<4} {'Repository':<35} {'Source Branch':<20} {'Status'}")
    print(f"{'─' * 70}")
    
    for i, (task, repo_info) in enumerate(tasks, 1):
        source = task.source_branch or repo_info.get("source_branch", "?")
        print(f"  {i:<4} {task.repo_name:<35} {source:<20} {'ready'}")
    
    print(f"{'=' * 70}\n")


def print_results(results: list):
    """Print execution results as a summary table"""
    print(f"\n{'=' * 80}")
    print(f"  📊 EXECUTION RESULTS")
    print(f"{'=' * 80}")
    print(f"  {'#':<4} {'Repository':<30} {'Status':<12} {'Branch':<25} {'Details'}")
    print(f"{'─' * 80}")
    
    success = 0
    failed = 0
    
    for i, result in enumerate(results, 1):
        status = result.get("status", "unknown")
        repo = result.get("repo", "?")
        branch = result.get("branch", "?")
        
        if status == "completed":
            emoji = "✅"
            success += 1
        elif status == "failed":
            emoji = "❌"
            failed += 1
        else:
            emoji = "🔄"
        
        # Get extra details
        details = ""
        steps = result.get("steps", [])
        mr_step = next((s for s in steps if s.get("step") == "create_mr"), None)
        if mr_step and mr_step.get("mr_url"):
            details = f"MR: {mr_step['mr_url']}"
        elif result.get("error"):
            details = result["error"][:40]
        
        validation_step = next((s for s in steps if s.get("step") == "pre_push_validation"), None)
        if validation_step and validation_step.get("status") == "warning":
            details += " [validation warnings]"
        
        print(f"  {i:<4} {repo:<30} {emoji} {status:<10} {branch:<25} {details}")
    
    print(f"{'─' * 80}")
    print(f"  Total: {len(results)} | ✅ Success: {success} | ❌ Failed: {failed}")
    print(f"{'=' * 80}\n")


def execute_tasks(tasks: list, max_workers: int = 5, remote: str = "origin"):
    """Execute tasks in parallel using ParallelRepoWorker"""
    if not tasks:
        print("❌ No tasks to execute")
        return []
    
    # Group tasks by base_path (need separate workers per base path)
    tasks_by_base = {}
    for task, repo_info in tasks:
        bp = repo_info["base_path"]
        if bp not in tasks_by_base:
            tasks_by_base[bp] = []
        tasks_by_base[bp].append((task, repo_info))
    
    all_results = []
    
    for base_path, bp_tasks in tasks_by_base.items():
        print(f"\n🏗️  Processing base path: {base_path}")
        
        worker = ParallelRepoWorker(base_path=base_path)
        
        # Register repos and tasks
        for task, repo_info in bp_tasks:
            repo_config = RepoConfig(
                name=task.repo_name,
                local_path=repo_info["local_path"],
                gitlab_url=repo_info.get("gitlab_url", ""),
                source_branch=repo_info.get("source_branch", "master"),
                component=repo_info.get("component", "")
            )
            worker.add_repo(repo_config)
            worker.add_task(task)
        
        # Execute in parallel
        results = worker.execute_parallel(
            max_workers=min(max_workers, len(bp_tasks)),
            remote=remote
        )
        
        all_results.extend(results)
        
        # Save work log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        jira_id = bp_tasks[0][0].jira_id or "notask"
        worker.save_work_log(f"task_run_{jira_id}_{timestamp}.json")
    
    return all_results


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Parallel Multi-Repo Task Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Branch-only across 3 repos
  python3 scripts/run_task.py \\
    --repos service-alpha,service-beta,service-gamma \\
    --jira PROJ-1234 --description "Add health check" \\
    --source master --branch feature/PROJ-1234-health \\
    --base-path /path/to/your/repos --branch-only

  # From JSON file
  python3 scripts/run_task.py --from-json tasks/my_task.json

  # Interactive mode
  python3 scripts/run_task.py --interactive

  # Dry run
  python3 scripts/run_task.py --from-json tasks/my_task.json --dry-run
        """
    )
    
    # Input modes
    mode_group = parser.add_argument_group("Input Mode")
    mode_group.add_argument("--from-json", type=str, help="Load task from JSON file")
    mode_group.add_argument("--interactive", action="store_true", help="Interactive mode")
    
    # Task parameters (CLI mode)
    task_group = parser.add_argument_group("Task Parameters (CLI mode)")
    task_group.add_argument("--repos", type=str, help="Comma-separated repo names")
    task_group.add_argument("--jira", type=str, default="", help="Jira ticket ID (e.g., PROJ-1234)")
    task_group.add_argument("--description", type=str, default="Parallel task", help="Task description")
    task_group.add_argument("--source", type=str, default="", help="Source branch to create from")
    task_group.add_argument("--branch", type=str, default="", help="New branch name to create")
    task_group.add_argument("--branch-only", action="store_true", help="Only create branch and push (no code changes)")
    task_group.add_argument("--delete-branch-first", action="store_true", help="Delete branch before creating")
    
    # Execution options
    exec_group = parser.add_argument_group("Execution Options")
    exec_group.add_argument("--base-path", action="append", default=[], help="Base path(s) for repos (can specify multiple)")
    exec_group.add_argument("--max-workers", type=int, default=5, help="Max parallel workers (default: 5)")
    exec_group.add_argument("--remote", type=str, default="origin", help="Git remote name (default: origin)")
    exec_group.add_argument("--dry-run", action="store_true", help="Preview tasks without executing")
    
    args = parser.parse_args()
    
    # Determine base paths
    base_paths = args.base_path
    if not base_paths:
        # Load from config: base_paths_config (primary) or base_path + additional (fallback)
        config_path = Path(project_root) / "config" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # Primary: use base_paths_config entries
                bpc = config.get("base_paths_config", [])
                if bpc:
                    base_paths = [entry["path"] for entry in bpc if entry.get("path")]
                else:
                    # Fallback: base_path + additional_base_paths
                    bp = config.get("base_path", "")
                    if bp:
                        base_paths = [bp]
                    extra = config.get("additional_base_paths", [])
                    base_paths.extend(extra)
            except (json.JSONDecodeError, IOError):
                pass
    
    if not base_paths:
        print("❌ No base paths specified. Use --base-path or set base_path in config/config.json")
        sys.exit(1)
    
    print(f"📂 Base paths: {', '.join(base_paths)}")
    
    # Discover all repos
    print("🔍 Discovering repositories...")
    discovered = discover_all_repos(base_paths)
    print(f"   Found {len(discovered)} repositories\n")
    
    if not discovered:
        print("❌ No repositories found. Check your base paths.")
        sys.exit(1)
    
    # Build task parameters based on input mode
    if args.interactive:
        task_params = interactive_mode(base_paths)
    elif args.from_json:
        task_params = load_task_from_json(args.from_json)
        # Merge base_paths from JSON if present
        if "base_paths" in task_params:
            extra_bp = task_params["base_paths"]
            for bp in extra_bp:
                if bp not in base_paths:
                    base_paths.append(bp)
            # Re-discover with additional paths
            discovered = discover_all_repos(base_paths)
    else:
        # CLI mode
        if not args.repos:
            parser.error("--repos is required in CLI mode (or use --interactive / --from-json)")
        
        task_params = {
            "repos": [r.strip() for r in args.repos.split(",")],
            "jira_id": args.jira,
            "description": args.description,
            "source_branch": args.source,
            "branch_name": args.branch,
            "branch_only": args.branch_only,
            "delete_branch_first": args.delete_branch_first
        }
    
    # Build Task objects
    tasks = build_tasks_from_args(task_params, discovered)
    
    if not tasks:
        print("❌ No valid tasks could be created. Check repo names.")
        sys.exit(1)
    
    # Print summary
    print_task_summary(tasks, dry_run=args.dry_run)
    
    # Dry run - stop here
    if args.dry_run:
        print("🏁 Dry run complete. No changes were made.")
        sys.exit(0)
    
    # Confirm execution
    confirm = input("▶️  Execute? [y/N]: ").strip().lower()
    if confirm not in ("y", "yes"):
        print("⏹️  Cancelled.")
        sys.exit(0)
    
    # Execute
    start = time.time()
    results = execute_tasks(tasks, max_workers=args.max_workers, remote=args.remote)
    elapsed = time.time() - start
    
    # Print results
    print_results(results)
    print(f"⏱️  Total time: {elapsed:.1f}s\n")


if __name__ == "__main__":
    main()
