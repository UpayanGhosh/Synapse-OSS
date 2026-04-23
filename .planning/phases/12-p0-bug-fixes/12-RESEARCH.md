# Phase 12: P0 Bug Fixes (Ship-Blocking) — Research

**Researched:** 2026-04-21
**Domain:** WhatsApp reliability, async supervision, proactive outreach wiring
**Confidence:** HIGH (all findings verified against current source files + tests)

## Summary

Phase 12 is nine surgical fixes across five files — `routes/whatsapp.py`, `channels/whatsapp.py` (no edit, but informs fix), `chat_pipeline.py`, `pipeline_helpers.py`, and `api_gateway.py` (add GentleWorker wiring). All four code bugs are confirmed smoking-guns with explicit file:line coordinates. The proactive-outreach wiring is a wiring job, not new feature work — `GentleWorker.heavy_task_proactive_checkin()` already exists and already calls `channel.send()`; it just never gets instantiated in the live gateway. `ProactiveAwarenessEngine.maybe_reach_out()` already exists, takes `user_id` + `channel_id`, already enforces the 23:00-08:00 IST sleep window and the 8-hour silence gap, and returns a generated check-in message. Everything needed is present — the glue is missing.

The goal is **smallest diff**, not architecture. No module splits, no new tests infra — just (a) add `await` to one call, (b) delete 41 duplicate lines, (c) rename one f-string to a function call, (d) instantiate one class in lifespan, (e) emit one SSE event. Each fix is independently verifiable and independently testable.

**Primary recommendation:** Ship each REQ as a single-commit, single-test task. Nine REQs → nine tasks → one wave. Don't bundle fixes into "cleanup PRs"; the traceability matters for rollback.

## User Constraints (from CONTEXT.md)

**Note:** No CONTEXT.md exists for Phase 12 — research proceeded without upstream decisions. All scoping constraints in this document derive from the ROADMAP.md Phase 12 goal + success criteria and from `CLAUDE.md` OSS workflow standards.

### Locked Decisions
None (no CONTEXT.md). The ROADMAP's success criteria serve as the de-facto lock list:
1. `update_connection_state()` awaited → retry queue flushes on reconnect (WA-FIX-01)
2. Code 515 triggers bridge re-open without manual restart (WA-FIX-02)
3. `GET /channels/whatsapp/status` surfaces `isLoggedOut: true` within 10s (WA-FIX-03)
4. `on_batch_ready` + `process_message_pipeline` agree on one canonical `build_session_key()` (WA-FIX-04)
5. Duplicate skill-routing block at `chat_pipeline.py:546-586` removed; skills fire exactly once (WA-FIX-05)
6. `heavy_task_proactive_checkin` runs in live gateway — not only `if __name__ == "__main__"` (PROA-01)
7. `maybe_reach_out()` dispatches via `channel_registry.get(channel_id).send()` (PROA-02)
8. Proactive check-in is thermal-guarded (CPU < 20% AND plugged in) (PROA-03)
9. Proactive sends emit SSE event visible in dashboard (PROA-04)

### Claude's Discretion
- Naming of the SSE event for PROA-04 (suggest: `proactive.sent` matching `pipeline.start`/`llm.stream_start` convention)
- Exact field name for WA-FIX-03 (roadmap says `isLoggedOut: true` — keep that literal name)
- Whether to delete the first OR second duplicate skill-routing block (roadmap specifies `chat_pipeline.py:546-586` is the one to delete)
- Test style: mock vs subprocess (recommend mock — existing `test_polling_resilience.py` uses AsyncMock + monkeypatch; follow pattern)

### Deferred Ideas (OUT OF SCOPE)
- OpenClaw watchdog port (30-min-silence force reconnect) → Phase 14
- Configurable reconnect policy with jitter → Phase 14
- Echo/self-echo tracker → Phase 14
- `healthState` enum on status endpoint → Phase 14
- Structured logging / redaction helpers → Phase 13
- DmPolicy pre-FloodGate gate → Phase 17
- Per-authDir atomic creds queue → Phase 15
- Multi-account WhatsApp → Phase 18
- Making sleep window configurable (currently hard-coded 23:00-08:00 IST in `maybe_reach_out`) — leave as-is for Phase 12

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WA-FIX-01 | `update_connection_state()` awaited | `routes/whatsapp.py:147` is synchronous call; `channels/whatsapp.py:215` method is `async def`. Fix: add `await`. Existing tests in `tests/test_polling_resilience.py:423-484` already cover the channel-side method; route-side test missing. |
| WA-FIX-02 | Code 515 triggers bridge re-open | Already implemented in `channels/whatsapp.py:228-234` (`_restart_bridge()` dispatches on `lastDisconnectReason == 515`). BLOCKED by WA-FIX-01 (coroutine never runs without await). Tests exist: `test_polling_resilience.py:424-461`. |
| WA-FIX-03 | `isLoggedOut: true` in `/status` within 10s | Bridge sends `connectionState: 'logged_out'` (`baileys-bridge/index.js:319-321`). Python currently stores in `_connection_state` but does NOT expose a boolean `isLoggedOut` field. Add one derived field in `get_status()`. |
| WA-FIX-04 | One canonical `build_session_key()` | `pipeline_helpers.py:383` uses canonical builder; `pipeline_helpers.py:519` uses inline f-string `f"{metadata.get('channel_id', 'whatsapp')}:{chat_type}:{chat_id}"`. Builder lives at `multiuser/session_key.py:62`. Fix: replace inline with builder call. Latent bug — `task.session_key` not yet consumed downstream, but two builders will drift. |
| WA-FIX-05 | Duplicate skill-routing block removed | Block #1 at `chat_pipeline.py:472-509`; block #2 at `chat_pipeline.py:546-586`. Roadmap success criteria #4 specifies block #2 (lines 546-586) is the one to delete. Second block has slightly different semantics (`getattr()` safety checks and adds `session_context` kwarg). Migrate useful bits to block #1, then delete block #2. |
| PROA-01 | `heavy_task_proactive_checkin` in live gateway | `GentleWorker` class at `gentle_worker.py:10` — instantiated only at `gentle_worker.py:124` `if __name__ == "__main__":`. `api_gateway.py` starts `gentle_worker_loop()` (async, from `pipeline_helpers.py:538`) but NOT `GentleWorker`. Fix: instantiate `GentleWorker` in `lifespan()`, or replicate its scheduling into `gentle_worker_loop()`. |
| PROA-02 | `maybe_reach_out` → `channel_registry.get(...).send()` | `proactive_engine.py:133-188` already has `maybe_reach_out(user_id, channel_id, last_message_time)` returning a reply string. `gentle_worker.py:94-105` already wires it to `channel_registry.get(channel_id).send()`. Both pieces exist; just need the glue (PROA-01) to actually run. |
| PROA-03 | Thermal guard honored | `GentleWorker.check_conditions()` at `gentle_worker.py:29-47` already enforces CPU < 20% AND plugged in. Preserved automatically if `GentleWorker` is instantiated (PROA-01). |
| PROA-04 | SSE event `proactive.sent` visible in dashboard | `PipelineEventEmitter` singleton at `pipeline_emitter.py` already supports `emit(event_type, data)`. No `proactive.sent` event emitted today. Fix: add `_get_emitter().emit("proactive.sent", {...})` after successful `channel.send()` in `GentleWorker._async_proactive_checkin()`. |

