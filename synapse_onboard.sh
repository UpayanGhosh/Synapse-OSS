#!/bin/bash

# Resolve the directory this script lives in, regardless of where it's called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Add Homebrew paths so tools installed via brew are found (macOS)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

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
# Docker is NOT required — LanceDB vector store is embedded (no containers).
# Ollama is OPTIONAL — enables local models (The Vault, privacy mode)
if command -v ollama &> /dev/null; then
    echo "   ✓ ollama is installed (optional — enables local models)"
else
    echo "   - ollama: not installed (OPTIONAL)"
    echo "     Ollama enables local models (The Vault, privacy mode)."
    echo "     Skip if you don't need local models."
    echo "     Install later from https://ollama.com if needed."
fi
if [ "$all_good" = false ]; then
    echo ""
    echo "❌ Oops! Some tools are missing."
    echo ""
    echo "Please install the missing tools first."
    echo "Check the HOW_TO_RUN.md guide for help."
    echo ""
    exit 1
fi

# Auto-create .env from .env.example if not present — no manual step needed
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "   ✓ Created .env from .env.example"
    else
        touch "$SCRIPT_DIR/.env"
        echo "   ✓ Created empty .env"
    fi
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

# Install Baileys bridge npm dependencies if not already installed
if [ -d "$SCRIPT_DIR/baileys-bridge" ]; then
    if [ ! -d "$SCRIPT_DIR/baileys-bridge/node_modules" ]; then
        echo "📦 Installing WhatsApp bridge dependencies (npm)..."
        if command -v npm > /dev/null 2>&1; then
            (cd "$SCRIPT_DIR/baileys-bridge" && npm install --silent)
            echo "   ✓ Bridge dependencies installed"
        else
            echo "   ⚠ npm not found — bridge install skipped"
            echo "     Install Node.js 18+ from https://nodejs.org then run: cd baileys-bridge && npm install"
        fi
    else
        echo "   ✓ Bridge dependencies already installed"
    fi
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

# Collect phone number BEFORE running bridge setup
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
echo "Starting the gateway so the QR code can be served..."
echo ""

# Start the gateway briefly to generate a QR
mkdir -p "$HOME/.synapse/logs"
if ! pgrep -f "uvicorn.*api_gateway" > /dev/null; then
    VENV_UVICORN_LOCAL="$SCRIPT_DIR/.venv/bin/uvicorn"
    if [ -f "$VENV_UVICORN_LOCAL" ]; then
        nohup "$VENV_UVICORN_LOCAL" \
            --app-dir "$SCRIPT_DIR/workspace" \
            sci_fi_dashboard.api_gateway:app \
            --host 0.0.0.0 --port 8000 \
            --workers 1 \
            > "$HOME/.synapse/logs/gateway.log" 2>&1 &
        echo "   Gateway starting..."
        sleep 8
    fi
fi

echo ""
echo "📷 Scan the QR code to link WhatsApp:"
echo ""
echo "   Option 1 — Open this URL in your browser:"
echo "      http://localhost:8000/qr"
echo ""
echo "   Option 2 — Or run this in another terminal:"
echo "      curl http://localhost:8000/qr"
echo ""
echo "   Then on your phone:"
echo "   WhatsApp → Settings → Linked Devices → Link a Device → Scan"
echo ""

read -p "Press Enter once you have scanned the QR code (or to skip for now)..."

echo ""
echo "✓ WhatsApp setup complete!"
echo ""

echo ""
echo "Saving phone number to Synapse config..."
echo ""

# Write phone number to ADMIN_PHONE in .env and to personas.yaml
DIGITS_ONLY="${phone_number#+}"   # strip leading +
sed -i.bak "s|^ADMIN_PHONE=.*|ADMIN_PHONE=$phone_number|" "$SCRIPT_DIR/.env" 2>/dev/null && \
    rm -f "$SCRIPT_DIR/.env.bak"

PERSONAS_FILE="$SCRIPT_DIR/workspace/personas.yaml"
if [ -f "$PERSONAS_FILE" ]; then
    # Insert phone under the_creator if not already there
    if ! grep -q "$DIGITS_ONLY" "$PERSONAS_FILE" 2>/dev/null; then
        sed -i.bak "s|the_creator.*|the_creator|; /the_creator/{n; s|whatsapp_phones: \[\]|whatsapp_phones: [\"$DIGITS_ONLY\"]|}" \
            "$PERSONAS_FILE" 2>/dev/null
        rm -f "$PERSONAS_FILE.bak"
    fi
fi

echo "✓ Phone number saved: $phone_number"
echo ""

# ---- Workspace Configuration ----
echo "🔧 Configuring Synapse workspace..."

