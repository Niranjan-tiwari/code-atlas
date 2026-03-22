#!/usr/bin/env python3
"""
Daemon mode for Code Atlas
Runs continuously, monitoring tasks and executing them
"""

import sys
import os
import time
import json
import signal
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from src.core.worker import ParallelRepoWorker
from src.core.models import RepoConfig, Task
from src.utils.auto_discover import RepoDiscoverer


class DaemonWorker:
    """Daemon worker that runs continuously"""
    
    def __init__(self, config_path: str = "config/config.json", 
                 tasks_config: str = "config/tasks_config.json",
                 check_interval: int = 60,
                 enable_api: bool = False,
                 api_port: int = 8080):
        """
        Initialize daemon worker
        
        Args:
            config_path: Path to main config
            tasks_config: Path to tasks config
            check_interval: Seconds between task checks
        """
        self.config_path = config_path
        self.tasks_config = tasks_config
        self.check_interval = check_interval
        self.running = True
        self.worker = None
        
        # Setup logging
        self.setup_logging()
        self.logger = logging.getLogger("daemon_worker")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
    def setup_logging(self):
        """Setup logging for daemon"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / "daemon.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def load_config(self) -> dict:
        """Load configuration"""
        config_file = Path(self.config_path)
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)
        return {}
    
    def load_tasks(self) -> List[Task]:
        """Load tasks from config"""
        tasks_file = Path(self.tasks_config)
        if not tasks_file.exists():
            self.logger.warning(f"Tasks config not found: {tasks_file}")
            return []
        
        with open(tasks_file, 'r') as f:
            config = json.load(f)
            tasks_data = config.get("tasks", [])
        
        tasks = []
        for task_data in tasks_data:
            try:
                task = Task.from_dict(task_data)
                tasks.append(task)
            except Exception as e:
                self.logger.error(f"Error loading task: {e}")
        
        return tasks
    
    def initialize_worker(self):
        """Initialize worker with config and auto-discover repos"""
        config = self.load_config()
        base_path = config.get("base_path", os.getcwd())
        
        self.worker = ParallelRepoWorker(base_path=base_path, config_path=self.config_path)
        
        # Auto-discover repos if enabled
        auto_discover = config.get("auto_discover_repos", True)
        
        if auto_discover:
            self.logger.info("🔍 Auto-discovering repositories...")
            try:
                discoverer = RepoDiscoverer(base_path)
                discovered_repos = discoverer.discover_repos()
                
                if discovered_repos:
                    self.logger.info(f"✅ Discovered {len(discovered_repos)} repositories")
                    for repo_data in discovered_repos:
                        repo = RepoConfig.from_dict(repo_data)
                        self.worker.add_repo(repo)
                    
                    # Save discovered repos to config
                    repos_config = Path("config/repos_config.json")
                    repos_config.parent.mkdir(exist_ok=True)
                    with open(repos_config, 'w') as f:
                        json.dump({"repos": discovered_repos}, f, indent=2)
                    self.logger.info(f"💾 Saved discovered repos to {repos_config}")
                else:
                    self.logger.warning("⚠️  No repositories discovered, loading from config")
                    self._load_repos_from_config()
            except Exception as e:
                self.logger.error(f"❌ Auto-discovery failed: {e}, loading from config")
                self._load_repos_from_config()
        else:
            self.logger.info("📋 Auto-discovery disabled, loading from config")
            self._load_repos_from_config()
        
        self.logger.info(f"✅ Worker initialized with {len(self.worker.repos)} repositories")
    
    def _load_repos_from_config(self):
        """Load repos from config file"""
        repos_config = Path("config/repos_config.json")
        if repos_config.exists():
            with open(repos_config, 'r') as f:
                repos_data = json.load(f).get("repos", [])
                for repo_data in repos_data:
                    repo = RepoConfig.from_dict(repo_data)
                    self.worker.add_repo(repo)
    
    def execute_pending_tasks(self):
        """Execute pending tasks"""
        tasks = self.load_tasks()
        
        if not tasks:
            return
        
        # Filter pending tasks
        pending_tasks = [t for t in tasks if t.status == "pending"]
        
        if not pending_tasks:
            return
        
        self.logger.info(f"Found {len(pending_tasks)} pending tasks")
        
        # Add tasks to worker
        for task in pending_tasks:
            self.worker.add_task(task)
        
        # Execute with configurable parallel workers
        config = self.load_config()
        
        # Get parallel execution config
        parallel_config = config.get("parallel_execution", {})
        max_workers = parallel_config.get("max_workers") or config.get("max_workers", 5)
        max_workers_per_repo = parallel_config.get("max_workers_per_repo", 1)
        enable_agent_pool = parallel_config.get("enable_agent_pool", False)
        agent_pool_size = parallel_config.get("agent_pool_size", max_workers)
        
        remote = config.get("remote", "origin")
        
        # Log parallel configuration
        self.logger.info(f"⚙️  Parallel Execution Config:")
        self.logger.info(f"   Max Workers: {max_workers}")
        self.logger.info(f"   Workers per Repo: {max_workers_per_repo}")
        self.logger.info(f"   Agent Pool: {'Enabled' if enable_agent_pool else 'Disabled'}")
        if enable_agent_pool:
            self.logger.info(f"   Agent Pool Size: {agent_pool_size}")
        
        self.logger.info(f"🚀 Executing {len(pending_tasks)} tasks with {max_workers} workers")
        results = self.worker.execute_parallel(
            max_workers=max_workers,
            remote=remote,
            max_workers_per_repo=max_workers_per_repo,
            enable_agent_pool=enable_agent_pool,
            agent_pool_size=agent_pool_size
        )
        
        # Save work log
        self.worker.save_work_log()
        
        # Log results
        for result in results:
            status = result.get("status", "unknown")
            repo = result.get("repo", "unknown")
            task_id = result.get("task_id", "unknown")
            self.logger.info(f"Task {task_id} ({repo}): {status}")
            if result.get("error"):
                self.logger.error(f"Error: {result['error']}")
    
    def run(self):
        """Run daemon loop"""
        self.logger.info("="*80)
        self.logger.info("Starting Code Atlas Daemon")
        self.logger.info("="*80)
        
        # Check work mode
        config = self.load_config()
        work_mode = config.get("work_mode", "agent_24_7")
        
        # Initialize worker
        self.initialize_worker()
        
        if work_mode == "simple_task":
            # Simple task mode: execute once and exit
            self.logger.info("Mode: SIMPLE_TASK - Executing tasks once and exiting")
            self.execute_pending_tasks()
            self.logger.info("Tasks completed. Exiting.")
            return
        
        # Agent 24/7 mode: continuous loop
        self.logger.info(f"Mode: AGENT_24_7 - Continuous monitoring (interval: {self.check_interval}s)")
        
        # Main loop
        iteration = 0
        max_iterations = config.get("max_iterations")
        
        while self.running:
            try:
                iteration += 1
                
                # Check max iterations
                if max_iterations and iteration > max_iterations:
                    self.logger.info(f"Reached max iterations ({max_iterations}), stopping")
                    break
                
                self.logger.info(f"Iteration {iteration}: Checking for pending tasks...")
                
                # Execute pending tasks
                self.execute_pending_tasks()
                
                # Sleep until next check
                if self.running:
                    self.logger.info(f"Sleeping for {self.check_interval} seconds...")
                    time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt")
                self.running = False
            except Exception as e:
                self.logger.error(f"Error in daemon loop: {e}", exc_info=True)
                time.sleep(10)  # Wait before retrying
        
        self.logger.info("Daemon stopped")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Code Atlas Daemon")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to main config file"
    )
    parser.add_argument(
        "--tasks-config",
        default="config/tasks_config.json",
        help="Path to tasks config file"
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=60,
        help="Seconds between task checks (default: 60)"
    )
    
    args = parser.parse_args()
    
    daemon = DaemonWorker(
        config_path=args.config,
        tasks_config=args.tasks_config,
        check_interval=args.check_interval
    )
    
    daemon.run()


if __name__ == "__main__":
    main()
