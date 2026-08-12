---
phase: 04-onboarding-wizard-v2
verified: 2026-04-07T12:00:00Z
status: gaps_found
score: 10/12 must-haves verified
gaps:
  - truth: "Test suite for _run_sbs_questions correctly patches initialize_sbs_from_wizard"
    status: failed
    reason: "Tests patch 'cli.onboard.initialize_sbs_from_wizard' but onboard.py imports it inside each function body via deferred 'from cli.sbs_profile_init import ...' — no module-level attribute exists on cli.onboard, so patch() adds an attribute the function never reads. Correct target is 'cli.sbs_profile_init.initialize_sbs_from_wizard'."
    artifacts:
      - path: "workspace/tests/test_onboard_v2.py"
        issue: "All 10 occurrences of patch('cli.onboard.initialize_sbs_from_wizard') silently mis-patch — the intercepted mock is never called by _run_sbs_questions or _run_non_interactive"
    missing:
      - "Change all 10 patch() calls from 'cli.onboard.initialize_sbs_from_wizard' to 'cli.sbs_profile_init.initialize_sbs_from_wizard'"
  - truth: "Test for verify parallel execution (test_run_verify_parallel_providers) exists"
    status: failed
    reason: "Plan 04-04 specified test_run_verify_parallel_providers (test 39 in the plan). The test file ends at line 863 with test_run_verify_handles_validation_result_not_bool. No parallelism timing test exists in the file."
    artifacts:
      - path: "workspace/tests/test_onboard_v2.py"
        issue: "test_run_verify_parallel_providers is absent — the file has 5 verify tests but not this one"
    missing:
      - "Add test_run_verify_parallel_providers verifying asyncio.gather is called (parallelism can be structural, not timing-based)"
human_verification:
  - test: "Run 'python -m synapse setup' on a fresh machine"
    expected: "Wizard completes in under 5 minutes including provider validation, SBS questions, and WhatsApp import offer"
    why_human: "The 5-minute runtime claim requires a real machine with live provider API calls — cannot verify from static code analysis"
  - test: "Run 'python -m synapse setup --verify' with a real synapse.json"
    expected: "Outputs a table of PASS/FAIL per provider and channel, exits 0 on all pass, 1 on any fail"
    why_human: "Requires a configured installation with real provider keys and live network calls"
---

# Phase 4: Onboarding Wizard v2 Verification Report

**Phase Goal:** A brand-new user runs `python -m synapse setup` and reaches a personalized, meaningful baseline in under 5 minutes — with an initial SBS profile built from targeted questions, not just blank defaults.
**Verified:** 2026-04-07T12:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Success Criteria from ROADMAP.md

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Fresh install runs `python -m synapse setup` and completes with personalized config in ≤ 5 min | ? HUMAN | Command path verified: `__main__.py` → `synapse_cli.setup` → `onboard.run_wizard`. Runtime cannot be verified statically. |
| 2 | After wizard, SBS profile has 3+ non-empty layers (linguistic, emotional_state, interaction) from wizard questions | ✓ VERIFIED | `initialize_sbs_from_wizard()` writes all 4 layers (linguistic, emotional_state, domain, interaction) via `ProfileManager.save_layer()`. Each uses wizard answers with safe defaults. |
| 3 | Wizard questions cover: communication style, interests, privacy sensitivity, chat history import | ✓ VERIFIED | `_run_sbs_questions()` asks 4 questions in order: style, energy, interests, privacy — plus WhatsApp import offer |
| 4 | `python -m synapse setup --non-interactive` with env vars completes without prompts, exit 0 | ✓ VERIFIED | `_run_non_interactive()` reads all 4 SBS env vars; validates values against STYLE/ENERGY/PRIVACY_CHOICES constants; calls `initialize_sbs_from_wizard()` only when at least one SBS var is set |
| 5 | `python -m synapse setup --verify` tests each provider and channel, reports pass/fail per item | ✓ VERIFIED | `verify_steps.py` has `run_verify()` returning 0/1; uses `asyncio.gather` for parallel providers; covers all 4 channel types |

**Score:** 4/5 criteria fully verifiable (1 needs human runtime test)

---

