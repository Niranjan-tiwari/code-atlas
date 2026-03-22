#!/usr/bin/env python3
"""
Test Slack notification
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notifications.slack import SlackNotifier

def test_notification():
    """Test Slack notification"""
    print("🧪 Testing Slack Notification...")
    print("")
    
    # Get webhook URL from environment or config
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    
    if not webhook_url:
        print("❌ SLACK_WEBHOOK_URL not set")
        print("")
        print("Please set it:")
        print("  export SLACK_WEBHOOK_URL='(paste URL from Slack Incoming Webhooks)'")
        print("")
        print("Or add it to config/notifications_config.json:")
        print('  "slack": {')
        print('    "enabled": true,')
        print('    "webhook_url": "(paste from Slack)"')
        print('  }')
        return False
    
    print(f"Webhook URL: {webhook_url[:50]}...")
    print("")
    
    notifier = SlackNotifier(webhook_url)
    
    # Test message
    print("Sending test notification...")
    success = notifier.send_task_notification(
        "test_task",
        "webhook-generation",
        "test_branch",
        "completed",
        {
            "steps": [
                {"step": "create_branch", "status": "success"},
                {"step": "apply_code_changes", "status": "success"},
                {"step": "commit", "status": "success"},
                {"step": "push", "status": "success"}
            ]
        }
    )
    
    if success:
        print("✅ Slack notification sent successfully!")
        print("Check your Slack channel!")
    else:
        print("❌ Failed to send Slack notification")
        print("Please check:")
        print("  1. Webhook URL is correct")
        print("  2. Webhook is active in Slack")
        print("  3. Internet connection is working")
    
    return success

if __name__ == "__main__":
    test_notification()
