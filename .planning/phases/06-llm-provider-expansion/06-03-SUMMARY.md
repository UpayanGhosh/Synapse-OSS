---
phase: 06-llm-provider-expansion
plan: 03
subsystem: testing
tags: [pytest, unit-tests, budget-enforcement, deepseek, llm-router, provider-steps]

# Dependency graph
requires:
  - phase: 06-01
    provides: DeepSeek in provider_steps._KEY_MAP, VALIDATION_MODELS, PROVIDER_GROUPS
  - phase: 06-02
    provides: BudgetExceededError handling, get_provider_spend(), pre-call budget check in llm_router.py

provides:
  - 10 unit tests covering all four PROV requirements (PROV-01 through PROV-04)
  - _KEY_MAP mirror contract test catching future drift between llm_router.py and provider_steps.py
  - BudgetExceededError fallback and no-fallback path verification
  - Pre-call budget enforcement test (raises before LLM call)
  - VALIDATION_MODELS completeness guard for future provider additions

affects: [07-bundled-skills-library, any phase that modifies llm_router or provider_steps]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "object.__new__(SynapseLLMRouter) for minimal router instantiation without full __init__ in unit tests"
    - "Pre-call budget check tested by patching get_provider_spend at module level"
    - "asyncio_mode=auto (pytest.ini) means no @pytest.mark.asyncio needed — async def test_ runs automatically"

key-files:
  created:
    - workspace/tests/test_provider_expansion.py
  modified:
    - workspace/sci_fi_dashboard/llm_router.py

key-decisions:
  - "BudgetExceededError(approx_spend, max_budget, message) — three positional args required by litellm, not a single string; production code was wrong and fixed as Rule 1 deviation"
  - "qianfan listed as intentional _KEY_MAP divergence — provider_steps only, not in llm_router._KEY_MAP; encoded as _PS_ONLY_KEYS constant in test for future documentation"
  - "ollama, github_copilot, vllm exempted from VALIDATION_MODELS guard — they use non-litellm validation paths"

patterns-established:
  - "Rule 1 bug fix: BudgetExceededError must be raised with (current_cost, max_budget, message) signature matching litellm.exceptions.BudgetExceededError"

requirements-completed: [PROV-01, PROV-02, PROV-03, PROV-04]

# Metrics
duration: 8min
completed: 2026-04-09
---

# Phase 6 Plan 03: Provider Expansion Tests Summary

**10-test regression suite for PROV-01 through PROV-04: _KEY_MAP mirror contract, BudgetExceededError fallback/propagation, pre-call budget enforcement, and DeepSeek presence in all provider maps**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-09T07:49:00Z
- **Completed:** 2026-04-09T07:57:24Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `workspace/tests/test_provider_expansion.py` with 10 unit tests across 3 test classes covering all PROV requirements
- Caught and fixed a production bug: `BudgetExceededError` was being raised with a single string arg; litellm requires `(current_cost, max_budget, message)` positional args
- Mirror contract test (`test_key_maps_in_sync`) will catch future drift if a provider is added to one _KEY_MAP but not the other
- VALIDATION_MODELS guard test prevents future providers from being added to the wizard without a validation model

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_provider_expansion.py with full Phase 6 test suite** - `9aaa421` (test)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `workspace/tests/test_provider_expansion.py` - 10 unit tests: TestProviderMaps (4), TestBudgetFallback (3), TestBudgetEnforcement (3)
- `workspace/sci_fi_dashboard/llm_router.py` - Fixed BudgetExceededError raise signature (Rule 1 auto-fix)

## Decisions Made

- `object.__new__(SynapseLLMRouter)` used to create a minimal router instance without triggering the full `__init__` (which requires synapse.json), then manually setting `_config` and `_router` attributes via mocks
- `qianfan` encoded as intentional _KEY_MAP divergence in `_PS_ONLY_KEYS` constant rather than a comment — self-documenting for future readers
- `_do_call` fallback test verifies the fallback model role name is `f"{role}_fallback"` (not the model string directly), which is the litellm Router convention

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed BudgetExceededError constructor call signature in llm_router.py**
- **Found during:** Task 1 (running tests for the first time)
- **Issue:** `raise BudgetExceededError(f"Provider '{provider_prefix}' budget exceeded: ...")` passes a single string, but `litellm.exceptions.BudgetExceededError.__init__` requires `(current_cost: float, max_budget: float, message: Optional[str] = None)` — raises `TypeError: BudgetExceededError.__init__() missing 1 required positional argument: 'max_budget'` at runtime
- **Fix:** Changed to `raise BudgetExceededError(approx_spend, budget_usd, f"...")` with explicit positional args; also updated test mocks to use `BudgetExceededError(2.0, 0.001, "budget exceeded")`
- **Files modified:** workspace/sci_fi_dashboard/llm_router.py
- **Verification:** All 10 tests pass (`pytest tests/test_provider_expansion.py -v`)
- **Committed in:** `9aaa421` (included in task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Bug fix was necessary for correctness — the pre-call budget check would have raised TypeError at runtime whenever it triggered. No scope creep.

## Issues Encountered

The real litellm `BudgetExceededError` has a different constructor signature than the placeholder class defined as fallback in llm_router.py. The placeholder `class BudgetExceededError(Exception): pass` accepts any args, so the mismatch was invisible during development. Tests exposed this by importing the real litellm class.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All Phase 6 (PROV-01 through PROV-04) requirements are now verified by tests
- `test_key_maps_in_sync` provides permanent drift protection for Phase 6 provider maps
- The BudgetExceededError fix ensures budget enforcement actually works at runtime
- Phase 7 (Bundled Skills Library) can proceed — no blockers

---
*Phase: 06-llm-provider-expansion*
*Completed: 2026-04-09*