## Project Constraints (from CLAUDE.md)

### OSS Workflow Rules (CRITICAL — read before push)
- **No personal data in commits**: no real `entities.json`, no real tokens, no `synapse.json` with real keys. Testing uses personal data, commits use placeholders.
- **Pre-push checklist**: (1) `entities.json` is empty `{}`, (2) tokens only in gitignored files, (3) code works for fresh OSS install.
- **Commit discipline**: Each REQ = one commit. Keep diffs surgical.

### Code Style
- Python 3.11, line-length 100, `ruff check` + `black` — both pass before push.
- `asyncio` throughout (no Redis/Celery).
- Windows cp1252 safety: all preview log strings must be ASCII with `replace` error handling.

### Code Graph First
- Use `semantic_search_nodes_tool` / `query_graph_tool` / `get_impact_radius_tool` before reading files.
- Use `detect_changes` after edits for risk-scored analysis.
- Graph auto-updates via PostToolUse hooks — no manual rebuild.

### Critical Gotchas That Apply to This Phase
- **Gotcha #4 (CLAUDE.md)**: Gateway does NOT auto-reload unless started with `--reload`. After code edits, the running uvicorn process must be killed. Affects manual verification of all WA-FIX-* bugs.
- **Gotcha #5**: Windows cp1252 can't print emoji. Any new log lines added (e.g., for PROA-04) must ASCII-encode.
- **Gotcha #10**: `MemoryEngine.query()` is called ONCE in `persona_chat()` and shared with dual cognition. Don't add a second query inside the skill-routing cleanup.

## Standard Stack

No new libraries needed. All fixes use already-installed code.

### Core (already in repo)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | existing | Route handler for `/connection-state` webhook | Already the gateway framework |
| httpx | existing | Bridge HTTP client (unchanged) | Already how Python talks to Baileys |
| asyncio | stdlib | Async coroutines, `create_task`, `wait_for` | Python 3.11 built-in |
| psutil | existing | `sensors_battery()`, `cpu_percent()` for thermal guard | Already used by `GentleWorker` |
| schedule | existing | `schedule.every(15).minutes.do(...)` in `GentleWorker` | Already imported by `gentle_worker.py:6` |

### Supporting
| Library | Purpose |
|---------|---------|
| `sci_fi_dashboard.pipeline_emitter.get_emitter` | SSE event emission (PROA-04) |
| `sci_fi_dashboard.multiuser.session_key.build_session_key` | Canonical session-key builder (WA-FIX-04) |
| `sci_fi_dashboard.gentle_worker.GentleWorker` | Thermal-guarded scheduled tasks (PROA-01) |
| `sci_fi_dashboard.proactive_engine.ProactiveAwarenessEngine.maybe_reach_out` | Generator of proactive reply text (PROA-02) |
| `sci_fi_dashboard.channels.whatsapp.WhatsAppChannel.update_connection_state` | Bridge state updater (WA-FIX-01) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Instantiating `GentleWorker` in lifespan | Merging `heavy_task_proactive_checkin` logic into existing async `gentle_worker_loop()` | PRO: no new background thread. CON: more surgery, mixes the sync `schedule.run_pending()` model with async. RECOMMEND: Instantiate `GentleWorker` as a threading.Thread — it's already written as sync code with `time.sleep(1)` loop. Smallest diff. |
| Add `isLoggedOut` as bool field | Re-use existing `connection_state == "logged_out"` check | Roadmap success criteria explicitly names `isLoggedOut: true`. Keep literal. |
| Delete chat_pipeline block #2 (546-586) | Delete block #1 (472-509) | Roadmap specifies block #2 is the duplicate. Block #2 has the `getattr()` safety + `session_context` extras — migrate those into block #1 before deleting block #2 (or document the intentional omission). |

**Installation:**
```bash
# No new packages — all dependencies already installed
cd workspace && pip list | grep -iE "fastapi|httpx|psutil|schedule"
```

**Version verification:** Not applicable — no new packages introduced.

## Architecture Patterns

### Recommended Project Structure (unchanged)
```
workspace/sci_fi_dashboard/
├── api_gateway.py            # edit: wire GentleWorker in lifespan() [PROA-01]
├── chat_pipeline.py          # edit: delete lines 546-586 [WA-FIX-05]
├── channels/whatsapp.py      # edit: expose isLoggedOut in get_status() [WA-FIX-03]
├── gentle_worker.py          # edit: emit proactive.sent SSE [PROA-04]
├── pipeline_helpers.py       # edit: replace f-string with build_session_key() [WA-FIX-04]
├── routes/whatsapp.py        # edit: add await at line 147 [WA-FIX-01]
└── ... (unchanged)
```

### Pattern 1: The One-Line Await Fix
**What:** Route handlers that call async methods without `await` create a "coroutine was never awaited" warning and silently drop the work. The handler returns `{"ok": True}` to the bridge, bridge thinks Python acknowledged the event, Python's state is never actually updated.
**When to use:** Always `await` async methods from async route handlers. FastAPI already marks `async def whatsapp_connection_state(...)` as async (`routes/whatsapp.py:138`), so the await is legal.
**Example:**
```python
# BAD (current):
# Source: routes/whatsapp.py:137-148
@router.post("/channels/whatsapp/connection-state")
async def whatsapp_connection_state(request: Request):
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        return {"ok": False, "detail": "WhatsApp channel not registered"}
    payload = await request.json()
    wa_channel.update_connection_state(payload)  # ← coroutine created, never awaited
    return {"ok": True}

# GOOD:
    await wa_channel.update_connection_state(payload)
```

