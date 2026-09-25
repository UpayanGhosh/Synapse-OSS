#!/bin/bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

sync_state="$project_root/.tmp/context-sync"
export UV_CACHE_DIR="$project_root/.tmp/uv-cache"
export UV_TOOL_DIR="$project_root/.tmp/uv-tools"
export UV_TOOL_BIN_DIR="$project_root/.tmp/uv-bin"
export HOME="$sync_state/home"
export LOCALAPPDATA="$sync_state/localappdata"
export MEMPALACE_CONFIG_DIR="$sync_state/mempalace/config"
export MEMPALACE_PALACE_PATH="$sync_state/mempalace/palace"
export TMPDIR="$sync_state/tmp"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
export PYTHONPYCACHEPREFIX="$sync_state/pycache"
mkdir -p "$UV_CACHE_DIR" "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" "$HOME" "$LOCALAPPDATA" "$MEMPALACE_CONFIG_DIR" "$TMPDIR" "$PYTHONPYCACHEPREFIX"

graph_tool="code-review-graph@2.3.9"
memory_tool="mempalace@3.10.0"
if [ ! -x "$UV_TOOL_BIN_DIR/code-review-graph" ] || [ ! -x "$UV_TOOL_BIN_DIR/mempalace" ]; then
  echo "[ERROR] Pinned local tools missing. Install once with:"
  echo "        UV_CACHE_DIR='$UV_CACHE_DIR' UV_TOOL_DIR='$UV_TOOL_DIR' UV_TOOL_BIN_DIR='$UV_TOOL_BIN_DIR' uv tool install code-review-graph==2.3.9"
  echo "        UV_CACHE_DIR='$UV_CACHE_DIR' UV_TOOL_DIR='$UV_TOOL_DIR' UV_TOOL_BIN_DIR='$UV_TOOL_BIN_DIR' uv tool install mempalace==3.10.0"
  exit 1
fi

echo "[1/4] Updating code-review-graph..."
uv tool run --offline "$graph_tool" update

echo "[2/4] Graph status..."
uv tool run --offline "$graph_tool" status

echo "[3/4] Change risk snapshot..."
uv tool run --offline "$graph_tool" detect-changes --base HEAD --brief

echo "[4/4] Mining MemPalace..."
if [ ! -d "$MEMPALACE_PALACE_PATH" ]; then
  uv tool run --offline "$memory_tool" init . --yes --no-llm
fi
if [ "${SYNAPSE_CONTEXT_FULL_MINE:-}" = "1" ]; then
  echo "[INFO] Full project mine requested."
  uv tool run --offline "$memory_tool" mine .
else
  if [ -d "$project_root/tasks" ]; then
    echo "[INFO] Mining tasks, up to 50 files..."
    uv tool run --offline "$memory_tool" mine "$project_root/tasks" --limit 50
  else
    echo "[INFO] Skipping missing tasks directory."
  fi
  if [ -d "$project_root/docs/audits" ]; then
    echo "[INFO] Mining docs/audits, up to 50 files..."
    uv tool run --offline "$memory_tool" mine "$project_root/docs/audits" --limit 50
  else
    echo "[INFO] Skipping missing docs/audits directory."
  fi
fi

echo "[OK] Context sync complete."
