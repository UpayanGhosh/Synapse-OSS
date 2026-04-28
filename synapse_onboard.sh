#!/bin/bash

# Synapse Onboard Script for macOS / Linux
# Run this ONCE on first setup. For daily use, run ./synapse_start.sh instead.
#
# This script is a thin bootstrap launcher:
#   1. Checks prerequisites (Python 3 required; Ollama optional — for local models only)
#   2. Creates .venv and installs dependencies
#   3. Installs Baileys bridge npm deps + Playwright Chromium
#   4. Hands off to the Python wizard (workspace/synapse_cli.py onboard) which supports
#      19 LLM providers incl. Gemini / Anthropic / OpenAI / Groq / OpenRouter /
#      Mistral / xAI / Cohere / DeepSeek / Together AI, Chinese providers
#      (MiniMax / Moonshot / Z.AI / Volcengine / Qianfan), self-hosted
#      (Ollama / vLLM), and special providers (AWS Bedrock, Google Vertex AI,
#      NVIDIA NIM, HuggingFace, GitHub Copilot OAuth).
#   5. The wizard prefetches the embedding model (FastEmbed) and, if Ollama is
#      selected, also pulls nomic-embed-text for offline fallback.
#   6. Starts all services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add Homebrew paths so tools installed via brew are found (macOS)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

echo ""
echo "======================================="
echo "   Synapse Onboard"
echo "======================================="
echo ""
echo "This runs once to configure Synapse."
echo "For daily use, run ./synapse_start.sh instead."
echo ""
read -p "Press Enter to continue..."

# ============================================================
# Step 1: Check prerequisites
# ============================================================
echo ""
echo "Step 1: Checking prerequisites..."
echo ""

MISSING=""

if command -v python3 > /dev/null 2>&1; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
    echo "   [OK] Python $PY_VER"
else
    echo "   [X] Python 3 not found. Install from https://python.org"
    MISSING=1
fi

if command -v node > /dev/null 2>&1; then
    NODE_VER=$(node --version 2>&1)
    echo "   [OK] Node.js $NODE_VER (required for WhatsApp Baileys bridge)"
else
    echo "   [X] Node.js not found. Install 18+ from https://nodejs.org"
    MISSING=1
fi

# Docker is NOT required — LanceDB vector store is embedded (no containers).

# Ollama is OPTIONAL — enables local models (The Vault, privacy mode)
if command -v ollama > /dev/null 2>&1; then
    echo "   [OK] Ollama (optional — enables local models)"
else
    echo "   [--] Ollama: not installed (OPTIONAL)"
    echo "        Ollama enables local models (The Vault, privacy mode)."
    echo "        Skip if you don't need local models."
    echo "        Install later from https://ollama.com if needed."
fi

if [ -n "$MISSING" ]; then
    echo ""
    echo "ERROR: Install the missing tools above and run this script again."
    echo ""
    exit 1
fi

# ============================================================
# Step 2: Create .env from example if missing
# ============================================================
echo ""
echo "Step 2: Checking .env..."
echo ""

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "   [OK] Created .env from .env.example"
    else
        touch "$SCRIPT_DIR/.env"
        echo "   [OK] Created empty .env"
    fi
else
    echo "   [OK] .env already exists"
fi

# ============================================================
# Step 3: Python virtual environment + dependencies
# ============================================================
echo ""
echo "Step 3: Setting up Python environment..."
echo ""

if [ ! -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    echo "   Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    echo "   [OK] Virtual environment created."
fi

VENV_PIP="$SCRIPT_DIR/.venv/bin/pip"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

echo "   Installing core dependencies (this takes a minute on first run)..."
"$VENV_PIP" install -r "$SCRIPT_DIR/requirements.txt" -q
echo "   [OK] Core dependencies installed."

echo "   Installing Synapse CLI..."
"$VENV_PIP" install -e "$SCRIPT_DIR" -q
echo "   [OK] Synapse CLI installed."

if [ -f "$SCRIPT_DIR/requirements-channels.txt" ]; then
    echo "   Installing channel dependencies..."
    "$VENV_PIP" install -r "$SCRIPT_DIR/requirements-channels.txt" -q || \
        echo "   [--] Channel dependencies failed (non-fatal)."
fi

echo "   Installing Playwright browser (Chromium)..."
"$VENV_PYTHON" -m playwright install chromium > /dev/null 2>&1 || \
    echo "   [--] Playwright install failed — /browse tool will not work."
echo "   [OK] Playwright ready."

# ============================================================
# Step 4: Baileys WhatsApp bridge (Node.js subprocess)
# ============================================================
if [ -d "$SCRIPT_DIR/baileys-bridge" ]; then
    echo ""
    echo "Step 4: Installing WhatsApp bridge dependencies (npm)..."
    if [ ! -d "$SCRIPT_DIR/baileys-bridge/node_modules" ]; then
        (cd "$SCRIPT_DIR/baileys-bridge" && npm install --silent)
        echo "   [OK] Bridge dependencies installed."
    else
        echo "   [OK] Bridge dependencies already installed."
    fi
fi

# ============================================================
# Step 5: Python wizard — provider + channel + persona setup
# ============================================================
echo ""
echo "Step 5: Running Synapse setup wizard..."
echo ""
echo "The wizard will ask which LLM provider(s) you want to use."
echo "Supported: Gemini, Anthropic, OpenAI, Groq, OpenRouter, Mistral, xAI,"
echo "  Cohere, Together AI, DeepSeek, MiniMax, Moonshot, Z.AI, Volcengine,"
echo "  Qianfan, Ollama, vLLM, AWS Bedrock, Google Vertex AI, NVIDIA NIM,"
echo "  HuggingFace, and GitHub Copilot (OAuth device flow)."
echo ""
read -p "Press Enter to launch the wizard..."

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

"$VENV_PYTHON" -X utf8 "$SCRIPT_DIR/workspace/synapse_cli.py" onboard
WIZARD_EXIT=$?

if [ "$WIZARD_EXIT" != "0" ]; then
    echo ""
    echo "[X] Wizard exited with an error (code: $WIZARD_EXIT)."
    echo "Fix the issue and run this script again."
    echo ""
    exit 1
fi

echo "   [OK] Wizard completed successfully."

# ============================================================
# Step 6: Start all services
# ============================================================
echo ""
echo "Step 6: Starting services..."
echo ""

bash "$SCRIPT_DIR/synapse_start.sh"

# ============================================================
# Done
# ============================================================
# Note: Embedding model (FastEmbed nomic-embed-text-v1.5) is prefetched
# by the Python wizard in Step 5. No separate download needed here.

echo ""
echo "========================================"
echo "[OK] Onboarding complete"
echo "========================================"
echo ""
echo "Next time, just run ./synapse_start.sh"
echo ""
