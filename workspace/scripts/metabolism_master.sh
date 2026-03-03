#!/bin/bash
#
# DEPRECATED — V2-only script, not applicable to Synapse-OSS
# ============================================================
# This script was written for the private Jarvis V2 deployment and
# references the openclaw binary and ~/.openclaw/ paths which do not
# exist in Synapse-OSS. It is kept for historical reference only.
# Synapse-OSS users should use synapse_start.sh instead.
#

# Metabolism Master Script (v1.0)
# Handles 3 AM routine with notifications and busy state.

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
VENV_PYTHON="$OPENCLAW_HOME/.venv/bin/python"
WORKSPACE="$OPENCLAW_HOME/workspace"
CLI=$(command -v openclaw 2>/dev/null || echo "openclaw")
USER1="${ADMIN_PHONE}"
USER2="${VIP_PHONE}"

notify() {
    $CLI message send --target "$USER1" --message "$1"
    $CLI message send --target "$USER2" --message "$1"
}

set_busy() {
    sqlite3 "$WORKSPACE/db/memory.db" "INSERT OR REPLACE INTO system_state (key, value) VALUES ('maintenance', '$1');"
}

# 1. Start Notification
notify "🌙 Nightly metabolism starting. I'll be offline for routine maintenance (Ingestion + Backups). See you in ~45 mins! 🦞💤"
set_busy "busy"

# 2. Step 1: Nightly Distillation (LLM extraction + Graph)
echo "Starting Nightly Ingest..."
$VENV_PYTHON "$WORKSPACE/scripts/nightly_ingest.py" >> "$WORKSPACE/logs/nightly_ingest.log" 2>&1

# 3. Step 2: Raw File Ingestion
echo "Starting File Ingest..."
$VENV_PYTHON "$WORKSPACE/db/ingest.py" >> "$WORKSPACE/logs/ingest.log" 2>&1

# 4. Step 3: Backups
echo "Starting Backup..."
bash "$WORKSPACE/db/backup_db.sh" >> "$WORKSPACE/logs/backup.log" 2>&1

# 5. Finish Notification
set_busy "idle"
notify "✅ Metabolism complete. Brain is refreshed, data is backed up, and I'm officially back online! 🦞🧠"

echo "Done."
