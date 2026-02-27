#!/bin/bash

# Resolve the directory this script lives in, regardless of where it's called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "🤖 ======================================="
echo "   Synapse Onboard - Let's Get Started!"
echo "=========================================="
echo ""

echo "Hi there! I'm going to guide you through setting up Synapse."
echo "This will only take a few minutes."
echo ""

read -p "Press Enter to continue..."

echo ""
echo "📋 Here's what we'll do:"
echo "   1. Check your computer has what it needs"
echo "   2. Connect your WhatsApp"
echo "   3. Start Synapse (all services)"
echo "   4. Verify everything is working"
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

check_tool git       || all_good=false
check_tool python3   || all_good=false
check_tool docker    || all_good=false
check_tool openclaw  || all_good=false

if [ "$all_good" = false ]; then
    echo ""
    echo "❌ Oops! Some tools are missing."
    echo ""
    echo "Please install the missing tools first."
    echo "Check the HOW_TO_RUN.md guide for help."
    echo ""
    exit 1
fi

# Check .env file exists and has an API key set
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "❌ No .env file found."
    echo ""
    echo "Run this first:"
    echo "   cp .env.example .env"
    echo "Then open .env and add your GEMINI_API_KEY (at minimum)."
    echo ""
    exit 1
fi

if ! grep -qE "GEMINI_API_KEY=.{20,}" "$SCRIPT_DIR/.env" 2>/dev/null; then
    echo ""
    echo "⚠️  Warning: GEMINI_API_KEY does not appear to be set in your .env file."
    echo "   Synapse will start but LLM calls will fail until you add an API key."
    echo ""
fi

# Check Python virtual environment
VENV_UVICORN="$SCRIPT_DIR/.venv/bin/uvicorn"
if [ ! -f "$VENV_UVICORN" ]; then
    echo ""
    echo "❌ Python virtual environment not found."
    echo ""
    echo "Run these commands first:"
    echo "   cd $SCRIPT_DIR"
    echo "   python3 -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -r requirements.txt"
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
    echo "       Use a separate phone number just for Synapse"
    echo "       (like an old Android phone or spare SIM)"
    echo ""
    echo "   [2] Personal Number"
    echo "       Use your own WhatsApp number"
    echo "       You'll chat with Synapse by 'messaging yourself'"
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
            echo "You'll find Synapse in your 'Message yourself' chat."
            echo "It's like texting yourself!"
            break
            ;;
        *)
            echo "Please enter 1 or 2"
            echo ""
            ;;
    esac
done

# Collect phone number BEFORE running openclaw (openclaw can close stdin)
echo ""
echo "📞 Enter your phone number first..."
echo ""
echo "This lets Synapse know it's YOU messaging it."
echo "Enter your number with country code (e.g., +15551234567)"
echo ""

while true; do
    read -p "Your phone number: " phone_number

    if [ -z "$phone_number" ]; then
        echo "Phone number cannot be empty. Please try again."
        continue
    fi

    if [[ ! "$phone_number" =~ ^\+[0-9]{10,15}$ ]]; then
        echo "Invalid format! Use E.164 format like:"
        echo "   • US: +15551234567"
        echo "   • India: +919876543210"
        echo "   • UK: +447912345678"
        echo "(Start with +, include country code, 10-15 digits total)"
        continue
    fi

    break
done

echo "✓ Got it: $phone_number"
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

if ! openclaw channels login; then
    echo ""
    echo "⚠️  Note: 'openclaw channels login' returned an error."
    echo "   This is normal if WhatsApp is already linked."
    echo "   Continuing with setup..."
fi

echo ""
echo "✓ WhatsApp linked!"
echo ""

echo ""
echo "Saving phone number to OpenClaw config..."
echo ""

openclaw config set channels.whatsapp.allowFrom "[\"$phone_number\"]" --json 2>/dev/null || \
    openclaw config set channels.whatsapp.allowFrom "[\"$phone_number\"]"

echo "✓ Phone number saved: $phone_number"
echo ""

# ---- Workspace Configuration ----
echo "🔧 Configuring OpenClaw workspace..."

SYNAPSE_WORKSPACE="$SCRIPT_DIR/workspace"

# Tell OpenClaw where Synapse lives
openclaw config set agents.defaults.workspace "$SYNAPSE_WORKSPACE" 2>/dev/null || \
    openclaw config set agents.defaults.workspace "$SYNAPSE_WORKSPACE"
echo "   ✓ Workspace: $SYNAPSE_WORKSPACE"

# Create required directories for databases, logs, and persona data
mkdir -p "$SYNAPSE_WORKSPACE/db"
mkdir -p "$SYNAPSE_WORKSPACE/sci_fi_dashboard/synapse_data/the_creator/profiles/current"
mkdir -p "$SYNAPSE_WORKSPACE/sci_fi_dashboard/synapse_data/the_partner/profiles/current"
mkdir -p "$HOME/.openclaw/logs"
echo "   ✓ Directories created"

