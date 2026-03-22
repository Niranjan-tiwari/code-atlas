"""
Direct WhatsApp notification using web.whatsapp.com or API
Simplest implementation for immediate use
"""

import os
import requests
import logging
from datetime import datetime
from typing import Dict, Optional


class WhatsAppNotifier:
    """
    Direct WhatsApp notification sender
    Uses various free/paid WhatsApp API services
    """
    
    def __init__(self, phone_number: str = ""):
        self.phone_number = phone_number.replace('+', '').replace(' ', '').replace('-', '')
        self.logger = logging.getLogger("whatsapp_direct")
    
    def send_via_callmebot(self, message: str) -> bool:
        """
        Send via CallMeBot (Free WhatsApp API)
        https://www.callmebot.com/blog/free-api-whatsapp-messages/
        """
        # Format: https://api.callmebot.com/whatsapp.php?phone=PHONE&text=MESSAGE&apikey=APIKEY
        api_key = os.getenv("CALLMEBOT_API_KEY", "")
        
        if not api_key:
            self.logger.warning("CallMeBot API key not set. Set CALLMEBOT_API_KEY env var")
            return False
        
        url = "https://api.callmebot.com/whatsapp.php"
        params = {
            "phone": f"+{self.phone_number}",
            "text": message,
            "apikey": api_key
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if "success" in response.text.lower() or response.status_code == 200:
                self.logger.info(f"WhatsApp notification sent via CallMeBot to {self.phone_number}")
                return True
        except Exception as e:
            self.logger.error(f"CallMeBot error: {e}")
        
        return False
    
    def send_via_whatsapp_webhook(self, message: str, webhook_url: str) -> bool:
        """Send via custom webhook URL"""
        payload = {
            "phone": self.phone_number,
            "message": message
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            return response.status_code in [200, 201]
        except Exception as e:
            self.logger.error(f"Webhook error: {e}")
            return False
    
    def send_task_notification(self, task_id: str, repo_name: str, branch_name: str,
                              status: str, details: Optional[Dict] = None) -> bool:
        """Send formatted task notification"""
        emoji_map = {
            "completed": "✅",
            "failed": "❌",
            "in_progress": "🔄"
        }
        emoji = emoji_map.get(status, "📋")
        
        message = f"""{emoji} Task Completed

Task ID: {task_id}
Repository: {repo_name}
Branch: {branch_name}
Status: {status}
"""
        
        # Add task description if available
        if details and details.get("task_description"):
            message += f"\nTask Description: {details['task_description']}\n"
        
        # Add committer info if available
        if details and details.get("committer"):
            committer = details["committer"]
            committer_display = committer.get("display", committer.get("name", "Unknown"))
            message += f"\nCommitter: {committer_display}\n"
        
        message += f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if details:
            if details.get("steps"):
                message += "\nSteps:\n"
                for step in details["steps"]:
                    step_name = step.get("step", "unknown")
                    step_status = step.get("status", "unknown")
                    step_emoji = "✅" if step_status == "success" else "❌" if step_status == "failed" else "⏭️"
                    message += f"{step_emoji} {step_name}: {step_status}\n"
            
            if details.get("error"):
                message += f"\nError: {details['error']}\n"
        
        # Try CallMeBot first
        if self.send_via_callmebot(message):
            return True
        
        # Try webhook if configured
        webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL", "")
        if webhook_url:
            return self.send_via_whatsapp_webhook(message, webhook_url)
        
        self.logger.warning("No WhatsApp API configured. Set CALLMEBOT_API_KEY or WHATSAPP_WEBHOOK_URL")
        return False
