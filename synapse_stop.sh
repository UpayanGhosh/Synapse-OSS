#!/bin/bash
echo "Stopping Synapse..."

pkill -f "uvicorn" 2>/dev/null
pkill -f "ollama serve" 2>/dev/null

sleep 2

echo "Remaining:"
pgrep -fl "uvicorn|ollama" 2>/dev/null | grep -v "vscode\|isort" || echo "(clean)"
