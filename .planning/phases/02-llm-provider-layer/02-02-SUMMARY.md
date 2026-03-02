---
phase: 02-llm-provider-layer
plan: 02
subsystem: llm
tags: [litellm, router, async, provider-routing, fallback, bedrock, ollama, github-copilot]

# Dependency graph
requires:
  - phase: 01-foundation-config
    provides: SynapseConfig dataclass in workspace/synapse_config.py with providers, channels, model_mappings fields
  - phase: 02-llm-provider-layer
    plan: 01
    provides: workspace/tests/test_llm_router.py RED scaffold (20 tests) and SynapseConfig.model_mappings field

provides:
  - SynapseLLMRouter class in workspace/sci_fi_dashboard/llm_router.py — unified async LLM dispatch via litellm.Router
  - build_router() function — builds litellm.Router from model_mappings with fallback chains and Ollama/vLLM api_base injection
  - _inject_provider_keys() function — injects provider API keys from SynapseConfig.providers into os.environ for litellm
  - litellm>=1.82.0,<1.83.0 pinned in pyproject.toml [project] dependencies
  - github_copilot_fake_auth autouse fixture in conftest.py — prevents OAuth flow during unit tests

affects:
  - 02-03-PLAN (api_gateway.py wiring — replace Brain/call_gemini_direct with SynapseLLMRouter.call())
  - 02-04-PLAN (skills/llm_router.py wiring — replace LLMRouter with SynapseLLMRouter)
  - All plans that call LLM APIs (must use SynapseLLMRouter.call(role, messages) not direct litellm calls)

# Tech tracking
tech-stack:
  added:
    - "litellm>=1.82.0,<1.83.0 — unified LLM dispatch layer covering all 25 providers"
  patterns:
    - "SynapseLLMRouter is instantiated once per process (FastAPI lifespan) and reused — not created per request"
    - "All provider API keys injected into os.environ before first acompletion() call via _inject_provider_keys()"
    - "Bedrock auth uses AWS_* env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION_NAME), not api_key"
    - "Ollama calls always use ollama_chat/ prefix — build_router() raises ValueError on bare ollama/ prefix"
    - "litellm.Router built with num_retries=0 — fallback chain handles redundancy, not same-model retries"
    - "call_model() bypasses Router for direct model string calls (tools server, validation pings)"
    - "github_copilot_fake_auth conftest fixture creates fake api-key.json to bypass OAuth in unit tests"

key-files:
  created:
    - workspace/sci_fi_dashboard/llm_router.py
  modified:
    - pyproject.toml
    - workspace/tests/test_llm_router.py
    - workspace/tests/conftest.py

key-decisions:
  - "num_retries=0 in litellm.Router — fallback chain (role → role_fallback) handles provider redundancy; retrying the same model on RateLimitError is not useful and breaks test expectations"
  - "Ollama prefix enforced via ValueError in build_router() — fail loud rather than silently routing to wrong endpoint"
  - "github_copilot_fake_auth is autouse so every test in the suite gets it — prevents accidental OAuth flows from other tests that happen to create Router instances"
  - "_inject_provider_keys() respects env var precedence: only injects if env var not already set"

patterns-established:
  - "All LLM calls: await router.call(role, messages) — never litellm.acompletion() directly in application code"
  - "Provider model strings only in synapse.json model_mappings — zero hardcoded strings in application code (enforced by test_no_hardcoded_models xfail)"
  - "build_router() raises ValueError on invalid model prefixes (ollama/) — makes misconfiguration immediately visible"
  - "conftest.py autouse fixture pattern for external auth services during unit tests (github_copilot_fake_auth)"

requirements-completed: [LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, LLM-09, LLM-10, LLM-11, LLM-12, LLM-13, LLM-14, LLM-15, LLM-16, LLM-17]

# Metrics
duration: 18min
completed: 2026-03-02
---

# Phase 2 Plan 02: SynapseLLMRouter Implementation Summary

**SynapseLLMRouter wrapping litellm.Router with 14-provider key injection, ollama_chat/ enforcement, and immediate-fallback routing — 19/20 tests GREEN, test_no_hardcoded_models XFAIL as expected**

## Performance

- **Duration:** 18 min
- **Started:** 2026-03-02T10:18:06Z
- **Completed:** 2026-03-02T10:36:27Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `workspace/sci_fi_dashboard/llm_router.py` (241 lines): SynapseLLMRouter class, build_router(), and _inject_provider_keys() — the unified litellm dispatch layer Plans 03/04 will wire into api_gateway.py and skills/llm_router.py
- Pinned `litellm>=1.82.0,<1.83.0` in pyproject.toml [project] dependencies to prevent litellm 2.x breaking changes
- All 19 tests GREEN (LLM-01 through LLM-15, test_fallback_on_auth_error, test_fallback_on_rate_limit, test_casual_route, test_vault_route), test_no_hardcoded_models correctly XFAIL
- Fixed test infrastructure: sys.path missing in test_llm_router.py and github_copilot OAuth flow triggered during Router init in unit tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Pin litellm in pyproject.toml** - `227c746` (chore)
2. **Task 2: Create workspace/sci_fi_dashboard/llm_router.py (SynapseLLMRouter)** - `d1d6ca5` (feat)

**Plan metadata:** (docs commit below)

_Note: Deviations (Rule 1 + Rule 2 fixes) committed as part of Task 2 atomic commit_

## Files Created/Modified