### Observable Truths (from Plan 04-01 must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `python -m synapse setup` invokes the wizard | ✓ VERIFIED | `workspace/__main__.py` imports `app` from `synapse_cli`; `synapse_cli.setup` command dispatches to `run_wizard()` when `--verify` not set |
| 2 | Wizard asks 4 SBS persona questions after provider/channel setup | ✓ VERIFIED | `_run_sbs_questions()` at line 877 in `onboard.py`; 4 prompter calls (select×3, multiselect×1); called after `write_config()` at line 1165 |
| 3 | SBS profile layers (linguistic, emotional_state, domain, interaction) written from wizard answers | ✓ VERIFIED | `initialize_sbs_from_wizard()` writes all 4 layers via `mgr.save_layer()`. Each call individually try/excepted. |
| 4 | domain layer includes both interests dict AND active_domains list | ✓ VERIFIED | Lines 158-165 in `sbs_profile_init.py`: `domain["interests"][topic] = 1.0` for each interest AND `domain["active_domains"] = interests` |
| 5 | compiler.py `_compile_style()` reads preferred_style and emits natural-language prompt segment | ✓ VERIFIED | Lines 137, 148-154, 161 in `compiler.py`: `style.get("preferred_style", "")` → `style_directives.get(preferred_style, "")` appended to output |
| 6 | compiler.py `_compile_interaction()` reads privacy_sensitivity and emits a privacy directive | ✓ VERIFIED | Lines 198-205 in `compiler.py`: `interaction.get("privacy_sensitivity", "")` → `privacy_directives[privacy]` appended to parts list |
| 7 | Wizard offers WhatsApp history import as an optional step | ✓ VERIFIED | Lines 950-968 in `onboard.py`: `prompter.confirm(...)` with `default=False`, then `subprocess.run([sys.executable, "scripts/import_whatsapp.py", ...])` when accepted and file exists |
| 8 | Existing onboard tests still pass — SBS questions are patchable | ? UNCERTAIN | `_run_sbs_questions` is defined as a standalone function (patchable as `cli.onboard._run_sbs_questions`). However, the test file patches `cli.onboard.initialize_sbs_from_wizard` (wrong target) — existing tests in `test_onboard.py` may not be affected since they predate SBS questions, but new tests in `test_onboard_v2.py` won't intercept the actual SBS init call |

**Score (Plan 04-01 truths):** 7/8 verified (1 uncertain due to patch target gap)

### Observable Truths (from Plan 04-02 must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `synapse setup --verify` tests all configured providers and reports pass/fail | ✓ VERIFIED | `run_verify()` iterates `config.providers`, calls `_validate_all_providers`, prints PASS/FAIL table |
| 2 | `synapse setup --verify` tests all configured channels and reports pass/fail | ✓ VERIFIED | `_validate_channels()` covers telegram, discord, slack, whatsapp (last is always PASS with note) |
| 3 | `synapse setup --verify` is read-only — never modifies synapse.json | ✓ VERIFIED | No `write_config` call anywhere in `verify_steps.py`; function is explicitly documented as READ-ONLY |
| 4 | Provider validation runs in parallel via asyncio.gather | ✓ VERIFIED | Line 130 in `verify_steps.py`: `asyncio.gather(*coros, return_exceptions=True)` |
| 5 | Exit code 0 on all-pass, exit code 1 on any failure | ✓ VERIFIED | `run_verify()` returns 0 or 1; `synapse_cli.setup` does `raise typer.Exit(run_verify(...))` |

**Score (Plan 04-02 truths):** 5/5 verified

### Observable Truths (from Plan 04-03 must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `synapse setup --non-interactive` with SBS env vars writes profile layers | ✓ VERIFIED | Lines 263-327 in `onboard.py`: reads 4 SBS env vars, calls `initialize_sbs_from_wizard()` with validated values |
| 2 | Without SBS env vars, non-interactive uses defaults silently | ✓ VERIFIED | Lines 268: `if any([communication_style, energy_level, interests_raw, privacy_level]):` — block skipped entirely when all empty |
| 3 | Missing SBS env vars do not cause errors in non-interactive mode | ✓ VERIFIED | Entire SBS block wrapped in try/except; each validate call only fires when the var is non-empty |
| 4 | SYNAPSE_COMMUNICATION_STYLE, SYNAPSE_ENERGY_LEVEL, SYNAPSE_INTERESTS, SYNAPSE_PRIVACY_LEVEL are the env vars | ✓ VERIFIED | All 4 present at lines 263-266; docstring updated at lines 142-151 |

