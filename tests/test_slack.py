#!/usr/bin/env python3
"""
Test Slack notification
"""

import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notifications.slack import SlackNotifier

def test_notification():
    """Test Slack notification"""
    print("🧪 Testing Slack Notification...")
    print("")

    # Get webhook URL from environment or config
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")

    if not webhook_url:
        pytest.skip(
            "SLACK_WEBHOOK_URL not set — export it or set slack.webhook_url in notifications_config.json"
        )
    
    print(f"Webhook URL: {webhook_url[:50]}...")
    print("")
    
    notifier = SlackNotifier(webhook_url)
    
    # Test message
    print("Sending test notification...")
    success = notifier.send_task_notification(
        "test_task",
        "example-service",
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

    assert success, "Slack webhook send failed"

if __name__ == "__main__":
    test_notification()
