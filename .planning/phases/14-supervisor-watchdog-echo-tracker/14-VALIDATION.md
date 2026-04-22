---
phase: 14
slug: supervisor-watchdog-echo-tracker
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-22
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | workspace/pytest.ini (or none — Wave 0 installs stubs) |
| **Quick run command** | `cd workspace && pytest tests/test_supervisor_watchdog.py tests/test_echo_tracker.py -v` |
| **Full suite command** | `cd workspace && pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd workspace && pytest tests/test_supervisor_watchdog.py tests/test_echo_tracker.py -v`
- **After every plan wave:** Run `cd workspace && pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 0 | SUPV-01 | — | N/A | unit stub | `pytest tests/test_supervisor_watchdog.py -v` | ✅ W0 | ✅ green |
| 14-01-02 | 01 | 0 | ACL-01 | — | N/A | unit stub | `pytest tests/test_echo_tracker.py -v` | ✅ W0 | ✅ green |
| 14-02-01 | 02 | 1 | SUPV-01 | — | N/A | unit | `pytest tests/test_supervisor_watchdog.py::test_watchdog_fires -v` | ✅ W0 | ✅ green |
| 14-02-02 | 02 | 1 | SUPV-02 | — | N/A | unit | `pytest tests/test_supervisor_watchdog.py::test_reconnect_policy -v` | ✅ W0 | ✅ green |
| 14-02-03 | 02 | 1 | SUPV-03 | — | N/A | unit | `pytest tests/test_supervisor_watchdog.py::test_health_state_transitions -v` | ✅ W0 | ✅ green |
| 14-02-04 | 02 | 1 | SUPV-04 | — | N/A | unit | `pytest tests/test_supervisor_watchdog.py::test_nonretryable_codes -v` | ✅ W0 | ✅ green |
| 14-03-01 | 03 | 1 | ACL-01 | — | Echo fingerprint prevents self-loop | unit | `pytest tests/test_echo_tracker.py::test_echo_dropped -v` | ✅ W0 | ✅ green |
| 14-03-02 | 03 | 1 | ACL-02 | — | N/A | unit | `pytest tests/test_echo_tracker.py::test_non_echo_passes -v` | ✅ W0 | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `workspace/tests/test_supervisor_watchdog.py` — stubs for SUPV-01..04
- [x] `workspace/tests/test_echo_tracker.py` — stubs for ACL-01..02
- [x] `workspace/tests/conftest.py` — Phase 14 fixtures (`reset_run_id`, `fake_monotonic`)

*Existing pytest infrastructure covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 30-min inbound silence → force-reconnect | SUPV-01 | Requires live WhatsApp bridge + time | Set `watchdog_timeout_s=30` in test config, silence bridge for 30s, confirm `supv.watchdog.fired` log |
| 440 conflict stops reconnect loop | SUPV-04 | Requires live bridge sending 440 close | Trigger `connectionReplaced` from bridge, confirm `healthState=conflict` and no retry |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Wave 0 complete — 2026-04-22