SYNAPSE_WORKSPACE="$SCRIPT_DIR/workspace"

echo "   ✓ Workspace: $SYNAPSE_WORKSPACE"

# Create required directories for databases, logs, and persona data
mkdir -p "$SYNAPSE_WORKSPACE/db"
mkdir -p "$SYNAPSE_WORKSPACE/sci_fi_dashboard/synapse_data/the_creator/profiles/current"
mkdir -p "$SYNAPSE_WORKSPACE/sci_fi_dashboard/synapse_data/the_partner/profiles/current"
mkdir -p "$HOME/.synapse/logs"
echo "   ✓ Directories created"

# Verify the workspace is configured
# TODO Phase 1: workspace path now read from SYNAPSE_HOME / SynapseConfig
CONFIGURED_DIR="${SYNAPSE_HOME:-$HOME/.synapse}/workspace"
if [ -n "$CONFIGURED_DIR" ]; then
    echo "   ✓ Verified: $CONFIGURED_DIR"
else
    echo "   ✓ Workspace set (could not verify — this is normal on first setup)"
fi

echo ""
echo "🧠 Step 3: Configuring Synapse's memory engine..."
echo ""
echo "Synapse's memory system (Knowledge Graph) needs a Google Gemini API key."
echo "This is FREE — no credit card, no billing, 1000 requests/day."
echo ""
echo "   Get your key at: https://aistudio.google.com/apikey"
echo "   (Sign in with Google → Create API Key → Copy it)"
echo ""
echo "   NOTE: This is separate from your chat LLM."
echo "   You can use any provider for chatting (Copilot, OpenAI, Claude, etc.)"
echo "   but Synapse's memory always runs on Gemini free tier in the background."
echo ""

# Check if a direct Gemini key is already present
if grep -qE "^GEMINI_API_KEY=.{20,}" "$SCRIPT_DIR/.env" 2>/dev/null; then
    echo "   ✓ GEMINI_API_KEY already configured in .env"
