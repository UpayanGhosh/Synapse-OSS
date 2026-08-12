---
phase: 2
slug: safe-self-modification-rollback
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| **Config file** | `workspace/tests/pytest.ini` |
| **Quick run command** | `cd workspace && python -m pytest tests/test_snapshot_engine.py tests/test_consent_protocol.py -v -x` |
| **Full suite command** | `cd workspace && python -m pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds (unit) / ~90 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `cd workspace && python -m pytest tests/test_snapshot_engine.py tests/test_consent_protocol.py -v -x`
- **After every plan wave:** Run `cd workspace && python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite green (minus 2 pre-existing Sentinel failures noted below)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | MOD-02 | T-02-03 | Snapshot write is atomic (temp+rename) | unit | `pytest tests/test_snapshot_engine.py::test_snapshot_atomicity -x` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | MOD-10 | — | Restore from snapshot directory only | unit | `pytest tests/test_snapshot_engine.py::test_restore_without_prior_snapshots -x` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 1 | MOD-02 | — | Snapshot created after confirm | unit | `pytest tests/test_snapshot_engine.py::test_snapshot_created_after_confirm -x` | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 1 | MOD-07 | T-02-01 | Zone 1 writes rejected at Sentinel level | unit | `pytest tests/test_zone_registry.py::test_zone1_paths_all_blocked -x` | ❌ W0 | ⬜ pending |
| 2-02-02 | 02 | 1 | MOD-08 | — | Zone 2 paths all writable | unit | `pytest tests/test_zone_registry.py::test_zone2_paths_all_writable -x` | ❌ W0 | ⬜ pending |
| 2-03-01 | 03 | 2 | MOD-01 | T-02-04 | Consent explains before any write | unit | `pytest tests/test_consent_protocol.py::test_explanation_before_write -x` | ❌ W0 | ⬜ pending |
| 2-03-02 | 03 | 2 | MOD-03 | — | Auto-revert on failure | unit | `pytest tests/test_consent_protocol.py::test_auto_revert_on_failure -x` | ❌ W0 | ⬜ pending |
| 2-03-03 | 03 | 2 | MOD-01 | T-02-02 | Consent is session-scoped (no cross-user hijack) | unit | `pytest tests/test_consent_protocol.py::test_consent_session_scoped -x` | ❌ W0 | ⬜ pending |
| 2-04-01 | 04 | 3 | MOD-01 | — | Modification intent intercept before LLM call | unit | `pytest tests/test_consent_protocol.py::test_intercept_before_llm -x` | ❌ W0 | ⬜ pending |
| 2-05-01 | 05 | 3 | MOD-04 | T-02-03 | Rollback by date string | unit | `pytest tests/test_rollback.py::test_rollback_by_date -x` | ❌ W0 | ⬜ pending |
| 2-05-02 | 05 | 3 | MOD-05 | — | Rollback by "undo last" | unit | `pytest tests/test_rollback.py::test_rollback_undo_last -x` | ❌ W0 | ⬜ pending |
| 2-05-03 | 05 | 3 | MOD-06 | — | Rollback preserves forward history | unit | `pytest tests/test_rollback.py::test_rollback_preserves_forward_history -x` | ❌ W0 | ⬜ pending |
| 2-06-01 | 06 | 4 | MOD-09 | T-02-05 | GET /snapshots requires auth | integration | `pytest tests/test_snapshots_api.py::test_list_snapshots -x` | ❌ W0 | ⬜ pending |
| 2-06-02 | 06 | 4 | MOD-02 | — | Full consent→execute→snapshot cycle | integration | `pytest tests/test_snapshots_api.py::test_full_consent_snapshot_cycle -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_snapshot_engine.py` — stubs for MOD-02, MOD-03, MOD-10
- [ ] `tests/test_consent_protocol.py` — stubs for MOD-01, MOD-03
- [ ] `tests/test_rollback.py` — stubs for MOD-04, MOD-05, MOD-06
- [ ] `tests/test_zone_registry.py` — stubs for MOD-07, MOD-08
- [ ] `tests/test_snapshots_api.py` — stubs for MOD-09

**Note:** `tests/test_sbs_sentinel.py` exists but has 2 pre-existing failures unrelated to Phase 2:
- `TestSentinel::test_monitored_zone_delete_restricted`
- `TestSentinel::test_safe_delete`

These failures are pre-existing bugs in `_apply_rules()` path matching and MUST NOT be treated as Phase 2 regressions. The full suite gate excludes these 2 tests from the green requirement.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| "Undo the last change" in live conversation | MOD-05 | Requires live LLM + actual skill on disk | 1. Create test skill. 2. Send "undo last change". 3. Verify skill directory removed. |
| "Go back to how you were on [date]" | MOD-04 | NLP date parsing requires live LLM confirmation | 1. Create 2 snapshots on different dates. 2. Send date-reference rollback. 3. Verify correct snapshot restored. |
| Auto-revert description in chat | MOD-03 | Requires live conversation to verify message quality | 1. Create intentionally broken skill (syntax error). 2. Verify chat response describes what went wrong. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
