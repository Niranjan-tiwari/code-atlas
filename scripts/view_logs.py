#!/usr/bin/env python3
"""
View logs in a readable format
"""

import sys
import json
from pathlib import Path
from datetime import datetime

def view_task_logs(task_id=None, repo_name=None, limit=20):
    """View task execution logs"""
    log_file = Path("logs/task_executions.jsonl")
    
    if not log_file.exists():
        print("❌ No task logs found")
        return
    
    print("\n" + "="*80)
    print("📋 TASK EXECUTION LOGS")
    print("="*80)
    
    entries = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if task_id and entry.get("task_id") != task_id:
                    continue
                if repo_name and entry.get("repo_name") != repo_name:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    
    # Show most recent first
    entries = entries[-limit:] if len(entries) > limit else entries
    
    for entry in entries:
        timestamp = entry.get("timestamp", "N/A")
        event = entry.get("event", "unknown")
        task_id = entry.get("task_id", "N/A")
        repo = entry.get("repo_name", "N/A")
        
        print(f"\n⏰ {timestamp}")
        print(f"   Event: {event}")
        print(f"   Task: {task_id} | Repo: {repo}")
        
        if event == "task_start":
            branch = entry.get("branch_name", "N/A")
            print(f"   Branch: {branch}")
            desc = entry.get("task_details", {}).get("description", "N/A")
            print(f"   Description: {desc}")
        
        elif event == "task_step":
            step = entry.get("step", "N/A")
            status = entry.get("status", "N/A")
            status_emoji = {
                "success": "✅",
                "failed": "❌",
                "skipped": "⏭️",
                "pending": "⏳"
            }.get(status, "❓")
            print(f"   Step: {step} | Status: {status_emoji} {status}")
        
        elif event == "task_complete":
            status = entry.get("status", "N/A")
            status_emoji = {
                "completed": "✅",
                "failed": "❌",
                "in_progress": "🔄"
            }.get(status, "❓")
            print(f"   Status: {status_emoji} {status}")
            if entry.get("result", {}).get("error"):
                print(f"   Error: {entry['result']['error']}")
    
    print("\n" + "="*80)
    print(f"Total entries shown: {len(entries)}")


def view_repo_logs(repo_name=None, limit=20):
    """View repository operation logs"""
    log_file = Path("logs/repo_operations.jsonl")
    
    if not log_file.exists():
        print("❌ No repo operation logs found")
        return
    
    print("\n" + "="*80)
    print("📁 REPOSITORY OPERATION LOGS")
    print("="*80)
    
    entries = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if repo_name and entry.get("repo_name") != repo_name:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    
    entries = entries[-limit:] if len(entries) > limit else entries
    
    for entry in entries:
        timestamp = entry.get("timestamp", "N/A")
        operation = entry.get("operation", "unknown")
        repo = entry.get("repo_name", "N/A")
        details = entry.get("details", {})
        
        print(f"\n⏰ {timestamp}")
        print(f"   Operation: {operation}")
        print(f"   Repo: {repo}")
        print(f"   Details: {json.dumps(details, indent=6)}")
    
    print("\n" + "="*80)
    print(f"Total entries shown: {len(entries)}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View Code Atlas logs")
    parser.add_argument("--type", choices=["tasks", "repos", "all"], default="all")
    parser.add_argument("--task-id", help="Filter by task ID")
    parser.add_argument("--repo", help="Filter by repo name")
    parser.add_argument("--limit", type=int, default=20, help="Number of entries to show")
    
    args = parser.parse_args()
    
    if args.type in ("tasks", "all"):
        view_task_logs(args.task_id, args.repo, args.limit)
    
    if args.type in ("repos", "all"):
        view_repo_logs(args.repo, args.limit)
