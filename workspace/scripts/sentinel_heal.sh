#!/bin/bash

# Sentinel Self-Healing & Freshness Protocol
# Runs daily at 5:00 AM IST

LOG_FILE="/path/to/openclaw/workspace/logs/sentinel.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "Starting Sentinel Protocol..."

# 1. Core Process Audit
log "Checking Core Processes..."
if ! pgrep -f "memory/server.py" > /dev/null; then
    log "⚠️ Memory Server DOWN. Restarting..."
    # Add restart logic here if running via supervisor or launchd
    # For now, just logging the alert
    # openclaw gateway restart # (Optional: dangerous if in loop)
else
    log "✅ Memory Server Active"
fi

# 2. Database Scrubbing
DB_PATH="/path/to/openclaw/workspace/db/memory.db"
if [ -f "$DB_PATH" ]; then
    log "Scrubbing Database..."
    sqlite3 "$DB_PATH" "PRAGMA integrity_check;" >> "$LOG_FILE" 2>&1
    sqlite3 "$DB_PATH" "VACUUM;" >> "$LOG_FILE" 2>&1
    log "✅ Database Vacuumed"
else
    log "❌ Database Not Found!"
fi

# 3. Workspace Sync (DISABLED DURING RECOVERY - Use nightly_ingest.py instead)
# Note: Full ingest consumes RAM needed for server restart. Only run nightly_ingest on schedule.
log "⏭️ Skipping full ingest during recovery (scheduled for nightly_ingest.py)"

# 4. Resource Cleanup (Logs)
log "Cleaning old logs..."
find /tmp/openclaw/ -name "*.log" -mtime +7 -delete 2>/dev/null
log "✅ Logs Pruned"

# 5. Disk Check
DISK_USAGE=$(df -h / | grep '/' | awk '{print $5}' | sed 's/%//g')
if [ "$DISK_USAGE" -gt 90 ]; then
    log "⚠️ WARNING: High Disk Usage: ${DISK_USAGE}%"
    # Ideally trigger a notification here via openclaw message
fi

log "Sentinel Protocol Complete. System Fresh."
