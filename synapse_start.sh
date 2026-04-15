#!/bin/bash
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Add Homebrew paths so tools installed via brew are found (macOS)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

echo "[INFO] Starting Synapse services..."
echo ""

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

LOG_DIR="${SYNAPSE_HOME:-$HOME/.synapse}/logs"
mkdir -p "$LOG_DIR"

if grep -q '"ollama"' ~/.synapse/synapse.json 2>/dev/null; then
    echo "[1/2] Starting Ollama..."
    if command -v ollama > /dev/null 2>&1; then
        if ! pgrep -f "ollama serve" > /dev/null; then
            export OLLAMA_KEEP_ALIVE=0
            export OLLAMA_MAX_LOADED_MODELS=1
            export OLLAMA_NUM_PARALLEL=1
            nohup ollama serve > $LOG_DIR/ollama.log 2>&1 &
            echo "   [OK] Started"
        else
            echo "   [OK] Already running"
        fi
    else
        echo "   [--] Ollama not installed -- local embedding and The Vault will be disabled"
    fi
else
    echo "[1/2] Ollama: skipped (not configured — optional)"
fi

echo "[2/2] Starting API Gateway..."
if ! pgrep -f "uvicorn.*api_gateway" > /dev/null; then
    source "$project_root/.venv/bin/activate" 2>/dev/null || true
    nohup python -X utf8 -m uvicorn --app-dir "$project_root/workspace" \
        sci_fi_dashboard.api_gateway:app \
        --host 0.0.0.0 --port 8000 \
        --workers 1 \
        > $LOG_DIR/gateway.log 2>&1 &
    echo "   [OK] Started"
else
    echo "   [OK] Already running"
fi

echo ""
echo "[OK] Synapse is starting up. It may take a moment."
echo "You can now message Synapse on WhatsApp."
