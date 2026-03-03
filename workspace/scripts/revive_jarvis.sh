#!/bin/bash
#
# DEPRECATED — V2-only script, not applicable to Synapse-OSS
# ============================================================
# This script was written for the private Jarvis V2 deployment and
# references the openclaw binary and ~/.openclaw/ paths which do not
# exist in Synapse-OSS. It is kept for historical reference only.
# Synapse-OSS users should use synapse_start.sh instead.
#

# One-Click Jarvis Revival Script
# Run after reboot to bring everything back online.

echo "🦞 Awakening Jarvis..."

# 1. Start Ollama (Required for Memory/Embeddings)
if ! pgrep -x "ollama" > /dev/null; then
    echo "🧠 Starting Ollama..."
    open -a Ollama
    sleep 5
else
    echo "✅ Ollama is running."
fi

# 2. Check Redis (Required for Celery Worker)
if ! pgrep -x "redis-server" > /dev/null; then
    echo "🔴 Redis not found! Please ensure Redis is running (brew services start redis)."
    # Optional: Try to start if brew is available
    # brew services start redis
fi

# 3. Start OpenClaw Gateway (The Brain)
echo "🌐 Starting OpenClaw Gateway..."
# Using the standard CLI command which handles daemonizing
openclaw gateway start

# 4. Start Memory Server (The Soul)
echo "👻 Starting Memory Server (Soul)..."
# Check if already running
if ! pgrep -f "memory/server.py" > /dev/null; then
    OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
    cd "$OPENCLAW_HOME/workspace"
    nohup "$OPENCLAW_HOME/.venv/bin/python3" db/server.py > "$OPENCLAW_HOME/server.log" 2>&1 &
    echo "✅ Memory Server launched (PID: $!)"
else
    echo "✅ Memory Server already running."
fi

# 5. Start Worker (The Hands - Celery)
echo "✋ Starting Worker (Hands)..."
if ! pgrep -f "celery worker" > /dev/null; then
    OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
    cd "$OPENCLAW_HOME/workspace"
    nohup "$OPENCLAW_HOME/.venv/bin/celery" -A db.worker worker --loglevel=info > "$OPENCLAW_HOME/worker.log" 2>&1 &
    echo "✅ Worker launched (PID: $!)"
else
    echo "✅ Worker already running."
fi

# 6. Prevent System Sleep (Caffeine)
echo "☕ Injecting Caffeine..."
if ! pgrep -x "caffeinate" > /dev/null; then
    caffeinate -u -t 86400 &
    echo "✅ Sleep prevention active for 24h."
else
    echo "✅ Caffeine already active."
fi

echo "🚀 Jarvis is Online! Ping me on WhatsApp."
