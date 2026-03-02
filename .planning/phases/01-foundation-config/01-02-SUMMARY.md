---
phase: "01-foundation-config"
plan: "01-02"
subsystem: "database"
tags: ["config", "database", "path-resolution", "synapse-config"]
dependency_graph:
  requires: ["01-01"]
  provides: ["db-path-resolution", "memory-engine-config"]
  affects: ["db.py", "sqlite_graph.py", "emotional_trajectory.py", "memory_engine.py"]
tech_stack:
  added: []
  patterns: ["lazy-import for SynapseConfig to allow test monkeypatching", "deferred-path-resolution via _get_db_path() function"]
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/db.py
    - workspace/sci_fi_dashboard/sqlite_graph.py
    - workspace/sci_fi_dashboard/emotional_trajectory.py
    - workspace/sci_fi_dashboard/memory_engine.py
decisions:
  - "DB_PATH resolved at module load time (not import time) via _get_db_path() so SYNAPSE_HOME can be monkeypatched in tests before DB_PATH is evaluated"
  - "memory_engine.py top-level SynapseConfig import uses try/except with path insertion fallback to handle both package-style and direct invocation"
  - "WORKSPACE_ROOT retained in memory_engine.py — it is still used for sys.path management; only the DB_PATH line was replaced"
metrics:
  duration: "2 min"
  completed_date: "2026-03-02"
  tasks_completed: 2
  files_modified: 4
---

# Phase 1 Plan 02: Wire DB Modules to SynapseConfig Summary

**One-liner:** Replaced four `~/.openclaw` hardcoded paths with `SynapseConfig.load().db_dir` and `data_root` in all core database modules.

## What Was Changed

### Task 1: db.py, sqlite_graph.py, emotional_trajectory.py

**workspace/sci_fi_dashboard/db.py**
- Removed: `DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/memory.db")`
- Added: `_get_db_path()` function that imports `SynapseConfig` lazily (inside the function body) and returns `str(SynapseConfig.load().db_dir / "memory.db")`
- `DB_PATH = _get_db_path()` is evaluated at module load time
- Lazy import pattern preserves test monkeypatching: tests can set `SYNAPSE_HOME` before the module is imported

**workspace/sci_fi_dashboard/sqlite_graph.py**
- Removed: `DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/knowledge_graph.db")`
- Added: same `_get_db_path()` pattern returning `SynapseConfig.load().db_dir / "knowledge_graph.db"`

**workspace/sci_fi_dashboard/emotional_trajectory.py**
- Removed: `DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/emotional_trajectory.db")`
- Added: same `_get_db_path()` pattern returning `SynapseConfig.load().db_dir / "emotional_trajectory.db"`

### Task 2: memory_engine.py

**workspace/sci_fi_dashboard/memory_engine.py** had two issues:

**Issue 1 — Conflicting WORKSPACE_ROOT-relative DB_PATH:**
- Removed: `DB_PATH = os.path.join(WORKSPACE_ROOT, "db", "memory.db")`
- Added: same `_get_db_path()` pattern consistent with the other three files
- `WORKSPACE_ROOT` was preserved — it is still used for `sys.path.append()` calls

**Issue 2 — Hardcoded models cache dir:**
- Removed: `cache_dir=os.path.join(os.path.expanduser("~/.openclaw"), "models")`
- Added: `cache_dir=str(SynapseConfig.load().data_root / "models")`
- Added top-level `SynapseConfig` import with try/except fallback for path insertion:
  ```python
  try:
      from synapse_config import SynapseConfig
  except ImportError:
      import sys as _sys
      import os as _os
      _sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
      from synapse_config import SynapseConfig
  ```

## Verification Results

**Check 1 — Zero `.openclaw` references in all four files:**
```
$ grep -rn "openclaw" sci_fi_dashboard/db.py sci_fi_dashboard/sqlite_graph.py \
    sci_fi_dashboard/emotional_trajectory.py sci_fi_dashboard/memory_engine.py
(no output — zero matches)
```
Result: PASS

**Check 2 — SynapseConfig path resolution confirmed .synapse:**
```
$ python -c "from synapse_config import SynapseConfig; cfg = SynapseConfig.load(); print(cfg.db_dir)"
C:\Users\upayan.ghosh\.synapse\workspace\db
```
Result: PASS — paths correctly resolve to `.synapse`, not `.openclaw`

**Check 3 — Direct DB_PATH import:**
- `sqlite_vec` module is not installed in this dev environment, so direct import of `sci_fi_dashboard.db` fails at `import sqlite_vec` (pre-existing environmental dependency, not caused by this plan)
- SynapseConfig resolution verified independently — all paths correct

**Check 4 — Existing test suite:**
```
$ pytest tests/test_config.py -v
7 passed, 2 warnings in 0.07s
```
Result: PASS — all 7 SynapseConfig unit tests continue to pass

## Deviations from Plan

**1. [Rule 1 - Bug] Fixed missing blank line before _get_db_path() in memory_engine.py**
- Found during: Task 2 review
- Issue: After inserting `_get_db_path()` function, there was no blank line before the `def`, violating PEP8 and the project's ruff/black style
- Fix: Added two blank lines before the function definition
- Files modified: `workspace/sci_fi_dashboard/memory_engine.py`
- Commit: 6df4bad (included in the same commit)

## Commit

`6df4bad` — feat: wire DB modules to SynapseConfig (plan 01-02)

## Self-Check: PASSED

- [x] `workspace/sci_fi_dashboard/db.py` — modified, `_get_db_path()` present
- [x] `workspace/sci_fi_dashboard/sqlite_graph.py` — modified, `_get_db_path()` present
- [x] `workspace/sci_fi_dashboard/emotional_trajectory.py` — modified, `_get_db_path()` present
- [x] `workspace/sci_fi_dashboard/memory_engine.py` — modified, `_get_db_path()` + top-level import + models cache updated
- [x] Commit `6df4bad` exists
- [x] Zero `.openclaw` references in all four files