**Score (Plan 04-03 truths):** 4/4 verified

### Observable Truths (from Plan 04-04 must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Test suite covers all 5 ONBOARD2 requirements | ✓ VERIFIED | 5 test classes, each mapped to one or more ONBOARD2 requirement IDs in their docstrings |
| 2 | SBS profile initialization is tested with mock ProfileManager | ✓ VERIFIED | `TestSBSProfileInit._call_with_mock_mgr()` mocks ProfileManager and patches SynapseConfig |
| 3 | emotional_state layer write is tested — wizard energy_level maps to current_dominant_mood | ✓ VERIFIED | Tests at lines 160-189 cover all 3 energy mappings: high_energy→energetic, calm_and_steady→calm, adaptive→neutral |
| 4 | domain layer write is tested — both interests dict AND active_domains list are written | ✓ VERIFIED | Test at lines 191-205 asserts `interests["technology"] == 1.0` AND `active_domains == ["technology", "music"]` |
| 5 | compiler `_compile_style()` tested — preferred_style emits tone directive | ✓ VERIFIED | 5 compiler style tests at lines 281-336 cover all 4 style values + absent-field backward compatibility |
| 6 | compiler `_compile_interaction()` tested — privacy_sensitivity emits privacy directive | ✓ VERIFIED | 5 compiler interaction tests at lines 340-387 cover all 3 privacy values + absent-field + privacy-only (no peak_hours) |
| 7 | compiler `_compile_emotional()` tested — energetic and calm produce non-neutral instructions | ✓ VERIFIED | Tests at lines 398-426 assert neither "normal mode" nor "be your usual self" appear in energetic/calm output |
| 8 | Non-interactive SBS env vars are tested (set, missing, invalid) including SYNAPSE_ENERGY_LEVEL | ✓ VERIFIED | 6 tests in TestNonInteractiveSBS covering all-set, none-set, invalid style, invalid energy, invalid privacy, unknown interests |
| 9 | Verify subcommand is tested (pass and fail cases) | ✓ VERIFIED | 5 tests in TestVerifySubcommand covering pass, fail, no-config, read-only, ValidationResult.ok guard |
| 10 | Verify tests use ValidationResult.ok (not raw truthiness) | ✓ VERIFIED | `test_run_verify_handles_validation_result_not_bool` at line 828 explicitly tests this guard |
| 11 | WhatsApp import offer is tested (accept and decline) | ✓ VERIFIED | Tests at lines 473-513 cover both accept (subprocess called with import_whatsapp.py) and decline (subprocess not called) |
| 12 | Tests use correct patch target for initialize_sbs_from_wizard | ✗ FAILED | All 10 patch calls use `'cli.onboard.initialize_sbs_from_wizard'` but the function is imported inside each function body — no module-level attribute exists on `cli.onboard`. The patch silently creates a new attribute the functions never read. Correct target: `'cli.sbs_profile_init.initialize_sbs_from_wizard'` |

