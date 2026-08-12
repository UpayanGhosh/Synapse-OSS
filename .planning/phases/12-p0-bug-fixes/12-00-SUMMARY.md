---
phase: 12
plan: 12-00
slug: p0-bug-fixes-wave-0
status: complete
wave: 0
created: 2026-04-21
decision_set: decisions-a
---

# Phase 12 · Plan 12-00 · Wave 0 Summary

Wave 0 contract for Phase 12 (P0 Bug Fixes). Failing-test stubs land first; Wave 2 plans (12-01, 12-02, 12-03) flip them green without changing the assertions.

---

## Locked Decisions

User selected **decisions-a** (smallest diff — zero new config keys) on 2026-04-21.

### OQ-1 — `_resolve_target` I/O

- **Decision:** `_resolve_target` is pure (no I/O) — verified in `workspace/sci_fi_dashboard/_deps.py:224-232`. It is a synchronous in-memory iteration over `PERSONAS_CONFIG["personas"]`. Wave 2 Plan 12-02 MAY call it inline in `on_batch_ready` without caching.
- **Acceptance (machine-checkable):** `_resolve_target` body contains no `await`, no file/network/DB access. Grep: `grep -A 10 "def _resolve_target" workspace/sci_fi_dashboard/_deps.py | grep -E "await |open\(|requests\.|sqlite|\.db"` returns empty.

### OQ-2 — `proactive.sent` SSE event shape

- **Decision:** Emit metadata + 80-char ASCII-safe preview. NO full message body.
- **Payload contract:**
  ```python
  {
      "channel_id": str,
      "user_id": str,
      "reason": "silence_gap_8h",
      "preview": reply[:80].encode("ascii", errors="replace").decode("ascii"),
  }
  ```
- **Acceptance:** Wave 2 Plan 12-03 emit site produces event with these 4 keys exactly. Matches existing `llm.stream_start` / `cognition.analyze_start` schema and Gotcha #5 (Windows cp1252 safety).

### OQ-3 — Bridge `/connection-state` payload keys

- **Decision:** Payload uses `connectionState` (camelCase) and `lastDisconnectReason` (camelCase). Verified in `workspace/sci_fi_dashboard/channels/whatsapp.py:222` and `baileys-bridge/index.js:91-101`.
- **Acceptance:** Wave 2 Plan 12-01 route-level tests assert exact keys `connectionState` and `lastDisconnectReason` (NOT `connection_state` / `last_disconnect_reason`).

### OQ-4 — JID resolution inside `GentleWorker._async_proactive_checkin`

- **Decision:** Before calling `channel.send(...)`, resolve the canonical `user_id` (e.g. `"the_creator"`) to a concrete JID by reading `synapse.json → session.identityLinks[user_id][0]` (first JID in list). If missing, skip that `user_id` with a `logger.debug` (not an error — fresh OSS installs legitimately have empty links).
- **Canonical import path:** `from synapse_config import SynapseConfig` — NO `sci_fi_dashboard.` prefix. Required so the Wave 0 test monkeypatch at `"synapse_config.SynapseConfig.load"` takes effect.
- **Implementation sketch for Plan 12-03:**
  ```python
  from synapse_config import SynapseConfig
  cfg = SynapseConfig.load()
  links = (getattr(cfg, "session", {}) or {}).get("identityLinks", {}) or {}
  jids = links.get(user_id, []) or []
  if isinstance(jids, str):
      jids = [jids]
  if not jids:
      continue  # no JID paired — skip silently
  jid = jids[0]
  ok = await channel.send(jid, reply)
  ```
- **Acceptance:** `_async_proactive_checkin` imports `SynapseConfig` from `synapse_config` (exact string); dispatches to `channel.send(jid, reply)` where `jid` is a resolved string, not `"the_creator"`.

### OQ-5 — `PipelineEventEmitter.emit()` thread-safety

