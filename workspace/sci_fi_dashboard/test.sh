kill $(pgrep -f "db/server.py")
cd /path/to/openclaw/workspace
nohup python db/server.py > ~/.openclaw/logs/memory.log 2>&1 &