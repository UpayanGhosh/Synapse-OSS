# Phase 16 Plan 04 Task 2 — Summary

## What was done

Three edits to `workspace/sci_fi_dashboard/api_gateway.py::lifespan()`.

### Edit 1 — HeartbeatRunner startup (after CronService block)

- `app.state.heartbeat_runner = None` initialised unconditionally before the try/except
- Guarded behind `cfg.heartbeat.get("enabled", False)` — disabled by default, zero runtime cost
- `_heartbeat_reply_adapter` closure wraps `persona_chat(req, "the_creator")` with `session_key="heartbeat"` to isolate heartbeat cycles from user conversation history
- `asyncio.wait_for(..., timeout=60.0)` prevents a slow LLM from blocking the loop forever
- `HeartbeatRunner` receives `get_emitter()` (not a module-level singleton — `pipeline_emitter.py` exposes a factory, not a `pipeline_emitter` attribute; plan had the wrong import, fixed here)
- Non-fatal: exception logs `[HEARTBEAT] Runner init failed` and resets state to `None`

### Edit 2 — BridgeHealthPoller startup (after WhatsApp retry queue)

- `app.state.bridge_health_poller = None` initialised unconditionally
- Guard: `isinstance(wa_ch, WhatsAppChannel) and hasattr(wa_ch, "_supervisor") and wa_ch._supervisor is not None`
- Config keys read from `cfg.bridge` with safe defaults: interval=30s, failures=3, timeout=5s, grace=60s
- `wa_ch._bridge_health_poller = poller` wired so `GET /channels/whatsapp/status` surfaces live `/health` data
- Same `get_emitter()` factory pattern for the emitter
- Non-fatal: exception logs `[BRIDGE_HEALTH] Poller init failed` and resets state to `None`

### Edit 3 — Shutdown (before `channel_registry.stop_all()`)

- Both stops execute BEFORE `channel_registry.stop_all()` — heartbeat cycles cannot race channel-down; poller cannot trigger a restart during shutdown
- Both guarded with `hasattr(app.state, ...) and app.state.<x> is not None`
- Both wrapped with `with suppress(Exception)` to guarantee clean shutdown even if `.stop()` raises

## Config fields consumed

| Field | Path in synapse.json | Default |
|---|---|---|
| `heartbeat.enabled` | `session.heartbeat.enabled` | `false` |
| `heartbeat.interval_s` | `session.heartbeat.interval_s` | `1800` |
| `heartbeat.recipients` | `session.heartbeat.recipients` | `[]` |
| `bridge.healthPollIntervalSeconds` | `session.bridge.healthPollIntervalSeconds` | `30` |
| `bridge.healthFailuresBeforeRestart` | `session.bridge.healthFailuresBeforeRestart` | `3` |
| `bridge.healthPollTimeoutSeconds` | `session.bridge.healthPollTimeoutSeconds` | `5` |
| `bridge.healthGraceWindowSeconds` | `session.bridge.healthGraceWindowSeconds` | `60` |

## app.state attributes added

| Attribute | Type when active | Type when disabled/failed |
|---|---|---|
| `app.state.heartbeat_runner` | `HeartbeatRunner` | `None` |
| `app.state.bridge_health_poller` | `BridgeHealthPoller` | `None` |

## Plan deviation

The plan specified `from sci_fi_dashboard.pipeline_emitter import pipeline_emitter as _pipeline_emitter` but `pipeline_emitter.py` exposes no module-level `pipeline_emitter` attribute — only `get_emitter()` factory function (confirmed by grep; all existing callers use `get_emitter`). Used `get_emitter()` instead to match actual module API.

## Verification results

- Import smoke: `python -c "from sci_fi_dashboard.api_gateway import app; print('import_ok')"` → `import_ok`
- `grep -c HeartbeatRunner api_gateway.py` → `2`
- `grep -c BridgeHealthPoller api_gateway.py` → `2`
- `grep -c heartbeat_runner.stop api_gateway.py` → `1`
- `grep -c bridge_health_poller.stop api_gateway.py` → `1`
- `ruff check` → no issues
- `black --check` → clean after autoformat

## Files touched

- `workspace/sci_fi_dashboard/api_gateway.py` — 3 edits (startup x2, shutdown x1)
- `.planning/phases/16-heartbeat-bridge-hardening/16-04-SUMMARY.md` — this file
