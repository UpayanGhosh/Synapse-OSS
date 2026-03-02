---
phase: 02-llm-provider-layer
plan: 03
subsystem: llm
tags: [litellm, router, async, sync-wrapper, ollama, skills, thread-pool]

# Dependency graph
requires:
  - phase: 01-foundation-config
    provides: SynapseConfig dataclass in workspace/synapse_config.py with providers, channels, model_mappings fields
  - phase: 02-llm-provider-layer
    plan: 02
    provides: SynapseLLMRouter class in workspace/sci_fi_dashboard/llm_router.py — unified async LLM dispatch via litellm.Router

provides:
  - workspace/skills/llm_router.py rewritten — LLMRouter.generate() backed by SynapseLLMRouter.call() via _run_async()
  - _run_async() helper — safe sync-to-async bridge using ThreadPoolExecutor when event loop already running
  - Ollama fallback when SynapseLLMRouter unavailable (no synapse.json) or raises any exception
  - All openclaw/antigravity/urllib.request/gateway_token references removed from skills/llm_router.py

affects:
  - 02-04-PLAN (api_gateway.py wiring — SynapseLLMRouter now also used by skills callers)
  - db/tools.py, db/model_orchestrator.py (use llm singleton — interface unchanged, now litellm-backed)
  - test_llm_router.py (test_no_hardcoded_models XFAIL until Plan 04 sweeps call sites)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_run_async() pattern: try asyncio.get_running_loop() — if running, use ThreadPoolExecutor(max_workers=1) to call asyncio.run() on worker thread; otherwise asyncio.run() directly"
    - "LLMRouter.__init__ wraps SynapseLLMRouter init in try/except — graceful Ollama-only degradation when synapse.json absent"
    - "role selection from cloud_models[0]: if first entry is a key in model_mappings, use it as role; else default to 'casual'"

key-files:
  created: []
  modified:
    - workspace/skills/llm_router.py

key-decisions:
  - "_run_async() uses ThreadPoolExecutor not nest_asyncio — clean solution that avoids installing an extra library and works in both sync and async contexts without patching asyncio internals"
  - "force_kimi arg preserved in generate() signature for backward compat but ignored — role-based routing replaces old Kimi/NVIDIA path"
  - "cloud_models defaults to ['casual'] instead of ['google-antigravity/gemini-3-flash'] — 'casual' is a valid synapse role name, not a provider-qualified model string"
  - "kimi_model = cloud_models[0] backward-compat attribute preserved — db/server.py status payload reads this field"

patterns-established:
  - "Sync callers use llm.generate() — never call SynapseLLMRouter directly from sync code"
  - "_run_async() is the canonical pattern for bridging sync→async in the skills layer"

requirements-completed: [LLM-01, LLM-06, LLM-18]

# Metrics
duration: 2min
completed: 2026-03-02
---

# Phase 2 Plan 03: skills/llm_router.py Rewrite Summary

**LLMRouter.generate() now dispatches through SynapseLLMRouter.call() (litellm backend) via a ThreadPoolExecutor-based sync wrapper, with automatic Ollama fallback — all urllib.request and openclaw gateway code removed**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-02T10:41:54Z
- **Completed:** 2026-03-02T10:44:46Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Rewrote `workspace/skills/llm_router.py` (183 lines deleted → 126 lines): removed `_call_antigravity()`, `_load_gateway_config()`, `_normalize_google_model()`, `_call_kimi()`, `_extract_gateway_text()`, SAFETY_SETTINGS, and all urllib.request imports
- Added `_run_async()` helper: safe sync-to-async bridge using `concurrent.futures.ThreadPoolExecutor(max_workers=1)` when called from a running event loop (FastAPI handlers), falling back to direct `asyncio.run()` in sync contexts (db/tools.py)
- `LLMRouter.__init__` initialises `SynapseLLMRouter` via `SynapseConfig.load()`; silently falls back to Ollama-only when synapse.json is absent or litellm is unavailable — no ImportError raised at module import
- All 19 tests in `test_llm_router.py` GREEN; `test_no_hardcoded_models` correctly XFAIL (Plan 04 responsibility)

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite workspace/skills/llm_router.py to use SynapseLLMRouter** - `557f14a` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `workspace/skills/llm_router.py` - Rewritten; LLMRouter.generate() backed by SynapseLLMRouter.call() via _run_async(); all openclaw/antigravity/urllib.request code removed; _sanitize(), _call_ollama(), embed() preserved unchanged; llm singleton at module bottom works after rewrite

## Decisions Made

- `_run_async()` uses `ThreadPoolExecutor` not `nest_asyncio` — avoids patching asyncio internals and works in both sync and async contexts cleanly
- `cloud_models` defaults to `["casual"]` instead of `["google-antigravity/gemini-3-flash"]` — `"casual"` is a valid synapse role name, so `LLMRouter()` with no args uses the default casual routing path
- `force_kimi` preserved in `generate()` signature with `# ARG002` noqa comment — backward compat for any callers that pass it positionally

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. SynapseLLMRouter falls back to Ollama when synapse.json is absent.

## Next Phase Readiness

- Plan 04 (api_gateway.py wiring): Both SynapseLLMRouter (for FastAPI async handlers) and LLMRouter (for sync skills callers) are now wired to litellm. Next: replace Brain singleton and call_gemini_direct() in api_gateway.py with SynapseLLMRouter.call()
- `test_no_hardcoded_models` XFAIL until Plan 04 sweeps hardcoded model strings in workspace/sci_fi_dashboard/ and workspace/skills/
- No blockers.

## Self-Check: PASSED

- FOUND: workspace/skills/llm_router.py (rewritten, 126 lines)
- FOUND commit 557f14a: feat(02-03): rewrite skills/llm_router.py to use SynapseLLMRouter
- VERIFIED: zero matches for antigravity|gateway_token|urllib.request|OPENCLAW in skills/llm_router.py
- VERIFIED: SynapseLLMRouter import present in skills/llm_router.py
- VERIFIED: 19 tests GREEN, 1 XFAIL in test_llm_router.py

---
*Phase: 02-llm-provider-layer*
*Completed: 2026-03-02*
