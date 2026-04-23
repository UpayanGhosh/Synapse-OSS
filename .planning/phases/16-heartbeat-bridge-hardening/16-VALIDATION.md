---
phase: 16
slug: heartbeat-bridge-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| _tbd_   | _planner fills_ | _planner fills_ | _planner fills_ | _planner fills_ | _planner fills_ | _planner fills_ | _planner fills_ | _planner fills_ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ✅ manual-passed*

---

## Wave 0 Requirements

Wave 0 creates test scaffolding + RED stubs so every subsequent wave has an automated verify target. Planner MUST create a Plan 00 that writes these files before any HEART-* / BRIDGE-* implementation starts.

- [ ] `workspace/tests/test_heartbeat_runner.py` — RED stubs covering HEART-01..05
  - `test_config_recipient_is_sent`, `test_no_recipients_is_noop`
  - `test_prompt_override`, `test_prompt_default`
  - `test_token_stripped_silent`, `test_token_with_trailing_punct_stripped`, `test_token_prefix_stripped`
  - `test_show_ok_sends_ok_ping`, `test_show_alerts_false_drops_content`, `test_use_indicator_false_omits_field`, `test_visibility_flag_matrix` (table-driven, 8 combinations)
  - `test_never_crashes_after_failures`, `test_llm_exception_does_not_stop_loop`
- [ ] `workspace/tests/test_bridge_health_poller.py` — RED stubs covering BRIDGE-02..03
  - `test_poll_cadence`, `test_status_surfaces_health`
  - `test_three_failures_trigger_restart`, `test_threshold_configurable`
  - `test_stop_reconnect_blocks_restart`, `test_401_not_counted_as_failure`, `test_grace_window_after_restart`
- [ ] `workspace/tests/test_webhook_dedup.py` — RED stubs covering BRIDGE-04
  - `test_duplicate_returns_accepted_true`, `test_first_passes_second_dropped`, `test_ttl_expiry_allows_retransmit`
- [ ] `baileys-bridge/test/health_endpoint.test.js` — RED stubs covering BRIDGE-01
  - `test_health_returns_new_fields`, `test_last_inbound_updates`, `test_last_outbound_updates`, `test_bridge_version_from_pkgjson`
- [ ] `workspace/tests/conftest.py` — add `fake_channel_with_recorded_sends` fixture (reusable across heartbeat tests)
- [ ] `workspace/tests/fixtures/bridge_health_transport.py` — `httpx.MockTransport` factory returning configurable `/health` responses (success, 401, 500, timeout)
- [ ] `.planning/phases/16-heartbeat-bridge-hardening/16-MANUAL-VALIDATION.md` — manual sign-off scaffold with HEART-01 / BRIDGE-03 rows

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

- [ ] All tasks have `<automated>` verify command or Wave 0 dependency reference
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING file references in per-task map
- [ ] No watch-mode flags (pytest no `--looponfail`; node `--test` not `--watch`)
- [ ] Feedback latency < 15s for quick run
- [ ] `nyquist_compliant: true` set in frontmatter (flip after planner fills per-task map)

**Approval:** pending
