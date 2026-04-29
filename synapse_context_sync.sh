#!/bin/bash
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

echo "[1/4] Updating code-review-graph..."
uv tool run --offline code-review-graph update

echo "[2/4] Graph status..."
uv tool run --offline code-review-graph status

echo "[3/4] Change risk snapshot..."
uv tool run --offline code-review-graph detect-changes --base HEAD --brief

echo "[4/4] Mining MemPalace..."
if [ ! -f "$project_root/mempalace.yaml" ]; then
  mempalace init . --yes
fi
mempalace mine .

echo "[OK] Context sync complete."
