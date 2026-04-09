---
phase: 06-llm-provider-expansion
verified: 2026-04-09T08:30:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
---

# Phase 6: LLM Provider Expansion Verification Report

**Phase Goal:** Users can route to any of 10+ LLM providers by editing synapse.json — no code changes. The litellm budget-fallback bug is patched so failover chains actually work.
**Verified:** 2026-04-09T08:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                             | Status     | Evidence                                                                                              |
|----|---------------------------------------------------------------------------------------------------|------------|-------------------------------------------------------------------------------------------------------|
| 1  | 10+ providers available in onboarding wizard for user selection                                  | VERIFIED   | 21 providers in PROVIDER_GROUPS confirmed via runtime import                                          |
| 2  | DeepSeek appears in wizard checkbox list (PROVIDER_GROUPS)                                        | VERIFIED   | `deepseek` key found in Major Cloud (US) group at line 124, provider_steps.py                        |
| 3  | DeepSeek has a validation ping model (VALIDATION_MODELS)                                          | VERIFIED   | `"deepseek": "deepseek/deepseek-chat"` at line 77, provider_steps.py                                 |
| 4  | DeepSeek env var is injected at runtime (llm_router._KEY_MAP)                                     | VERIFIED   | `"deepseek": "DEEPSEEK_API_KEY"` at line 227, llm_router.py                                          |
| 5  | _KEY_MAP dicts in provider_steps.py and llm_router.py stay in sync                               | VERIFIED   | test_key_maps_in_sync passes; only intentional divergence is qianfan (provider_steps only)           |
| 6  | litellm BudgetExceededError triggers fallback model instead of hard 500 error                     | VERIFIED   | except BudgetExceededError in _do_call() (line 853) and _do_tool_call() (line 1186) of llm_router.py |
| 7  | When no fallback is configured and budget is exceeded, error propagates cleanly with warning log  | VERIFIED   | handler re-raises after logger.error when fallback_cfg is falsy; test_budget_exceeded_no_fallback_raises passes |
| 8  | User can set budget_usd and budget_duration per provider in synapse.json                          | VERIFIED   | Pre-call check in _do_call() reads providers.*.budget_usd; synapse.json.example documents the schema |
| 9  | Budget cap enforcement is pre-call (fires before LLM call)                                        | VERIFIED   | Budget check is before try/acompletion block in _do_call(); test_pre_call_budget_check_raises_when_exceeded confirms no acompletion called |
| 10 | synapse.json.example documents DeepSeek provider config                                            | VERIFIED   | `"deepseek": {"api_key": "YOUR_DEEPSEEK_API_KEY"}` in synapse.json.example providers section         |
| 11 | croniter and sse-starlette declared as pip-installable dependencies                               | VERIFIED   | Both present in requirements.txt with version pins (>= 6.2.2 and >= 2.0.0)                           |
| 12 | togetherai key mismatch fixed in synapse.json.example                                             | VERIFIED   | `togetherai` key present, `together_ai` absent — confirmed via json.load check                       |

**Score:** 12/12 truths verified

---

### Required Artifacts

| Artifact                                         | Expected                                                        | Status     | Details                                                                                       |
|--------------------------------------------------|-----------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------------|
| `workspace/cli/provider_steps.py`                | DeepSeek in _KEY_MAP, VALIDATION_MODELS, PROVIDER_GROUPS        | VERIFIED   | All three maps contain deepseek; VALIDATION_MODELS["deepseek"] == "deepseek/deepseek-chat"   |
| `workspace/sci_fi_dashboard/llm_router.py`       | DeepSeek in _KEY_MAP + BudgetExceededError handler + get_provider_spend() | VERIFIED | deepseek in _KEY_MAP; except BudgetExceededError in both _do_call and _do_tool_call; get_provider_spend function at line 483 |
| `requirements.txt`                               | croniter and sse-starlette declarations                         | VERIFIED   | Lines 54-57 have both with version pins and inline comments                                   |
| `synapse.json.example`                           | DeepSeek entry + budget_usd/budget_duration documented          | VERIFIED   | deepseek provider entry present; openai entry has budget_usd and budget_duration fields        |
| `workspace/tests/test_provider_expansion.py`     | 10-test regression suite for all PROV requirements              | VERIFIED   | 10 tests across 3 classes; all pass in 3.98s                                                 |

---

### Key Link Verification

