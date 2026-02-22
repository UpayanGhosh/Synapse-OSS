#!/bin/bash
#
# Sleep/Wake Watcher for OpenClaw
# Monitors system power events and restarts services on wake
#

LOG="$HOME/.openclaw/wake.log"
LAST_WAKE=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

# Monitor for wake events using pmset -g assertions
# This runs continuously but uses minimal CPU

while true; do
    # Check if system just woke up (power assertion changed)
    CURRENT_WAKE=$(date +%s)
    
    # Use pmset to detect wake
    SLEEP_STATUS=$(pmset -g assertions | grep "No assertions" | wc -l)
    
    if [ "$SLEEP_STATUS" -eq 1 ]; then
        # System is awake - check if we need to restart services
        DIFF=$((CURRENT_WAKE - LAST_WAKE))
        
        # If it's been more than 60 seconds since last wake check, services might need restart
        if [ "$DIFF" -gt 60 ]; then
            # Check if gateway is responding
            if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
                log "Gateway not responding, restarting services..."
                "$HOME/.openclaw/jarvis_manager.sh" restart
                sleep 10
            fi
        fi
        LAST_WAKE=$CURRENT_WAKE
    fi
    
    sleep 30
done
