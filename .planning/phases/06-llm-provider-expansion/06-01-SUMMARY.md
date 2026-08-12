---
phase: 06-llm-provider-expansion
plan: 01
subsystem: llm-routing
tags: [deepseek, litellm, onboarding-wizard, provider-config, croniter, sse-starlette]

# Dependency graph
requires: []
provides:
  - DeepSeek as a fully-recognized provider in the onboarding wizard (VALIDATION_MODELS, _KEY_MAP, PROVIDER_GROUPS)
  - croniter and sse-starlette declared in requirements.txt for cron scheduling and SSE dashboard events
  - synapse.json.example documenting DeepSeek provider config and budget_usd/budget_duration cap fields
  - together_ai key mismatch fixed (now togetherai to match _KEY_MAP contract)
affects:
  - 06-02 (llm_router.py side of _KEY_MAP mirror contract for DeepSeek)
  - 06-03 (budget enforcement relies on synapse.json.example budget fields as doc)
  - 10-cron-dash (croniter dependency declared here)
  - 10-cron-dash (sse-starlette dependency declared here)

# Tech tracking
tech-stack:
  added:
    - croniter>=6.2.2 (cron expression parsing)
    - sse-starlette>=2.0.0 (SSE endpoints)
  patterns:
    - _KEY_MAP in provider_steps.py mirrors llm_router.py exactly — any new provider must appear in both files
    - synapse.json.example providers use api_key field; budget_usd/budget_duration fields are optional cap docs

key-files:
  created: []
  modified:
    - workspace/cli/provider_steps.py
    - requirements.txt
    - synapse.json.example

key-decisions:
  - "DeepSeek placed in Major Cloud (US) group, not Chinese Providers — USD pricing, globally accessible"
  - "deepseek/deepseek-chat chosen as validation model — cheapest chat model; deepseek-reasoner excluded due to special response format"
  - "together_ai renamed to togetherai in synapse.json.example to eliminate silent key injection mismatch"
  - "budget_usd/budget_duration documented on openai entry as canonical example for PROV-02 budget enforcement"

patterns-established:
  - "Provider registration pattern: add to VALIDATION_MODELS + _KEY_MAP + PROVIDER_GROUPS (all three required)"
  - "PROVIDER_LIST is auto-derived from PROVIDER_GROUPS — no separate update needed"

requirements-completed: [PROV-01, PROV-04]

# Metrics
duration: 2min
completed: 2026-04-09
---

# Phase 06 Plan 01: LLM Provider Expansion Foundation Summary

**DeepSeek added to onboarding wizard provider maps, croniter/sse-starlette declared for Phase 6 v3.0, and together_ai key mismatch fixed in synapse.json.example**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-09T07:47:01Z
- **Completed:** 2026-04-09T07:48:47Z
- **Tasks:** 1 of 1
- **Files modified:** 3

## Accomplishments

- DeepSeek is now a fully-recognized provider in the onboarding wizard: validation ping model (`deepseek/deepseek-chat`), env var mapping (`DEEPSEEK_API_KEY`), and checkbox display in the Major Cloud (US) group
- `croniter>=6.2.2` and `sse-starlette>=2.0.0` declared as explicit dependencies in requirements.txt — both were previously imported but undeclared (pre-existing dependency gap closed at Phase 6 entry)
- `synapse.json.example` now documents DeepSeek provider config and OpenAI budget cap fields (`budget_usd`, `budget_duration`) as reference for PROV-02
- Fixed silent bug: `together_ai` key in synapse.json.example renamed to `togetherai` to match the `_KEY_MAP` contract; previously `_inject_provider_keys()` would silently ignore Together AI keys

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DeepSeek to provider_steps.py maps and update config files** - `aed478f` (feat)

**Plan metadata:** (follows in final docs commit)

## Files Created/Modified

- `workspace/cli/provider_steps.py` - Added DeepSeek to VALIDATION_MODELS, _KEY_MAP, PROVIDER_GROUPS
- `requirements.txt` - Declared croniter and sse-starlette with version pins and inline comments
- `synapse.json.example` - Fixed togetherai key, added deepseek provider entry, documented budget_usd/budget_duration on openai entry

## Decisions Made

- DeepSeek placed in "Major Cloud (US)" group rather than "Chinese Providers" — DeepSeek serves global users with USD pricing and is the primary non-Chinese-market use case
- `deepseek/deepseek-chat` chosen as the validation ping model; `deepseek-reasoner` excluded because its response format (chain-of-thought `reasoning_content` field) is not yet handled in the pipeline
- `budget_usd`/`budget_duration` documented on the `openai` entry as the canonical example — OpenAI is the most common provider to budget-cap

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. DeepSeek API key setup is handled by the onboarding wizard (`DEEPSEEK_API_KEY` env var).

## Next Phase Readiness

- Plan 02 must mirror the `_KEY_MAP` DeepSeek entry to `workspace/sci_fi_dashboard/llm_router.py` (the contract requires both files stay in sync)
- croniter and sse-starlette are now pip-installable; Plan 10 (cron/dash) can import them without dependency errors
- Budget cap documentation in synapse.json.example provides the config schema reference for Plan 03 (PROV-02 enforcement)

---
*Phase: 06-llm-provider-expansion*
*Completed: 2026-04-09*

## Self-Check: PASSED

- workspace/cli/provider_steps.py: FOUND
- requirements.txt: FOUND
- synapse.json.example: FOUND
- .planning/phases/06-llm-provider-expansion/06-01-SUMMARY.md: FOUND
- Commit aed478f: FOUND