### Pattern 2: Add, Don't Replace, for Backward-Compat Fields
**What:** Dashboards and CLI clients already parse `connection_state` (string field). Adding `isLoggedOut` (boolean, derived) as a NEW field is safer than changing the contract.
**Example:**
```python
# Source: channels/whatsapp.py:283-291 (current get_status)
async def get_status(self) -> dict:
    base = await self.health_check()
    base["connected_since"] = self._connected_since
    base["auth_timestamp"] = self._auth_timestamp
    base["restart_count"] = self._restart_count
    base["last_disconnect_reason"] = self._last_disconnect_reason
    base["connection_state"] = self._connection_state
    # NEW (WA-FIX-03):
    base["isLoggedOut"] = self._connection_state == "logged_out"
    return base
```

### Pattern 3: Canonical Key Builder as Single Source of Truth
**What:** When two code paths assemble the same data structure (here, session key), they must call ONE function. Inline f-strings diverge silently.
**Example:**
```python
# BAD (current):
# Source: pipeline_helpers.py:514-530 (on_batch_ready)
async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
    is_group = metadata.get("is_group", False)
    chat_type = "group" if is_group else "direct"
    session_key = f"{metadata.get('channel_id', 'whatsapp')}:{chat_type}:{chat_id}"
    # produces e.g. "whatsapp:direct:919876@s.whatsapp.net"

# GOOD — use the canonical builder:
# Source: multiuser/session_key.py:62 (build_session_key)
from sci_fi_dashboard.multiuser.session_key import build_session_key
from sci_fi_dashboard.synapse_config import SynapseConfig

cfg = SynapseConfig.load()
session_cfg = getattr(cfg, "session", {}) or {}
target = deps._resolve_target(chat_id)
session_key = build_session_key(
    agent_id=target,
    channel=metadata.get("channel_id", "whatsapp"),
    peer_id=chat_id,
    peer_kind="group" if is_group else "direct",
    account_id=metadata.get("channel_id", "whatsapp"),
    dm_scope=session_cfg.get("dmScope", "per-channel-peer"),
    main_key="whatsapp:dm",
    identity_links=session_cfg.get("identityLinks", {}),
)
# produces e.g. "agent:the_creator:whatsapp:dm:919876-s-whatsapp-net"
```
This matches `process_message_pipeline()` at `pipeline_helpers.py:383-392`. The key shape will change (from `"whatsapp:direct:<chat_id>"` to `"agent:<target>:whatsapp:dm:<sanitized_peer>"`) — verify no downstream code parses the old shape.

### Pattern 4: Thermal-Guarded Scheduled Task
**What:** Background tasks that touch LLMs, WhatsApp, or heavy memory operations should gate on battery + CPU to avoid interrupting the user.
**Example:**
```python
# Source: gentle_worker.py:29-47
def check_conditions(self):
    try:
        battery = psutil.sensors_battery()
        if battery is not None and not battery.power_plugged:
            return False, "[BATTERY] On Battery"
    except Exception as e:
        print(f"[WARN] Battery check error: {e}")
    cpu_load = psutil.cpu_percent(interval=1)
    if cpu_load > 20:
        return False, f"[FIRE] CPU Busy ({cpu_load}%)"
    return True, "[OK] System Idle & Plugged In"
```
Already implemented. PROA-03 is satisfied by instantiating `GentleWorker` — no new code needed.

### Pattern 5: Fire-and-Forget SSE Emit
**What:** Non-critical events (`proactive.sent`) should emit via the module singleton without blocking the sender.
**Example:**
```python
# Source: pipeline_emitter.py:47 — emit() is sync-safe from any context
from sci_fi_dashboard.pipeline_emitter import get_emitter

# In GentleWorker._async_proactive_checkin:
await channel.send(user_id, reply)
get_emitter().emit("proactive.sent", {
    "channel_id": channel_id,
    "user_id": user_id,
    "reason": "silence_gap_8h",
})
```

### Anti-Patterns to Avoid
- **Trying to Fix WA-FIX-04 by changing `process_message_pipeline` instead of `on_batch_ready`**: `process_message_pipeline` already uses the canonical builder (`pipeline_helpers.py:383`). The bug is in `on_batch_ready` (`:519`). Don't touch `process_message_pipeline`.
- **Adding tests for bugs that are already tested at the class level**: `test_polling_resilience.py:420-484` already asserts `update_connection_state` is async, handles 515, flushes retry queue. Phase 12 only needs a NEW test at the ROUTE level asserting the handler awaits the coroutine.
- **Introducing new config keys**: Roadmap says "smallest possible diff, no architectural work." Resist the urge to add `proactive.enabled` or `sleep_window_start` config keys — defer to later phases.
- **Bundling fixes into one commit**: Each REQ is independently testable. One commit per REQ preserves rollback granularity.
- **Fixing the bridge-side code 515 behavior**: The Baileys bridge already auto-restarts the socket on any non-loggedOut close (`index.js:327`). The Python-side 515 restart at `channels/whatsapp.py:228-234` is defensive-in-depth — don't disable it just because the bridge also handles it. Just make sure the method actually gets awaited (WA-FIX-01 unblocks WA-FIX-02).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sleep-window math (23:00-08:00 IST) | A new helper | `ProactiveAwarenessEngine.maybe_reach_out()` already does this at `proactive_engine.py:151-157` | Already written, already tested, already correct for IST timezone |
| 8-hour silence gap detection | A timer loop | `maybe_reach_out(last_message_time)` at `proactive_engine.py:160-165` | Already implemented; caller just passes `last_message_time` (or `None`) |
| CPU + battery thermal guard | `psutil` calls in new code | `GentleWorker.check_conditions()` at `gentle_worker.py:29-47` | Already handles exceptions, already logs reason |
| SSE event emitter singleton | A new broadcaster | `pipeline_emitter.get_emitter()` | Already sync-safe, already wired to dashboard subscribers |
| Session key assembly | New string concat | `multiuser.session_key.build_session_key()` at `session_key.py:62` | Handles normalization, sanitization, identity-link substitution |
| Periodic task scheduling | `asyncio.create_task` + manual `while True: await sleep` | `schedule.every(N).minutes.do(fn)` from the `schedule` lib | Already in `GentleWorker.start()` at `gentle_worker.py:110-119` |

