---
phase: 04-onboarding-wizard-v2
plan: 02
subsystem: cli
tags: [asyncio, rich, validation, providers, channels, litellm]

# Dependency graph
requires:
  - phase: 04-onboarding-wizard-v2
    provides: "provider_steps.py (validate_provider, validate_ollama, ValidationResult) and channel_steps.py (validate_telegram_token, validate_discord_token, validate_slack_tokens)"
provides:
  - "workspace/cli/verify_steps.py with run_verify() — parallel provider validation + sequential channel validation"
  - "synapse setup --verify dispatches to run_verify() via deferred import in synapse_cli.py"
affects:
  - 04-onboarding-wizard-v2
  - users running synapse setup --verify

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.gather() for parallel provider validation via run_in_executor wrapping sync functions"
    - "ValidationResult.ok access pattern — explicitly extract .ok and .detail, never use dataclass as plain bool"
    - "Lazy imports inside function body (noqa: PLC0415) to avoid import-time side effects"
    - "Rich conditional import with _RICH_AVAILABLE guard matching cli/onboard.py pattern"

key-files:
  created:
    - workspace/cli/verify_steps.py
  modified:
    - workspace/synapse_cli.py

key-decisions:
  - "validate_telegram_token, validate_discord_token, validate_slack_tokens raise ValueError on failure (not return bool) — channel validation uses try/except"
  - "validate_ollama returns ValidationResult not bool — treat same as validate_provider (.ok, .detail)"
  - "github_copilot skipped from provider verification — token is auto-managed via OAuth device flow"
  - "whatsapp always returns PASS with note — QR pairing cannot be validated offline"
  - "run_verify() is strictly read-only — no write_config() calls anywhere in the module"

patterns-established:
  - "verify_steps.py: all network calls wrapped in try/except, failures return (name, False, error_msg) tuples never raise"
  - "Provider verification always parallel via asyncio.gather; channel verification sequential (fast, typically 1-2 channels)"

requirements-completed:
  - ONBOARD2-05

# Metrics
duration: 15min
completed: 2026-04-07
---

# Phase 04 Plan 02: Verify Subcommand Summary

**`synapse setup --verify` reads all configured providers and channels from synapse.json and reports PASS/FAIL per component, running provider checks in parallel via asyncio.gather**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-07
- **Completed:** 2026-04-07
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `verify_steps.py` created with `run_verify()` returning exit code 0 (all-pass) or 1 (any failure)
- Provider validation runs in parallel via `asyncio.gather()` using `run_in_executor` to wrap sync `validate_provider()` and `validate_ollama()` calls
- `ValidationResult.ok` correctly extracted (not used as raw dataclass truthiness which would always be `True`)
- Channel validation covers all 4 types: telegram/discord/slack raise `ValueError` on failure (caught), whatsapp always passes with offline note
- Rich table output when available, plain-text fallback matching project pattern
- `synapse setup --verify` integration via deferred import in `synapse_cli.py` passes `non_interactive` arg through

## Task Commits

1. **Task 1: Create verify_steps.py with parallel provider + channel validation** - `bf704ab` (feat)
2. **Task 2: Validate setup --verify integration end-to-end** - `71fe2ba` (feat)

## Files Created/Modified
- `workspace/cli/verify_steps.py` - New file: `run_verify()`, async provider helpers, sync channel helpers, Rich/plain output
- `workspace/synapse_cli.py` - Fixed `run_verify()` call to pass `non_interactive` parameter

## Decisions Made
- Channel validation functions (`validate_telegram_token`, `validate_discord_token`, `validate_slack_tokens`) raise `ValueError` on failure in the actual implementation — the plan's interface spec said they return `bool` but the actual code raises. Used try/except wrapping to adapt.
- `validate_ollama` returns `ValidationResult` in the actual implementation (plan said it returns `bool`). Applied `.ok` extraction consistently.
- `github_copilot` skipped from provider verification — its token is auto-managed via OAuth device flow, no static API key exists to test.
- WhatsApp always returns PASS with an explanatory note — QR-based pairing cannot be validated without a running bridge server.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Channel validation functions raise ValueError, not return bool**
- **Found during:** Task 1 (creating verify_steps.py)
- **Issue:** Plan specified `validate_telegram_token(token) -> bool`, `validate_discord_token(token) -> bool`, and `validate_slack_tokens() -> tuple[bool, str]` but actual implementation returns dicts on success and raises `ValueError` on failure
- **Fix:** Wrapped each channel call in `try/except ValueError` and `except Exception`, return `(name, True, info_str)` on success and `(name, False, str(exc))` on failure
- **Files modified:** workspace/cli/verify_steps.py
- **Committed in:** bf704ab (Task 1 commit)

**2. [Rule 1 - Bug] validate_ollama returns ValidationResult not bool**
- **Found during:** Task 1 (creating `_validate_ollama_async`)
- **Issue:** Plan's interface spec said `validate_ollama() -> bool` but actual function returns `ValidationResult`. Plan note mentioned `quiet=True` parameter that doesn't exist.
- **Fix:** Treated `validate_ollama` same as `validate_provider` — extract `.ok` and `.detail` from result
- **Files modified:** workspace/cli/verify_steps.py
- **Committed in:** bf704ab (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bug: interface spec mismatch between plan and actual codebase)
**Impact on plan:** Both fixes essential for correct boolean extraction. No scope creep. Outcome unchanged.

## Issues Encountered
- `synapse_cli.py` already had the `setup` command from prior work (not from Plan 04-01 since no SUMMARY exists) — Task 2 only needed to fix the `run_verify()` call to pass `non_interactive` argument.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `synapse setup --verify` is fully operational: tests all configured providers in parallel and all configured channels sequentially
- Ready for Plan 04-03 and beyond

---
*Phase: 04-onboarding-wizard-v2*
*Completed: 2026-04-07*
