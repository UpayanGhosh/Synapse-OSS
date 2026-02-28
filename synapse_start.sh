#!/bin/bash
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "[INFO] Starting Synapse services..."
echo ""

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

mkdir -p "$HOME/.openclaw/logs"

echo "[1/4] Starting Qdrant..."
docker start antigravity_qdrant 2>/dev/null && echo "   [OK] Started" || echo "   [OK] Already running or not found"

echo "[2/4] Starting Ollama..."
if command -v ollama > /dev/null 2>&1; then
    if ! pgrep -f "ollama serve" > /dev/null; then
        export OLLAMA_KEEP_ALIVE=0
        export OLLAMA_MAX_LOADED_MODELS=1
        export OLLAMA_NUM_PARALLEL=1
        nohup ollama serve > ~/.openclaw/logs/ollama.log 2>&1 &
        echo "   [OK] Started"
    else
        echo "   [OK] Already running"
    fi
else
    echo "   [--] Ollama not installed -- local embedding and The Vault will be disabled"
fi

echo "[3/4] Starting API Gateway..."
if ! pgrep -f "uvicorn.*api_gateway" > /dev/null; then
    source "$project_root/.venv/bin/activate" 2>/dev/null || true
    nohup python -X utf8 -m uvicorn --app-dir "$project_root/workspace" \
        sci_fi_dashboard.api_gateway:app \
        --host 0.0.0.0 --port 8000 \
        --workers 1 \
        > ~/.openclaw/logs/gateway.log 2>&1 &
    echo "   [OK] Started"
else
    echo "   [OK] Already running"
fi

echo "[4/4] Starting OpenClaw Gateway..."
if ! pgrep -f "openclaw.*gateway" > /dev/null; then
    nohup openclaw gateway > ~/.openclaw/logs/openclaw_gateway.log 2>&1 &
    echo "   [OK] Started"
else
    echo "   [OK] Already running"
fi

echo ""
echo "[OK] Synapse is starting up. It may take a moment."
echo "You can now message Synapse on WhatsApp."
