#!/bin/bash
echo "╔══════════════════════════════════════╗"
echo "║   OpenClaw v3.0 Health Check         ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "=== Processes ==="
PROCS=$(pgrep -fl "uvicorn|ollama" | grep -v "vscode\|isort" | wc -l)
echo "Running: $PROCS (expected: 2)"
pgrep -fl "uvicorn|ollama" | grep -v "vscode\|isort"
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
sysctl vm.swapusage
memory_pressure | grep "free percentage"
echo ""

echo "=== Services ==="
curl -sf http://localhost:8000/ > /dev/null && echo "✅ Gateway    (8000)" || echo "❌ Gateway DOWN"
curl -sf http://localhost:6333/collections > /dev/null && echo "✅ Qdrant     (6333)" || echo "❌ Qdrant DOWN"
curl -sf http://localhost:11434/api/tags > /dev/null && echo "✅ Ollama     (11434)" || echo "❌ Ollama DOWN"

# server.py should NOT be running
curl -sf http://localhost:8989/health > /dev/null && echo "⚠️  server.py  (8989) — should be OFF" || echo "✅ server.py  (eliminated)"
echo ""

SWAP_USED=$(sysctl vm.swapusage | grep -oE 'used = [0-9.]+' | grep -oE '[0-9.]+')
if (( $(echo "$SWAP_USED > 2000" | bc -l 2>/dev/null || echo 0) )); then
    echo "🔴 Swap high — consider reboot"
elif (( $(echo "$SWAP_USED > 500" | bc -l 2>/dev/null || echo 0) )); then
    echo "🟡 Swap moderate"
else
    echo "✅ Swap healthy"
fi
