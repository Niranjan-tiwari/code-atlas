"""
Slack notification module
Sends notifications via Slack webhook
"""

import os
import json
import logging
import requests
from typing import Dict, Optional
from datetime import datetime


class SlackNotifier:
    """Send Slack notifications via webhook"""
    
    def __init__(self, webhook_url: Optional[str] = None):
        """
        Initialize Slack notifier
        
        Args:
            webhook_url: Slack webhook URL (or read from env/config)
        """
        self.logger = logging.getLogger("slack_notifier")
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.enabled = bool(self.webhook_url)
        
        if not self.webhook_url:
            self.logger.debug("Slack webhook URL not configured")
    
    def send_message(self, text: str, blocks: Optional[list] = None, 
                    username: str = "Repo Worker", 
                    icon_emoji: str = ":robot_face:") -> bool:
        """
        Send message to Slack
        
        Args:
            text: Plain text message (fallback)
            blocks: Slack block kit format (optional, for rich formatting)
            username: Bot username
            icon_emoji: Bot icon emoji
        """
        if not self.enabled:
            self.logger.debug("Slack notifications disabled")
            return False
        
        # Check if this is a Slack Workflow trigger (has /triggers/ in URL)
        is_workflow_trigger = "/triggers/" in self.webhook_url
        
        if is_workflow_trigger:
            # Slack Workflow triggers use a simpler format
            # Build a formatted text message with all details
            payload = {
                "text": text
            }
        else:
            # Standard incoming webhook format
            payload = {
                "text": text,
                "username": username,
                "icon_emoji": icon_emoji
            }
            
            if blocks:
                payload["blocks"] = blocks
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info("Slack notification sent successfully")
                return True
            else:
                self.logger.error(f"Failed to send Slack notification: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {e}")
            return False
    
    def send_task_notification(self, task_id: str, repo_name: str, branch_name: str,
                              status: str, details: Optional[Dict] = None) -> bool:
        """Send formatted task completion notification"""
        
        # Status emoji and color
        status_config = {
            "completed": {"emoji": "✅", "color": "good"},
            "failed": {"emoji": "❌", "color": "danger"},
            "in_progress": {"emoji": "🔄", "color": "warning"}
        }
        
        config = status_config.get(status, {"emoji": "📋", "color": "#36a64f"})
        
        # Build concise text message (works for both webhooks and workflow triggers)
        text = f"""{config['emoji']} *Task {status.title()}*

*Repo:* {repo_name} | *Branch:* {branch_name}
*Task:* {task_id}
"""
        
        # Add commit message if available
        commit_message = ""
        if details and details.get("steps"):
            commit_step = next((s for s in details["steps"] if s.get("step") == "commit" and s.get("commit_message")), None)
            if commit_step:
                commit_message = commit_step.get("commit_message", "")
        
        if commit_message:
            text += f"*Commit:* `{commit_message}`\n"
        
        # Add committer info if available
        if details and details.get("committer"):
            committer = details["committer"]
            committer_name = committer.get("name", "Unknown")
            text += f"*By:* {committer_name}\n"
        
        # Add steps (simplified - skip delete_branch, combine similar steps)
        if details and details.get("steps"):
            steps_text = ""
            for step in details["steps"]:
                step_name = step.get("step", "unknown")
                step_status = step.get("status", "unknown")
                
                # Skip delete_branch step
                if step_name == "delete_branch":
                    continue
                
                # Simplify step names
                if step_name == "create_branch":
                    step_display = "Branch created"
                elif step_name == "apply_code_changes":
                    step_display = "Changes applied"
                elif step_name == "commit":
                    step_display = "Committed"
                elif step_name == "push":
                    step_display = "Pushed"
                else:
                    step_display = step_name.replace("_", " ").title()
                
                step_emoji = "✅" if step_status == "success" else "❌" if step_status == "failed" else "⏭️"
                steps_text += f"{step_emoji} {step_display}\n"
            
            if steps_text:
                text += f"\n{steps_text}"
        
        # Add error if available
        if details and details.get("error"):
            text += f"\n*Error:* {details['error']}\n"
        
        text += f"\n_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
        
        # Build rich blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{config['emoji']} Task {status.title()}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Task ID:*\n`{task_id}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Repository:*\n`{repo_name}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Branch:*\n`{branch_name}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Status:*\n{config['emoji']} {status}"
                    }
                ]
            }
        ]
        
        # Add task description if available
        if details and details.get("task_description"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Task Description:*\n{details['task_description']}"
                }
            })
        
        # Add committer info if available
        if details and details.get("committer"):
            committer = details["committer"]
            committer_display = committer.get("display", committer.get("name", "Unknown"))
            blocks.append({
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Committer:*\n{committer_display}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Time:*\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                ]
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            })
        
        # Add steps if available
        if details and details.get("steps"):
            steps_text = "*Steps:*\n"
            for step in details["steps"]:
                step_name = step.get("step", "unknown")
                step_status = step.get("status", "unknown")
                step_emoji = "✅" if step_status == "success" else "❌" if step_status == "failed" else "⏭️"
                steps_text += f"{step_emoji} *{step_name}*: {step_status}\n"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": steps_text
                }
            })
        
        # Add error if available
        if details and details.get("error"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:*\n```{details['error']}```"
                }
            })
        
        # Add divider
        blocks.append({"type": "divider"})
        
        # Add footer with timestamp
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Code Atlas | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            ]
        })
        
        return self.send_message(text, blocks)
    
    def send_simple_notification(self, message: str) -> bool:
        """Send a simple text notification"""
        return self.send_message(message)


# Global notifier instance
_notifier: Optional[SlackNotifier] = None


def get_slack_notifier(webhook_url: Optional[str] = None) -> SlackNotifier:
    """Get or create global Slack notifier instance"""
    global _notifier
    
    # Try to load from config if webhook_url not provided
    if webhook_url is None:
        try:
            from pathlib import Path
            config_file = Path("config/notifications_config.json")
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    slack_config = config.get("slack", {})
                    if slack_config.get("enabled") and slack_config.get("webhook_url"):
                        webhook_url = slack_config["webhook_url"]
        except Exception:
            pass
    
    # Fallback to environment variable
    if not webhook_url:
        webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    
    if _notifier is None:
        _notifier = SlackNotifier(webhook_url)
    elif webhook_url and webhook_url != _notifier.webhook_url:
        # Update if webhook URL changed
        _notifier = SlackNotifier(webhook_url)
    
    return _notifier


def send_slack_notification(webhook_url: str, message: str) -> bool:
    """Quick function to send Slack notification"""
    notifier = SlackNotifier(webhook_url)
    return notifier.send_message(message)
