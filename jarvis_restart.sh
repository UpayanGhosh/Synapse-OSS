#!/bin/bash
set -e
cd /path/to/openclaw/workspace
source /path/to/openclaw/.venv/bin/activate
mkdir -p ~/.openclaw/logs

echo "╔══════════════════════════════════════╗"
echo "║  Jarvis v3.0 — Lean Architecture   ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Memory before:"
memory_pressure | grep "free percentage"
sysctl vm.swapusage
echo ""

# Qdrant (docker for now, native later)
docker start antigravity_qdrant 2>/dev/null && echo "[✓] Qdrant (docker)" || echo "[!] Qdrant not started"

# Ollama (zero persistence)
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
nohup ollama serve > ~/.openclaw/logs/ollama.log 2>&1 &
echo "[✓] Ollama (PID $!)"

# Single unified gateway (includes memory engine)
nohup uvicorn sci_fi_dashboard.api_gateway:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 \
    > ~/.openclaw/logs/gateway.log 2>&1 &
echo "[✓] Gateway + MemoryEngine (PID $!)"

# NOTE: server.py is NO LONGER NEEDED
# MemoryEngine runs inside the gateway process

sleep 5
echo ""
echo "Memory after:"
memory_pressure | grep "free percentage"
sysctl vm.swapusage
echo ""

echo "Processes:"
pgrep -fl "uvicorn|ollama|qdrant" | grep -v "vscode\|isort"
echo ""

PROCS=$(pgrep -fl "uvicorn|ollama" | grep -v "vscode\|isort" | wc -l)
echo "Python processes: $PROCS (target: 1 uvicorn + 1 ollama)"
echo "=== Running ==="