- `workspace/sci_fi_dashboard/llm_router.py` - New file; SynapseLLMRouter class, build_router(), _inject_provider_keys(); 241 lines; exports all three symbols; enforces ollama_chat/ prefix; stream=False on all Router entries
- `pyproject.toml` - Added `dependencies = ["litellm>=1.82.0,<1.83.0"]` under [project] section
- `workspace/tests/test_llm_router.py` - Added `sys.path.insert(0, str(Path(__file__).parent.parent))` to fix ModuleNotFoundError on synapse_config import
- `workspace/tests/conftest.py` - Added `github_copilot_fake_auth` autouse fixture to prevent OAuth device-code flow during Router init in unit tests

## Decisions Made

- `num_retries=0` in litellm.Router because: (a) fallback chain handles provider redundancy, (b) retrying same model on RateLimitError consumes quota without benefit, (c) test_fallback_on_rate_limit expects immediate fallback (call_count==2, not 3+)
- `_inject_provider_keys()` only injects if env var not already set — environment variable takes precedence over synapse.json (Layer 1 > Layer 2 consistency with SynapseConfig)
- `call_model()` added to bypass Router for direct model string calls — needed by tools server validation pings that must call specific Ollama models directly without role-based routing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ModuleNotFoundError for synapse_config in test_llm_router.py**
- **Found during:** Task 2 (running tests after creating llm_router.py)
- **Issue:** `test_llm_router.py` had `from synapse_config import SynapseConfig` without adding workspace/ to sys.path. When ROUTER_AVAILABLE was False (RED phase), the test was skipped before this import ran. Now that the router exists and tests execute, the import fails with ModuleNotFoundError.
- **Fix:** Added `sys.path.insert(0, str(Path(__file__).parent.parent))` before the synapse_config import (matches the pattern already used in test_config.py)
- **Files modified:** workspace/tests/test_llm_router.py
- **Verification:** Tests collected and ran successfully after fix
- **Committed in:** d1d6ca5 (Task 2 commit)

**2. [Rule 2 - Missing Critical] Added github_copilot_fake_auth autouse fixture to conftest.py**
- **Found during:** Task 2 (test_github_copilot_prefix failure)
- **Issue:** litellm 1.82.0 calls `GithubCopilotConfig._get_openai_compatible_provider_info()` during Router.__init__(), which calls `Authenticator.get_api_key()`, which triggers a 3-attempt GitHub OAuth device-code flow before raising `BadRequestError`. This causes a ~3 minute timeout and test failure with no way to bypass via api_key.
- **Fix:** Added `github_copilot_fake_auth` autouse fixture that (a) creates a temp directory, (b) writes a fake api-key.json with future expiry token, (c) sets `GITHUB_COPILOT_TOKEN_DIR` env var to redirect the Authenticator to the temp directory. Authenticator reads the cached token and skips OAuth entirely.
- **Files modified:** workspace/tests/conftest.py
- **Verification:** test_github_copilot_prefix PASSED in 25s total (vs ~3 min timeout before fix)
- **Committed in:** d1d6ca5 (Task 2 commit)

**3. [Rule 1 - Bug] Changed num_retries from 2 to 0 in build_router()**
- **Found during:** Task 2 (test_fallback_on_rate_limit failure)
- **Issue:** With `num_retries=2`, litellm.Router retries the primary model on RateLimitError before falling back. The mock provided `side_effect=[RateLimitError, mock_response]`, and `call_count==2` was expected with the second call being the fallback model. But the Router retried the same primary model first (call 1: RateLimitError, call 2: retry primary → succeeds), never reaching the fallback.
- **Fix:** Changed `num_retries=2` to `num_retries=0` — Router goes directly to fallback on first failure. The fallback chain handles redundancy; retrying the same failing model is counterproductive.
- **Files modified:** workspace/sci_fi_dashboard/llm_router.py
- **Verification:** test_fallback_on_rate_limit PASSED; test_fallback_on_auth_error still PASSED
- **Committed in:** d1d6ca5 (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs, 1 Rule 2 missing critical)
**Impact on plan:** All fixes required for correct test execution. No scope creep. The num_retries=0 change is actually a correctness improvement — immediate fallback is more useful behavior than retrying a rate-limited/auth-failed provider.

## Issues Encountered

- litellm 1.82.0 does not expose `__version__` attribute — used `pip show litellm` to verify version instead. Does not affect functionality.
- Background pytest process output handling on Windows required polling the output file directly.

## User Setup Required

None — no external service configuration required. Tests run fully offline with mocked litellm.acompletion.

## Next Phase Readiness

- Plan 03 (api_gateway.py wiring): SynapseLLMRouter ready to replace Brain singleton. Import: `from sci_fi_dashboard.llm_router import SynapseLLMRouter`
- Plan 04 (skills/llm_router.py wiring): SynapseLLMRouter ready to replace LLMRouter. All hardcoded model strings in workspace/sci_fi_dashboard/ and workspace/skills/ to be replaced with SynapseConfig.model_mappings lookups — test_no_hardcoded_models will flip from XFAIL to XPASS when done
- No blockers. SynapseLLMRouter contract is stable and fully tested.

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/llm_router.py
- FOUND: pyproject.toml with litellm>=1.82.0,<1.83.0 pin
- FOUND: .planning/phases/02-llm-provider-layer/02-02-SUMMARY.md
- FOUND commit 227c746: chore(02-02): pin litellm
- FOUND commit d1d6ca5: feat(02-02): implement SynapseLLMRouter

---
*Phase: 02-llm-provider-layer*
*Completed: 2026-03-02*
