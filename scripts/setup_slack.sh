#!/bin/bash
# Slack Webhook Setup Script

echo "🔔 Slack Notification Setup"
echo "==========================="
echo ""

# Step 1: Instructions
echo "Step 1: Get your Slack Webhook URL"
echo "-----------------------------------"
echo "1. Go to: https://api.slack.com/apps"
echo "2. Create a new app (or use existing)"
echo "3. Enable 'Incoming Webhooks'"
echo "4. Add webhook to your workspace/channel"
echo "5. Copy the webhook URL"
echo ""
echo "Webhook URL: Slack app → Incoming Webhooks → copy URL (starts with https:// and contains /services/ or /triggers/)."
echo "Do not commit real webhook URLs to git."
echo ""
read -p "Press Enter when you have your webhook URL..."

# Step 2: Get webhook URL
echo ""
echo "Step 2: Enter your Slack Webhook URL"
echo "-------------------------------------"
read -p "Enter your Slack webhook URL: " webhook_url

if [ -z "$webhook_url" ]; then
    echo "❌ Webhook URL cannot be empty"
    exit 1
fi

# Validate URL format (incoming webhooks use hooks.slack.com)
if [[ ! "$webhook_url" =~ ^https://hooks\.slack\.com/ ]]; then
    echo "⚠️  Warning: host should be hooks.slack.com (from Slack Incoming Webhooks)"
    echo "   See: https://api.slack.com/messaging/webhooks"
    read -p "Continue anyway? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        exit 1
    fi
fi

# Step 3: Set environment variable
echo ""
echo "Step 3: Setting up environment variable..."
export SLACK_WEBHOOK_URL="$webhook_url"

# Add to .bashrc if not already there
if ! grep -q "SLACK_WEBHOOK_URL" ~/.bashrc 2>/dev/null; then
    echo "" >> ~/.bashrc
    echo "# Slack Notification Webhook" >> ~/.bashrc
    echo "export SLACK_WEBHOOK_URL=\"$webhook_url\"" >> ~/.bashrc
    echo "✅ Added to ~/.bashrc"
else
    echo "⚠️  SLACK_WEBHOOK_URL already exists in ~/.bashrc"
    echo "   Please update it manually if needed"
fi

# Step 4: Update config file
echo ""
echo "Step 4: Updating config file..."
config_file="config/notifications_config.json"
if [ -f "$config_file" ]; then
    # Use Python to update JSON (more reliable than sed)
    python3 << EOF
import json
import sys

try:
    with open('$config_file', 'r') as f:
        config = json.load(f)
    
    if 'slack' not in config:
        config['slack'] = {}
    
    config['slack']['enabled'] = True
    config['slack']['webhook_url'] = '$webhook_url'
    
    with open('$config_file', 'w') as f:
        json.dump(config, f, indent=2)
    
    print("✅ Updated config/notifications_config.json")
except Exception as e:
    print(f"⚠️  Could not update config file: {e}")
    print("   You can manually add it to config/notifications_config.json:")
    print('   "slack": {')
    print('     "enabled": true,')
    print(f'     "webhook_url": "$webhook_url"')
    print('   }')
EOF
else
    echo "⚠️  Config file not found: $config_file"
fi

# Step 5: Test
echo ""
echo "Step 5: Testing Slack notification..."
echo "--------------------------------------"

cd "$(dirname "$0")"
python3 test_slack.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "Your Slack notifications are now configured."
    echo "You'll receive notifications in your Slack channel after each task completion."
else
    echo ""
    echo "⚠️  Test failed. Please check:"
    echo "   1. Is the webhook URL correct?"
    echo "   2. Is the webhook active in Slack?"
    echo "   3. Do you have internet connection?"
    echo "   4. Check your Slack channel for the notification"
fi