- **Decision:** `emit()` is safe IF the caller runs on the event loop thread. Wave 2 Plan 12-03 MUST use `asyncio.run_coroutine_threadsafe(coro, loop)` to hop from GentleWorker's background thread into the loop — emit calls INSIDE `_async_proactive_checkin` (which runs on the loop thread via `run_coroutine_threadsafe`) are then inherently safe.
- **Acceptance:** `heavy_task_proactive_checkin` calls `asyncio.run_coroutine_threadsafe(self._async_proactive_checkin(), self._event_loop)`. No direct `emit()` call from the worker's background thread.

---

## Test Stubs Created

| File | Tests | Failing | Passing (regression guard) | Notes |
|------|-------|---------|----------------------------|-------|
| `workspace/tests/test_whatsapp_routes.py` | 4 | 4 | 0 | `TestConnectionStateRoute::test_route_awaits_update`, `test_515_routes_to_restart`, plus `TestGetStatusIsLoggedOut::test_is_logged_out_true_when_connection_state_logged_out`, `test_is_logged_out_false_when_connected`. Uses `mock_ch.__class__ = WhatsAppChannel` to bypass `isinstance()` guard at `routes/whatsapp.py:144`. The 515 test uses a real `WhatsAppChannel(bridge_port=5010)` with only `_restart_bridge` + `asyncio.sleep` monkeypatched. |
| `workspace/tests/test_chat_pipeline_skill_routing.py` | 3 | 2 | 1 (A2) | A1 `TestSessionKeyCanonical` FAILS (non-canonical key today). A2 `TestSkillRouting` (runtime regression guard) PASSES — but see deviation below. A3 `TestSkillRoutingSource::test_persona_chat_has_single_skill_routing_block` FAILS — source-level red→green signal (counts `skill_router.match` calls in `persona_chat` via `inspect.getsource`). |
| `workspace/tests/test_proactive_awareness_wiring.py` | 5 | 3 | 2 (B2, B3) | B1 app.state presence, B4 SSE emit, B5 run_coroutine_threadsafe — all FAIL. B2 (thermal guard battery-skip) and B3 (`maybe_reach_out` wires channel.send) PASS as pre-fix regression guards. Monkeypatches `synapse_config.SynapseConfig.load` with populated `identityLinks` so Wave 2 JID-gate does not early-`continue`. |

Total: **12 tests** collected. 9 fail today (red signals for Wave 2), 3 pass today (regression guards).

---

## Deviations from Plan

### DEV-1 · `WA-FIX-05` test re-framed: runtime pass, source-level fail

**Plan 12-00 claim (line 4 of REQUIREMENTS + STATE.md seed finding):**
> "`chat_pipeline.py` lines 472-509 and 546-586 — duplicate skill-routing block -> state mutations fire twice on skill match"

**Actual behavior discovered during Task 2 implementation:**

