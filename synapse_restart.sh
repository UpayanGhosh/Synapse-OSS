#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════╗"
echo "║  Synapse — Restart                   ║"
echo "╚══════════════════════════════════════╝"
echo ""

echo "Stopping services..."
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

echo ""
echo "Starting services..."
bash "$SCRIPT_DIR/synapse_start.sh"