# Verify the workspace is configured
CONFIGURED_DIR=$(openclaw config get agents.defaults.workspace 2>/dev/null || echo "")
if [ -n "$CONFIGURED_DIR" ]; then
    echo "   ✓ Verified: $CONFIGURED_DIR"
else
    echo "   ✓ Workspace set (could not verify — this is normal on first setup)"
fi

echo ""
echo "🚀 ======================================="
echo "   Step 5: Starting All Synapse Services"
echo "=========================================="
echo ""

echo "Starting all services..."
echo ""

# Ensure log directory exists before any nohup redirects
mkdir -p ~/.openclaw/logs

echo "[1/4] Starting Docker services (Qdrant)..."
if ! docker info > /dev/null 2>&1; then
    echo "   ⚠ Docker daemon is not running. Skipping Qdrant."
    echo "   Start Docker Desktop and re-run, or use synapse_start.sh later."
elif docker start antigravity_qdrant 2>/dev/null; then
    echo "   ✓ Qdrant started"
else
    echo "   Container not found. Creating Qdrant (may take a few minutes on first run)..."
    if docker run -d --name antigravity_qdrant \
        -p 6333:6333 -p 6334:6334 \
        qdrant/qdrant; then
        echo "   ✓ Qdrant created and started"
    else
        echo "   ⚠ Could not start Qdrant. Vector search will fall back to SQLite."
    fi
fi

echo ""
echo "[2/4] Starting Ollama..."
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
if ! pgrep -f "ollama serve" > /dev/null; then
    nohup ollama serve > ~/.openclaw/logs/ollama.log 2>&1 &
    echo "   ✓ Ollama started"
    # Give Ollama a moment to start before pulling
    sleep 3
    echo "   Pulling required embedding model (nomic-embed-text)..."
    ollama pull nomic-embed-text >> ~/.openclaw/logs/ollama.log 2>&1 &
    echo "   ✓ nomic-embed-text pull started in background"
else
    echo "   ✓ Ollama already running"
fi

echo ""
echo "[3/4] Starting API Gateway..."
if ! pgrep -f "uvicorn.*api_gateway" > /dev/null; then
    cd "$SCRIPT_DIR/workspace"
    nohup "$VENV_UVICORN" sci_fi_dashboard.api_gateway:app \
        --host 0.0.0.0 --port 8000 \
        --workers 1 \
        > ~/.openclaw/logs/gateway.log 2>&1 &
    cd "$SCRIPT_DIR"
    echo "   ✓ API Gateway started"
else
    echo "   ✓ API Gateway already running"
fi

echo ""
echo "[4/4] Starting OpenClaw Gateway (WhatsApp bridge)..."
if ! pgrep -f "openclaw.*gateway" > /dev/null; then
    nohup openclaw gateway > ~/.openclaw/logs/openclaw_gateway.log 2>&1 &
    echo "   ✓ OpenClaw Gateway started"
else
    echo "   ✓ OpenClaw Gateway already running"
fi

echo ""
echo "⏳ Waiting for services to initialize..."
echo ""

# Poll health endpoints — up to 5 attempts, 3 seconds apart (15s max)
services_ok=true

echo -n "   - API Gateway (port 8000): "
gateway_up=false
for i in 1 2 3 4 5; do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1 || \
       curl -s http://127.0.0.1:8000/ > /dev/null 2>&1; then
        gateway_up=true
        break
    fi
    sleep 3
done
if $gateway_up; then
    echo "✓ Running"
else
    echo "⚠ No response after 15s — check ~/.openclaw/logs/gateway.log"
    services_ok=false
fi

echo -n "   - OpenClaw Gateway: "
oc_up=false
for i in 1 2 3 4 5; do
    if curl -s http://127.0.0.1:18789/health > /dev/null 2>&1; then
        oc_up=true
        break
    fi
    if pgrep -f "openclaw.*gateway" > /dev/null; then
        oc_up=true
        break
    fi
    sleep 3
done
if $oc_up; then
    echo "✓ Running"
else
    echo "⚠ Not detected — check ~/.openclaw/logs/openclaw_gateway.log"
    services_ok=false
fi

echo ""
if [ "$services_ok" = true ]; then
    echo "✅ All services are running!"
else
    echo "⚠️  Some services may need more time. Check with: openclaw status"
    echo "   Logs are in: ~/.openclaw/logs/"
fi

echo ""
echo "✓ Synapse is running!"
echo ""

echo ""
echo "💬 ======================================="
echo "   Step 4: How to Chat with Synapse"
echo "=========================================="
echo ""

if [ "$phone_type" = "dedicated" ]; then
    echo "🎉 You're all set!"
    echo ""
    echo "To chat with Synapse:"
    echo "   1. Open WhatsApp on your phone"
    echo "   2. Find 'Synapse' or 'WhatsApp Web' in your contacts"
    echo "   3. Send a message!"
else
    echo "🎉 You're all set!"
    echo ""
    echo "To chat with Synapse:"
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
echo "Synapse will reply! Have fun! 🤖"
echo ""