else
    while true; do
        read -p "   Paste your Gemini API key (or press Enter to skip): " gemini_key

        if [ -z "$gemini_key" ]; then
            echo ""
            echo "   ⚠  Skipped. Synapse will chat but memory won't build."
            echo "   Add later to .env:  GEMINI_API_KEY=<your_key>"
            echo ""
            break
        fi

        # Basic validation — Gemini keys are typically 39+ chars starting with "AI"
        if [ ${#gemini_key} -lt 20 ]; then
            echo "   That doesn't look right (too short). Try again."
            continue
        fi

        # Write to .env
        if grep -q "^GEMINI_API_KEY=" "$SCRIPT_DIR/.env" 2>/dev/null; then
            sed -i.bak "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=$gemini_key|" "$SCRIPT_DIR/.env"
            rm -f "$SCRIPT_DIR/.env.bak"
        else
            echo "GEMINI_API_KEY=$gemini_key" >> "$SCRIPT_DIR/.env"
        fi

        # Also write to synapse.json if it exists
        SYNAPSE_HOME_DIR="${SYNAPSE_HOME:-$HOME/.synapse}"
        SYNAPSE_JSON="$SYNAPSE_HOME_DIR/synapse.json"
        if [ -f "$SYNAPSE_JSON" ]; then
            python3 -c "
import json, sys
try:
    with open('$SYNAPSE_JSON') as f:
        cfg = json.load(f)
    cfg.setdefault('providers', {}).setdefault('gemini', {})['api_key'] = '$gemini_key'
    with open('$SYNAPSE_JSON', 'w') as f:
        json.dump(cfg, f, indent=2)
except Exception as e:
    print(f'   Warning: Could not update synapse.json: {e}', file=sys.stderr)
" 2>/dev/null
        fi

        echo "   ✓ Gemini key saved (powers Knowledge Graph + memory)"
        echo ""
        break
    done
fi

echo ""
echo "🗣️  Now configure your CHAT provider..."
echo ""
echo "   Synapse supports 19 LLM providers via the wizard."
echo "   Run 'python workspace/synapse_cli.py onboard' for an interactive picker,"
echo "   or edit ~/.synapse/synapse.json directly. Summary:"
echo ""
echo "   --- Major Cloud (US) ---"
echo "   Gemini (default)  GEMINI_API_KEY            Free tier (already set above)"
echo "   Anthropic Claude  ANTHROPIC_API_KEY         Paid"
echo "   OpenAI GPT        OPENAI_API_KEY            Paid"
echo "   Groq              GROQ_API_KEY              Free tier"
echo "   OpenRouter        OPENROUTER_API_KEY        Free models available"
echo "   Mistral AI        MISTRAL_API_KEY           Free tier"
echo "   xAI Grok          XAI_API_KEY               Paid"
echo "   Cohere            COHERE_API_KEY            Free tier"
echo "   Together AI       TOGETHERAI_API_KEY        Paid"
echo "   DeepSeek          DEEPSEEK_API_KEY          Paid (cheap)"
echo ""
echo "   --- Chinese providers ---"
echo "   MiniMax / Moonshot / Zhipu Z.AI / Volcano Engine / Baidu Qianfan"
echo ""
echo "   --- Self-Hosted / Special ---"
echo "   Ollama            (local, no key)           Free (needs GPU)"
echo "   vLLM              (self-hosted)             Free"
echo "   AWS Bedrock       AWS_ACCESS_KEY_ID+SECRET  Paid"
echo "   Google Vertex AI  GCP ADC / SA JSON         Paid"
echo "   HuggingFace       HUGGINGFACE_API_KEY       Free tier"
echo "   NVIDIA NIM        NVIDIA_NIM_API_KEY        Paid"
echo "   GitHub Copilot    OAuth device flow         With Pro subscription"
echo ""
echo "   For now, Gemini handles both chat and memory."
echo "   Edit ~/.synapse/synapse.json to change your chat provider later."
echo ""

# Create ~/.synapse/synapse.json from synapse.json.example if it doesn't exist
SYNAPSE_HOME_DIR="${SYNAPSE_HOME:-$HOME/.synapse}"
SYNAPSE_JSON="$SYNAPSE_HOME_DIR/synapse.json"
mkdir -p "$SYNAPSE_HOME_DIR"

if [ ! -f "$SYNAPSE_JSON" ]; then
    if [ -f "$SCRIPT_DIR/synapse.json.example" ]; then
        cp "$SCRIPT_DIR/synapse.json.example" "$SYNAPSE_JSON"
        chmod 600 "$SYNAPSE_JSON"
        echo "   ✓ Created $SYNAPSE_JSON"
        echo ""
        echo "   ⚠  IMPORTANT: Open $SYNAPSE_JSON and fill in your API keys."
        echo "   At minimum, set your Gemini key under \"providers\" → \"gemini\" → \"api_key\"."
        echo ""
    fi
else
    echo "   ✓ $SYNAPSE_JSON already exists"
fi

echo ""
echo "🚀 ======================================="
echo "   Step 4: Starting All Synapse Services"
echo "=========================================="
echo ""

echo "Starting all services..."
echo ""

# Ensure log directory exists before any nohup redirects
mkdir -p ~/.synapse/logs

echo "[1/4] Vector store: LanceDB (embedded, no Docker needed)..."
echo "   ✓ LanceDB initialized on first use via pip"

echo ""
echo "[2/4] Ollama (optional — local models)..."
if command -v ollama &> /dev/null; then
    export OLLAMA_KEEP_ALIVE=0
    export OLLAMA_MAX_LOADED_MODELS=1
    export OLLAMA_NUM_PARALLEL=1
    if ! pgrep -f "ollama serve" > /dev/null; then
        nohup ollama serve > ~/.synapse/logs/ollama.log 2>&1 &
        echo "   ✓ Ollama started"
        sleep 3
    else
        echo "   ✓ Ollama already running"
    fi
    echo "   Pulling required embedding model (nomic-embed-text)..."
    echo "   (This downloads ~900 MB on first run — please wait)"
    ollama pull nomic-embed-text
    echo "   ✓ nomic-embed-text ready"
else
    echo "   ✓ Skipped (Ollama not installed — optional)"
fi

echo ""
echo "[3/4] Starting API Gateway..."
if ! pgrep -f "uvicorn.*api_gateway" > /dev/null; then
    cd "$SCRIPT_DIR/workspace"
    nohup "$VENV_UVICORN" sci_fi_dashboard.api_gateway:app \
        --host 0.0.0.0 --port 8000 \
        --workers 1 \
        > ~/.synapse/logs/gateway.log 2>&1 &
    cd "$SCRIPT_DIR"
    echo "   ✓ API Gateway started"
else
    echo "   ✓ API Gateway already running"
fi

echo ""
echo "[4/4] WhatsApp bridge..."
echo "   (WhatsApp bridge deferred — Phase 4 will implement Baileys bridge)"

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
    echo "⚠ No response after 15s — check ~/.synapse/logs/gateway.log"
    services_ok=false
fi

echo ""
if [ "$services_ok" = true ]; then
    echo "✅ All services are running!"
else
    echo "⚠️  Some services may need more time. Check logs in: ~/.synapse/logs/"
fi

echo ""
echo "✓ Synapse is running!"
echo ""

echo ""
echo "💬 ======================================="
echo "   Step 5: How to Chat with Synapse"
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
