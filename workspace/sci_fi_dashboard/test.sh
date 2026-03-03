#!/bin/bash
#
# DEPRECATED — V1-only script, not applicable to Synapse-OSS
# ============================================================
# This script launches db/server.py from the ~/.openclaw/workspace path
# which does not exist in Synapse-OSS. It is kept for historical reference.
# Synapse-OSS users should use synapse_start.sh to start all services.
#
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
kill $(pgrep -f "db/server.py")
cd "$OPENCLAW_HOME/workspace"
nohup python db/server.py > ~/.openclaw/logs/memory.log 2>&1 &
