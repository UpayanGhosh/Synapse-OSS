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

echo "[1/3] Starting Qdrant..."
if ! docker info > /dev/null 2>&1; then
    echo "   [--] Docker not running — skipping Qdrant (vector search disabled)"
elif docker start antigravity_qdrant > /dev/null 2>&1; then
    echo "   [OK] Started"
else
    echo "   Container not found. Creating Qdrant..."
    if docker run -d --name antigravity_qdrant \
        -p 6333:6333 -p 6334:6334 \
        qdrant/qdrant > /dev/null 2>&1; then
        echo "   [OK] Created and started"
    else
        echo "   [--] Could not start Qdrant — vector search will fall back to SQLite"
    fi
fi

echo "[2/3] Starting Ollama..."
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

echo "[3/3] Starting API Gateway..."
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
