#!/bin/bash
#
# OpenClaw Manager - Handles start/stop for launchd
# Works with OrbStack (lighter than Docker)
#

LOG="$HOME/.openclaw/manager.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

start_services() {
    log "Starting OpenClaw services..."
    
    # Activate venv and set env
    export PATH="$HOME/.openclaw/.venv/bin:$PATH"
    export OLLAMA_KEEP_ALIVE=0
    export OLLAMA_MAX_LOADED_MODELS=1
    export OLLAMA_NUM_PARALLEL=1
    
    cd "$HOME/.openclaw/workspace"
    
    # Start Qdrant via OrbStack (if container exists and OrbStack is running)
    if command -v orbctl &> /dev/null; then
        if orbctl list containers 2>/dev/null | grep -q antigravity_qdrant; then
            orbctl start antigravity_qdrant 2>/dev/null
            log "Qdrant (OrbStack) started"
        else
            # Fallback to docker if OrbStack container not found
            docker start antigravity_qdrant 2>/dev/null
        fi
    else
        # Try docker (Docker Desktop fallback)
        docker start antigravity_qdrant 2>/dev/null
    fi
    
    # Start Ollama (check if already running)
    if ! pgrep -f "ollama serve" >/dev/null; then
        nohup ollama serve >> "$HOME/.openclaw/logs/ollama.log" 2>&1 &
        log "Ollama started"
    fi
    
    # Start Gateway (check if already running)
    if ! pgrep -f "uvicorn.*api_gateway" >/dev/null; then
        nohup uvicorn sci_fi_dashboard.api_gateway:app \
            --host 0.0.0.0 --port 8000 \
            --workers 1 \
            >> "$HOME/.openclaw/logs/gateway.log" 2>&1 &
        log "Gateway started"
    fi

    # Start WhatsApp Bridge (openclaw gateway)
    if ! pgrep -f "openclaw-gateway" >/dev/null; then
        nohup openclaw gateway >> "$HOME/.openclaw/logs/node_gateway.log" 2>&1 &
        log "WhatsApp bridge started"
    fi
    
    log "Start complete"
}

stop_services() {
    log "Stopping OpenClaw services..."
    
    pkill -f "uvicorn.*api_gateway" 2>/dev/null
    pkill -f "ollama serve" 2>/dev/null
    pkill -f "openclaw-gateway" 2>/dev/null
    
    # Stop Qdrant (try both OrbStack and docker)
    if command -v orbctl &> /dev/null; then
        orbctl stop antigravity_qdrant 2>/dev/null
    fi
    docker stop antigravity_qdrant 2>/dev/null
    
    log "Stop complete"
}

case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        sleep 2
        start_services
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac
