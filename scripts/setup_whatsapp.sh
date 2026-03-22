#!/bin/bash
# WhatsApp API Key Setup Script

echo "📱 WhatsApp Notification Setup"
echo "=============================="
echo ""

# Step 1: Instructions
echo "Step 1: Get your CallMeBot API Key"
echo "-----------------------------------"
echo "1. Open WhatsApp on your phone"
echo "2. Send this EXACT message to +34 603 21 25 47:"
echo ""
echo "   I allow callmebot to send me messages"
echo ""
echo "3. You'll receive a response with your API key"
echo ""
read -p "Press Enter when you have your API key..."

# Step 2: Get API key
echo ""
echo "Step 2: Enter your API key"
echo "--------------------------"
read -p "Enter your CallMeBot API key: " api_key

if [ -z "$api_key" ]; then
    echo "❌ API key cannot be empty"
    exit 1
fi

# Step 3: Set environment variable
echo ""
echo "Step 3: Setting up environment variable..."
export CALLMEBOT_API_KEY="$api_key"

# Add to .bashrc if not already there
if ! grep -q "CALLMEBOT_API_KEY" ~/.bashrc 2>/dev/null; then
    echo "" >> ~/.bashrc
    echo "# WhatsApp Notification API Key" >> ~/.bashrc
    echo "export CALLMEBOT_API_KEY=\"$api_key\"" >> ~/.bashrc
    echo "✅ Added to ~/.bashrc"
else
    echo "⚠️  CALLMEBOT_API_KEY already exists in ~/.bashrc"
    echo "   Please update it manually if needed"
fi

# Step 4: Test
echo ""
echo "Step 4: Testing WhatsApp notification..."
echo "------------------------------------------"

cd "$(dirname "$0")"
python3 test_whatsapp.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "Your WhatsApp notifications are now configured."
    echo "You'll receive notifications on the phone number in config after each task completion."
else
    echo ""
    echo "⚠️  Test failed. Please check:"
    echo "   1. Did you send the message to +34 603 21 25 47?"
    echo "   2. Did you receive an API key?"
    echo "   3. Is the API key correct?"
fi
