---
phase: 04-onboarding-wizard-v2
plan: 01
subsystem: cli
tags: [typer, sbs, persona, onboarding, wizard, profile, compiler]

# Dependency graph
requires:
  - phase: 01-skill-architecture
    provides: core skill and config foundation that sbs_profile_init imports via SynapseConfig
provides:
  - python -m synapse / synapse setup entry points
  - SBSProfileInitializer that seeds 4 profile layers from wizard answers
  - _run_sbs_questions wired into interactive wizard after config write
  - compiler extensions: preferred_style tone directives, privacy_sensitivity directives, energetic/calm mood instructions
affects:
  - 04-02 (verify steps — setup --verify deferred import)
  - compiler tests (test_sbs_extended.py — backward-compatible changes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred import pattern for --verify flag: import inside if-branch so missing verify_steps.py only fails when flag is used"
    - "Additive wizard step pattern: isolated _run_sbs_questions() callable so existing tests can patch it"
    - "Graceful degradation: each profile layer write wrapped in individual try/except — wizard never crashes on SBS failure"

key-files:
  created:
    - workspace/__main__.py
    - workspace/cli/sbs_profile_init.py
  modified:
    - workspace/synapse_cli.py
    - workspace/cli/onboard.py
    - workspace/sci_fi_dashboard/sbs/injection/compiler.py

key-decisions:
  - "Only sbs_the_creator is seeded by wizard — sbs_the_partner retains defaults (wizard collects primary user data only)"
  - "domain layer writes BOTH interests dict AND active_domains list — compiler reads active_domains (list), not interests (dict)"
  - "verify_steps import deferred inside if-verify branch — allows 04-01 to ship before 04-02 without import errors"
  - "_compile_interaction() refactored to parts list so privacy_sensitivity has runtime effect even when peak_hours is empty"

patterns-established:
  - "Wizard question isolation: _run_sbs_questions() defined as standalone function before _run_interactive for testability"
  - "Profile seeding via SynapseConfig.load() path resolution — never hardcode ~/.synapse"

requirements-completed:
  - ONBOARD2-01
  - ONBOARD2-02
  - ONBOARD2-03

# Metrics
duration: 25min
completed: 2026-04-07
---

# Phase 4 Plan 01: Onboarding Wizard v2 Core Summary

**`synapse setup` command with 4-question SBS persona wizard that seeds linguistic, emotional_state, domain, and interaction profile layers — and extends the SBS compiler to emit tone/privacy/mood directives from wizard-written fields**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-07T00:00:00Z
- **Completed:** 2026-04-07T00:25:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- `python -m synapse setup` and `synapse setup` now work as canonical setup entry points (alias for onboard + `--verify` flag)
- `initialize_sbs_from_wizard()` seeds 4 SBS profile layers from wizard answers; domain layer writes BOTH `interests` dict AND `active_domains` list so compiler consumption works
- `_run_sbs_questions()` integrated into interactive wizard after `write_config()` — 4 questions + optional WhatsApp history import
- SBS compiler extended: `_compile_style()` emits tone directives, `_compile_interaction()` emits privacy directives, `_compile_emotional()` handles "energetic" and "calm" wizard moods

## Task Commits

Each task was committed atomically:

1. **Task 1: sbs_profile_init + __main__ + setup command** - `72d4099` (feat)
2. **Task 2: SBS questions + WhatsApp import in wizard** - `46ead40` (feat)
3. **Task 3: Extend compiler.py for wizard fields** - `f7d8557` (feat)

## Files Created/Modified

- `workspace/__main__.py` — python -m workspace entrypoint dispatching to synapse_cli:app (6 lines)
- `workspace/cli/sbs_profile_init.py` — `initialize_sbs_from_wizard()`, STYLE/INTEREST/PRIVACY/ENERGY constants and display maps (162 lines)
- `workspace/synapse_cli.py` — added `setup` command with `--verify`, `--non-interactive`, `--flow`, `--accept-risk`, `--reset` flags
- `workspace/cli/onboard.py` — added `_run_sbs_questions()` function and Step 10b call in `_run_interactive_impl()`
- `workspace/sci_fi_dashboard/sbs/injection/compiler.py` — extended `_compile_style()`, `_compile_interaction()`, and `_compile_emotional()`

## Decisions Made

- **Only sbs_the_creator seeded:** wizard collects primary user preferences, not partner data. sbs_the_partner retains default layers.
- **Both interests + active_domains written:** `_compile_domain()` reads `active_domains` (list), not `interests` (dict). Without writing `active_domains`, user interest selections would have zero runtime effect on system prompt.
- **Deferred verify_steps import:** the `--verify` branch imports `cli.verify_steps` inside the `if verify:` block. This allows Plan 04-01 to ship before Plan 04-02 (verify_steps.py) without causing import errors on startup.
- **_compile_interaction refactor to parts list:** the old implementation returned `""` when `peak_hours` was empty, which meant `privacy_sensitivity` alone would also produce no output. The refactor ensures wizard privacy answers always have runtime effect.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `synapse setup` command ships and routes to the onboarding wizard with persona seeding
- Plan 04-02 (verify steps / `--verify` flag) can now implement `cli/verify_steps.py` — the deferred import is already wired
- All wizard answers have observable runtime effect on system prompt generation (compiler extensions complete)
- Existing `test_onboard.py` tests remain unaffected — `_run_sbs_questions` is patchable

---
*Phase: 04-onboarding-wizard-v2*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: workspace/__main__.py
- FOUND: workspace/cli/sbs_profile_init.py
- FOUND: .planning/phases/04-onboarding-wizard-v2/04-01-SUMMARY.md
- FOUND commit: 72d4099 (Task 1 — sbs_profile_init, __main__, setup command)
- FOUND commit: 46ead40 (Task 2 — SBS wizard questions + WhatsApp import)
- FOUND commit: f7d8557 (Task 3 — compiler extensions)
- FOUND commit: 339932e (metadata — SUMMARY.md, STATE.md, ROADMAP.md, REQUIREMENTS.md)