**Key insight:** This phase is ENTIRELY wiring work. Every component exists. The problem is glue, not invention. Anyone proposing a "small helper" or "utility function" should justify why the existing code doesn't work — usually it does.

## Runtime State Inventory

This is not a rename/migration phase, so this section documents the _behavioral_ runtime state that the bugs affect (not data-at-rest).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None. No schema changes, no migrations. | None — verified by grep for `CREATE TABLE`, `ALTER TABLE` in phase scope. |
| Live service config | `baileys-bridge` subprocess state (connection_state, auth_timestamp, restart_count) — in-process only, not persisted. Python side mirrors via `update_connection_state()` webhook. | None — bug is in Python; bridge state unaffected. |
| OS-registered state | `baileys-bridge/auth_state/` dir holds `creds.json` + `meta.json`. Not touched by Phase 12. | None — Phase 15 covers auth persistence. |
| Secrets/env vars | `BRIDGE_PORT`, `PYTHON_WEBHOOK_URL`, `PYTHON_STATE_WEBHOOK_URL` env vars set in `WhatsAppChannel.start()` (`channels/whatsapp.py:152-156`) — unchanged by this phase. | None. |
| Build artifacts | `baileys-bridge/node_modules/` — unchanged. | None. |

**Nothing found in category: Build artifacts** — verified by grepping for `.py[c]`, `__pycache__`, `.egg-info` references in phase-edited files. All Phase 12 edits are Python source — no compiled artifacts need refresh.

## Common Pitfalls

### Pitfall 1: Forgetting to Restart the Gateway After the Fix
**What goes wrong:** You fix `routes/whatsapp.py:147`, run tests (they pass because tests directly call the async method), then manually test — it still fails.
**Why it happens:** Uvicorn does not reload by default. The running process has the old bytecode cached. `CLAUDE.md` Gotcha #4 calls this out.
**How to avoid:** Kill the uvicorn process (`./synapse_stop.sh` or Ctrl-C on `uvicorn --reload`) and restart after ANY Python source edit.
**Warning signs:** Bug appears fixed in tests but reproduces in real WhatsApp traffic. Check `ps aux | grep uvicorn` — if the PID predates your edit, you're running stale code.

### Pitfall 2: Session Key Shape Change Breaks Unknown Downstream Consumers
**What goes wrong:** Fixing WA-FIX-04 changes `task.session_key` from `"whatsapp:direct:<chat_id>"` to `"agent:<target>:whatsapp:dm:<sanitized_peer>"`. If anyone downstream parses the old shape, it breaks silently.
**Why it happens:** `MessageTask.session_key` is set in `on_batch_ready` but is not currently consumed anywhere in production code (verified by grep: no `task.session_key` references in `sci_fi_dashboard/`). Future phases WILL consume it.
**How to avoid:** Before changing the shape, `grep -r "task\.session_key\|MessageTask.*session_key" workspace/` and confirm zero production consumers. Then the change is safe.
**Warning signs:** Tests pass but `conversation_cache.get()` always misses, or `SessionActorQueue` serializes when it shouldn't. Both are downstream symptoms of key mismatch.

### Pitfall 3: Deleting the Wrong Duplicate Skill-Routing Block
**What goes wrong:** You delete block #1 (`chat_pipeline.py:472-509`) instead of block #2 (`:546-586`). The second block has `getattr()` safety and `session_context` — losing those silently breaks spicy-session skill blocking.
**Why it happens:** Both blocks look nearly identical. A casual reader might think either is fine.
**How to avoid:** Roadmap explicitly names `chat_pipeline.py:546-586` as the duplicate to remove. Before deleting, diff the two blocks — block #2 has extras worth migrating to block #1 (e.g., the `session_context={"session_type": session_mode or ""}` kwarg to `SkillRunner.execute`). Merge then delete.
**Warning signs:** Skills that use `session_context` (like a hypothetical "notes" skill that branches on session type) misbehave after the cleanup. Also: if logs show `[Skills] Message routed to skill 'X'` twice per message instead of once, the delete didn't happen at all.

### Pitfall 4: Sleep Window is IST-Only, Hard-Coded
**What goes wrong:** A user in a different timezone expects proactive check-ins during their waking hours but doesn't get them because `maybe_reach_out()` uses IST (UTC+5:30) for the sleep window.
**Why it happens:** `proactive_engine.py:151` hard-codes `IST = timezone(timedelta(hours=5, minutes=30))`.
**How to avoid:** Document as a known limitation in the phase verification notes. Do NOT fix in this phase — that's a config addition (breaks "smallest diff" rule). Raise for future roadmap consideration.
**Warning signs:** Upstream bug reports about "no proactive messages during my morning." File for Phase 14+ config expansion.

### Pitfall 5: Event Loop Already Running When GentleWorker Schedules
**What goes wrong:** `GentleWorker.heavy_task_proactive_checkin()` at `gentle_worker.py:86-92` calls `asyncio.get_event_loop()` + `loop.create_task(...)`. If run from a thread other than the event loop's thread, `get_event_loop()` returns a new loop or raises.
**Why it happens:** `GentleWorker.start()` runs a sync `while True: schedule.run_pending(); time.sleep(1)` loop (`gentle_worker.py:116-119`). It's designed to run in its own thread, not the main event loop.
**How to avoid:** If you instantiate `GentleWorker` in `lifespan()`, run it via `asyncio.to_thread()` or `threading.Thread(target=worker.start)`. Use `asyncio.run_coroutine_threadsafe(coro, loop)` inside `heavy_task_proactive_checkin` instead of `loop.create_task` to safely cross threads. Capture the main loop via `asyncio.get_running_loop()` inside `lifespan` and pass it into `GentleWorker` at construction.
**Warning signs:** `RuntimeError: There is no current event loop in thread 'Thread-N'` — that's the smoking gun.

### Pitfall 6: `_proactive_engine` vs `GentleWorker.proactive_engine` Confusion
**What goes wrong:** `ProactiveAwarenessEngine` is assigned to `deps._proactive_engine` in `api_gateway.py:221` AND must be passed to `GentleWorker(proactive_engine=...)` separately. If you wire only one, the other is stale.
**Why it happens:** The engine serves two roles: (1) polls MCP sources for prompt injection (role A, handled in `lifespan()`), and (2) generates proactive check-in replies (role B, handled in `GentleWorker`). Both need the SAME instance for consistency.
**How to avoid:** Pass `deps._proactive_engine` (the already-initialized singleton) to `GentleWorker(proactive_engine=deps._proactive_engine, channel_registry=deps.channel_registry)`. Never construct a second `ProactiveAwarenessEngine`.
**Warning signs:** Proactive check-ins work but don't reference calendar/email context — or vice versa. Both are symptoms of two engine instances.

