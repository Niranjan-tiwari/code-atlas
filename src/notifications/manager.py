"""
Notification Manager - Unified interface for all notification services
"""

import logging
from typing import Dict, Optional
from .whatsapp import WhatsAppNotifier
from .slack import SlackNotifier


class NotificationManager:
    """Manages all notification services"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize notification manager
        
        Args:
            config: Notification configuration dict
        """
        self.logger = logging.getLogger("notification_manager")
        self.config = config or {}
        
        # Initialize WhatsApp notifier
        self.whatsapp = WhatsAppNotifier()
        
        # Initialize Slack notifier
        slack_config = self.config.get("slack", {})
        slack_webhook = slack_config.get("webhook_url") if slack_config.get("enabled") else None
        self.slack = SlackNotifier(slack_webhook)
    
    def send_task_notification(self, task_id: str, repo_name: str, branch_name: str,
                              status: str, details: Optional[Dict] = None) -> Dict[str, bool]:
        """
        Send task notification with fallback mechanism
        If Slack fails, try WhatsApp. If WhatsApp fails, try Slack again.
        
        Returns:
            Dict with service names as keys and success status as values
        """
        results = {}
        
        # Try Slack first
        slack_success = False
        try:
            slack_success = self.slack.send_task_notification(
                task_id, repo_name, branch_name, status, details
            )
            results['slack'] = slack_success
        except Exception as e:
            self.logger.warning(f"Failed to send Slack notification: {e}")
            results['slack'] = False
        
        # If Slack failed, try WhatsApp as fallback
        if not slack_success:
            try:
                whatsapp_success = self.whatsapp.send_task_notification(
                    task_id, repo_name, branch_name, status, details
                )
                results['whatsapp'] = whatsapp_success
                if whatsapp_success:
                    self.logger.info("WhatsApp notification sent as fallback (Slack failed)")
            except Exception as e:
                self.logger.warning(f"Failed to send WhatsApp notification: {e}")
                results['whatsapp'] = False
        else:
            # Slack succeeded, also try WhatsApp if enabled
            try:
                results['whatsapp'] = self.whatsapp.send_task_notification(
                    task_id, repo_name, branch_name, status, details
                )
            except Exception as e:
                self.logger.debug(f"WhatsApp notification skipped: {e}")
                results['whatsapp'] = False
        
        # If both failed, log warning
        if not results.get('slack') and not results.get('whatsapp'):
            self.logger.error("All notification methods failed - no notifications sent")
        
        return results


# Global manager instance
_manager: Optional[NotificationManager] = None


def get_notification_manager(config: Optional[Dict] = None) -> NotificationManager:
    """Get or create global notification manager"""
    global _manager
    if _manager is None:
        _manager = NotificationManager(config)
    return _manager
