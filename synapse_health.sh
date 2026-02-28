#!/bin/bash
echo "╔══════════════════════════════════════╗"
echo "║   Synapse Health Check               ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "=== Processes ==="
PROCS=$(pgrep -fl "uvicorn|ollama" 2>/dev/null | grep -v "vscode\|isort" | wc -l)
echo "Running: $PROCS (expected: 2)"
pgrep -fl "uvicorn|ollama" 2>/dev/null | grep -v "vscode\|isort"
echo ""

# Should be ZERO
for check in celery redis "db/server.py"; do
    COUNT=$(pgrep -fl "$check" 2>/dev/null | wc -l)
    if [ "$COUNT" -gt 0 ]; then
        echo "⚠️  $check still running ($COUNT processes)"
    else
        echo "✅ No $check (eliminated)"
    fi
done
echo ""

echo "=== Memory ==="
if [ "$(uname)" = "Darwin" ]; then
    sysctl vm.swapusage 2>/dev/null
    memory_pressure 2>/dev/null | grep "free percentage" || true
else
    # Linux: use free -h or /proc/meminfo
    free -h 2>/dev/null || grep -E "MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree" /proc/meminfo 2>/dev/null
fi
echo ""

echo "=== Services ==="
curl -sf http://localhost:8000/ > /dev/null && echo "✅ Gateway    (8000)" || echo "❌ Gateway DOWN"
curl -sf http://localhost:6333/collections > /dev/null && echo "✅ Qdrant     (6333)" || echo "❌ Qdrant DOWN"
curl -sf http://localhost:11434/api/tags > /dev/null && echo "✅ Ollama     (11434)" || echo "❌ Ollama DOWN (or not installed)"

# server.py should NOT be running
curl -sf http://localhost:8989/health > /dev/null && echo "⚠️  server.py  (8989) — should be OFF" || echo "✅ server.py  (eliminated)"
echo ""

# Swap health check (cross-platform)
if [ "$(uname)" = "Darwin" ]; then
    SWAP_USED=$(sysctl vm.swapusage 2>/dev/null | grep -oE 'used = [0-9.]+' | grep -oE '[0-9.]+')
    if [ -n "$SWAP_USED" ] && command -v bc > /dev/null 2>&1; then
        if (( $(echo "$SWAP_USED > 2000" | bc -l 2>/dev/null || echo 0) )); then
            echo "🔴 Swap high — consider reboot"
        elif (( $(echo "$SWAP_USED > 500" | bc -l 2>/dev/null || echo 0) )); then
            echo "🟡 Swap moderate"
        else
            echo "✅ Swap healthy"
        fi
    fi
else
    # Linux swap check via /proc/meminfo
    SWAP_FREE=$(grep SwapFree /proc/meminfo 2>/dev/null | awk '{print $2}')
    SWAP_TOTAL=$(grep SwapTotal /proc/meminfo 2>/dev/null | awk '{print $2}')
    if [ -n "$SWAP_TOTAL" ] && [ "$SWAP_TOTAL" -gt 0 ]; then
        SWAP_USED_KB=$((SWAP_TOTAL - SWAP_FREE))
        SWAP_USED_MB=$((SWAP_USED_KB / 1024))
        if [ "$SWAP_USED_MB" -gt 2000 ]; then
            echo "🔴 Swap high — consider reboot"
        elif [ "$SWAP_USED_MB" -gt 500 ]; then
            echo "🟡 Swap moderate"
        else
            echo "✅ Swap healthy"
        fi
    else
        echo "✅ No swap configured"
    fi
fi