### Pitfall 7: Testing `await` Fix Without an Actual Route-Level Test
**What goes wrong:** You add `await` at `routes/whatsapp.py:147`, all existing tests in `test_polling_resilience.py` pass (they were already passing — they test the channel-side method, not the route handler). No regression test catches a future regression of the same bug.
**Why it happens:** Existing tests exercise `WhatsAppChannel.update_connection_state()` directly. The bug was in the HTTP route handler, which is not covered.
**How to avoid:** Add a NEW test in `tests/test_channel_whatsapp_extended.py` or `tests/test_api_gateway.py` that uses FastAPI TestClient + AsyncMock to POST to `/channels/whatsapp/connection-state` and assert `wa_channel.update_connection_state` was awaited (not just called).
**Warning signs:** Test suite is green but manual smoke test still fails. The unit tests don't reach the bug site.

## Code Examples

Verified patterns from the existing codebase — use directly, no adaptation needed.

### Fix WA-FIX-01: Await the coroutine
```python
# File: workspace/sci_fi_dashboard/routes/whatsapp.py:137-148
# Source: routes/whatsapp.py (current)
@router.post("/channels/whatsapp/connection-state")
async def whatsapp_connection_state(request: Request):
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        return {"ok": False, "detail": "WhatsApp channel not registered"}
    payload = await request.json()
    await wa_channel.update_connection_state(payload)  # ← ADD await
    return {"ok": True}
```

### Fix WA-FIX-03: Add isLoggedOut field
```python
# File: workspace/sci_fi_dashboard/channels/whatsapp.py:283-291
# Source: channels/whatsapp.py
async def get_status(self) -> dict:
    base = await self.health_check()
    base["connected_since"] = self._connected_since
    base["auth_timestamp"] = self._auth_timestamp
    base["restart_count"] = self._restart_count
    base["last_disconnect_reason"] = self._last_disconnect_reason
    base["connection_state"] = self._connection_state
    base["isLoggedOut"] = self._connection_state == "logged_out"  # ← NEW
    return base
```

### Fix WA-FIX-04: Use canonical builder
```python
# File: workspace/sci_fi_dashboard/pipeline_helpers.py:514-530
# Source: pipeline_helpers.py (current line 519 is the inline builder)
async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
    from gateway.queue import MessageTask
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.synapse_config import SynapseConfig

    is_group = metadata.get("is_group", False)
    channel_id = metadata.get("channel_id", "whatsapp")

    cfg = SynapseConfig.load()
    session_cfg = getattr(cfg, "session", {}) or {}
    target = deps._resolve_target(chat_id)
    session_key = build_session_key(
        agent_id=target,
        channel=channel_id,
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id=channel_id,
        dm_scope=session_cfg.get("dmScope", "per-channel-peer"),
        main_key="whatsapp:dm",
        identity_links=session_cfg.get("identityLinks", {}),
    )
    task = MessageTask(
        task_id=str(uuid.uuid4()),
        chat_id=chat_id,
        user_message=combined_message,
        message_id=metadata.get("message_id", ""),
        sender_name=metadata.get("sender_name", ""),
        channel_id=channel_id,
        is_group=is_group,
        session_key=session_key,
    )
    await deps.task_queue.enqueue(task)
```
Note: `_resolve_target(chat_id)` may perform I/O (checking SBS registry); if that's too heavy for the hot path, pass `target` through the metadata from `receive()` instead. Worth checking with a quick `grep "_resolve_target" workspace/` during implementation.

### Fix WA-FIX-05: Delete duplicate block
```python
# File: workspace/sci_fi_dashboard/chat_pipeline.py
# DELETE lines 546-586 (the second skill-routing block).
# MIGRATE to block #1 (lines 472-509) before deletion:
#   - `getattr(deps, "_SKILL_SYSTEM_AVAILABLE", False)` defensive form (probably safe to skip — deps is stable)
#   - `session_context={"session_type": session_mode or ""}` kwarg to SkillRunner.execute
#
# AFTER: line 509's `return {...}` is immediately followed by line 510 (current 588) — the `if session_mode == "spicy":` block.
# Verify: a single `grep -n "Skills] Message routed" workspace/sci_fi_dashboard/chat_pipeline.py` returns exactly ONE line.
```

### Fix PROA-01 + PROA-02 + PROA-03: Wire GentleWorker in lifespan
```python
# File: workspace/sci_fi_dashboard/api_gateway.py
# Add around line 221 (just after ProactiveAwarenessEngine init):
import threading

if deps._proactive_engine is not None:
    from sci_fi_dashboard.gentle_worker import GentleWorker
    app.state.gentle_worker = GentleWorker(
        graph=deps.brain,
        cron_service=app.state.cron_service,  # nullable
        proactive_engine=deps._proactive_engine,
        channel_registry=deps.channel_registry,
    )
    # Capture the running loop so heavy_task_proactive_checkin can submit coros
    app.state.gentle_worker._event_loop = asyncio.get_running_loop()
    app.state.gentle_worker_thread = threading.Thread(
        target=app.state.gentle_worker.start,
        daemon=True,
        name="gentle-worker",
    )
    app.state.gentle_worker_thread.start()
    logger.info("[GentleWorker] Started in background thread")

# Shutdown (add to the shutdown section around line 340):
if hasattr(app.state, "gentle_worker"):
    app.state.gentle_worker.is_running = False
    # Thread is daemon — will exit with process
```

And inside `gentle_worker.py`, adjust `heavy_task_proactive_checkin` to use `run_coroutine_threadsafe`:
```python
# File: workspace/sci_fi_dashboard/gentle_worker.py:77-92
def heavy_task_proactive_checkin(self):
    """Maybe reach out to users who haven't messaged in 8h+."""
    can_run, reason = self.check_conditions()
    if not can_run:
        return
    if not self.proactive_engine or not self.channel_registry:
        return
    loop = getattr(self, "_event_loop", None)
    if loop is None or not loop.is_running():
        return
    try:
        # run_coroutine_threadsafe is thread-safe; create_task is NOT
        asyncio.run_coroutine_threadsafe(self._async_proactive_checkin(), loop)
    except Exception as e:
        print(f"[WARN] Proactive check-in scheduling failed: {e}")
```

