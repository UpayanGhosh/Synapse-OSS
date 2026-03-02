---
phase: 02-llm-provider-layer
plan: 01
subsystem: testing
tags: [litellm, pytest, asyncmock, tdd, synapse-config, model-mappings]

# Dependency graph
requires:
  - phase: 01-foundation-config
    provides: SynapseConfig dataclass in workspace/synapse_config.py with providers and channels fields

provides:
  - SynapseConfig.model_mappings field carrying per-role LLM routing table from synapse.json
  - workspace/tests/test_llm_router.py with 20 test functions covering LLM-01 through LLM-18
  - mock_acompletion fixture in conftest.py using unittest.mock.AsyncMock to patch litellm.acompletion

affects:
  - 02-02-PLAN (SynapseLLMRouter implementation — tests become GREEN when router is built)
  - 02-03-PLAN (provider key injection — tests for _inject_provider_keys)
  - 02-04-PLAN (call site sweep — LLM-16 xfail becomes passing after hardcoded strings removed)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED phase: all tests skipped via pytestmark skipif until target module exists"
    - "mock_acompletion fixture patches litellm.acompletion globally for isolation"
    - "LLM-16 xfail pattern: mark test as expected-failure until future plan completes migration"
    - "model_mappings dict field with file > default precedence (consistent with providers/channels)"

key-files:
  created:
    - workspace/tests/test_llm_router.py
  modified:
    - workspace/synapse_config.py
    - workspace/tests/conftest.py

key-decisions:
  - "Tests use pytestmark skipif (ROUTER_AVAILABLE=False) rather than pytest.mark.skip on each function — single guard makes RED->GREEN transition a one-line edit when Plan 02 ships the router"
  - "LLM-16 (no hardcoded models) marked xfail with strict=False — test will PASS once Plan 04 sweeps call sites, no test rewrite needed"
  - "model_mappings defaults to empty dict {} same as providers/channels — consistent three-layer precedence already established in Phase 1"
  - "Negative prefix assertions included in LLM-06 (ollama_chat/ not ollama/) and LLM-12 (zai/ not zhipu/) to catch wrong-prefix bugs that would pass positive-only checks"

patterns-established:
  - "TDD RED: import guard pattern using try/except ImportError + ROUTER_AVAILABLE flag + pytestmark skipif"
  - "Helper _make_config() builds minimal SynapseConfig directly (no file I/O) for fast unit tests"
  - "_get_model_arg() extracts model kwarg from mock call_args handling both positional and keyword call styles"

requirements-completed: [LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, LLM-09, LLM-10, LLM-11, LLM-12, LLM-13, LLM-14, LLM-15, LLM-16, LLM-17, LLM-18]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 2 Plan 01: LLM Provider Layer Test Scaffold Summary

**TDD RED phase: 20-test scaffold covering all 18 LLM provider requirements with mocked litellm.acompletion, plus SynapseConfig.model_mappings field for per-role routing table**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T10:11:36Z
- **Completed:** 2026-03-02T10:14:20Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Extended SynapseConfig frozen dataclass with model_mappings field that reads from synapse.json key "model_mappings" (empty dict default, consistent with providers/channels)
- Created workspace/tests/test_llm_router.py with 20 test functions covering LLM-01 through LLM-18 — all SKIPPED in RED phase via pytestmark skipif guard
- Added mock_acompletion fixture to conftest.py using unittest.mock.AsyncMock patching litellm.acompletion, returning structured mock response (choices[0].message.content, role, finish_reason)
- All 7 existing test_config.py tests still pass — no regressions from model_mappings addition

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend SynapseConfig with model_mappings field** - `adcb858` (feat)
2. **Task 2: Create test scaffold (RED) for LLM-01 through LLM-18** - `a1305f0` (test)

**Plan metadata:** (docs commit below)

_Note: TDD tasks committed in task order — feat (config extension) then test (RED scaffold)_

## Files Created/Modified

- `workspace/synapse_config.py` - Added model_mappings: dict field after channels; updated load() to read from synapse.json with empty dict default; updated docstring
- `workspace/tests/test_llm_router.py` - New file; 20 test functions covering all 18 LLM requirements; pytestmark skipif RED guard; mock_acompletion fixture usage; negative prefix checks for ollama_chat/ and zai/
- `workspace/tests/conftest.py` - Added import unittest.mock; added mock_acompletion fixture (27 lines) using AsyncMock patch of litellm.acompletion

## Decisions Made

- Tests use `pytestmark = pytest.mark.skipif(not ROUTER_AVAILABLE, ...)` rather than individual `@pytest.mark.skip` decorators — single guard at module level makes RED->GREEN transition a one-line edit when Plan 02 creates the router
- LLM-16 (no hardcoded model strings) marked `@pytest.mark.xfail(strict=False)` rather than skipped — it will naturally pass once Plan 04 sweeps call sites, requiring no test changes
- model_mappings field added after channels (not after providers) to maintain logical grouping: paths → credentials → routing
- Negative assertions for Ollama (ollama_chat/ not ollama/) and Zhipu Z.AI (zai/ not zhipu/) prevent wrong-prefix bugs that would pass positive-only checks

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. litellm is imported conditionally (try/except) so tests work even before litellm is installed in the environment.

## Next Phase Readiness

- Plan 02 (SynapseLLMRouter implementation): Test file ready. Remove pytestmark skipif guard and implement `SynapseLLMRouter`, `build_router`, and `_inject_provider_keys` in `workspace/sci_fi_dashboard/llm_router.py`. Tests will go GREEN.
- Plan 03 (provider key injection): _inject_provider_keys stub already imported in test file — tests will exercise it once Plan 02 implements it.
- Plan 04 (call site sweep): test_no_hardcoded_models (LLM-16) is marked xfail — it will automatically change to XPASS (expected fail that now passes) when all hardcoded strings are replaced.
- No blockers. SynapseConfig contract is established and stable.

---
*Phase: 02-llm-provider-layer*
*Completed: 2026-03-02*
