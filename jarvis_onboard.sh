#!/bin/bash

set -e

echo ""
echo "🤖 ======================================="
echo "   Jarvis Onboard - Let's Get Started!"
echo "=========================================="
echo ""

echo "Hi there! I'm going to guide you through setting up Jarvis."
echo "This will only take a few minutes."
echo ""

read -p "Press Enter to continue..."

echo ""
echo "📋 Here's what we'll do:"
echo "   1. Check your computer has what it needs"
echo "   2. Connect your WhatsApp"
echo "   3. Start Jarvis"
echo "   4. Show you how to chat with Jarvis"
echo ""

read -p "Press Enter to continue..."

echo ""
echo "🔍 Step 1: Checking your tools..."
echo ""

check_tool() {
    if command -v "$1" &> /dev/null; then
        echo "   ✓ $1 is installed"
        return 0
    else
        echo "   ✗ $1 is NOT installed"
        return 1
    fi
}

all_good=true

check_tool git || all_good=false
check_tool python3 || all_good=false
check_tool docker || all_good=false
check_tool openclaw || all_good=false

if [ "$all_good" = false ]; then
    echo ""
    echo "❌ Oops! Some tools are missing."
    echo ""
    echo "Please install the missing tools first."
    echo "Check the HOW_TO_RUN.md guide for help."
    echo ""
    exit 1
fi

echo ""
echo "✅ All tools are ready!"
echo ""

read -p "Press Enter to continue to WhatsApp setup..."

echo ""
echo "📱 ======================================="
echo "   Step 2: Connect Your WhatsApp"
echo "=========================================="
echo ""

echo "Here's an important question:"
echo ""

while true; do
    echo "Do you want to use:"
    echo ""
    echo "   [1] Dedicated Number (recommended)"
    echo "       Use a separate phone number just for Jarvis"
    echo "       (like an old Android phone or spare SIM)"
    echo ""
    echo "   [2] Personal Number"
    echo "       Use your own WhatsApp number"
    echo "       You'll chat with Jarvis by 'messaging yourself'"
    echo ""
    read -p "Enter 1 or 2: " choice

    case $choice in
        1)
            phone_type="dedicated"
            echo ""
            echo "✓ Great choice!"
            echo ""
            echo "With a dedicated number, your personal WhatsApp stays private."
            echo "Just use an old phone or spare SIM card."
            break
            ;;
        2)
            phone_type="personal"
            echo ""
            echo "✓ No problem!"
            echo ""
            echo "You'll find Jarvis in your 'Message yourself' chat."
            echo "It's like texting yourself!"
            break
            ;;
        *)
            echo "Please enter 1 or 2"
            echo ""
            ;;
    esac
done

echo ""
echo "Now let's link your WhatsApp..."
echo ""
echo "⚠️  A QR code will appear on your screen!"
echo ""
echo "   1. Open WhatsApp on your phone"
echo "   2. Go to Settings → Linked Devices"
echo "   3. Tap 'Link a Device'"
echo "   4. Scan the QR code below"
echo ""

read -p "Press Enter to show the QR code..."

echo ""
echo "Scan the QR code now! I'll wait..."
echo ""

openclaw channels login

echo ""
echo "✓ WhatsApp linked!"
echo ""

read -p "Press Enter to continue..."

echo ""
echo "📞 Enter your phone number..."
echo ""
echo "This lets Jarvis know it's YOU messaging it."
echo "Enter your number with country code (e.g., +15551234567)"
echo ""

read -p "Your phone number: " phone_number

echo ""
echo "✓ Phone number saved: $phone_number"
echo ""

echo ""
echo "🚀 ======================================="
echo "   Step 3: Start Jarvis"
echo "=========================================="
echo ""

echo "Starting Jarvis now..."
echo ""

openclaw gateway &

sleep 5

echo ""
echo "✓ Jarvis is running!"
echo ""

echo ""
echo "💬 ======================================="
echo "   Step 4: How to Chat with Jarvis"
echo "=========================================="
echo ""

if [ "$phone_type" = "dedicated" ]; then
    echo "🎉 You're all set!"
    echo ""
    echo "To chat with Jarvis:"
    echo "   1. Open WhatsApp on your phone"
    echo "   2. Find 'Jarvis' or 'WhatsApp Web' in your contacts"
    echo "   3. Send a message!"
else
    echo "🎉 You're all set!"
    echo ""
    echo "To chat with Jarvis:"
    echo "   1. Open WhatsApp on your phone"
    echo "   2. Go to your chat list"
    echo "   3. Tap on 'Message yourself' (your name at the top)"
    echo "   4. Send a message to yourself!"
    echo ""
    echo "   Don't see 'Message yourself'?"
    echo "   - Tap the pencil icon in your chat list"
    echo "   - Your name should be at the top"
fi

echo ""
echo "=========================================="
echo "   🎉 You're Ready!"
echo "=========================================="
echo ""
echo "Try sending:"
echo "   • 'Hello'"
echo "   • 'What's the weather?'"
echo "   • 'Tell me a joke'"
echo ""
echo "Jarvis will reply! Have fun! 🤖"
echo ""
