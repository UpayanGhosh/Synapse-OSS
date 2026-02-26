#!/bin/bash
echo "Stopping Jarvis v3..."
pkill -f "uvicorn" 2>/dev/null
pkill -f "ollama serve" 2>/dev/null
sleep 2
echo "Remaining:"
pgrep -fl "uvicorn|ollama" | grep -v "vscode\|isort" || echo "(clean)"
sysctl vm.swapusage