- Block #1 (lines 472-509) calls `SkillRunner.execute` and then at line 503 does `return {...}`. That early return is unconditional on skill match.
- Block #2 (lines 546-586) is therefore UNREACHABLE when a skill matches — it is dead code, not a runtime duplicate.
- A runtime "fires twice" assertion would NEVER be red (it's already green by accident because of the early return).

**Deviation taken:**
- Kept the runtime regression guard as test A2 (`TestSkillRouting::test_skill_fires_exactly_once`) — it confirms the accidental single-fire is preserved.
- Added test A3 (`TestSkillRoutingSource::test_persona_chat_has_single_skill_routing_block`) that uses `inspect.getsource(persona_chat).count("skill_router.match") == 1` — this provides the red→green signal Wave 2 Plan 12-02 needs for `WA-FIX-05`.
- Wave 2 Plan 12-02 must therefore:
  1. Physically delete block #2 (the unreachable block).
  2. `test_persona_chat_has_single_skill_routing_block` flips from red to green when the deletion lands.

**Why this matters:** Plan 12-00's validation table originally pointed `12-02-T2` at `TestSkillRouting` (the runtime test). That pointer has been re-targeted in `12-VALIDATION.md` to `TestSkillRoutingSource`, which is the actual red-signal test for `WA-FIX-05`.

---

## Handoff to Wave 2

### Plan 12-01 (WhatsApp route fixes)

| Wave 2 task | Red test today | Action |
|-------------|----------------|--------|
| 12-01-T1 | `test_route_awaits_update` | `await wa_channel.update_connection_state(payload)` at `routes/whatsapp.py:147`. Change method to `async def` in `channels/whatsapp.py`. |
| 12-01-T2 | `test_515_routes_to_restart` | Ensure the (already-async) `update_connection_state` path triggers `_restart_bridge` on `lastDisconnectReason == 515`. |
| 12-01-T3 | `test_get_status_surfaces_is_logged_out` + `test_is_logged_out_flips_after_logged_out_state` | Add `isLoggedOut` to `WhatsAppChannel.get_status()`; set flag when `connectionState == "logged_out"`. |

### Plan 12-02 (chat pipeline fixes)

| Wave 2 task | Red test today | Action |
|-------------|----------------|--------|
| 12-02-T1 | `TestSessionKeyCanonical` | Replace ad-hoc session-key f-string in `on_batch_ready` with `build_session_key(...)` producing `agent:<agentId>:<channel>:dm:<peerId>`. |
| 12-02-T2 | `TestSkillRoutingSource` | Delete unreachable block #2 at `chat_pipeline.py:546-586`. |

### Plan 12-03 (proactive awareness wiring)

| Wave 2 task | Red test today | Action |
|-------------|----------------|--------|
| 12-03-T1 | `test_gentle_worker_present_on_app_state` | Instantiate `GentleWorker` in `api_gateway.lifespan()` and attach to `app.state.gentle_worker`. Pass `graph`, `proactive_engine`, `channel_registry` from existing singletons. |
| 12-03-T2 | `test_heavy_task_uses_run_coroutine_threadsafe` + `test_maybe_reach_out_dispatches_via_channel_registry` | `heavy_task_proactive_checkin` must call `asyncio.run_coroutine_threadsafe(self._async_proactive_checkin(), self._event_loop)`. `_async_proactive_checkin` must resolve JID via OQ-4 and dispatch via `channel_registry.get(channel_id).send(jid, reply)`. |
| 12-03-T3 | `test_emits_proactive_sent_event` | After successful send, emit `proactive.sent` event with OQ-2 payload. |

---

## Acceptance Grep

```bash
# All 5 OQs resolved
grep -E "OQ-[1-5]" .planning/phases/12-p0-bug-fixes/12-00-SUMMARY.md | wc -l  # >= 5

# Research file pointer added
grep "## Open Questions (RESOLVED)" .planning/phases/12-p0-bug-fixes/12-RESEARCH.md   # exactly 1
grep "12-00-SUMMARY.md" .planning/phases/12-p0-bug-fixes/12-RESEARCH.md               # >= 1

# Validation map populated + flags flipped
grep -c "12-0[123]-T" .planning/phases/12-p0-bug-fixes/12-VALIDATION.md               # >= 8
grep "nyquist_compliant: true" .planning/phases/12-p0-bug-fixes/12-VALIDATION.md
grep "wave_0_complete: true" .planning/phases/12-p0-bug-fixes/12-VALIDATION.md

# Stubs in place + defensive monkeypatches
grep -c 'monkeypatch.setattr.*synapse_config.SynapseConfig.load' workspace/tests/test_proactive_awareness_wiring.py    # >= 2
grep -c 'monkeypatch.setattr.*synapse_config.SynapseConfig.load' workspace/tests/test_chat_pipeline_skill_routing.py   # >= 1

# Zero production file edits in Wave 0
git diff --name-only HEAD workspace/sci_fi_dashboard/ | wc -l                          # == 0
```