| From                                              | To                                              | Via                                              | Status   | Details                                                                                  |
|---------------------------------------------------|-------------------------------------------------|--------------------------------------------------|----------|------------------------------------------------------------------------------------------|
| provider_steps.py PROVIDER_GROUPS                 | provider_steps.py VALIDATION_MODELS             | every cloud provider has a VALIDATION_MODELS entry | VERIFIED | test_provider_groups_all_have_validation_models passes; exemptions: ollama, github_copilot, vllm |
| provider_steps.py _KEY_MAP                        | llm_router.py _KEY_MAP                          | identical deepseek entry                          | VERIFIED | Both have `"deepseek": "DEEPSEEK_API_KEY"`; test_key_maps_in_sync passes                 |
| llm_router.py _do_call()                          | litellm.exceptions.BudgetExceededError           | except clause triggers fallback                   | VERIFIED | except BudgetExceededError at line 853 with fallback_cfg lookup and re-raise path         |
| llm_router.py _do_call()                          | synapse.json providers.*.budget_usd              | SynapseConfig providers dict read                 | VERIFIED | self._config.providers.get(provider_prefix, {}).get("budget_usd") in pre-call block      |
| tests/test_provider_expansion.py                  | workspace/sci_fi_dashboard/llm_router.py         | imports _KEY_MAP, BudgetExceededError, get_provider_spend | VERIFIED | Import at line 24-28 of test file; all symbols resolve at runtime                       |
| tests/test_provider_expansion.py                  | workspace/cli/provider_steps.py                  | imports _KEY_MAP, VALIDATION_MODELS, PROVIDER_GROUPS | VERIFIED | Import at line 29-34 of test file; all symbols resolve at runtime                      |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description                                                             | Status    | Evidence                                                                                              |
|-------------|----------------|-------------------------------------------------------------------------|-----------|-------------------------------------------------------------------------------------------------------|
| PROV-01     | 06-01, 06-02, 06-03 | User can add OpenAI, Anthropic, DeepSeek, Mistral, or Together as providers via synapse.json | SATISFIED | DeepSeek in _KEY_MAP in both files; togetherai key fixed in synapse.json.example; _inject_provider_keys() active |
| PROV-02     | 06-02, 06-03   | User can set per-provider rate limits and budget caps in config          | SATISFIED | budget_usd/budget_duration fields read in _do_call() pre-call check; get_provider_spend() helper; synapse.json.example documents schema |
| PROV-03     | 06-02, 06-03   | litellm BudgetExceededError triggers fallback chain instead of hard error | SATISFIED | except BudgetExceededError in _do_call() and _do_tool_call(); fallback_role pattern used; BudgetExceededError constructor fix (3 positional args) applied in Plan 03 |
| PROV-04     | 06-01, 06-03   | Onboarding wizard offers all 10+ providers during setup                 | SATISFIED | 21 providers in PROVIDER_GROUPS; deepseek confirmed present in Major Cloud (US) group; all cloud providers have VALIDATION_MODELS entries |

No orphaned PROV-* requirements. All 4 IDs from REQUIREMENTS.md Phase 6 traceability table are satisfied.

---

### Anti-Patterns Found

| File                                    | Line | Pattern              | Severity | Impact  |
|-----------------------------------------|------|----------------------|----------|---------|
| workspace/sci_fi_dashboard/llm_router.py | 52   | `# ...placeholder`  | Info     | Comment describes the import-guard fallback class — it is intentional and correct, not a stub. No action needed. |

No blocker or warning anti-patterns found. The single "placeholder" keyword match is in a code comment describing the intentional fallback class behavior for older litellm versions.

---

### Human Verification Required

None. All phase 6 behaviors are verifiable via static analysis and unit tests. No visual UI, real-time streaming, or external service integration is involved in this phase.

---

### Test Results

All 10 tests in `workspace/tests/test_provider_expansion.py` pass:

```
tests/test_provider_expansion.py::TestProviderMaps::test_key_maps_in_sync              PASSED
tests/test_provider_expansion.py::TestProviderMaps::test_deepseek_in_llm_router_key_map PASSED
tests/test_provider_expansion.py::TestProviderMaps::test_deepseek_in_provider_steps     PASSED
tests/test_provider_expansion.py::TestProviderMaps::test_provider_groups_all_have_validation_models PASSED
tests/test_provider_expansion.py::TestBudgetFallback::test_budget_exceeded_error_importable PASSED
tests/test_provider_expansion.py::TestBudgetFallback::test_budget_exceeded_triggers_fallback PASSED
tests/test_provider_expansion.py::TestBudgetFallback::test_budget_exceeded_no_fallback_raises PASSED
tests/test_provider_expansion.py::TestBudgetEnforcement::test_get_provider_spend_returns_dict PASSED
tests/test_provider_expansion.py::TestBudgetEnforcement::test_get_provider_spend_accepts_all_durations PASSED
tests/test_provider_expansion.py::TestBudgetEnforcement::test_pre_call_budget_check_raises_when_exceeded PASSED

10 passed in 3.98s
```

---

### Notable Implementation Details

- **BudgetExceededError constructor fix:** Plan 03 caught and fixed a production bug — the original raise used a single string arg, but litellm's `BudgetExceededError.__init__` requires `(current_cost: float, max_budget: float, message: Optional[str])`. Fixed in commit `9aaa421`.
- **Import guard:** BudgetExceededError import is wrapped in try/except to handle older litellm versions gracefully — the placeholder class never matches a real exception.
- **qianfan intentional divergence:** provider_steps._KEY_MAP has `qianfan` (Baidu dual-key scheme) while llm_router._KEY_MAP does not. This is documented as `_PS_ONLY_KEYS` in the test file.
- **All 4 commits verified:** aed478f, 58254fb, 18dbf73, 9aaa421 all present in git history.

---

_Verified: 2026-04-09T08:30:00Z_
_Verifier: Claude (gsd-verifier)_
