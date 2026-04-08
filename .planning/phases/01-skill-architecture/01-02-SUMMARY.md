---
phase: 01-skill-architecture
plan: "02"
subsystem: skills
tags: [skill-registry, skill-watcher, watchdog, hot-reload, fastapi, thread-safety, tdd]

# Dependency graph
requires:
  - phase: 01-skill-architecture
    plan: "01"
    provides: "SkillManifest frozen dataclass, SkillValidationError, SkillLoader classmethods"
provides:
  - SkillRegistry thread-safe singleton — scan/reload/list_skills/get_skill
  - SkillWatcher watchdog-based filesystem watcher with 2s debounce and polling fallback
  - GET /skills FastAPI endpoint returning {skills:[...], count:N} JSON
  - sci_fi_dashboard/routes/skills.py route module
  - sci_fi_dashboard/_deps.py stub with skill_registry attribute
affects: [skill-router, api-gateway, skill-dispatch, 01-03, 01-04, 01-05]

# Tech tracking
tech-stack:
  added: [watchdog>=4.0.0]
  patterns:
    - "Thread-safe registry pattern: RLock wraps all state reads and writes"
    - "Watchdog observer pattern: event handler with debounce guards against rapid-fire reloads"
    - "Polling fallback pattern: graceful degradation when optional watchdog not installed"
    - "Lazy deps import: routes import sci_fi_dashboard._deps at call time to avoid circular imports"

key-files:
  created:
    - workspace/sci_fi_dashboard/skills/registry.py
    - workspace/sci_fi_dashboard/skills/watcher.py
    - workspace/sci_fi_dashboard/routes/skills.py
    - workspace/sci_fi_dashboard/routes/__init__.py
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/tests/test_skill_registry.py
  modified:
    - requirements.txt

key-decisions:
  - "SkillRegistry uses threading.RLock (reentrant) not Lock — allows reload() to call list_skills() internally without deadlock"
  - "SkillWatcher debounce of 2s prevents rapid-fire reload loops from directory-level create events (T-01-04)"
  - "Polling fallback runs at debounce*5 interval with explicit warning log — watchdog is optional but recommended"
  - "GET /skills reads deps.skill_registry via getattr() — returns graceful empty response when not yet initialised"
  - "_deps.py in this worktree is a minimal stub; full _deps.py with all singletons lives in main codebase"
  - "Routes __init__.py imports skills module explicitly for clean package structure"

patterns-established:
  - "Registry reload pattern: scan fresh, compute added/removed diff, replace atomically under lock, log summary"
  - "Watcher event pattern: check debounce, call reload() in try/except, update last_reload timestamp"
  - "Route laziness pattern: deps imported inside route handler body to prevent circular import at module level"

requirements-completed:
  - SKILL-02
  - SKILL-05
  - SKILL-07

# Metrics
duration: 20min
completed: 2026-04-07
---

# Phase 01 Plan 02: Skill Architecture — Registry, Watcher, and GET /skills Summary

**Thread-safe SkillRegistry with watchdog hot-reload and GET /skills endpoint — 45 tests passing**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-07T09:00:00Z
- **Completed:** 2026-04-07T09:20:00Z
- **Tasks:** 2 (TDD RED + GREEN for Task 1; Task 2 implemented in GREEN commit)
- **Files modified:** 7 created, 1 modified

## Accomplishments

- `SkillRegistry` thread-safe singleton using `threading.RLock` — `scan()` at init, `reload()` diffs old vs new (adds/removes), `list_skills()` returns sorted manifests, `get_skill(name)` returns single manifest or None
- `SkillWatcher` watchdog-based observer watching `~/.synapse/skills/` recursively — 2s debounce prevents rapid-fire reload loops (T-01-04 mitigation); polling fallback when watchdog not installed logs a warning
- `GET /skills` FastAPI endpoint returning `{"skills": [...], "count": N}` — reads from `deps.skill_registry`, returns graceful empty response with `status: "skill_system_not_initialized"` when not yet wired up
- `sci_fi_dashboard/_deps.py` minimal stub with `skill_registry: SkillRegistry | None = None` for clean endpoint testing
- 14 new tests (8 registry, 3 watcher, 2 endpoint) + 31 existing from 01-01 = 45 total passing

## Task Commits

Each task was committed atomically:

1. **TDD RED — Failing tests for SkillRegistry, SkillWatcher, GET /skills** - `8662e21` (test)
2. **TDD GREEN — SkillRegistry, SkillWatcher, routes, _deps stub** - `7f12371` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/skills/registry.py` — SkillRegistry: scan/reload/list_skills/get_skill, RLock, logging
- `workspace/sci_fi_dashboard/skills/watcher.py` — SkillWatcher: watchdog Observer + polling fallback, 2s debounce
- `workspace/sci_fi_dashboard/routes/skills.py` — GET /skills endpoint, reads deps.skill_registry
- `workspace/sci_fi_dashboard/routes/__init__.py` — Route package init, imports skills submodule
- `workspace/sci_fi_dashboard/_deps.py` — Minimal singleton stub (skill_registry attribute)
- `workspace/tests/test_skill_registry.py` — 14 tests covering all public API surface
- `requirements.txt` — Added `watchdog>=4.0.0` under File Watching section

## Decisions Made

- `threading.RLock` chosen over `Lock` — reentrant allows nested lock acquisitions within the same thread; future callers that call `reload()` then `list_skills()` won't deadlock
- `SkillWatcher` uses watchdog's `Observer` (inotify/FSEvents/ReadDirectoryChangesW depending on platform) — cross-platform filesystem events without polling overhead
- Polling fallback interval set to `debounce_seconds * 5` — conservative enough to not hammer disk, responsive enough for development use
- `GET /skills` uses `getattr(deps, "skill_registry", None)` instead of `hasattr` + attribute access — single expression, idiomatic Python
- `_deps.py` stub in worktree is intentionally minimal — the orchestrator merges it with the full `_deps.py` from main codebase during wave integration

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created minimal _deps.py stub**
- **Found during:** Task 2 (GET /skills endpoint tests)
- **Issue:** `sci_fi_dashboard._deps` module absent in worktree (this branch diverged from refactor/optimize which has the full `_deps.py`). Endpoint test imports `from sci_fi_dashboard import _deps as deps` — ImportError without it.
- **Fix:** Created minimal stub at `workspace/sci_fi_dashboard/_deps.py` with only `skill_registry: SkillRegistry | None = None`. Does not duplicate full `_deps.py` content — only the attribute needed by the skills subsystem.
- **Files modified:** workspace/sci_fi_dashboard/_deps.py
- **Verification:** Endpoint tests pass; import resolves cleanly
- **Committed in:** `7f12371` (Green commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking)
**Impact on plan:** Necessary for tests to run in the isolated worktree context. No scope creep — stub is 15 lines.

## Issues Encountered

The worktree is based on a commit that predates `_deps.py` (this is the skill architecture work happening in parallel with other work on the main branch). The worktree correctly isolates the skills feature — all existing files like `_deps.py` that are part of the main codebase are absent and must be created as stubs or pulled from git history as needed.

## Next Phase Readiness

- `SkillRegistry` and `SkillWatcher` are ready for Plan 03 (skill router/dispatch)
- `GET /skills` endpoint is wired and returns correct JSON shape
- The `skill_registry` attribute in `_deps.py` is the integration seam — Plan 04 (Wave 3) wires it to a real `SkillRegistry` instance during app startup
- `skills/__init__.py` export wiring is consolidated in Plan 04 Task 2 (Wave 3) per plan instructions

---
*Phase: 01-skill-architecture*
*Completed: 2026-04-07*
