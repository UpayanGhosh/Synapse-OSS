---
phase: 06-onboarding-wizard
plan: "04"
subsystem: cli
tags: [typer, questionary, rich, wizard, onboarding, non-interactive, migration]

# Dependency graph
requires:
  - workspace/cli/provider_steps.py (06-02)
  - workspace/cli/channel_steps.py (06-03)
  - workspace/synapse_config.py (write_config, 01-01)
  - workspace/scripts/migrate_openclaw.py (migrate, 01-05)
provides:
  - workspace/cli/onboard.py — full wizard orchestration layer
  - run_wizard() — entry point dispatching to interactive or non-interactive mode
  - _check_for_openclaw() — named top-level migration detection helper (importable by tests)
  - _run_non_interactive() — env-var driven config write with clean exit codes
  - _run_interactive() — 9-step questionary wizard with grouped provider checkbox
  - _run_migration() — dynamic import of migrate_openclaw with correct keyword args
  - _build_model_mappings() — role-based model defaults from configured provider set
affects:
  - workspace/synapse_cli.py (onboard command body — already lazy-imports run_wizard)
  - 06-05 (tests will import _check_for_openclaw, run_wizard with force_interactive=True)

# Tech tracking
tech-stack:
  added:
    - questionary>=2.1.0 (installed in dev env — was in requirements.txt but not installed)
  patterns:
    - Dispatcher pattern: run_wizard() -> _run_non_interactive() | _run_interactive() based on TTY/flag
    - force_interactive=False on run_wizard() — allows tests to call _run_interactive() directly with mocked questionary without triggering TTY check
    - _check_for_openclaw(openclaw_root=None) — injectable root for test isolation; defaults to ~/.openclaw
    - asyncio.run(github_copilot_device_flow()) — device flow only; all other providers are sync
    - Dynamic import via importlib.util.spec_from_file_location for migrate_openclaw.py
    - None guard on every questionary.ask() return — Ctrl+C raises typer.Exit(1)

key-files:
  created:
    - workspace/cli/onboard.py
  modified: []

key-decisions:
  - "run_wizard() accepts force_interactive=False — tests call _run_interactive() with mocked questionary without needing a TTY"
  - "_check_for_openclaw() defined as named top-level function (not inlined inside _run_interactive) — tests can import and call it directly with fake paths"
  - "_run_migration() calls mod.migrate(source_root=openclaw_root, dest_root=dest_root) — keyword args match actual migrate() signature in migrate_openclaw.py"
  - "questionary installed via pip install (Rule 3 auto-fix) — was listed in requirements.txt but missing from dev venv"

patterns-established:
  - "Non-interactive exit codes: missing SYNAPSE_PRIMARY_PROVIDER -> exit 1 with env var name; unknown provider -> exit 1; missing provider key -> exit 1 with env var name; validation fail -> exit 1 with error detail"
  - "Interactive wizard: all questionary.ask() returns None-guarded; None = Ctrl+C = raise typer.Exit(1)"
  - "bedrock special case: set 3 env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) before calling validate_provider('bedrock', ...)"

requirements-completed: [ONB-01, ONB-02, ONB-03, ONB-04, ONB-05, ONB-06, ONB-07, ONB-08, ONB-09, ONB-10]

# Metrics
duration: 5min
completed: 2026-03-02
---

# Phase 6 Plan 04: Onboarding Wizard Orchestration Summary

