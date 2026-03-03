---
phase: 07-session-metrics-health-cleanup
plan: "03"
subsystem: shell-scripts-cleanup
tags: [cleanup, openclaw-removal, health-check, scripts]
dependency_graph:
  requires: []
  provides: [HLTH-02, HLTH-03]
  affects: [synapse_start.sh, synapse_start.bat, synapse_stop.bat, synapse_health.sh, workspace-python-files]
tech_stack:
  added: []
  patterns: [SYNAPSE_HOME-env-var, LOG_DIR-via-fallback]
key_files:
  created: []
  modified:
    - synapse_start.sh
    - synapse_start.bat
    - synapse_stop.bat
    - synapse_health.sh
    - workspace/sci_fi_dashboard/state.py
    - workspace/scripts/latency_watcher.py
    - workspace/scripts/transcribe_v2.py
    - workspace/change_tracker.py
    - workspace/synapse_config.py
decisions:
  - "LOG_DIR uses SYNAPSE_HOME env var with $HOME/.synapse fallback — consistent with SynapseConfig.resolve_data_root() precedence"
  - "synapse_start.sh drops to 3 services (Qdrant, Ollama, API Gateway) — openclaw gateway was the only 4th service and has no replacement"
  - ".openclawignore renamed to .synapsenotrack in change_tracker.py CATEGORY_MAP — matches the Synapse-OSS naming convention"
  - "synapse_config.py docstring updated to reflect completed migration: zero ~/.openclaw/ references remain in active code"
metrics:
  duration: 2 min
  completed_date: "2026-03-03"
  tasks_completed: 2
  files_modified: 9
---

# Phase 07 Plan 03: Script and Python File openclaw Cleanup Summary

**One-liner:** Removed all openclaw binary calls and ~/.openclaw/ log paths from four shell/batch scripts; upgraded synapse_health.sh to check /health JSON endpoint; cleaned commented openclaw stubs from five workspace Python files.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix synapse_start.sh, synapse_start.bat, synapse_stop.bat, synapse_health.sh | 21c0e4d | 4 scripts |
| 2 | Clean commented openclaw code from workspace Python files | b5ddfc0 | 5 Python files |

## What Was Built

### Task 1: Shell/Batch Script Cleanup (HLTH-02, HLTH-03)

**synapse_start.sh:**
- Replaced `mkdir -p "$HOME/.openclaw/logs"` with `LOG_DIR="${SYNAPSE_HOME:-$HOME/.synapse}/logs"` + `mkdir -p "$LOG_DIR"`
- Replaced all three `~/.openclaw/logs/` log path references with `$LOG_DIR/`
- Removed the entire `[4/4] Starting OpenClaw Gateway...` block (lines 44-50)
- Updated step numbering from `[1/4]`, `[2/4]`, `[3/4]`, `[4/4]` to `[1/3]`, `[2/3]`, `[3/3]`

**synapse_start.bat:**
- Replaced `mkdir "%USERPROFILE%\.openclaw\logs"` with `mkdir "%USERPROFILE%\.synapse\logs"`
- Replaced both `%USERPROFILE%\.openclaw\logs\gateway.log` references with `.synapse` paths
- Removed the entire `[4/4] OpenClaw Gateway` block (REM section + start command)
- Updated step numbering to `[1/3]`, `[2/3]`, `[3/3]`
- Updated final echo to reference `.synapse\logs\gateway.log`

**synapse_stop.bat:**
- Removed the `REM --- Stop OpenClaw Gateway (port 18789) ---` block (5 lines total)
- Only stops API Gateway (port 8000) and Ollama now

**synapse_health.sh (HLTH-02):**
- Replaced root `/` curl check with `curl -sf http://localhost:8000/health` check
- Added `[ -n "$HEALTH" ]` guard to verify non-empty JSON response
- Success message: `"✅ Gateway (8000) — /health OK"`

### Task 2: Python File Cleanup

**workspace/sci_fi_dashboard/state.py:**
- Removed 2 comment lines: `# TODO Phase 7: openclaw sessions list...` and `# sessions_raw = subprocess.run(["openclaw", ...])`
- Placeholder `sessions_data: list = []` retained (still needed until Phase 7 Plan 02 runs)

**workspace/scripts/latency_watcher.py:**
- Removed the 5-line commented-out `subprocess.Popen(["openclaw", "message", "send", ...])` block
- Retained the `# TODO Phase 4: replace with Synapse WhatsApp bridge (Baileys) send call` comment (no openclaw reference)

**workspace/scripts/transcribe_v2.py:**
- Removed `# TODO Phase 2: openclaw.json key lookup...` line and the entire 12-line commented block referencing `~/.openclaw/openclaw.json`

**workspace/change_tracker.py:**
- Renamed `.openclawignore` to `.synapsenotrack` in `CATEGORY_MAP["config"]` list

**workspace/synapse_config.py:**
- Updated module docstring: replaced "All 36 Python files that currently hardcode ~/.openclaw/ will import SynapseConfig" with "All Python files use ~/.synapse/ via SynapseConfig — zero ~/.openclaw/ references remain"

## Verification Results

All plan verification checks passed:

```
PASS: synapse_start.sh clean
PASS: synapse_start.bat clean
PASS: synapse_stop.bat clean
PASS: synapse_health.sh checks /health
PASS: workspace Python files cleaned
PASS: renamed to .synapsenotrack
```

Final openclaw scan: only `synapse_config.py` line 4 mentions `~/.openclaw/` — in the docstring explaining the migration is complete (intentional, excluded from check per plan).

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

Files verified:
- synapse_start.sh: FOUND (modified)
- synapse_start.bat: FOUND (modified)
- synapse_stop.bat: FOUND (modified)
- synapse_health.sh: FOUND (modified)
- workspace/sci_fi_dashboard/state.py: FOUND (modified)
- workspace/scripts/latency_watcher.py: FOUND (modified)
- workspace/scripts/transcribe_v2.py: FOUND (modified)
- workspace/change_tracker.py: FOUND (modified)
- workspace/synapse_config.py: FOUND (modified)

Commits verified:
- 21c0e4d: FOUND (Task 1 — script fixes)
- b5ddfc0: FOUND (Task 2 — Python cleanup)
