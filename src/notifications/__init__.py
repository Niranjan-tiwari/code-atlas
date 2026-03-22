"""
Notification modules for Code Atlas
Supports WhatsApp and Slack notifications
"""

from .manager import NotificationManager, get_notification_manager
from .whatsapp import WhatsAppNotifier
from .slack import SlackNotifier

__all__ = ['NotificationManager', 'get_notification_manager', 'WhatsAppNotifier', 'SlackNotifier']
