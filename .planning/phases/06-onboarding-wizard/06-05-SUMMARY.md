---
phase: 06-onboarding-wizard
plan: "05"
subsystem: testing
tags: [pytest, typer, litellm, questionary, asyncmock, CliRunner, onboarding, wizard]

# Dependency graph
requires:
  - phase: 06-onboarding-wizard plan 04
    provides: run_wizard() with force_interactive, _check_for_openclaw(), provider_steps, channel_steps
provides:
  - 24-test suite covering all 10 ONB requirements in workspace/tests/test_onboard.py
  - CliRunner-based end-to-end tests for non-interactive mode
  - Mocked questionary tests for interactive mode via force_interactive=True
  - Isolated unit tests for validate_provider, validate_telegram_token, validate_discord_token, validate_slack_tokens, run_whatsapp_qr_flow, github_copilot_device_flow
affects: [future test additions, CI pipeline, Phase 7 if any]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - CliRunner without mix_stderr kwarg (typer 0.24.1 compatibility)
    - pytestmark skipif ONBOARD_AVAILABLE guard for module-level skip
    - AsyncMock side_effect for raising litellm exceptions in validate_provider tests
    - run_wizard(force_interactive=True) pattern to exercise _run_interactive() without TTY
    - Injectable openclaw_root in _check_for_openclaw() for deterministic migration tests

key-files:
  created:
    - workspace/tests/test_onboard.py
  modified: []

key-decisions:
  - "CliRunner() used without mix_stderr=False — typer 0.24.1 does not support that kwarg; stderr merged into stdout; result.output used for all assertions (Rule 1 auto-fix)"
  - "test_interactive_migration_offer uses partial string match ('Migrate' or 'igrate') — resilient to exact wording changes in questionary.confirm() call"
  - "test_github_copilot_device_flow_polls_github sets GITHUB_COPILOT_TOKEN_DIR via os.environ.setdefault to avoid clobbering conftest autouse fixture value"

patterns-established:
  - "Pattern 1: pytestmark.skipif with ONBOARD_AVAILABLE — all tests auto-skip when module unavailable; no per-function guards needed"
  - "Pattern 2: _make_mock_acompletion() factory function — reused across ONB-03 and interactive flow tests to avoid duplicate mock setup"
  - "Pattern 3: AsyncMock side_effect=async_fn for testing litellm exception paths — allows raising RateLimitError/AuthenticationError from async context"

requirements-completed: [ONB-01, ONB-02, ONB-03, ONB-04, ONB-05, ONB-06, ONB-07, ONB-08, ONB-09, ONB-10]

# Metrics
duration: 12min
completed: 2026-03-02
---

# Phase 6 Plan 05: Wizard Test Suite Summary

**24-test pytest suite covering all 10 ONB requirements via CliRunner, AsyncMock, and force_interactive=True — zero live API calls, no TTY, no Baileys bridge**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-02T20:12:24Z
- **Completed:** 2026-03-02T20:24:03Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- 24 passing tests covering ONB-01 through ONB-10 with zero failures and no hangs
- Non-interactive mode exit code matrix fully covered (exit 0 on success, exit 1 on missing SYNAPSE_PRIMARY_PROVIDER, exit 1 on missing API key, exit 1 via SYNAPSE_NON_INTERACTIVE=1 env var)
- Interactive path exercised via run_wizard(force_interactive=True) with mocked questionary — no TTY dependency
- GitHub Copilot device flow tested as async coroutine with mocked httpx.AsyncClient POST sequence

## Task Commits

Each task was committed atomically:

1. **Task 1: Test scaffold, availability guard, and non-interactive tests (ONB-01, ONB-07, ONB-09)** - `9ef1896` (test)
2. **Task 2: Provider validation tests (ONB-02, ONB-03, ONB-10), interactive flow tests, channel/migration tests (ONB-04, ONB-05, ONB-06, ONB-08)** - `f6d9c7a` (test)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `workspace/tests/test_onboard.py` - 24-test wizard suite, 520 lines, covers all ONB requirements

## Decisions Made

- `CliRunner()` used without `mix_stderr=False` — typer 0.24.1 does not support that kwarg; stderr is merged into stdout by default; `result.output` used for all assertions
- Migration confirm test uses partial string match (`"Migrate"` or `"igrate"`) for resilience against minor wording changes in wizard prompts
- `os.environ.setdefault("GITHUB_COPILOT_TOKEN_DIR", ...)` in the device flow test avoids clobbering the autouse fixture value from conftest.py

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CliRunner mix_stderr kwarg not supported in typer 0.24.1**
- **Found during:** Task 1 (test scaffold creation)
- **Issue:** Plan specified `CliRunner(mix_stderr=False)` but typer 0.24.1's CliRunner does not accept that keyword argument — `TypeError: CliRunner.__init__() got an unexpected keyword argument 'mix_stderr'`
- **Fix:** Removed `mix_stderr=False` kwarg; replaced all `(result.output or "") + (result.stderr or "")` combined output patterns with `result.output or ""` since typer's CliRunner merges stderr into stdout by default
- **Files modified:** workspace/tests/test_onboard.py
- **Verification:** All 4 Task 1 tests passed after fix
- **Committed in:** `9ef1896` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in plan spec vs installed library version)
**Impact on plan:** Fix was purely cosmetic to the test code; assertion logic unchanged; all ONB requirements still covered identically.

## Issues Encountered

None beyond the CliRunner kwarg auto-fix above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 10 ONB requirements have automated test coverage
- Phase 6 (Onboarding Wizard) is now complete — all 5 plans done
- Project milestone v1.0 complete: all 6 phases delivered (27/27 plans)

---
*Phase: 06-onboarding-wizard*
*Completed: 2026-03-02*
