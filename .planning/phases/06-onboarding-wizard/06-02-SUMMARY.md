---
phase: 06-onboarding-wizard
plan: "02"
subsystem: cli
tags: [litellm, httpx, validation, oauth, github-copilot, provider-catalog]

# Dependency graph
requires:
  - phase: 02-llm-provider-layer
    provides: _KEY_MAP env var names and litellm.Router pattern used as reference

provides:
  - ValidationResult dataclass with ok/error/detail fields
  - VALIDATION_MODELS dict (cheapest model per provider for max_tokens=1 ping)
  - _KEY_MAP dict (env var names mirroring llm_router.py exactly)
  - PROVIDER_GROUPS (3 groups for questionary display)
  - PROVIDER_LIST (flat list of all 19 provider keys)
  - validate_provider() function with env var save/restore and full exception mapping
  - validate_ollama() function using httpx GET (no litellm)
  - github_copilot_device_flow() async OAuth device code flow

affects:
  - 06-03 (wizard shell will import and call these functions)
  - 06-04 (non-interactive wizard may use PROVIDER_LIST for CLI args)
  - 06-05 (tests will mock validate_provider/validate_ollama)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "validate_provider() uses asyncio.run(_validate_async()) — sync wrapper over async litellm call"
    - "Env var save/restore pattern: old=get(), set(), try/finally restore — guarantees no env leak"
    - "RateLimitError -> ok=True (quota_exceeded) — key is valid, user gets warning not rejection"
    - "validate_ollama() uses httpx.get sync — no litellm, no API key, just HTTP 200 check"
    - "github_copilot_device_flow() is async, uses httpx.AsyncClient, writes token to GITHUB_COPILOT_TOKEN_DIR"

key-files:
  created:
    - workspace/cli/provider_steps.py
  modified: []

key-decisions:
  - "RateLimitError treated as ok=True (error='quota_exceeded') — key is valid; quota will reset; user should configure the provider with a warning displayed"
  - "validate_provider() is synchronous (asyncio.run wrapper) — wizard shell is sync CLI context, not FastAPI event loop"
  - "validate_ollama() uses httpx.get (sync) directly — no need for asyncio.run; simpler and consistent with httpx sync API"
  - "github_copilot_device_flow() respects GITHUB_COPILOT_TOKEN_DIR env var — same as conftest.py fake-auth fixture; test isolation automatic"
  - "_KEY_MAP in provider_steps.py is a copy of llm_router.py _KEY_MAP — deliberately duplicated to keep this module self-contained and independently testable"

patterns-established:
  - "Validation ping pattern: set env var, call litellm.acompletion(max_tokens=1, timeout=5, num_retries=0), restore env var"
  - "Exception mapping: AuthenticationError->invalid_key, RateLimitError->ok+quota_exceeded, Timeout->timeout, APIConnectionError->network_error, BadRequestError->bad_request"

requirements-completed: [ONB-02, ONB-03, ONB-10]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 6 Plan 02: Provider Validation Module Summary

**19-provider catalog with litellm ping validation, Ollama httpx health check, and GitHub Copilot OAuth device flow — all in a single self-contained module**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T19:53:09Z
- **Completed:** 2026-03-02T19:56:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Created `workspace/cli/provider_steps.py` with all required exports (PROVIDER_LIST, PROVIDER_GROUPS, VALIDATION_MODELS, _KEY_MAP, ValidationResult, validate_provider, validate_ollama, github_copilot_device_flow)
- Implemented validate_provider() with complete exception mapping: AuthenticationError -> invalid_key, RateLimitError -> ok=True (quota_exceeded), Timeout -> timeout, APIConnectionError -> network_error, BadRequestError -> bad_request
- Implemented env var save/restore in finally block — os.environ is guaranteed to be in original state after each call regardless of exception
- validate_ollama() uses httpx.get sync (no litellm) with ConnectError, TimeoutException, and non-200 response handling
- github_copilot_device_flow() async OAuth device code flow with polling loop (slow_down backoff, 5-minute deadline), token file write to GITHUB_COPILOT_TOKEN_DIR

## Task Commits

Each task was committed atomically:

1. **Task 1: Create provider catalog and ValidationResult dataclass** - `23e4553` (feat)
2. **Task 2: Implement validate_provider(), validate_ollama(), github_copilot_device_flow()** - `23e4553` (feat — combined in same commit as file)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `workspace/cli/provider_steps.py` — Complete provider validation module: ValidationResult, VALIDATION_MODELS, _KEY_MAP, PROVIDER_GROUPS, PROVIDER_LIST, validate_provider(), validate_ollama(), github_copilot_device_flow()

## Decisions Made
- RateLimitError treated as ok=True (error='quota_exceeded') — key is valid; quota will reset; user should configure the provider with a warning displayed
- validate_provider() is synchronous (asyncio.run wrapper) — wizard shell is sync CLI context, not FastAPI event loop
- validate_ollama() uses httpx.get (sync) directly — no need for asyncio.run; simpler and consistent with httpx sync API
- github_copilot_device_flow() respects GITHUB_COPILOT_TOKEN_DIR env var — same as conftest.py fake-auth fixture; test isolation automatic
- _KEY_MAP in provider_steps.py is a copy of llm_router.py _KEY_MAP — deliberately duplicated to keep this module self-contained and independently testable

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `workspace/cli/provider_steps.py` is importable with all 7 public exports ready
- Plan 06-03 (wizard shell) can import validate_provider, validate_ollama, github_copilot_device_flow, PROVIDER_GROUPS, PROVIDER_LIST directly
- Plan 06-05 (tests) can mock validate_provider/validate_ollama at their import location

## Self-Check: PASSED

- FOUND: workspace/cli/provider_steps.py
- FOUND commit: 23e4553

---
*Phase: 06-onboarding-wizard*
*Completed: 2026-03-02*