**Complete wizard orchestration layer wiring provider_steps + channel_steps into a linear 9-step interactive flow and a fully env-var-driven non-interactive mode — synapse onboard now fully operational**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-02T19:59:44Z
- **Completed:** 2026-03-02T20:04:47Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created `workspace/cli/onboard.py` implementing all 7 functions: `run_wizard()`, `_is_tty()`, `_run_non_interactive()`, `_run_interactive()`, `_check_for_openclaw()`, `_run_migration()`, `_build_model_mappings()`
- `run_wizard(non_interactive, force_interactive)` dispatches correctly: NI flag or no-TTY → `_run_non_interactive()`; else → `_run_interactive()`. `force_interactive=False` parameter enables test isolation
- Non-interactive mode validates SYNAPSE_PRIMARY_PROVIDER, provider env var (via `_KEY_MAP`), calls `validate_provider()` / `validate_ollama()`, writes synapse.json; exits 1 with clear message and env var name when any required var is missing
- Interactive wizard: 9-step linear flow — welcome panel → existing config check → openclaw migration detect → questionary.checkbox provider select (grouped by Separator) → per-provider key collection with `console.status()` spinner → questionary.checkbox channel select → per-channel `setup_*()` calls → `_build_model_mappings()` → `write_config()` with permissions panel
- GitHub Copilot special case: `asyncio.run(github_copilot_device_flow(console))` — device flow instead of password prompt
- `_check_for_openclaw(openclaw_root=None)` — named top-level function with injectable root for unit test isolation; returns Path if exists+is_dir, None otherwise
- `_run_migration()` dynamically imports `migrate_openclaw.py` via `importlib.util` and calls `mod.migrate(source_root=openclaw_root, dest_root=dest_root)` with correct keyword argument names

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: Full onboard.py implementation** - `88f2951` (feat)
   - Both tasks modify the same file; committed atomically as a single unit (same pattern as Plans 02/03)

## Files Created/Modified

- `workspace/cli/onboard.py` — Complete wizard orchestration: `run_wizard`, `_is_tty`, `_run_non_interactive`, `_run_interactive`, `_check_for_openclaw`, `_run_migration`, `_build_model_mappings`

## Decisions Made

- `force_interactive=False` parameter on `run_wizard()` — tests can call `_run_interactive()` directly with mocked questionary without needing a real TTY; does not affect production behavior (TTY check runs as normal when `force_interactive=False`)
- `_check_for_openclaw()` defined as a named top-level function — not inlined inside `_run_interactive()` — because tests import it directly (`from cli.onboard import _check_for_openclaw`) and call it with a fake `openclaw_root` to avoid touching `~/.openclaw`
- `_run_migration()` uses `mod.migrate(source_root=..., dest_root=...)` — keyword args match the actual function signature in `migrate_openclaw.py` exactly (not `src=`, not `dest=`)
- `questionary` installed in dev env (Rule 3 auto-fix) — was already listed in `requirements.txt` but not installed in the current venv; no requirements.txt changes needed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] questionary not installed in dev environment**
- **Found during:** Task 1 (import verification)
- **Issue:** `import questionary` raised `ModuleNotFoundError` — questionary not installed in current venv
- **Fix:** Ran `pip install "questionary>=2.1.0"` — installs questionary 2.1.0. Already listed in requirements.txt so no file changes needed.
- **Files modified:** None (requirements.txt already correct)
- **Verification:** Import succeeded; non-interactive run_wizard wrote config correctly
- **Committed in:** Not a code change; environment fix only

## Issues Encountered

None beyond the missing dev dependency auto-fixed above.

## User Setup Required

None — `workspace/cli/onboard.py` is the wizard users interact with via `synapse onboard`. No external services needed to create the file itself.

## Next Phase Readiness

- `workspace/cli/onboard.py` is the final piece of the onboarding wizard
- `synapse onboard` is now fully operational end-to-end (Plan 06-01 CLI scaffold + Plans 06-02/03 step modules + Plan 06-04 orchestration)
- Plan 06-05 (tests) can import `run_wizard`, `_check_for_openclaw`, `_build_model_mappings` directly; `force_interactive=True` enables testing the interactive flow with mocked questionary

---
*Phase: 06-onboarding-wizard*
*Completed: 2026-03-02*

## Self-Check: PASSED

- FOUND: workspace/cli/onboard.py
- FOUND: .planning/phases/06-onboarding-wizard/06-04-SUMMARY.md
- FOUND commit: 88f2951