**Score (Plan 04-04 truths):** 11/12 verified (1 failed on patch target)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `workspace/__main__.py` | python -m synapse entrypoint | ✓ VERIFIED | 6 lines; imports `app` from `synapse_cli`; `if __name__ == "__main__": app()` |
| `workspace/cli/sbs_profile_init.py` | SBSProfileInitializer | ✓ VERIFIED | 183 lines; exports `initialize_sbs_from_wizard`, `STYLE_CHOICES`, `INTEREST_CHOICES`, `PRIVACY_CHOICES`, `ENERGY_CHOICES`, plus display maps |
| `workspace/synapse_cli.py` | setup command alias | ✓ VERIFIED | `setup` command at line 100; has `--verify`, `--non-interactive`, `--flow`, `--accept-risk`, `--reset` flags |
| `workspace/cli/onboard.py` | `_run_sbs_questions` in interactive wizard | ✓ VERIFIED | Defined at line 877; called at line 1165 in `_run_interactive_impl` after `write_config()` |
| `workspace/sci_fi_dashboard/sbs/injection/compiler.py` | Extended `_compile_style` reads preferred_style | ✓ VERIFIED | Line 137: `preferred_style = style.get("preferred_style", "")`. Style directives dict at lines 148-154. `.rstrip()` handles empty case. |
| `workspace/cli/verify_steps.py` | `run_verify()` with parallel provider validation | ✓ VERIFIED | 363 lines; `run_verify()` at line 275; `asyncio.gather` at line 130; Rich+plaintext fallback |
| `workspace/tests/test_onboard_v2.py` | Complete test coverage for Phase 4 | ✓ SUBSTANTIVE (with gap) | 862 lines; 5 test classes; 40 test methods. Patch target bug means `_run_sbs_questions` and `_run_non_interactive` SBS tests don't intercept the real function. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `workspace/__main__.py` | `workspace/synapse_cli.py` | `from synapse_cli import app` | ✓ WIRED | Line 3 in `__main__.py`: `from synapse_cli import app` |
| `workspace/cli/onboard.py` | `workspace/cli/sbs_profile_init.py` | `initialize_sbs_from_wizard` in `_run_sbs_questions` | ✓ WIRED | Line 893-898 in `onboard.py`: deferred import inside `_run_sbs_questions()`; called at line 939 |
| `workspace/cli/sbs_profile_init.py` | `workspace/sci_fi_dashboard/sbs/profile/manager.py` | `mgr.save_layer()` for all 4 layers | ✓ WIRED | Lines 134, 147, 165, 176 in `sbs_profile_init.py`: `mgr.save_layer("linguistic", ...)`, `mgr.save_layer("emotional_state", ...)`, `mgr.save_layer("domain", ...)`, `mgr.save_layer("interaction", ...)` |
| `workspace/sci_fi_dashboard/sbs/injection/compiler.py` | wizard-written fields | `preferred_style` read in `_compile_style`; `privacy_sensitivity` in `_compile_interaction` | ✓ WIRED | `preferred_style` at compiler line 137; `privacy_sensitivity` at compiler line 198 |
| `workspace/cli/verify_steps.py` | `workspace/cli/provider_steps.py` | `validate_provider` and `validate_ollama` calls | ✓ WIRED | Deferred imports at lines 62, 84; `result.ok` extracted (not raw truthiness) |
| `workspace/cli/verify_steps.py` | `workspace/cli/channel_steps.py` | `validate_telegram_token`, `validate_discord_token`, `validate_slack_tokens` | ✓ WIRED | Deferred imports at lines 160, 174, 189; all 4 channel types covered |
| `workspace/synapse_cli.py` | `workspace/cli/verify_steps.py` | `setup --verify` deferred import | ✓ WIRED | Line 137 in `synapse_cli.py`: `from cli.verify_steps import run_verify` inside `if verify:` block |
| `workspace/tests/test_onboard_v2.py` | `workspace/cli/sbs_profile_init.py` | `initialize_sbs_from_wizard` via correct `_call_with_mock_mgr` | ✓ WIRED (unit layer tests) | `TestSBSProfileInit._call_with_mock_mgr` patches `cli.sbs_profile_init.ProfileManager` and `cli.sbs_profile_init.SynapseConfig` — these are correct patch targets |
| `workspace/tests/test_onboard_v2.py` | `workspace/cli/onboard.initialize_sbs_from_wizard` | patch in `TestSBSQuestions` and `TestNonInteractiveSBS` | ✗ NOT WIRED | Patch target `cli.onboard.initialize_sbs_from_wizard` does not exist as a module attribute. The `from ... import` inside each function creates a local binding, not a module attribute. The mock is never called by the real functions. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| ONBOARD2-01 | 04-01, 04-04 | `python -m synapse setup` completes full setup in under 5 minutes | ✓ SATISFIED | `__main__.py` + `synapse_cli.setup` command exist and wire correctly; 5-minute runtime needs human |
| ONBOARD2-02 | 04-01, 04-03, 04-04 | Wizard builds initial SBS profile via targeted questions | ✓ SATISFIED | `_run_sbs_questions()` asks 4 questions; `initialize_sbs_from_wizard()` writes linguistic, emotional_state, domain (with active_domains), interaction layers |
| ONBOARD2-03 | 04-01, 04-03, 04-04 | Wizard offers WhatsApp history import during setup | ✓ SATISFIED | `prompter.confirm("Would you like to import...")` with default=False; `subprocess.run(["scripts/import_whatsapp.py", ...])` on accept |
| ONBOARD2-04 | 04-03, 04-04 | Wizard supports `--non-interactive` flag with env vars | ✓ SATISFIED | `_run_non_interactive()` reads SYNAPSE_COMMUNICATION_STYLE, SYNAPSE_ENERGY_LEVEL, SYNAPSE_INTERESTS, SYNAPSE_PRIVACY_LEVEL; validates against choice constants; graceful defaults |
| ONBOARD2-05 | 04-02, 04-04 | `python -m synapse setup --verify` confirms providers and channels | ✓ SATISFIED | `verify_steps.run_verify()` exists; parallel provider validation via `asyncio.gather`; 4 channel types; Rich+plaintext output; exits 0/1 |

