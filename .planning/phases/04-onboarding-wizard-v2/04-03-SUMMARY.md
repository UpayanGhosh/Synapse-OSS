---
phase: 04-onboarding-wizard-v2
plan: 03
subsystem: cli
tags: [typer, sbs, persona, onboarding, non-interactive, docker, ci, env-vars]

# Dependency graph
requires:
  - phase: 04-01
    provides: initialize_sbs_from_wizard + STYLE/ENERGY/INTEREST/PRIVACY_CHOICES from sbs_profile_init.py
provides:
  - _run_non_interactive() reads SBS persona env vars for headless/Docker/CI setups
  - SYNAPSE_COMMUNICATION_STYLE, SYNAPSE_ENERGY_LEVEL, SYNAPSE_INTERESTS, SYNAPSE_PRIVACY_LEVEL env var support
affects:
  - Docker/CI consumers of `synapse setup --non-interactive --accept-risk`
  - docs/onboarding reference (env var table)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred import of sbs_profile_init inside try/except block — keeps import cost only when SBS env vars are set"
    - "any([...]) guard before try/except — silently skips entire SBS block when no SBS env vars are set"
    - "Validate-then-default pattern: check each env var against canonical CHOICES list, warn to stderr, fall back to safe default"
    - "Comma-split interests with unknown-filter: split on comma, strip/lowercase each, filter unknowns with warning"

key-files:
  created: []
  modified:
    - workspace/cli/onboard.py

key-decisions:
  - "SBS block placed after write_config() and before _validate_environment() — config is persisted first so SBS failure has no config impact"
  - "All validation warnings go to stderr (err=True) so stdout remains clean for pipeline consumption"
  - "Deferred import inside try/except means sbs_profile_init.py is not imported at all unless at least one SBS env var is set — zero cost for non-SBS pipelines"
  - "parsed_interests uses empty list when interests_raw is empty — initialize_sbs_from_wizard receives empty list, not [''] "

# Metrics
duration: 10min
completed: 2026-04-07
---

# Phase 4 Plan 03: Non-Interactive SBS Env Var Support Summary

**Extended `_run_non_interactive()` to read four optional SBS persona env vars (SYNAPSE_COMMUNICATION_STYLE, SYNAPSE_ENERGY_LEVEL, SYNAPSE_INTERESTS, SYNAPSE_PRIVACY_LEVEL), validate each against canonical choice lists with stderr warnings, and call `initialize_sbs_from_wizard()` for headless/Docker/CI setups**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-07
- **Completed:** 2026-04-07
- **Tasks:** 2 (implemented together in one atomic edit — both modify the same function)
- **Files modified:** 1

## Accomplishments

- `synapse setup --non-interactive --accept-risk` now accepts optional SBS persona env vars
- All four vars are optional — if none are set, the entire SBS block is skipped silently (no warning, no error)
- If any var is set, all four are read, validated, and passed to `initialize_sbs_from_wizard()` with safe defaults for missing ones
- Invalid `SYNAPSE_COMMUNICATION_STYLE` / `SYNAPSE_ENERGY_LEVEL` / `SYNAPSE_PRIVACY_LEVEL` values trigger stderr warnings and fall back to defaults
- `SYNAPSE_INTERESTS` is comma-separated, split/stripped/lowercased; unknown topics are filtered with a stderr warning
- Entire SBS block wrapped in `try/except Exception` — non-interactive mode never crashes on SBS failure
- `_run_non_interactive()` docstring extended with SBS env var reference block

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1+2 | SBS env var seeding + validation in _run_non_interactive() | 93a7a0b | workspace/cli/onboard.py |

(Tasks 1 and 2 both target the same function in the same file — implemented as one atomic commit.)

## Files Created/Modified

- `workspace/cli/onboard.py` — added SBS env var seeding block (lines 262–330): read 4 env vars, validate each against canonical CHOICES, call `initialize_sbs_from_wizard()` with validated+defaulted values, wrapped in try/except

## Decisions Made

- **SBS block after write_config(), before _validate_environment():** config is persisted to disk first, so any SBS exception has zero impact on the main config write path.
- **Deferred import inside try/except:** `sbs_profile_init` is only imported when at least one SBS env var is set — no import cost for pipelines that don't use SBS seeding.
- **Warnings to stderr, success to stdout:** pipeline scripts that capture stdout get clean output; humans reading stderr see validation warnings.
- **Empty `parsed_interests` for blank `SYNAPSE_INTERESTS`:** `"".split(",")` produces `[""]`, so the list comprehension guard (`if i.strip()`) ensures the empty string is filtered — `initialize_sbs_from_wizard` receives `[]`, not `[""]`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four SBS env vars are wired for Docker/CI consumers
- Plan 04-04 (final onboarding integration / e2e tests) can now test the non-interactive SBS path via env var injection

---
*Phase: 04-onboarding-wizard-v2*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: workspace/cli/onboard.py (modified — SBS block at lines 262-330)
- FOUND commit: 93a7a0b (feat(04-03): add SBS env var seeding to _run_non_interactive())
- SYNAPSE_COMMUNICATION_STYLE referenced in workspace/cli/onboard.py
- SYNAPSE_ENERGY_LEVEL referenced in workspace/cli/onboard.py
- SYNAPSE_INTERESTS referenced in workspace/cli/onboard.py
- SYNAPSE_PRIVACY_LEVEL referenced in workspace/cli/onboard.py