### Fix PROA-04: Emit SSE event
```python
# File: workspace/sci_fi_dashboard/gentle_worker.py:94-105
async def _async_proactive_checkin(self):
    from sci_fi_dashboard.pipeline_emitter import get_emitter
    for user_id, channel_id in [("the_creator", "whatsapp"), ("the_partner", "whatsapp")]:
        try:
            reply = await self.proactive_engine.maybe_reach_out(user_id, channel_id)
            if reply:
                channel = self.channel_registry.get(channel_id)
                if channel:
                    ok = await channel.send(user_id, reply)
                    if ok:
                        get_emitter().emit("proactive.sent", {
                            "channel_id": channel_id,
                            "user_id": user_id,
                            "reason": "silence_gap_8h",
                            "preview": reply[:80].encode("ascii", errors="replace").decode("ascii"),
                        })
                        print(f"[PROACTIVE] Sent check-in to {user_id}")
        except Exception as e:
            print(f"[WARN] Proactive {user_id} failed: {e}")
```
Preview is ASCII-encoded per CLAUDE.md Gotcha #5 (Windows cp1252 safety).

## State of the Art

### Async/Await Hygiene in FastAPI
| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `def handler(...)` sync + blocking calls | `async def handler(...)` + await all coroutines | FastAPI 0.x → 0.68+ | Linters now warn on "coroutine was never awaited" — unclear if Ruff catches it in this repo's config; consider enabling `RUF006` for future prevention |

### Baileys Bridge Patterns
| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual socket restart on any error | `DisconnectReason.loggedOut` vs other close codes branch | Baileys 6.x docs | `baileys-bridge/index.js:315-331` already does this correctly. No change needed for Phase 12. Phase 15 upgrades to 7.x. |

### Session-Key Builders in OpenClaw
| Synapse (current) | OpenClaw equivalent | Note |
|--------------|------------------|------|
| `multiuser/session_key.py:62` `build_session_key()` returns `agent:...` keys | `extensions/whatsapp/src/accounts.ts` + `resolve-target.ts` resolve `accountId` → peer tuples | Synapse's builder is MORE sophisticated (handles identity-link substitution, dm_scope variants). Don't downgrade — keep Synapse's version. |

**Deprecated/outdated:**
- The inline f-string at `pipeline_helpers.py:519` predates `build_session_key()` (which landed in the multi-user refactor). This PR cleans up the leftover.

## Assumptions Log

All claims in this research are VERIFIED by direct source-file grep / read, or CITED from roadmap/requirements text. No `[ASSUMED]` claims remain after verification.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | (None) | — | — |

**Table is empty — no user confirmation required for the research findings.**

One soft assumption worth flagging (not a hard claim, but a design choice):
- **Choice A:** Instantiate `GentleWorker` as a daemon thread vs. **Choice B:** Inline the proactive checkin into the existing async `gentle_worker_loop()`. The research recommends Choice A for smallest diff. If the planner wants Choice B for asyncio purity, that's also defensible — both satisfy the REQs. Leave for planner discretion.

## Open Questions (RESOLVED)

> **Status:** All 5 questions resolved during Wave 0 (Plan 12-00 Task 3).
> See `.planning/phases/12-p0-bug-fixes/12-00-SUMMARY.md` → `## Locked Decisions`
> for the machine-checkable resolution of each question. Wave 2 plans
> (12-01, 12-02, 12-03) cite these decisions by OQ-id.

1. **Does `_resolve_target(chat_id)` perform I/O that would make calling it from `on_batch_ready` too slow?**
   - What we know: `on_batch_ready` runs after FloodGate's 3s batch window — not in the HTTP hot path. One extra `dict.get()` or `SBSRegistry.lookup()` is fine.
   - What's unclear: Is `_resolve_target` pure, or does it touch disk?
   - Recommendation: During implementation, `grep "def _resolve_target" workspace/` and read the function. If it's pure dict lookup, inline is fine. If it touches disk, either cache it in `MessageTask.target` or keep the old f-string shape as fallback with a `TODO(WA-FIX-04)`. Planner should assign this as a 10-minute spike at the start of the task.

2. **Should PROA-04's `proactive.sent` event include the generated message body, or just metadata?**
   - What we know: Dashboard already renders `llm.stream_start`, `cognition.analyze_start` events with text previews.
   - What's unclear: Privacy concern — does the dashboard audit-log the full proactive reply?
   - Recommendation: Emit metadata only (`channel_id`, `user_id`, `reason`, 80-char preview). Matches existing event semantics. Planner can decide final shape.

3. **Does the bridge actually send `connectionState: "logged_out"` or is it `connectionState: "logged_out"` (string) vs `connection_state: "logged_out"` (snake_case mismatch)?**
   - What we know: `baileys-bridge/index.js:321` sends `notifyStateChange('logged_out')`. The payload shape at lines 91-101 uses `connectionState` (camelCase). Python at `channels/whatsapp.py:222` reads `payload.get("connectionState", "unknown")`. Shapes agree.
   - What's unclear: None — verified.
   - Recommendation: Test assertion should POST exactly `{"connectionState": "logged_out"}` (camelCase) to match the real bridge payload.

4. **Does `channel.send(the_creator, text)` correctly resolve "the_creator" as a JID?**
   - What we know: `WhatsAppChannel.send(chat_id, text)` at `channels/whatsapp.py:382` POSTs `{"jid": chat_id, ...}` to the bridge. The bridge expects a real JID like `919876@s.whatsapp.net`, NOT the string `"the_creator"`.
   - What's unclear: Does `GentleWorker._async_proactive_checkin` need to resolve `user_id → JID` via `deps._synapse_cfg.identityLinks` or equivalent?
   - Recommendation: Before shipping PROA-02, verify `channel.send("the_creator", ...)` produces a real delivery. If not, add JID resolution via `session.identityLinks["the_creator"][0]` or a lookup helper. This is the highest-risk piece of the phase — flag for the verification step. **This may require a Wave 0 spike.**

5. **Is `PipelineEventEmitter.emit()` safe to call from a non-event-loop thread?**
   - What we know: `pipeline_emitter.py:47-62` uses `q.put_nowait(msg)` inside `_broadcast()`. `put_nowait` is not thread-safe for `asyncio.Queue` — it should only be called from the loop's own thread.
   - What's unclear: Since `_async_proactive_checkin` runs as a coroutine via `run_coroutine_threadsafe`, the `emit()` call inside IS on the loop thread. Safe.
   - Recommendation: Verified safe as long as `run_coroutine_threadsafe` is used (per Pitfall 5). If planner picks Choice B (inline into `gentle_worker_loop()`), it's trivially safe since that loop already runs on the main event loop.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | All code | ✓ (assumed — project target) | 3.11 | — |
