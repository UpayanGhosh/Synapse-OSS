---
phase: 06-onboarding-wizard
plan: "01"
subsystem: cli
tags: [typer, questionary, qrcode, cli, onboarding, entry-point]

# Dependency graph
requires: []
provides:
  - workspace/cli/__init__.py CLI subpackage marker
  - workspace/synapse_cli.py root Typer app with onboard, chat, ingest, vacuum, verify subcommands
  - requirements.txt with typer[all]>=0.24.0, questionary>=2.1.0, qrcode>=8.0
  - pyproject.toml [project.scripts] entry: synapse = "synapse_cli:app"
affects:
  - 06-02-PLAN (wizard logic — imports from cli.onboard)
  - 06-03-PLAN (channel wizard steps)
  - 06-04-PLAN (onboard.py run_wizard implementation)

# Tech tracking
tech-stack:
  added:
    - typer[all]>=0.24.0 (CLI framework, shell completion, rich help)
    - questionary>=2.1.0 (interactive prompts for wizard)
    - qrcode>=8.0 (ASCII QR rendering in terminal for WhatsApp pairing)
  patterns:
    - Lazy imports inside Typer command bodies — CLI compiles before optional dependencies exist
    - workspace/cli/ subpackage pattern — wizard modules isolated from core workspace
    - [project.scripts] entry point — pip-installable synapse console script

key-files:
  created:
    - workspace/cli/__init__.py
    - workspace/synapse_cli.py
  modified:
    - requirements.txt
    - pyproject.toml

key-decisions:
  - "synapse_cli.py delegates to main.py named functions (start_chat, ingest_data, optimized_vacuum, verify_system) via lazy imports — avoids modifying main.py"
  - "onboard command uses lazy import (from cli.onboard import run_wizard) — synapse_cli.py importable before cli/onboard.py exists; ImportError fires only when command is invoked"
  - "Typer registered_commands[i].name is None by default (set only when @app.command(name=...) used); use .callback.__name__ for programmatic command name access"

patterns-established:
  - "Lazy import pattern: all Typer command bodies import from workspace modules inside the function body, not at module top-level"
  - "CLI subpackage: workspace/cli/ holds all wizard and CLI helper modules; root synapse_cli.py is thin mount layer"

requirements-completed: [ONB-01, ONB-07]

# Metrics
duration: 2min
completed: 2026-03-02
---

# Phase 6 Plan 01: CLI Entry-Point Scaffold Summary

**Typer root app with five subcommands (onboard/chat/ingest/vacuum/verify) wired via lazy imports, pyproject.toml console script entry, and three wizard dependencies added**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-02T19:53:00Z
- **Completed:** 2026-03-02T19:54:58Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `workspace/cli/__init__.py` as CLI subpackage marker with module docstring
- Created `workspace/synapse_cli.py` with root Typer app: `onboard`, `chat`, `ingest`, `vacuum`, `verify` subcommands all registered and showing in `--help`
- Added `typer[all]>=0.24.0`, `questionary>=2.1.0`, `qrcode>=8.0` to both `requirements.txt` (Terminal UI section) and `pyproject.toml` dependencies
- Added `[project.scripts]` section to `pyproject.toml` with `synapse = "synapse_cli:app"` for pip-installable console script

## Task Commits

Each task was committed atomically:

1. **Task 1: Add typer, questionary, qrcode to requirements.txt and pyproject.toml** - `7043649` (chore)
2. **Task 2: Create workspace/cli/__init__.py and workspace/synapse_cli.py** - `bf08806` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `requirements.txt` - Added typer[all], questionary, qrcode under Terminal UI section
- `pyproject.toml` - Added three deps to [project] dependencies; added [project.scripts] section
- `workspace/cli/__init__.py` - CLI subpackage marker with module docstring
- `workspace/synapse_cli.py` - Root Typer app; mounts five subcommands; onboard lazy-imports cli.onboard.run_wizard

## Decisions Made

- **Delegate to main.py named functions**: `start_chat()`, `ingest_data()`, `optimized_vacuum()`, `verify_system()` exist in main.py so imported directly instead of subprocess wrapping. main.py NOT modified.
- **Lazy import pattern**: All imports inside command bodies so synapse_cli.py stays importable before workspace deps are installed.
- **onboard lazy import**: `from cli.onboard import run_wizard` inside the command body means ImportError only fires when `synapse onboard` is actually invoked — cli/onboard.py does not exist until Plan 04.
- **Typer `.name` vs `.callback.__name__`**: Plan verification script uses `cmd.name` but Typer only populates `.name` when `@app.command(name=...)` is explicitly provided; callback function names are the source of truth via `.callback.__name__`. Both `--help` output and callback name confirm all 5 commands registered correctly.

## Deviations from Plan

None - plan executed exactly as written.

Minor note: `workspace/cli/__init__.py` existed as an empty stub (`# workspace/cli — ...`) before execution started (visible in `git status` as untracked). Updated to the plan-specified module docstring format. No behavior difference.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. The `synapse onboard` command will guide users through setup in a later plan.

## Next Phase Readiness

- `workspace/synapse_cli.py` is the stable entry point all subsequent wizard plans build on
- `workspace/cli/` subpackage directory ready to receive `onboard.py` (Plan 04)
- Deps declared in requirements.txt and pyproject.toml — install with `pip install typer[all] questionary qrcode` or `pip install -r requirements.txt`
- No blockers for Phase 6 Plan 02

---
*Phase: 06-onboarding-wizard*
*Completed: 2026-03-02*

## Self-Check: PASSED

- FOUND: workspace/cli/__init__.py
- FOUND: workspace/synapse_cli.py
- FOUND: requirements.txt
- FOUND: pyproject.toml
- FOUND: .planning/phases/06-onboarding-wizard/06-01-SUMMARY.md
- FOUND commit: 7043649 (Task 1)
- FOUND commit: bf08806 (Task 2)
