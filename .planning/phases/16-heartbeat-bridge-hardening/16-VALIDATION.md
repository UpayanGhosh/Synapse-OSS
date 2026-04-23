---
phase: 16
slug: heartbeat-bridge-hardening
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-23
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python: pytest 7.x + pytest-asyncio 0.23+ (`asyncio_mode = auto`, existing); Node: `node --test` (Node 20+ built-in, existing in baileys-bridge) |
| **Config file** | `workspace/pytest.ini` (existing); `baileys-bridge/package.json` → `scripts.test` (existing) |
| **Quick run command** | `cd workspace && pytest tests/test_heartbeat_runner.py tests/test_bridge_health_poller.py tests/test_webhook_dedup.py -v` |
| **Full suite command** | `cd workspace && pytest tests/ -v && cd ../baileys-bridge && npm test` |
| **Estimated runtime** | ~15 seconds (Python unit ~8s + Node unit ~3s + integration ~4s); manual smoke ~10-15 min |

---

## Sampling Rate

- **After every task commit:** Quick run command (<10s)
- **After every plan wave:** Full suite command (~15s)
- **Before `/gsd-verify-work`:** Full suite green + `16-MANUAL-VALIDATION.md` sign-off (HEART-01 live smoke + BRIDGE-03 kill-pid smoke) PASS
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

> Filled in by gsd-planner once tasks are decomposed. Each task row lists: Task ID, Plan, Wave, Requirement (HEART-01..05 or BRIDGE-01..04), Threat Ref, Secure Behavior, Test Type, Automated Command, File Exists (W0 dependency), Status.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-00-01 | 00 | 0 | all | — | N/A | scaffold (RED) | `cd workspace && python -m pytest tests/test_heartbeat_runner.py tests/test_bridge_health_poller.py tests/test_webhook_dedup.py --collect-only` | ✅ W0 | ⬜ |
| 16-00-02 | 00 | 0 | BRIDGE-01 | — | N/A | scaffold (RED) | `cd baileys-bridge && node -c test/health_endpoint.test.js` | ✅ W0 | ⬜ |
| 16-00-03 | 00 | 0 | all | — | N/A | doc | `test -f .planning/phases/16-heartbeat-bridge-hardening/16-MANUAL-VALIDATION.md` | ✅ W0 | ⬜ |
| 16-01-01 | 01 | 1 | BRIDGE-01 | T-16-04 | /health augmented with 4 fields + test exports | node unit | `cd baileys-bridge && node --test test/health_endpoint.test.js` | ✅ W0 | ⬜ |
| 16-02-01 | 02 | 1 | HEART-01,02 | T-16-06 | resolve_recipients + prompt fallback | unit | `cd workspace && python -m pytest tests/test_heartbeat_runner.py::test_config_recipient_is_sent tests/test_heartbeat_runner.py::test_no_recipients_is_noop tests/test_heartbeat_runner.py::test_prompt_override tests/test_heartbeat_runner.py::test_prompt_default -v` | ✅ W0 | ⬜ |
| 16-02-02 | 02 | 1 | HEART-03 | T-16-03 | strip_heartbeat_token end/start/punct semantics | unit | `cd workspace && python -m pytest "tests/test_heartbeat_runner.py::test_token_stripped_silent" "tests/test_heartbeat_runner.py::test_token_with_trailing_punct_stripped" "tests/test_heartbeat_runner.py::test_token_prefix_stripped" -v` | ✅ W0 | ⬜ |
| 16-02-03 | 02 | 1 | HEART-04 | T-16-02 | 8-combination visibility matrix | unit | `cd workspace && python -m pytest "tests/test_heartbeat_runner.py::test_visibility_flag_matrix" "tests/test_heartbeat_runner.py::test_show_ok_sends_ok_ping" "tests/test_heartbeat_runner.py::test_show_alerts_false_drops_content" "tests/test_heartbeat_runner.py::test_use_indicator_false_omits_field" -v` | ✅ W0 | ⬜ |
| 16-02-04 | 02 | 1 | HEART-05 | T-16-02 | never-crash loop swallows exceptions | unit | `cd workspace && python -m pytest "tests/test_heartbeat_runner.py::test_never_crashes_after_failures" "tests/test_heartbeat_runner.py::test_llm_exception_does_not_stop_loop" -v` | ✅ W0 | ⬜ |
| 16-03-01 | 03 | 2 | BRIDGE-02 | T-16-04 | Poll cadence + status surface | unit | `cd workspace && python -m pytest "tests/test_bridge_health_poller.py::test_poll_cadence" "tests/test_bridge_health_poller.py::test_status_surfaces_health" -v` | ✅ W0 | ⬜ |
| 16-03-02 | 03 | 2 | BRIDGE-03 | T-16-01 | 3-strike restart + configurable threshold + grace window | unit | `cd workspace && python -m pytest "tests/test_bridge_health_poller.py::test_three_failures_trigger_restart" "tests/test_bridge_health_poller.py::test_threshold_configurable" "tests/test_bridge_health_poller.py::test_grace_window_after_restart" -v` | ✅ W0 | ⬜ |
| 16-03-03 | 03 | 2 | BRIDGE-03 | T-16-01 | stop_reconnect gate + 401 non-failure | unit | `cd workspace && python -m pytest "tests/test_bridge_health_poller.py::test_stop_reconnect_blocks_restart" "tests/test_bridge_health_poller.py::test_401_not_counted_as_failure" -v` | ✅ W0 | ⬜ |
| 16-04-01 | 04 | 2 | HEART-01..05 | T-16-06 | synapse_config heartbeat/bridge blocks + lifespan wiring | integration | `cd workspace && python -c "from synapse_config import SynapseConfig; c = SynapseConfig.load(); assert hasattr(c, 'heartbeat') and hasattr(c, 'bridge')"` | ✅ W0 | ⬜ |
| 16-04-02 | 04 | 2 | HEART-01..05 | T-16-06 | Heartbeat runner started in lifespan | grep | `grep -n "HeartbeatRunner\|heartbeat_runner" workspace/sci_fi_dashboard/api_gateway.py` | ✅ W0 | ⬜ |
| 16-05-01 | 05 | 3 | BRIDGE-04 | T-16-05 | Dedup contract + hit/miss counters | unit | `cd workspace && python -m pytest tests/test_webhook_dedup.py -v` | ✅ W0 | ⬜ |
| 16-05-02 | 05 | 3 | BRIDGE-04 | T-16-05 | /channels/whatsapp/status surfaces dedup + bridge_health | integration | `cd workspace && python -m pytest tests/test_webhook_dedup.py::test_first_passes_second_dropped -v` | ✅ W0 | ⬜ |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ✅ manual-passed*