| fastapi | Route handler | ✓ | existing in repo | — |
| httpx | Bridge client | ✓ | existing | — |
| psutil | Thermal guard | ✓ | existing | — |
| schedule | GentleWorker scheduler | ✓ | existing (import at `gentle_worker.py:6`) | — |
| Node.js 18+ | Baileys bridge | ✓ (validated at `channels/whatsapp.py:108-133`) | 18+ | Bridge fails at startup if absent — unrelated to Phase 12 |
| pytest + pytest-asyncio | Test framework | ✓ | existing (`workspace/tests/pytest.ini`) | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

Phase 12 is purely internal code edits using already-installed packages. No external service adds, no new pip installs, no new binaries.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (auto mode) |
| Config file | `workspace/tests/pytest.ini` |
| Quick run command | `cd workspace && pytest tests/test_polling_resilience.py tests/test_channel_whatsapp_extended.py tests/test_skill_pipeline.py tests/test_proactive_engine.py -x` |
| Full suite command | `cd workspace && pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WA-FIX-01 | Route handler awaits `update_connection_state` | unit (route-level) | `cd workspace && pytest tests/test_channel_whatsapp_extended.py::TestConnectionStateRoute::test_route_awaits_update -x` | ❌ Wave 0 (new test class needed) |
| WA-FIX-02 | Code 515 triggers bridge restart | unit (channel) | `cd workspace && pytest tests/test_polling_resilience.py::TestWhatsAppCode515::test_code_515_triggers_restart -x` | ✅ (exists) |
| WA-FIX-02 | Code 515 via route (end-to-end glue) | integration | `cd workspace && pytest tests/test_channel_whatsapp_extended.py::TestConnectionStateRoute::test_515_routes_to_restart -x` | ❌ Wave 0 (new) |
| WA-FIX-03 | `isLoggedOut: true` appears in status | unit | `cd workspace && pytest tests/test_channel_whatsapp_extended.py::TestGetStatus::test_is_logged_out_field -x` | ❌ Wave 0 (new test method) |
| WA-FIX-04 | `on_batch_ready` and `process_message_pipeline` produce the same key for the same (chat_id, is_group) | unit | `cd workspace && pytest tests/test_channel_pipeline.py::TestSessionKeyCanonical::test_on_batch_ready_uses_canonical_builder -x` | ❌ Wave 0 (new test) |
| WA-FIX-05 | Single inbound message matches skill → exactly one `[Skills] Message routed` log | unit | `cd workspace && pytest tests/test_skill_pipeline.py::TestSkillRouting::test_skill_fires_exactly_once -x` | ❌ Wave 0 (new — can extend existing file) |
| PROA-01 | `GentleWorker` exists in lifespan `app.state` | integration | `cd workspace && pytest tests/test_api_gateway.py::TestLifespan::test_gentle_worker_started -x` | ❌ Wave 0 (new) |
| PROA-02 | `maybe_reach_out` → `channel.send()` integration (mocked) | integration | `cd workspace && pytest tests/test_proactive_engine.py::TestMaybeReachOutIntegration::test_checkin_sends_via_channel -x` | ❌ Wave 0 (new test class — existing file) |
| PROA-03 | `GentleWorker` skips when on battery OR CPU > 20% | unit | Already covered by `GentleWorker.check_conditions` testability — add explicit check | ❌ Wave 0 (recommend new) |
| PROA-04 | `proactive.sent` SSE event emitted on successful send | unit | `cd workspace && pytest tests/test_proactive_engine.py::TestMaybeReachOutIntegration::test_emits_proactive_sent_event -x` | ❌ Wave 0 (new) |
| Manual smoke | Real bridge reconnect flushes retry queue (the whole success criteria #1) | manual | Run `./synapse_start.sh`, disconnect WiFi, reconnect, send a message queued during downtime, assert delivery | — (manual only) |
| Manual smoke | Real force-kill bridge → 515 auto-restart (success criteria #2) | manual | `kill -9 $(pgrep -f baileys-bridge/index.js)`, re-pair, assert replies resume without manual Python restart | — (manual only) |

### Sampling Rate
- **Per task commit:** `cd workspace && pytest tests/test_polling_resilience.py tests/test_channel_whatsapp_extended.py tests/test_skill_pipeline.py tests/test_proactive_engine.py -x` (should take < 15s)
- **Per wave merge:** `cd workspace && pytest tests/ -v` (full suite; expect 2-5 min)
- **Phase gate:** Full suite green + two manual smoke tests (reconnect + 515) documented in `12-VERIFICATION.md` before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_channel_whatsapp_extended.py` — add `TestConnectionStateRoute` class covering WA-FIX-01 (route awaits) + WA-FIX-02-route-level (515 via POST)
- [ ] `tests/test_channel_whatsapp_extended.py` — extend `TestGetStatus` with `test_is_logged_out_field` (WA-FIX-03)
- [ ] `tests/test_channel_pipeline.py` — add `TestSessionKeyCanonical` asserting `on_batch_ready` produces same shape as `process_message_pipeline` (WA-FIX-04)
- [ ] `tests/test_skill_pipeline.py` — add `test_skill_fires_exactly_once` counting log entries (WA-FIX-05)
- [ ] `tests/test_api_gateway.py` — add `TestLifespan::test_gentle_worker_started` (PROA-01)
- [ ] `tests/test_proactive_engine.py` — add `TestMaybeReachOutIntegration` class with 3 tests: `test_checkin_sends_via_channel` (PROA-02), `test_skipped_when_on_battery` (PROA-03), `test_emits_proactive_sent_event` (PROA-04)
- [ ] `tests/` fixture for TestClient with mocked `deps` singletons — already present via `conftest.py`, verify during Wave 0

*(No new test framework or config changes needed — `pytest-asyncio` auto mode already configured at `workspace/tests/pytest.ini:14`.)*

## Security Domain

