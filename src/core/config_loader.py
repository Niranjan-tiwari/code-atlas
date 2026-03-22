"""
Unified configuration loader
Consolidates all config files into single source
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Optional


class ConfigLoader:
    """Load and merge all configuration files"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.logger = logging.getLogger("config_loader")
    
    def load_all_config(self) -> Dict:
        """Load and merge all configuration files"""
        config = {}
        
        # Load main config (has everything now)
        main_config = self.config_dir / "config.json"
        if main_config.exists():
            with open(main_config, 'r') as f:
                config = json.load(f)
        
        # Backward compatibility: Load separate files if main config doesn't have them
        if "repos" not in config:
            repos_config = self.config_dir / "repos_config.json"
            if repos_config.exists():
                with open(repos_config, 'r') as f:
                    repos_data = json.load(f)
                    config["repos"] = repos_data.get("repos", [])
        
        if "tasks" not in config:
            tasks_config = self.config_dir / "tasks_config.json"
            if tasks_config.exists():
                with open(tasks_config, 'r') as f:
                    tasks_data = json.load(f)
                    config["tasks"] = tasks_data.get("tasks", [])
        
        # Load notifications from main config or separate file
        if "notifications" not in config:
            notifications_config = self.config_dir / "notifications_config.json"
            if notifications_config.exists():
                with open(notifications_config, 'r') as f:
                    config["notifications"] = json.load(f)
        
        return config
    
    def get_work_mode(self) -> str:
        """Get work mode from config"""
        config = self.load_all_config()
        return config.get("work_mode", "simple_task")
    
    def get_base_path(self) -> str:
        """Get base path from config"""
        config = self.load_all_config()
        return config.get("base_path", os.getcwd())
    
    def get_all_base_paths(self) -> list:
        """Get all base paths from config (primary + additional)"""
        config = self.load_all_config()
        paths = []
        
        # Primary: base_paths_config
        bpc = config.get("base_paths_config", [])
        if bpc:
            paths = [entry["path"] for entry in bpc if entry.get("path")]
        else:
            # Fallback: base_path + additional_base_paths
            bp = config.get("base_path", "")
            if bp:
                paths.append(bp)
            paths.extend(config.get("additional_base_paths", []))
        
        return paths
    
    def get_branch_rules(self) -> Dict:
        """
        Get base_path -> default_branch mapping.
        
        Rule: netcore_cpass_whatsapp repos -> 'master',
              netcore_cpass_rcs repos -> 'main'.
        
        Returns:
            Dict mapping base_path -> default_branch
        """
        config = self.load_all_config()
        rules = {}
        for entry in config.get("base_paths_config", []):
            path = entry.get("path", "")
            branch = entry.get("default_branch", "")
            if path and branch:
                rules[path] = branch
        return rules
    
    def get_notifications_config(self) -> Dict:
        """Get notifications configuration"""
        config = self.load_all_config()
        return config.get("notifications", {})
