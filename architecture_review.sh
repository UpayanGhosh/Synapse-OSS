#!/bin/bash
#
# OpenClaw Architecture Review Script
# Run this and paste the output for full system analysis
#

OUTPUT="$HOME/openclaw_architecture_review.txt"
cd "$HOME/.openclaw"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║           OPENCLAW ARCHITECTURE REVIEW                            ║"
echo "╚══════════════════════════════════════════════════════════════════════╝" | tee "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: SYSTEM RESOURCES
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 1: SYSTEM RESOURCES" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Hardware ---" | tee -a "$OUTPUT"
sysctl hw.ncpu | tee -a "$OUTPUT"
sysctl hw.memsize | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Memory ---" | tee -a "$OUTPUT"
memory_pressure | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"
sysctl vm.swapusage | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Battery ---" | tee -a "$OUTPUT"
pmset -g batt | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Running Processes ---" | tee -a "$OUTPUT"
ps aux --sort=-%mem | head -20 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: PROJECT STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 2: PROJECT STRUCTURE" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Directory Tree (top 3 levels) ---" | tee -a "$OUTPUT"
find . -maxdepth 3 -not -path './.venv/*' -not -path './.git/*' -not -path './node_modules/*' -not -path '*/__pycache__/*' -not -name '*.pyc' -not -name '*.log' -not -name '*.db' | head -100 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Database Files ---" | tee -a "$OUTPUT"
find . -name "*.db" -o -name "*.sqlite" 2>/dev/null | grep -v ".venv" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Configuration Files ---" | tee -a "$OUTPUT"
find . -maxdepth 3 \( -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.env*" -o -name "config*" \) 2>/dev/null | grep -v ".venv" | grep -v "node_modules" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: PYTHON CODEBASE
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 3: PYTHON CODEBASE" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- All Python Files ---" | tee -a "$OUTPUT"
find . -name "*.py" -not -path './.venv/*' -not -path '*/__pycache__/*' 2>/dev/null | sort | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Python Dependencies ---" | tee -a "$OUTPUT"
if [ -f "requirements.txt" ]; then
    cat requirements.txt | tee -a "$OUTPUT"
else
    pip freeze 2>/dev/null | tee -a "$OUTPUT"
fi
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 4: API ENDPOINTS" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Gateway Endpoints (from code) ---" | tee -a "$OUTPUT"
grep -rn "@app\.\|@router\." workspace/sci_fi_dashboard/*.py 2>/dev/null | grep -v ".venv" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Memory Server Endpoints (from code) ---" | tee -a "$OUTPUT"
grep -rn "@app\.\|@router\." workspace/db/*.py 2>/dev/null | grep -v ".venv" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: DATABASE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 5: DATABASE SCHEMAS" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- memory.db ---" | tee -a "$OUTPUT"
sqlite3 workspace/db/memory.db ".tables" 2>/dev/null | tee -a "$OUTPUT"
for table in $(sqlite3 workspace/db/memory.db ".tables" 2>/dev/null); do
    echo "--- $table ---" | tee -a "$OUTPUT"
    sqlite3 workspace/db/memory.db "PRAGMA table_info($table)" 2>/dev/null | tee -a "$OUTPUT"
    COUNT=$(sqlite3 workspace/db/memory.db "SELECT COUNT(*) FROM $table" 2>/dev/null)
    echo "Rows: $COUNT" | tee -a "$OUTPUT"
    echo "" | tee -a "$OUTPUT"
done

echo "--- knowledge_graph.db ---" | tee -a "$OUTPUT"
sqlite3 workspace/db/knowledge_graph.db ".tables" 2>/dev/null | tee -a "$OUTPUT"
for table in $(sqlite3 workspace/db/knowledge_graph.db ".tables" 2>/dev/null); do
    echo "--- $table ---" | tee -a "$OUTPUT"
    sqlite3 workspace/db/knowledge_graph.db "PRAGMA table_info($table)" 2>/dev/null | tee -a "$OUTPUT"
    COUNT=$(sqlite3 workspace/db/knowledge_graph.db "SELECT COUNT(*) FROM $table" 2>/dev/null)
    echo "Rows: $COUNT" | tee -a "$OUTPUT"
    echo "" | tee -a "$OUTPUT"
done

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: SERVICE CONNECTIVITY
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 6: SERVICE CONNECTIVITY" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Service Health Checks ---" | tee -a "$OUTPUT"
echo "Gateway (8000):" | tee -a "$OUTPUT"
curl -sf http://localhost:8000/health 2>/dev/null | head -20 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "Memory Server (8989):" | tee -a "$OUTPUT"
curl -sf http://localhost:8989/health 2>/dev/null | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "Qdrant (6333):" | tee -a "$OUTPUT"
curl -sf http://localhost:6333/collections 2>/dev/null | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "Ollama (11434):" | tee -a "$OUTPUT"
curl -sf http://localhost:11434/api/tags 2>/dev/null | head -20 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 7: ENVIRONMENT VARIABLES" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- .env file (redacted) ---" | tee -a "$OUTPUT"
if [ -f "workspace/.env" ]; then
    cat workspace/.env | sed 's/=.*/=REDACTED/' | tee -a "$OUTPUT"
else
    echo "No .env found" | tee -a "$OUTPUT"
fi
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8: CONTAINER STATUS
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 8: CONTAINER STATUS (OrbStack/Docker)" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- OrbStack Containers ---" | tee -a "$OUTPUT"
orbctl list containers 2>/dev/null | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Docker Containers ---" | tee -a "$OUTPUT"
docker ps -a 2>/dev/null | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9: AUTOSTART CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 9: AUTOSTART CONFIGURATION" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- LaunchAgents ---" | tee -a "$OUTPUT"
ls -la ~/Library/LaunchAgents/com.openclaw* 2>/dev/null | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- LaunchAgent Status ---" | tee -a "$OUTPUT"
launchctl list | grep openclaw | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10: KEY CODE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 10: KEY CODE ANALYSIS" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Gateway Imports ---" | tee -a "$OUTPUT"
head -50 workspace/sci_fi_dashboard/api_gateway.py | grep "^import\|^from" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Gateway Class Init ---" | tee -a "$OUTPUT"
grep -n "brain =\|gate =\|toxic_scorer =\|memory_engine =" workspace/sci_fi_dashboard/api_gateway.py | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- External API Calls (localhost) ---" | tee -a "$OUTPUT"
grep -rn "localhost:\|127.0.0.1:" workspace/sci_fi_dashboard/*.py 2>/dev/null | grep -v ".venv" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- LLM Configuration ---" | tee -a "$OUTPUT"
grep -rn "MODEL_\|llm\.\|model_id\|model =" workspace/sci_fi_dashboard/*.py 2>/dev/null | grep -v ".venv" | head -20 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11: NETWORK CONNECTIONS
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "SECTION 11: NETWORK CONNECTIONS" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Listening Ports ---" | tee -a "$OUTPUT"
lsof -i -P -n | grep LISTEN | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

echo "--- Active Connections ---" | tee -a "$OUTPUT"
lsof -i -P -n | grep ESTABLISHED | head -20 | tee -a "$OUTPUT"
echo "" | tee -a "$OUTPUT"

# ═══════════════════════════════════════════════════════════════════════════
# END
# ═══════════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"
echo "REVIEW COMPLETE - Output saved to: $OUTPUT" | tee -a "$OUTPUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUTPUT"

echo ""
echo "✅ Review complete! Output saved to: $OUTPUT"
echo "📋 Please paste the contents of this file for analysis."
