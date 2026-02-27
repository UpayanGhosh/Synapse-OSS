OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
kill $(pgrep -f "db/server.py")
cd "$OPENCLAW_HOME/workspace"
nohup python db/server.py > ~/.openclaw/logs/memory.log 2>&1 &