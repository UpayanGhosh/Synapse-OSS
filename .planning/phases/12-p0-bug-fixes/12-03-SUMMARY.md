---
phase: 12
plan: 3
status: complete
wave: 2
---

## Plan 03 — PROA-01 / PROA-02 / PROA-03 / PROA-04

### Changes

**workspace/sci_fi_dashboard/api_gateway.py**
- Task 1 (PROA-01): `import threading` added to top-level imports. New GentleWorker wiring block inserted in `lifespan()` after `CronService` init: `app.state.gentle_worker = GentleWorker(graph=deps.brain, cron_service=..., proactive_engine=deps._proactive_engine, channel_registry=deps.channel_registry)`. Main event loop captured: `app.state.gentle_worker._event_loop = asyncio.get_running_loop()`. Worker started in daemon thread: `threading.Thread(target=..., daemon=True, name="gentle-worker")`. Shutdown stop: `app.state.gentle_worker.is_running = False`. Uses existing `deps._proactive_engine` singleton — no second instance created (Pitfall 6 avoided).

**workspace/sci_fi_dashboard/gentle_worker.py**
- Task 2 (PROA-02 + PROA-04): Replaced `loop.create_task(self._async_proactive_checkin())` (RuntimeError from non-loop thread) with `asyncio.run_coroutine_threadsafe(self._async_proactive_checkin(), loop)` using `loop = getattr(self, "_event_loop", None)`. Added early-return when loop absent or stopped. In `_async_proactive_checkin`: reads `session.identityLinks` from `SynapseConfig.load()` (OQ-4 — pure dict scan, no I/O surprise), resolves `user_id` → JID (handles both `str` and `list[str]` shapes), skips silently when unpaired. Calls `channel.send(jid, reply)` with resolved JID (not raw user_id). On successful send: emits `get_emitter().emit("proactive.sent", {channel_id, user_id, reason: "silence_gap_8h", preview})` where preview is 80-char ASCII-safe (Gotcha #5 `.encode("ascii", errors="replace").decode("ascii")`).
- PROA-03 (thermal guard) preserved unchanged — `check_conditions()` returns False on battery OR CPU > 20%.

### Singletons / Thread Safety
- `deps._proactive_engine` re-used, not duplicated.
- `asyncio.run_coroutine_threadsafe` is the correct primitive for cross-thread event-loop submission.
- GentleWorker is `daemon=True` — exits cleanly with process, no join needed.

### Test Results
- `test_proactive_awareness_wiring.py::TestProactiveWiring::test_gentle_worker_present_on_app_state` ✅ green (PROA-01)
- `test_proactive_awareness_wiring.py::TestProactiveWiring::test_thermal_guard_skips_when_on_battery` ✅ green (PROA-03 regression guard)
- `test_proactive_awareness_wiring.py::TestProactiveWiring::test_heavy_task_uses_run_coroutine_threadsafe` ✅ green (PROA-02)
- `test_proactive_awareness_wiring.py::TestProactiveWiring::test_emits_proactive_sent_event` ✅ green (PROA-04)
- `test_proactive_awareness_wiring.py::TestProactiveSendWiring::test_maybe_reach_out_dispatches_via_channel_registry` ✅ green
- `test_gentle_worker.py` ✅ no regression
- `test_proactive_engine.py` ✅ no regression
- `test_api_gateway.py` ✅ no regression (pre-existing 3 failures are unrelated to this plan)

### Manual Smoke (required for full sign-off)
- Plug in charger, leave idle 8h outside sleep window, confirm SSE `proactive.sent` in dashboard, confirm message arrives on paired device — confirms PROA-01..04 end-to-end.

### Acceptance Criteria Verification
- `grep -n "app.state.gentle_worker = GentleWorker(" api_gateway.py` → 1 match ✅
- `grep -n "asyncio.run_coroutine_threadsafe" gentle_worker.py` → 1 match ✅
- `grep -c "loop.create_task(self._async_proactive_checkin" gentle_worker.py` = **0** ✅
- `grep -n "identityLinks" gentle_worker.py` → 1 match ✅
- `grep -n 'encode("ascii", errors="replace")' gentle_worker.py` → 1 match ✅
- `ruff check` + `black --check` both files → clean ✅
