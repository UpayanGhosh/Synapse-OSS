---
phase: 06-llm-provider-expansion
plan: 02
subsystem: api
tags: [litellm, llm-router, deepseek, budget, provider-keys, sqlite]

# Dependency graph
requires:
  - phase: 06-llm-provider-expansion-plan-01
    provides: DeepSeek entry in provider_steps.py _KEY_MAP (mirror contract partner)
provides:
  - DeepSeek runtime key injection via llm_router.py _KEY_MAP
  - BudgetExceededError fallback handler in _do_call() and _do_tool_call()
  - get_provider_spend() helper for querying cumulative token spend per provider
  - Pre-call budget enforcement reading budget_usd/budget_duration from synapse.json
affects:
  - 06-llm-provider-expansion (all remaining plans depend on correct LLM dispatch)
  - All phases using SynapseLLMRouter (persona chat, inference loop, tool calls)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - BudgetExceededError import-guarded for older litellm version compatibility
    - Pre-call budget check uses token-count proxy (1M tokens ~= $1 USD) — safety net, not billing
    - get_provider_spend() is non-fatal, returns zeros on DB error to avoid blocking LLM calls
    - BudgetExceededError handler placed before except Exception catchall to ensure correct priority

key-files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/llm_router.py

key-decisions:
  - "BudgetExceededError import wrapped in try/except guard to handle older litellm versions gracefully"
  - "Budget check uses token count as USD proxy (1M tokens ~= $1) — keeps it simple, no per-model pricing table"
  - "get_provider_spend() is non-fatal (returns zeros on error) so corrupt DB never blocks LLM calls"
  - "Do NOT use litellm BudgetManager class — requires Redis and a running litellm proxy"
  - "Fallback uses self._config.model_mappings.get(role).get('fallback') NOT self._router.model_list (avoids litellm internal coupling)"

patterns-established:
  - "Provider budget enforcement: pre-call check in _do_call() using sessions table token counts"
  - "Symmetric error handling: _do_call() and _do_tool_call() have identical except clause chains"

requirements-completed: [PROV-01, PROV-02, PROV-03]

# Metrics
duration: 2min
completed: 2026-04-09
---

# Phase 6 Plan 02: LLM Provider Expansion — Budget & DeepSeek Summary

**DeepSeek added to runtime key injection, litellm BudgetExceededError fallback patched in both _do_call() and _do_tool_call(), and per-provider budget cap enforcement added via sessions table token-count proxy**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-09T07:47:16Z
- **Completed:** 2026-04-09T07:49:36Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- DeepSeek added to `_KEY_MAP` completing the mirror contract with `provider_steps.py` (Plan 01), enabling `_inject_provider_keys()` to inject `DEEPSEEK_API_KEY` at startup
- `BudgetExceededError` caught in both `_do_call()` and `_do_tool_call()` — triggers fallback model if configured, otherwise re-raises with warning log (fixes litellm GitHub #10052 gap)
- `get_provider_spend()` helper added: queries `sessions` table for cumulative token counts by provider prefix and time window (daily/weekly/monthly)
- Pre-call budget enforcement in `_do_call()` reads `budget_usd`/`budget_duration` from `synapse.json` providers config — zero overhead when not configured

## Task Commits

Each task was committed atomically:

1. **Task 1: Add BudgetExceededError fallback handler to _do_call() and _do_tool_call()** - `58254fb` (feat)
2. **Task 2: Add get_provider_spend() helper and pre-call budget check** - `18dbf73` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `workspace/sci_fi_dashboard/llm_router.py` - Added DeepSeek to _KEY_MAP, BudgetExceededError import guard, except BudgetExceededError handlers in _do_call() and _do_tool_call(), get_provider_spend() function, pre-call budget check

## Decisions Made
- BudgetExceededError import wrapped in try/except guard so the code works on older litellm versions where the exception doesn't exist yet (the placeholder class never matches, so the except clause is effectively inert)
- Budget uses token count as USD proxy rather than per-model pricing tables — pricing tables change frequently and this is a safety net, not a billing system
- get_provider_spend() is non-fatal by design: DB errors return zeros so a corrupt or missing sessions table never blocks LLM calls
- Fallback resolution uses `self._config.model_mappings.get(role, {}).get("fallback")` not `self._router.model_list` — avoids coupling to litellm Router internals

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
To use per-provider budget caps, add `budget_usd` and `budget_duration` to any provider in `synapse.json`:

```json
"providers": {
    "openai": {
        "api_key": "sk-...",
        "budget_usd": 10.0,
        "budget_duration": "monthly"
    }
}
```

`budget_duration` accepts `"daily"`, `"weekly"`, or `"monthly"`. If omitted, defaults to `"monthly"`.

## Next Phase Readiness
- DeepSeek key injection is live — Plan 01's provider_steps.py side completes the mirror contract
- Budget exhaustion now triggers fallback chain (not 500 errors) across all LLM call sites
- Plan 03 (if any) can rely on correct BudgetExceededError propagation

---
*Phase: 06-llm-provider-expansion*
*Completed: 2026-04-09*
