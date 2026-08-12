---
phase: 12
slug: p0-bug-fixes
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-21
approved: 2026-04-21
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (py311, markers: unit/integration/smoke) |
| **Config file** | `workspace/pyproject.toml` (pytest section, `asyncio_mode = auto`) |
| **Quick run command** | `cd workspace && pytest tests/ -m unit -x --timeout=30` |
| **Full suite command** | `cd workspace && pytest tests/ -v` |
| **Wave 0 stub suite** | `cd workspace && pytest tests/test_whatsapp_routes.py tests/test_chat_pipeline_skill_routing.py tests/test_proactive_awareness_wiring.py -v` (~12s, 12 tests) |

---

## Sampling Rate

- **After every task commit:** Run `cd workspace && pytest tests/ -m unit -x --timeout=30`
- **After every plan wave:** Run `cd workspace && pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green + 5 roadmap success-criteria smoke checks green
- **Max feedback latency:** 30 seconds (unit quick run)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-T1 | 12-01 | 2 | WA-FIX-01 | T-12-01 | route awaits update_connection_state | unit | `cd workspace && pytest tests/test_whatsapp_routes.py::TestConnectionStateRoute::test_route_awaits_update -x` | yes | ✅ green |
| 12-01-T2 | 12-01 | 2 | WA-FIX-02 | T-12-01 | code 515 reaches _restart_bridge via route | unit | `cd workspace && pytest tests/test_whatsapp_routes.py::TestConnectionStateRoute::test_515_routes_to_restart -x` | yes | ✅ green |
| 12-01-T3 | 12-01 | 2 | WA-FIX-03 | T-12-04 | isLoggedOut in get_status() | unit | `cd workspace && pytest tests/test_whatsapp_routes.py::TestGetStatusIsLoggedOut -x` | yes | ✅ green |
| 12-02-T1 | 12-02 | 2 | WA-FIX-04 | T-12-02 | on_batch_ready uses canonical builder | unit | `cd workspace && pytest tests/test_chat_pipeline_skill_routing.py::TestSessionKeyCanonical -x` | yes | ✅ green |
| 12-02-T2 | 12-02 | 2 | WA-FIX-05 | T-12-02 | duplicate skill block deleted; persona_chat has single skill_router.match call | unit | `cd workspace && pytest tests/test_chat_pipeline_skill_routing.py::TestSkillRoutingSource -x` | yes | ✅ green |
| 12-03-T1 | 12-03 | 2 | PROA-01, PROA-03 | T-12-03 | GentleWorker on app.state; thermal guard preserved | integration | `cd workspace && pytest tests/test_proactive_awareness_wiring.py::TestProactiveWiring::test_gentle_worker_present_on_app_state tests/test_proactive_awareness_wiring.py::TestProactiveWiring::test_thermal_guard_skips_when_on_battery -x` | yes | ✅ green |
| 12-03-T2 | 12-03 | 2 | PROA-02 | T-12-03 | heavy_task uses run_coroutine_threadsafe; send via registry with JID | unit+integration | `cd workspace && pytest tests/test_proactive_awareness_wiring.py::TestProactiveWiring::test_heavy_task_uses_run_coroutine_threadsafe tests/test_proactive_awareness_wiring.py::TestProactiveSendWiring -x` | yes | ✅ green |
| 12-03-T3 | 12-03 | 2 | PROA-04 | T-12-05 | proactive.sent SSE event emitted on successful send | unit | `cd workspace && pytest tests/test_proactive_awareness_wiring.py::TestProactiveWiring::test_emits_proactive_sent_event -x` | yes | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] Confirm pytest config path (`workspace/pyproject.toml` — `asyncio_mode = auto`, markers registered)
- [x] `workspace/tests/test_whatsapp_routes.py` — stubs for WA-FIX-01/02/03 (async await, code 515, isLoggedOut surface) — 4 tests, all fail against current source
- [x] `workspace/tests/test_chat_pipeline_skill_routing.py` — stub for WA-FIX-04/05 (canonical session key + single skill-routing block via source inspection) — 3 tests: A1+A3 fail, A2 passes as regression guard
- [x] `workspace/tests/test_proactive_awareness_wiring.py` — stubs for PROA-01..04 (gateway init, cross-thread scheduling, thermal guard preserved, SSE emit, JID dispatch) — 5 tests: B1+B4+B5 fail, B2+B3 pass as regression guards
- [x] JID resolution spike — RESOLVED via OQ-4 (see 12-00-SUMMARY.md): `session.identityLinks[user_id][0]` lookup inside `_async_proactive_checkin`

*Note: No shared `conftest.py` created in Wave 0 — each stub file sets up its own monkeypatches; shared fixtures can be extracted later if duplication emerges.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end WhatsApp reply after forced bridge reconnect | WA-FIX-01, WA-FIX-02 | Requires live Baileys bridge + real WhatsApp account (OSS reality: personal device pairing) | 1) Start Synapse, 2) pair personal WhatsApp, 3) `kill -9 $(pgrep -f baileys-bridge)`, 4) observe bridge auto-restart with code 515, 5) send inbound msg from paired device, 6) verify bot replies within 15s |
| 8h+ proactive check-in landing on real device | PROA-01..04 | Thermal guard (CPU<20% AND plugged in) + 8h timer + identity routing makes automated flaky; requires observational run | 1) Plug in charger, 2) leave idle 8h, 3) ensure outside sleep window, 4) confirm SSE `proactive.sent` in dashboard, 5) confirm msg arrives on paired device |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-21