---

## Wave 0 Requirements

Wave 0 creates test scaffolding + RED stubs so every subsequent wave has an automated verify target. Planner MUST create a Plan 00 that writes these files before any HEART-* / BRIDGE-* implementation starts.

- [x] `workspace/tests/test_heartbeat_runner.py` — 12 RED stubs (HEART-01..05)
- [x] `workspace/tests/test_bridge_health_poller.py` — 7 RED stubs (BRIDGE-02, BRIDGE-03)
- [x] `workspace/tests/test_webhook_dedup.py` — 3 RED stubs (BRIDGE-04)
- [x] `baileys-bridge/test/health_endpoint.test.js` — 4 RED stubs (BRIDGE-01)
- [x] `workspace/tests/conftest.py` — `fake_channel_with_recorded_sends` + `fake_channel_registry_factory` + `reset_emitter_singleton`
- [x] `workspace/tests/fixtures/bridge_health_transport.py` — `make_mock_transport` + SUCCESS_HEALTH_JSON + AUTH_EXPIRED_RESPONSE + SERVER_ERROR_RESPONSE
- [x] `16-MANUAL-VALIDATION.md` — 9 rows (HEART-01 live, HEART-03 live strip, BRIDGE-01 flood, BRIDGE-03 kill-pid, BRIDGE-04 TTL, HEART-04 SSE, HEART-05 24h longevity, BRIDGE-01 version bump, BAIL_HEART sanity)

*If the planner decides some of these already exist: move to "File Exists: ✅" in the per-task map and skip the creation task.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real recipient on real WhatsApp receives scheduled heartbeat | HEART-01 | Requires live Baileys pairing (cannot be faked in pytest) | 1. Pair bridge to a test WhatsApp account. 2. Add own JID to `heartbeat.recipients`. 3. Set `heartbeat.intervalMs: 60000`. 4. Observe message arrives on the paired phone within 60s. |
| HEARTBEAT_TOKEN stripped end-to-end on real recipient reply | HEART-03 | Needs live phone to type the token-bearing reply | After heartbeat sends, reply from phone with literal text `HEARTBEAT_OK`. Verify logs show `heartbeat.reply.stripped`, no outbound echo, no user-visible message. |
| Bridge `/health` responds during live inbound flood | BRIDGE-01 | Real concurrency between Express `/health` and Baileys event-loop saturation | Send 50 inbound messages in 10s (another phone). Curl `/health` every 1s. No 5xx / no timeouts. |
| Subprocess restart after 3 real `/health` failures | BRIDGE-03 | Subprocess I/O is fragile in pytest; kill-PID on real process | `kill -STOP $(pgrep -f 'baileys-bridge')` (Linux/Mac) or `Stop-Process -Id (...) -PassThru` (Windows). Observe 3 × 30s polls fail, then gateway respawns. `healthState` transitions: healthy → degraded → restarting → healthy. |
| 300s dedup TTL real-clock expiry | BRIDGE-04 | Long wall-clock (test uses monkey-patched time) | Send same `message_id` twice: immediately (expect duplicate) then after 5+ min (expect accepted). |
| Dashboard SSE renders heartbeat events | HEART-04 (`useIndicator`) | Browser rendering — not testable in pytest | Open dashboard → Heartbeat tab. Trigger heartbeat. Event stream shows `heartbeat.cycle.*` events in order. |
| Longevity: heartbeat fires hourly for 24h with zero crashes | HEART-05 | 86400s wall time | Set `heartbeat.intervalMs: 3600000`. Let run for 24h. Assert gateway uptime + no heartbeat panic events in logs. |
| `bridge_version` reflects new Baileys after in-place upgrade | BRIDGE-01 | Requires `npm install --save baileys@<next>` + subprocess restart | After upgrade, curl `/health`, confirm `bridge_version` equals new package.json version. |

*All rows above are copied into `16-MANUAL-VALIDATION.md` by Plan 00 with reproduction steps and PASS/FAIL signoff columns.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify command or Wave 0 dependency reference
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING file references in per-task map
- [x] No watch-mode flags
- [x] Feedback latency < 15s for quick run
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Wave 0 complete — 2026-04-23