> Required since `security_enforcement` is not explicitly `false` in config.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Existing: `_require_gateway_auth` dep on `/channels/whatsapp/status` (`routes/whatsapp.py:104`). Phase 12 doesn't touch auth. Note: `/connection-state` at `:137` is UNAUTHENTICATED — the bridge POSTs to it without a token. This is existing behavior; Phase 12 preserves it. Phase 16 (BRIDGE hardening) may add token auth to this endpoint — out of scope here. |
| V3 Session Management | no | Phase 12 doesn't create sessions. |
| V4 Access Control | partial | `WhatsAppChannel.receive()` already invokes `resolve_dm_access()` (`channels/whatsapp.py:567-571`). No new access-control code in Phase 12. Phase 17 moves this pre-FloodGate. |
| V5 Input Validation | yes | Connection-state payload is JSON from trusted Node subprocess (localhost only). Risk: if an attacker reaches the loopback port, they could spoof logged-out state. Accept as current threat model — Phase 16 adds bridge-side auth. |
| V6 Cryptography | no | No crypto operations in this phase. Baileys auth creds are Phase 15. |
| V7 Error Handling & Logging | yes | **Gotcha #5 applies**: Any new log lines must be ASCII-safe (see PROA-04 emit preview encoding). |
| V8 Data Protection | partial | Proactive reply previews in SSE contain potentially sensitive AI-generated text. Truncating to 80 chars limits exposure; full body stays in chat only. |

### Known Threat Patterns for FastAPI + async Python

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Coroutine never awaited (WA-FIX-01 itself) | Tampering (state silently diverges) | Ruff `RUF006` if enabled; otherwise code review + route-level test asserting `.assert_awaited_once()` |
| Duplicate code path (WA-FIX-05) | Tampering (state mutations fire twice — here, skill execution + memory write + SBS log line) | Static duplication lint (unused in repo); mitigated by deletion |
| Unauthenticated webhook (`/connection-state`) | Spoofing | Deferred to Phase 16 (shared token in `BRIDGE_WEBHOOK_TOKEN` env) |
| Thread-unsafe singleton mutation (`GentleWorker` in thread + `PipelineEventEmitter` on main loop) | Repudiation (events dropped silently) | `run_coroutine_threadsafe` for cross-thread scheduling (see Pitfall 5) |
| SSE broadcast preview leaks PII (phone numbers) | Information Disclosure | PROA-04 preview truncated to 80 chars; Phase 13 adds `redact_identifier()`. Accept partial risk until then. |

No NEW security surface introduced by Phase 12. All four WA-FIX bugs REDUCE risk (fixing silent state divergence, duplicate state mutations). PROA features introduce outbound-message surface, but gated behind existing DmPolicy → `channel_registry.send()` → Baileys authenticated socket.

## Sources

### Primary (HIGH confidence — direct source file read)
- `workspace/sci_fi_dashboard/routes/whatsapp.py:137-148` — the bug site (WA-FIX-01)
- `workspace/sci_fi_dashboard/channels/whatsapp.py:215-238` — `update_connection_state` implementation, 515 handler, retry queue flush
- `workspace/sci_fi_dashboard/channels/whatsapp.py:283-291` — `get_status` where WA-FIX-03 field goes
- `workspace/sci_fi_dashboard/chat_pipeline.py:472-509` (block #1) and `:546-586` (block #2 — the duplicate to delete)
- `workspace/sci_fi_dashboard/pipeline_helpers.py:350-531` — `process_message_pipeline` (canonical key) + `on_batch_ready` (inline f-string to fix) + `gentle_worker_loop`
- `workspace/sci_fi_dashboard/multiuser/session_key.py:62-123` — `build_session_key` canonical implementation
- `workspace/sci_fi_dashboard/proactive_engine.py:133-188` — `maybe_reach_out` already complete
- `workspace/sci_fi_dashboard/gentle_worker.py:10-126` — `GentleWorker` class + `heavy_task_proactive_checkin` + thermal guard
- `workspace/sci_fi_dashboard/api_gateway.py:84-347` — full `lifespan()` where GentleWorker gets wired
- `workspace/sci_fi_dashboard/pipeline_emitter.py:47-102` — SSE emitter for PROA-04
- `workspace/sci_fi_dashboard/gateway/session_actor.py:13-57` — SessionActorQueue (consumer of session_key; verified it's instantiated but not yet wired to workers)
- `workspace/sci_fi_dashboard/gateway/worker.py:113-216` — `_handle_task` (confirms `task.session_key` unused downstream today)
- `workspace/sci_fi_dashboard/gateway/queue.py:17-37` — `MessageTask.session_key` field definition
- `baileys-bridge/index.js:282-332` — bridge connection.update handler, `logged_out` state emission
- `workspace/tests/test_polling_resilience.py:420-484` — existing channel-side tests for update_connection_state
- `workspace/tests/test_proactive_engine.py` — existing ProactiveAwarenessEngine tests
- `workspace/tests/pytest.ini` — test framework config (pytest-asyncio auto mode)
- `.planning/REQUIREMENTS.md:10-23` — WA-FIX-01..05 + PROA-01..04 canonical definitions
- `.planning/ROADMAP.md:109-119` — Phase 12 goal + 5 success criteria
- `.planning/STATE.md:93-110` — seed findings confirming bug sites

### Secondary (MEDIUM — reference context)
- `D:\Shorty\openclaw\extensions\whatsapp\src\auto-reply\monitor.ts:280-337` — OpenClaw watchdog pattern (Phase 14 reference, NOT Phase 12)
- `D:\Shorty\openclaw\extensions\whatsapp\src\reconnect.ts` — OpenClaw reconnect policy (Phase 14 reference)
- `CLAUDE.md` — OSS workflow rules, critical gotchas, code graph priority

### Tertiary (LOW — none)
No tertiary sources. All findings verified against repository contents.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies already installed and imported, zero new packages
- Architecture: HIGH — all patterns exist verbatim in the repo, Phase 12 is wiring not design
- Pitfalls: HIGH — Pitfalls 1-7 all derived from actual code inspection, not speculation
- Requirements → test map: MEDIUM — test methods are NEW (Wave 0), but existing test files + fixtures cover the plumbing

**Research date:** 2026-04-21
**Valid until:** 2026-05-21 (30 days — stable domain, no fast-moving libraries referenced)

**One open risk to re-verify at implementation start:**
- Whether `channel.send("the_creator", text)` resolves to a real WhatsApp JID without additional lookup. See Open Questions #4. If lookup is needed, the PROA-02 task gains ~30 lines; if not, it's 1 line. Recommend Wave 0 spike.