**All 5 requirements satisfied at the implementation level.** Test coverage for ONBOARD2-02 and ONBOARD2-04 has the patch target bug noted above, meaning some test assertions about `initialize_sbs_from_wizard` being called will silently pass even if the function is NOT called (or silently pass even if it IS called with wrong args).

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `workspace/tests/test_onboard_v2.py` | 458, 492, 508, 521, 558, 590, 620, 653, 684, 715 | `patch("cli.onboard.initialize_sbs_from_wizard")` on a non-existent module attribute | ✗ Blocker for test correctness | Tests in `TestSBSQuestions` and `TestNonInteractiveSBS` that assert `mock_init.assert_called_once()` or `mock_init.assert_not_called()` are asserting against a mock that was never connected to the real call site. The tests will always pass (mock_init reports 0 calls) even if the implementation is broken. |
| `workspace/cli/verify_steps.py` | 227 | `assert _RICH_AVAILABLE and Table is not None and console is not None` — bare assert in production code | ⚠️ Warning | `assert` statements are stripped with `python -O`. Should be an `if` guard. Low risk given Rich is optional and `_print_results_rich` is only called when `_RICH_AVAILABLE` is already True. |

---

## Human Verification Required

### 1. 5-Minute Fresh Install Timing

**Test:** On a clean machine (no `~/.synapse/`), run `python -m synapse setup` with a valid Gemini API key.
**Expected:** Wizard completes in under 5 minutes including: provider validation (live API call), SBS questions (4), and optionally WhatsApp import offer.
**Why human:** Runtime timing requires a live machine with network access. Provider validation makes real API calls.

### 2. End-to-End `--verify` with Live Config

**Test:** After a complete setup, run `python -m synapse setup --verify`.
**Expected:** Each configured provider shows PASS/FAIL based on live API response. Exit code 0 if all pass, 1 if any fail. No modifications to `synapse.json`.
**Why human:** Requires real provider API keys and live network. Static code verified the pass/fail logic but not the actual HTTP round-trips.

---

## Gaps Summary

### Gap 1: Wrong patch target for `initialize_sbs_from_wizard` in tests (Blocker)

Both `_run_sbs_questions()` and `_run_non_interactive()` import `initialize_sbs_from_wizard` inside their function bodies using deferred `from cli.sbs_profile_init import ...`. This creates a local binding within each function invocation, not a module-level attribute on `cli.onboard`.

`unittest.mock.patch("cli.onboard.initialize_sbs_from_wizard")` creates a new attribute on the `cli.onboard` module namespace during the patch context. But because the function uses `from ... import` (not `cli.sbs_profile_init.initialize_sbs_from_wizard`), the local name inside the function points to the original function object, not the patched one.

**Concrete effect:**
- `TestSBSQuestions.test_run_sbs_questions_calls_initialize`: `mock_init.assert_called_once()` will FAIL because the mock was never connected.
- `TestSBSQuestions.test_run_sbs_questions_failure_does_not_crash_wizard`: `side_effect=Exception(...)` is never triggered — the real function runs.
- All 6 `TestNonInteractiveSBS` tests: same problem.

**Fix:** Change all 10 patch targets from `"cli.onboard.initialize_sbs_from_wizard"` to `"cli.sbs_profile_init.initialize_sbs_from_wizard"`.

### Gap 2: Missing `test_run_verify_parallel_providers` test (Minor)

Plan 04-04 specified a test verifying `asyncio.gather` is used for parallel provider validation (test 39). This test is absent. The implementation correctly uses `asyncio.gather` (verified in code), but the test plan's intent to explicitly verify parallelism is unmet.

**Fix:** Add a structural test asserting `asyncio.gather` is called when multiple providers are configured (timing-based parallelism tests are fragile; structural assertion is sufficient).

---

*Verified: 2026-04-07T12:00:00Z*
*Verifier: Claude (gsd-verifier)*
