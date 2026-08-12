# Phase 16 Research: Heartbeat + Bridge Hardening

**Researched:** 2026-04-23
**Domain:** Python asyncio heartbeat scheduling + Node.js HTTP health contract + webhook idempotency
**Confidence:** HIGH (OpenClaw source read directly, Synapse bridge + channel + supervisor source read directly, Phase 13/14/15 primitives available) / MEDIUM (runtime flag semantics — showOk/showAlerts/useIndicator — ported from OpenClaw which is already in the repo at `D:/Shorty/openclaw/`)

---

## Summary

Phase 16 has **two tightly-bundled subsystems**, both built on top of Phase 13's emitter + Phase 14's supervisor infrastructure:

1. **Heartbeat runner (HEART-01..05)** — scheduled outbound pings to configured recipients. Port of OpenClaw's `extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` (`runWebHeartbeatOnce` + `resolveWhatsAppHeartbeatRecipients`) with the scheduling loop modelled after `src/infra/heartbeat-runner.ts::startHeartbeatRunner`.

2. **Bridge hardening (BRIDGE-01..04)** — Node bridge exposes `/health` with inbound/outbound activity timestamps + uptime + version; Python gateway polls every 30 s; N consecutive failures trigger a subprocess restart via the existing Phase 14 supervisor. Webhook dedup already exists (`MessageDeduplicator` at `gateway/dedup.py`, 300 s TTL) — this phase formalizes its response shape to `{accepted: true, reason: "duplicate"}` and makes it an explicit contract.

Three context-altering findings the planner must internalize:

1. **The `/health` endpoint already exists — but with the wrong shape.** `baileys-bridge/index.js:572-587` already returns `{status, connectionState, pid, connectedSince, authTimestamp, uptimeSeconds, restartCount, lastDisconnectReason}`. The BRIDGE-01 spec requires a slightly different shape: `{status, last_inbound_at, last_outbound_at, uptime_ms, bridge_version}`. **Decision needed:** extend the existing endpoint with the new fields (backward-compatible addition) OR migrate callers to the new schema. The existing shape is already consumed by `channels/whatsapp.py::health_check()` and surfaced at `GET /channels/whatsapp/status`. **Recommended:** additive — add the four new fields alongside the existing ones, never remove; `bridge_health` in `GET /channels/whatsapp/status` becomes the full superset. [VERIFIED via direct read of `baileys-bridge/index.js` + `channels/whatsapp.py`]

2. **MessageDeduplicator already does BRIDGE-04 — but callers don't get the canonical response shape.** `gateway/dedup.py` is a 32-line TTLCache with 300 s default window that returns `bool`. In `routes/whatsapp.py:81-82`, the current duplicate-hit response is `{"status": "skipped", "reason": "duplicate", "accepted": True}`. BRIDGE-04 asks for `{accepted: true, reason: "duplicate"}` which is *already satisfied* — but the `status: "skipped"` key is not explicitly contracted. Lowest-friction fix: keep the current shape, document it in a phase test, and add a `dedup_hit_rate` metric for operator observability. [VERIFIED via direct read]

3. **No Python heartbeat scheduler exists today, but every primitive needed is available.** `asyncio.create_task` loop with `monotonic()` + `asyncio.sleep` is the project's existing idiom (see `gateway/echo_tracker.py`, `channels/polling_watchdog.py::_watch_loop`). No new dependency is required — do NOT pull in APScheduler. The heartbeat loop is ~60 lines of Python matching the `PollingWatchdog` pattern exactly. [VERIFIED via direct read of `channels/polling_watchdog.py`]

**Primary recommendation:** Create `workspace/sci_fi_dashboard/gateway/heartbeat_runner.py` with a `HeartbeatRunner` class mirroring `PollingWatchdog`'s lifecycle (`start`/`stop`, `asyncio.create_task(_loop)` with `asyncio.sleep` interval). It reuses `channel_registry.get("whatsapp").send()` for delivery and Phase 13's `redact_identifier()` + `get_child_logger("gateway.heartbeat")` for PII-safe logging. Bridge-side: augment `GET /health` with `last_inbound_at`, `last_outbound_at`, `uptime_ms`, `bridge_version` (tracked via `sock.ev.on('messages.upsert'/'messages.update')` watchers that update module-level timestamps). Gateway-side: add `BridgeHealthPoller` under `channels/` that loops every 30 s, tallies consecutive failures, and calls `supervisor._on_stall`-equivalent to trigger `WhatsAppChannel._restart_bridge()` after N=3 consecutive failures. No new top-level dependency needed for either side.

---

## User Constraints (from CONTEXT.md)

**No CONTEXT.md exists for Phase 16 yet** (standalone research — discuss-phase not executed). Upstream constraints come from:

- `.planning/ROADMAP.md` Phase 16 block (6 success criteria)
- `.planning/REQUIREMENTS.md` HEART-01..05 + BRIDGE-01..04 (9 REQ-IDs)
- Roadmap dependency: Phases 13, 14, 15 are complete and their primitives MUST be reused (no duplication)
- Research-focus checklist provided at spawn

### Locked Decisions (from ROADMAP Phase 16 entry)

- **OpenClaw port target**: `extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` (`runWebHeartbeatOnce`, `resolveWhatsAppHeartbeatRecipients`, `HEARTBEAT_TOKEN`). Reference source is present in the repo at `D:/Shorty/openclaw/extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` and `D:/Shorty/openclaw/src/infra/heartbeat-runner.ts`.
- **Bridge /health poll cadence**: 30 s fixed (roadmap success criterion 3). Planner can expose as config but default MUST be 30 s.
- **Consecutive-failure restart threshold**: 3 (configurable via `bridge.healthFailuresBeforeRestart`; default 3 per roadmap).
- **Webhook dedup TTL**: 300 s (matches existing `MessageDeduplicator` default).
- **Dedup response shape**: `{accepted: true, reason: "duplicate"}` (BRIDGE-04).
- **Bridge restart uses Phase 14 supervisor**: `WhatsAppChannel._restart_bridge()` — no new restart path.
- **Heartbeat events carry runId**: every emit goes through Phase 13's `get_child_logger` + ContextVar so `runId` field appears in structured logs.

### Claude's Discretion

- Heartbeat scheduler: raw `asyncio.create_task` loop vs APScheduler. **Recommendation: raw asyncio** (matches project idiom, zero new dep, 60 lines).
- Heartbeat prompt source: inline default (OpenClaw style) vs externalized to `cli/templates/HEARTBEAT.md` (which already exists in the repo as a user-editable template for OpenClaw-compatible heartbeat). **Recommendation: config-first** — `heartbeat.prompt` in `synapse.json` overrides a sensible inline default; `HEARTBEAT.md` is OpenClaw's turn-of-events directive file and is orthogonal to the prompt itself.
- showOk / showAlerts / useIndicator semantics: ported from OpenClaw *as-is* (see "OpenClaw Port Map" below for exact semantics).
- Bridge /health field shape: extend existing or replace. **Recommendation: extend additively.**
- Bridge HTTP server: Express (already in place at `baileys-bridge/index.js`) — **no new server needed**, just add the fields and possibly a new middleware.
- Dedup metric: expose `dedup_hit_rate` under `GET /channels/whatsapp/status` as a bonus observability win (5 lines of code).
- Health-poll coupling: add `BridgeHealthPoller` as a sibling of `WhatsAppSupervisor`, NOT fold into it — they have different stall semantics (watchdog = inbound silence, poller = bridge unreachable).

### Deferred Ideas (OUT OF SCOPE for Phase 16)

- Multi-account heartbeat (Phase 18 — `MULT-*`).
- Heartbeat for channels other than WhatsApp (Telegram/Discord/Slack heartbeat). Roadmap scopes this to WhatsApp only.
- Full OpenClaw wake/schedule system (`heartbeat-wake.ts`, `heartbeat-events-filter.ts`, `heartbeat-active-hours.ts`) — Synapse's Phase 16 ships the minimum: fixed interval + HEARTBEAT_TOKEN strip + visibility flags. Active-hours gating, exec-event prompts, cron integration are deferred unless a success criterion requires them (none do).
- Heartbeat transcript pruning (OpenClaw prunes HEARTBEAT_OK turns from transcript files). Synapse doesn't have per-session transcript files in the same shape — defer.
- Heartbeat duplicate suppression (OpenClaw suppresses identical payloads within 24 h). Nice-to-have; not required by Phase 16 success criteria.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HEART-01 | User can configure heartbeat recipients (phone JIDs) in synapse.json | OpenClaw `resolveWhatsAppHeartbeatRecipients` — config key: `heartbeat.recipients: string[]`. Ported 1:1 to Python; stored under top-level `heartbeat.recipients` in synapse.json. |
| HEART-02 | Heartbeat prompt is user-configurable with a sensible default | OpenClaw `resolveHeartbeatPrompt(raw?: string): string` — returns raw if set else `HEARTBEAT_PROMPT` constant. Port: `heartbeat.prompt: string` in synapse.json, falls back to `"Health check — any updates?"` (recommended default; OpenClaw's default is more verbose because it references HEARTBEAT.md directives which Synapse does not use for this phase). |
| HEART-03 | Responses containing HEARTBEAT_TOKEN are stripped or suppressed | OpenClaw constant `HEARTBEAT_TOKEN = "HEARTBEAT_OK"` at `src/auto-reply/tokens.ts:3`. Port: Python constant + `strip_heartbeat_token()` helper that removes token at start/end with ≤4 trailing non-word chars (matches OpenClaw regex `${TOKEN}[^\\w]{0,4}$`). |
| HEART-04 | Visibility flags (showOk / showAlerts / useIndicator) independent per heartbeat | OpenClaw `resolveHeartbeatVisibility` at `src/infra/heartbeat-visibility.ts` — defaults `{showOk: false, showAlerts: true, useIndicator: true}`. Port: three independent booleans in `heartbeat.visibility` dict. Each controls a distinct behavior (OK ping vs content alerts vs typing indicator). |
| HEART-05 | Heartbeat failures never crash the gateway | Already a pattern Synapse uses — the `PollingWatchdog._watch_loop` swallows exceptions from `restart_callback` (`except Exception: logger.exception(...)`). Port the same shape: every heartbeat run is wrapped in `try/except Exception` with `_log.warning("heartbeat_failed", extra={"error": str(e)})`, then loop continues. |
| BRIDGE-01 | Node bridge exposes /health returning {status, last_inbound_at, last_outbound_at, uptime_ms, bridge_version} | Existing `/health` endpoint at `baileys-bridge/index.js:573` returns `{status, connectionState, pid, connectedSince, authTimestamp, uptimeSeconds, ...}`. Add new fields: `last_inbound_at` (tracked in `messages.upsert` event handler), `last_outbound_at` (tracked in `/send`, `/send-voice` response paths), `uptime_ms = Date.now() - processStartMs`, `bridge_version` read from `require('./package.json').version`. |
| BRIDGE-02 | Python gateway polls bridge /health every 30s and records results in /channels/whatsapp/status | New `BridgeHealthPoller` class under `channels/` with asyncio loop. Poll result cached on `WhatsAppChannel._bridge_health_cache` and surfaced at `get_status() → bridge_health` key. Existing `/channels/whatsapp/status` response already has `bridge` (old shape) and `bridge_health` is free; add it. |
| BRIDGE-03 | N consecutive bridge health failures trigger WhatsAppChannel subprocess restart | `BridgeHealthPoller._consecutive_failures` counter; at threshold N (default 3), call `WhatsAppChannel._restart_bridge()` which already exists. Planner must gate on `stop_reconnect` from Phase 14 supervisor so a `healthState=logged-out` does NOT trigger a restart (auth needs operator intervention). |
| BRIDGE-04 | Duplicate messageId within 300s returns {accepted: true, reason: "duplicate"} silently | Already in place at `routes/whatsapp.py:81-82` — current response is `{"status": "skipped", "reason": "duplicate", "accepted": True}`. Lock this contract in a test; optionally add a metric counter. |

---

## Dependencies From Prior Phases

### Phase 13 (Structured Observability) — COMPLETE

Key primitives this phase MUST reuse:

| Primitive | Location | Phase 16 Usage |
|-----------|----------|----------------|
| `mint_run_id()` | `sci_fi_dashboard.observability.context` | Heartbeat runner mints a runId at the start of each `run_heartbeat_once()` call so every emitted event/log in the cycle shares it. |
| `get_run_id()` | `sci_fi_dashboard.observability.context` | Bridge health poller reads the current ContextVar to tag each poll-result log with a correlation ID (one runId per poll cycle). |
| `get_child_logger(module, **extra)` | `sci_fi_dashboard.observability.logger_factory` | Every Phase 16 module uses `get_child_logger("gateway.heartbeat")` or `get_child_logger("channel.whatsapp.health")` — matches Phase 13 naming convention. |
| `redact_identifier(value)` | `sci_fi_dashboard.observability.redact` | Recipient JIDs in heartbeat logs MUST pass through `redact_identifier()`. OpenClaw's heartbeat-runner does exactly this (`redactIdentifier(to)` at `heartbeat-runner.ts:51`). |
| `JsonFormatter` + `RunIdFilter` | `sci_fi_dashboard.observability.formatter` + `.filters` | Already wired via `apply_logging_config()` in `api_gateway.lifespan()`. Phase 16 modules inherit this automatically — no wiring needed. |
| `PipelineEventEmitter.emit(event_type, data)` | `sci_fi_dashboard.pipeline_emitter` | [VERIFIED from read] `emit()` already reads `self._current_run_id` and includes it in SSE payload. After Phase 13-04, `start_run()` reuses ContextVar runId. For heartbeat: call `_get_emitter().emit("heartbeat.sent", {...})` — the emitter handles SSE dispatch + runId automatically. |
| MessageTask.run_id | `sci_fi_dashboard.gateway.queue` | Not directly used by heartbeat (heartbeats don't flow through FloodGate → Queue → Worker), but the ContextVar propagates across `asyncio.create_task` so a heartbeat-triggered `channel.send()` inherits the runId correctly. |

**New events this phase introduces** (all go through `PipelineEventEmitter.emit`):

```
heartbeat.send_start     { to_redacted, prompt_preview, run_id, cycle_index }
heartbeat.sent           { to_redacted, message_id, chars, run_id }
heartbeat.reply_received { to_redacted, reply_preview_redacted, run_id }
heartbeat.ok_empty       { to_redacted, silent, run_id }
heartbeat.ok_token       { to_redacted, silent, run_id }       # HEARTBEAT_TOKEN hit
heartbeat.skipped        { to_redacted, reason, run_id }       # alerts-disabled, dry-run, etc.
heartbeat.failed         { to_redacted, error, run_id }        # HEART-05 — never crash
bridge.health.poll       { ok, consecutive_failures, uptime_ms, last_inbound_age_s, run_id }
bridge.health.failed     { consecutive_failures, error, run_id }
bridge.health.restart    { reason, consecutive_failures, run_id }  # BRIDGE-03 trigger
bridge.webhook.duplicate { message_id_hash, age_s, run_id }    # BRIDGE-04 telemetry
```

### Phase 14 (Supervisor + Watchdog + Echo Tracker) — COMPLETE

| Primitive | Location | Phase 16 Usage |
|-----------|----------|----------------|
| `WhatsAppSupervisor.note_connected()` / `note_disconnect(code)` | `channels/supervisor.py` | Bridge health poller should call `note_connected()` on first success after a failure streak, and `note_disconnect("health-poll-timeout")` when the restart is triggered. Passing a non-numeric code ("health-poll-timeout") routes through `_CODE_TO_STATE.get(code, "stopped")` and falls through to `"reconnecting"` — confirmed by direct read of `supervisor.py:279-304`. |
| `WhatsAppSupervisor.stop_reconnect` | `channels/supervisor.py` | **Critical gate:** `BridgeHealthPoller` MUST check `supervisor.stop_reconnect` before triggering a restart. If the supervisor already halted reconnects (440 conflict, 401 logged-out), a health-poll-failure restart would loop a non-viable bridge. |
| `WhatsAppChannel._restart_bridge()` | `channels/whatsapp.py:236` | Already exists — used by code 515 restart-after-pairing. Phase 16 calls it for the same purpose: terminate subprocess, reschedule via existing supervisor restart path. No new restart code. |
| `ReconnectPolicy` | `channels/supervisor.py` | Backoff for bridge restarts is already driven by the supervisor's policy (read from `synapse.json → reconnect`). Phase 16 does NOT add a new backoff — consecutive-failures threshold just gates *when* to fire the existing restart path. |
| `healthState` enum | `channels/supervisor.py` | `connected | logged-out | reconnecting | conflict | stopped`. Phase 16 adds NO new states. Bridge unreachable for <N polls: state remains whatever supervisor last set (usually `connected`); at N failures: restart triggers → supervisor transitions to `reconnecting`. |

### Phase 15 (Auth Persistence + Baileys 7.x) — COMPLETE

- `@whiskeysockets/baileys@7.0.0-rc.9` is pinned in `baileys-bridge/package.json` [VERIFIED].
- Atomic creds queue (`lib/creds_queue.js::enqueueSaveCreds`) already runs — restarting the subprocess after 3 x 30 s = 90 s health failures is SAFE: in-flight saves drain via `waitForCredsSaveQueueWithTimeout(5000)` on SIGTERM (already wired in `index.js:702-713`).
- `creds.json.bak` restoration runs on `startSocket()` — so after a restart, corrupted creds are auto-healed via Phase 15's backup path.

**Implication:** Phase 16's subprocess restart path inherits Phase 15's auth-safety guarantees. No additional auth handling needed.

---

## OpenClaw Port Map

**Source availability:** OpenClaw is present in the repo at `D:/Shorty/openclaw/`. This phase ports from direct source reads, not from a spec.

### File-level port summary

| OpenClaw Source | Synapse Target | Port Scope |
|-----------------|----------------|------------|
| `extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` | `workspace/sci_fi_dashboard/gateway/heartbeat_runner.py` | Core `run_heartbeat_once()` logic — visibility check, prompt build, sender, token strip, event emit |
| `extensions/whatsapp/src/heartbeat-recipients.ts` | Inline helper in `heartbeat_runner.py` | `resolve_recipients(cfg)` — simpler than OpenClaw (no multi-account, no session-store cross-reference); Synapse reads `heartbeat.recipients: list[str]` directly |
| `src/auto-reply/tokens.ts` (`HEARTBEAT_TOKEN = "HEARTBEAT_OK"`) | Constant in `heartbeat_runner.py` | Literal port: `HEARTBEAT_TOKEN: str = "HEARTBEAT_OK"` |
| `src/auto-reply/heartbeat.ts::stripHeartbeatToken` | Function in `heartbeat_runner.py` | Port the start/end-trim semantics (≤4 trailing non-word chars stripped); markdown wrapper stripping is nice-to-have for MVP |
| `src/infra/heartbeat-visibility.ts::resolveHeartbeatVisibility` | `VisibilityConfig` dataclass + resolver in `heartbeat_runner.py` | Three-tier fallback (per-recipient > channel-defaults > hard-coded defaults). Synapse needs only one tier (top-level `heartbeat.visibility` dict) for MVP — planner may expose more tiers if a success criterion demands |
| `src/infra/heartbeat-runner.ts::startHeartbeatRunner` | `HeartbeatRunner` class in `heartbeat_runner.py` | Scheduling loop — `asyncio.create_task(_loop())` with `asyncio.sleep(interval)`. OpenClaw uses `setTimeout`; Synapse uses asyncio. Same shape, different primitive |

### `HEARTBEAT_TOKEN` semantics (verified from OpenClaw source)

Constant: `HEARTBEAT_TOKEN = "HEARTBEAT_OK"` [VERIFIED from `D:/Shorty/openclaw/src/auto-reply/tokens.ts:3`]

**Where the token is generated:** by the LLM, in response to the heartbeat prompt — the system prompt (or user prompt) tells the model *"if nothing needs attention, reply HEARTBEAT_OK"*. When the model replies with exactly `HEARTBEAT_OK` (or that substring with up to 4 trailing non-word chars), the runner treats this as a "no-news" signal and suppresses the reply from the user unless `showOk: true`.

**Where the token is stripped:** inside the runner after the LLM reply arrives, before deciding whether to send outbound. Strip logic:

```python
# Python port of stripHeartbeatToken (OpenClaw heartbeat.ts)
def strip_heartbeat_token(raw: str) -> tuple[str, bool]:
    """Return (stripped_text, should_skip).

    should_skip=True when the resulting text after strip is empty — meaning
    the original message was nothing BUT the token. Caller decides whether
    to send a HEARTBEAT_OK ping (showOk=True) or go silent (showOk=False).
    """
    text = (raw or "").strip()
    if not text:
        return "", True
    token = "HEARTBEAT_OK"
    if token not in text:
        return text, False

    # Strip from start:
    while text.startswith(token):
        text = text[len(token):].lstrip()

    # Strip from end with up to 4 trailing non-word chars:
    import re
    tail_pattern = re.compile(re.escape(token) + r"[^\w]{0,4}$")
    while tail_pattern.search(text):
        m = tail_pattern.search(text)
        text = text[:m.start()].rstrip()

    return text.strip(), not text.strip()
```

### Runtime flags — verified semantics

From OpenClaw `heartbeat-visibility.ts` (read directly):

| Flag | Default | Semantics |
|------|---------|-----------|
| `showOk` | `false` | If true AND the LLM reply is empty/HEARTBEAT_OK, send a literal "HEARTBEAT_OK" message to the recipient (confirms the bot is alive). If false, stay silent on ok responses. |
| `showAlerts` | `true` | If true, forward *content* replies (non-empty, non-HEARTBEAT_OK) to the recipient. If false, the LLM is consulted but its content reply is dropped — useful for telemetry-only mode. |
| `useIndicator` | `true` | If true, emit `indicatorType` in the heartbeat event — meaningful for UIs that render send/ok/ok-empty/ok-token/failed indicator badges. If false, events omit the indicator field. For Synapse, this maps to the dashboard SSE stream — the dashboard may or may not render indicators, but the flag's contract is "include the indicator metadata in the emit payload". |

**Independence is required (HEART-04):** each of the 3 flags is applied *independently*. `showAlerts: false, showOk: true, useIndicator: false` is a valid combination (telemetry-only mode with OK pings).

### Recipient resolution (simplified)

OpenClaw resolves recipients via a three-step waterfall (flag-override → session-store → configured allowFrom). Synapse Phase 16 does NOT have the same session-store shape (our session persistence is shaped differently) — **simplify to two sources:**

```python
def resolve_recipients(cfg: SynapseConfig, to_override: str | None = None) -> list[str]:
    if to_override:
        return [normalize_jid(to_override)]
    return [normalize_jid(r) for r in cfg.heartbeat.get("recipients", []) if r]
```

JIDs are already in `@s.whatsapp.net` form in the config; `normalize_jid` simply trims whitespace and validates the `@` suffix.

---

## Bridge /health Contract

### Current shape (read directly from `baileys-bridge/index.js:573-587`)

```json
{
  "status": "ok" | "degraded",
  "connectionState": "connected" | "reconnecting" | "logged_out" | "awaiting_qr" | "disconnected",
  "pid": 12345,
  "connectedSince": "2026-04-23T09:00:00.000Z" | null,
  "authTimestamp": "2026-03-15T18:20:33.000Z" | null,
  "uptimeSeconds": 3600,
  "restartCount": 0,
  "lastDisconnectReason": "515" | null
}
```

### Target shape (BRIDGE-01)

**Additive** — keep all existing keys, add 4 new ones:

```json
{
  "status": "ok" | "degraded",
  "connectionState": "...",
  "pid": 12345,
  "connectedSince": "...",
  "authTimestamp": "...",
  "uptimeSeconds": 3600,
  "restartCount": 0,
  "lastDisconnectReason": null,

  // NEW in Phase 16:
  "last_inbound_at": "2026-04-23T09:05:12.000Z" | null,
  "last_outbound_at": "2026-04-23T09:05:15.000Z" | null,
  "uptime_ms": 3600000,
  "bridge_version": "1.0.0"
}
```

### Bridge-side wiring

| Field | Source | Implementation |
|-------|--------|-----------------|
| `last_inbound_at` | `sock.ev.on('messages.upsert', ...)` (line 390) | Module-level `let lastInboundAtMs = null;`. In `messages.upsert` handler (AFTER the `if (msg.key.fromMe) continue;` filter), set `lastInboundAtMs = Date.now()`. Also update on `messages.update`, `message-receipt.update` if we want to count receipts. Recommended: inbound messages only (to align with Phase 14 watchdog semantics). |
| `last_outbound_at` | `/send`, `/send-voice`, `/react` routes | Module-level `let lastOutboundAtMs = null;`. Set inside each send route AFTER `sock.sendMessage(...)` succeeds. |
| `uptime_ms` | `Date.now() - processStartMs` | Already effectively tracked via `connectedSince`, but `uptime_ms` is *process* uptime, not connection uptime. Set `const processStartMs = Date.now();` at module top. `uptime_ms = Date.now() - processStartMs` at request time. |
| `bridge_version` | `require('./package.json').version` | One line: `const BRIDGE_VERSION = require('./package.json').version;` at module top. Currently `"1.0.0"`. |

**ISO serialization for timestamps** — match existing `connectedSince` convention (`new Date(ms).toISOString()`). This makes all timestamps uniformly comparable by operators via `jq` / `grep`.

**No new dependencies.** Express + existing Baileys event hooks cover everything.

### Gateway-side polling contract

```python
# workspace/sci_fi_dashboard/channels/bridge_health_poller.py  (new)
class BridgeHealthPoller:
    """Polls bridge GET /health every `interval_s` seconds.

    State tracked:
      - `_last_ok_at`: monotonic seconds of last successful poll
      - `_consecutive_failures`: int counter, reset on success
      - `_last_health`: dict of most recent /health response (for status API)

    On `_consecutive_failures >= failures_before_restart` AND NOT `supervisor.stop_reconnect`:
      - Emit `bridge.health.restart` event
      - Call `channel._restart_bridge()`  (Phase 14 path)
      - Reset `_consecutive_failures` to 0 AFTER restart initiates
    """

    def __init__(
        self,
        channel: WhatsAppChannel,
        supervisor: WhatsAppSupervisor,
        interval_s: float = 30.0,
        failures_before_restart: int = 3,
        timeout_s: float = 5.0,
    ) -> None:
        self._channel = channel
        self._supervisor = supervisor
        self._interval_s = interval_s
        self._failures_threshold = failures_before_restart
        self._timeout_s = timeout_s
        self._task: asyncio.Task | None = None
        self._consecutive_failures = 0
        self._last_health: dict = {}
        self._last_ok_at: float | None = None

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def poll_once(self) -> bool: ...  # returns True on success
    async def _loop(self) -> None: ...
    @property
    def last_health(self) -> dict: ...
    @property
    def consecutive_failures(self) -> int: ...
```

### Where the HTTP server lives

Already running. `baileys-bridge/index.js:697` — `app.listen(PORT, ...)`. No new server needed. Just add endpoint behavior.

---

## Webhook Idempotency Design

### Where dedup lives today (VERIFIED)

`gateway/dedup.py` — 32 LOC `MessageDeduplicator` class with `is_duplicate(message_id) -> bool`. 300 s TTL, periodic cleanup every 60 s.

Invoked in `routes/whatsapp.py:81-82`:

```python
effective_msg_id = msg.message_id or raw.get("message_id", "") or str(uuid.uuid4())
if deps.dedup.is_duplicate(effective_msg_id):
    return {"status": "skipped", "reason": "duplicate", "accepted": True}
```

### What BRIDGE-04 requires

Roadmap criterion 5: *"duplicate messageId within 300s — the second POST returns `{accepted: true, reason: "duplicate"}` and the message is not re-processed"*.

**Current behavior already satisfies this** (BRIDGE-04 is effectively a test-lock + metric, not new code). The only gap: the `status: "skipped"` key is not part of the REQ — the REQ says `{accepted: true, reason: "duplicate"}` literally. Both the current shape and the REQ shape are satisfiable simultaneously by keeping all three keys (`status`, `reason`, `accepted`).

### Where it sits: gateway vs bridge

**Decision: gateway side only** (status quo). Rationale:

1. Bridge is single-writer (one Baileys session → one `messages.upsert` stream) so inter-bridge dup is unlikely.
2. Gateway-side dedup also catches retries from HTTP middleware (if FastAPI or a reverse proxy ever retries a webhook), not just bridge-side retries.
3. Moving dedup to the bridge would require persistent storage (SQLite), making the bridge stateful — against the current design.

### Reuse of `MessageDeduplicator`

Direct reuse — no new dedup class. Add one observability upgrade:

```python
# in MessageDeduplicator
def __init__(self, window_seconds: int = 300) -> None:
    ...
    self.hits: int = 0        # NEW: count duplicates seen
    self.misses: int = 0      # NEW: count non-duplicates seen

def is_duplicate(self, message_id: str) -> bool:
    ...
    if message_id in self.seen:
        self.hits += 1
        return True
    self.seen[message_id] = now
    self.misses += 1
    return False
```

Surface at `/channels/whatsapp/status.dedup` or `/gateway/status.dedup`.

### Response shape (locked contract after Phase 16)

```json
{
  "status": "skipped",
  "reason": "duplicate",
  "accepted": true
}
```

All three keys required. Tests MUST assert *at least* `accepted == True` and `reason == "duplicate"` (the REQ-compliant subset).

---

## Config Shape (synapse.json)

### New top-level sections

```json
{
  "heartbeat": {
    "_comment": "HEART-01..05: scheduled bot-aliveness pings to configured recipients. Zero-config safe: omit this block to disable heartbeats.",
    "enabled": true,
    "interval_s": 1800,
    "recipients": ["919000000000@s.whatsapp.net"],
    "prompt": "Health check — any updates?",
    "ack_max_chars": 300,
    "visibility": {
      "showOk": false,
      "showAlerts": true,
      "useIndicator": true
    }
  },
  "bridge": {
    "_comment": "BRIDGE-02/03: health-poll contract between gateway and Baileys bridge.",
    "healthPollIntervalSeconds": 30,
    "healthFailuresBeforeRestart": 3,
    "healthPollTimeoutSeconds": 5
  }
}
```

### Validation rules

| Key | Type | Default | Validation |
|-----|------|---------|-----------|
| `heartbeat.enabled` | bool | `false` (absent section = disabled) | — |
| `heartbeat.interval_s` | int | `1800` (30 min) | must be ≥ 60 (prevent accidental DDoS-yourself); warn if < 300 |
| `heartbeat.recipients` | list[str] | `[]` | each entry matches `^\d+@s\.whatsapp\.net$` or `^\d+@g\.us$`; empty list means disabled |
| `heartbeat.prompt` | str | `"Health check — any updates?"` | strip to ensure not empty after trim |
| `heartbeat.ack_max_chars` | int | `300` | must be ≥ 0; matches OpenClaw default |
| `heartbeat.visibility.showOk` | bool | `false` | — |
| `heartbeat.visibility.showAlerts` | bool | `true` | — |
| `heartbeat.visibility.useIndicator` | bool | `true` | — |
| `bridge.healthPollIntervalSeconds` | int | `30` | must be ≥ 5 (don't hammer); warn if < 10 |
| `bridge.healthFailuresBeforeRestart` | int | `3` | must be ≥ 1 |
| `bridge.healthPollTimeoutSeconds` | int | `5` | must be < `healthPollIntervalSeconds` |

### Slot-in without breaking existing schema

`workspace/synapse_config.py::SynapseConfig` currently has 14 fields; adding 2 more:

```python
@dataclass(frozen=True)
class SynapseConfig:
    ...
    heartbeat: dict = field(default_factory=dict)   # NEW
    bridge: dict = field(default_factory=dict)      # NEW
```

Load classmethod additions (in `load()`):

```python
heartbeat_raw = raw.get("heartbeat", {})
bridge_raw = raw.get("bridge", {})
...
return cls(
    ...
    heartbeat=heartbeat_raw,
    bridge=bridge_raw,
)
```

**Reuse pattern from Phase 13 OBS-04:** keep the section as `dict` (not a typed dataclass), let the consumer-side code (heartbeat_runner, bridge_health_poller) do the `.get("interval_s", 1800)`-style lookups. This matches the existing `logging: dict` pattern perfectly.

Pydantic schema (`workspace/config/schema.py`) — optional: add `heartbeat` + `bridge` as optional fields on `SynapseConfigSchema` with proper validation. If the planner wants strict validation, this is the place.

---

## Scheduler Pattern

### Recommendation: raw asyncio (no APScheduler)

**Why:**
1. Project has zero APScheduler usage today — every scheduler-shaped thing uses `asyncio.create_task` + `asyncio.sleep`. See `gateway/flood.py::_wait_and_flush`, `channels/polling_watchdog.py::_watch_loop`, `gateway/retry_queue.py::start`. Consistency matters.
2. Heartbeat scheduling is trivial: fixed interval, one recipient list, no calendar/cron-expression complexity. A `while True: run(); await sleep(interval)` loop is ~15 lines.
3. APScheduler is ~250 KB of dep code for zero capability gain at Phase 16 scope.
4. CLAUDE.md § Code Style: *"asyncio throughout (no Redis/Celery)"* — direct alignment.

### Concrete shape (mirrors `PollingWatchdog`)

```python
# gateway/heartbeat_runner.py
class HeartbeatRunner:
    def __init__(
        self,
        channel_registry,
        cfg: SynapseConfig,
        interval_s: float = 1800.0,
    ) -> None:
        self._channel_registry = channel_registry
        self._cfg = cfg
        self._interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._cycle_count: int = 0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop())
        _log.info("heartbeat_runner_started", extra={"interval_s": self._interval_s})

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _loop(self) -> None:
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(self._interval_s)
                if self._stopped.is_set():
                    break
                try:
                    await self._run_cycle()
                except Exception as exc:
                    # HEART-05: never crash
                    _log.warning(
                        "heartbeat_cycle_failed",
                        extra={"error": str(exc), "cycle": self._cycle_count},
                    )
        except asyncio.CancelledError:
            pass

    async def _run_cycle(self) -> None:
        self._cycle_count += 1
        mint_run_id()  # Phase 13: new runId per cycle
        recipients = resolve_recipients(self._cfg)
        wa = self._channel_registry.get("whatsapp")
        if wa is None or not recipients:
            _log.debug("heartbeat_skip", extra={"reason": "no-channel-or-recipients"})
            return
        for to in recipients:
            await self._run_heartbeat_once(wa, to)
```

### Wiring into the gateway lifespan

`workspace/sci_fi_dashboard/api_gateway.py::lifespan` already constructs `CronService`, `GentleWorker`, and `RetryQueue`. Add the heartbeat runner alongside:

```python
# After channel_registry.start_all()
if deps._synapse_cfg.heartbeat.get("enabled", False):
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner
    app.state.heartbeat_runner = HeartbeatRunner(
        channel_registry=deps.channel_registry,
        cfg=deps._synapse_cfg,
        interval_s=float(deps._synapse_cfg.heartbeat.get("interval_s", 1800)),
    )
    await app.state.heartbeat_runner.start()
```

Teardown (in lifespan's shutdown phase):

```python
if hasattr(app.state, "heartbeat_runner"):
    await app.state.heartbeat_runner.stop()
```

### Bridge health poller — same pattern

```python
# channels/bridge_health_poller.py
class BridgeHealthPoller:
    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(self._interval_s)
                if self._stopped.is_set():
                    break
                ok = await self.poll_once()
                if not ok:
                    self._consecutive_failures += 1
                    if (
                        self._consecutive_failures >= self._failures_threshold
                        and not self._supervisor.stop_reconnect
                    ):
                        await self._trigger_restart()
                        self._consecutive_failures = 0
                else:
                    self._consecutive_failures = 0
        except asyncio.CancelledError:
            pass

    async def poll_once(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                r = await client.get(f"http://127.0.0.1:{self._channel._port}/health")
                if r.status_code != 200:
                    return False
                self._last_health = r.json()
                self._last_ok_at = time.monotonic()
                return True
        except httpx.RequestError:
            return False
```

Wire into `WhatsAppChannel.start()` alongside the existing supervisor start.

---

## PII Redaction

### Existing infrastructure (Phase 13)

`workspace/sci_fi_dashboard/observability/redact.py::redact_identifier(value: str | None) -> str` — HMAC-SHA256 salted redaction, returns `id_<8hex>` format. Per-install salt at `~/.synapse/state/logging_salt`, chmod 600 [VERIFIED from 13-RESEARCH.md + direct file read].

Used throughout the codebase:
- `routes/whatsapp.py:73` — `redact_identifier(msg.chat_id)` for echo-drop logs
- `channels/whatsapp.py:631-634` — `dm_blocked` log uses structured `extra={"user_id": cm.user_id}` (formatter auto-redacts sensitive field names)
- Phase 13's `JsonFormatter._SENSITIVE_FIELDS` set auto-redacts `chat_id`, `user_id`, `jid`, `phone`, `sender_id` when placed in `extra={}`

### Phase 16 application points

| Log site | Field | Redaction approach |
|----------|-------|--------------------|
| `heartbeat.send_start` event | `to_redacted` | Explicit — `redact_identifier(to)` in payload (OpenClaw pattern at `heartbeat-runner.ts:51`) |
| `heartbeat.sent` event | `to_redacted` | Same |
| `heartbeat.reply_received` event | `reply_preview_redacted` | Truncate to 60 chars AND explicitly call `redact_identifier` on it (replies can contain arbitrary JIDs if recipient echoes "my number is 91…") |
| `heartbeat_runner_loop_failed` log | `error` — user JID would be in exception message | Wrap exception: the outer `except` captures `str(exc)`. If the exception message contains a raw JID, it leaks. Mitigation: use `extra={"to": to}` (auto-redacted by formatter via `_SENSITIVE_FIELDS`); don't embed `to` in the exception text path |
| `bridge.health.poll` event | none (no PII in /health response) | None needed |

### No new redactor needed

OpenClaw's `redactIdentifier` is already ported as `redact_identifier` in Phase 13.

**Content-level redaction:** OpenClaw does NOT redact message content (reply previews) either. Synapse Phase 16 follows suit for consistency.

---

## Risks / Gotchas

### G1. FloodGate interaction with inbound heartbeat replies

When a recipient replies to the heartbeat prompt, that reply enters the normal WhatsApp pipeline: webhook → FloodGate → Dedup → Queue → Worker → persona_chat. This is correct — heartbeat replies go through the pipeline like any inbound message.

**But:** the heartbeat runner's `_run_heartbeat_once()` does NOT wait for the reply. It only records that a heartbeat was SENT. The reply arrives asynchronously via the normal inbound path. The ROADMAP success criterion says *"exactly N send-events and N response-events per heartbeat cycle"* — this is asserting the pipeline-emitter stream, not a RPC-style wait.

**Implication:** the heartbeat test harness needs to observe BOTH event streams: outbound `heartbeat.sent` (emitted from runner) + inbound `heartbeat.reply_received` (needs to be emitted from the inbound path when a reply matches a recent heartbeat message-id).

**Risk:** tracking "which inbound messages correspond to which heartbeat" requires a `recent_heartbeat_outbound` ring buffer (similar to `OutboundTracker` but keyed by chat_id + message_id). Without it, the reply-received event is indistinguishable from any other inbound message.

**Mitigation options:**
1. **Rider on OutboundTracker** — already records outbound `(chat_id, text_hash, timestamp)`. Extend with `message_id` and a `source` tag (`"heartbeat"` | `"user"`); `unified_webhook` can emit `heartbeat.reply_received` when an inbound's `in_reply_to_id` matches a tracked heartbeat. Low complexity.
2. **Separate `HeartbeatReplyTracker`** — duplicate OutboundTracker for heartbeats specifically. Clean separation but 80 LOC of duplicated logic.
3. **Look at WhatsApp's quoted-message reply-id** — when a user taps-to-reply on a heartbeat, WhatsApp payload includes `msg.key.quotedMessage.id`. The bridge can surface this as `quoted_message_id` in the webhook payload; the webhook compares against the heartbeat-sent message-id. Most precise, requires bridge-side enrichment (~10 LOC in `extractPayload`).

**Recommendation:** Option 1 (extend OutboundTracker) — reuses existing infra, 20 LOC change.

### G2. Three-strike restart race with supervisor watchdog

The Phase 14 `WhatsAppSupervisor` already has a stall-detection loop firing after 1800 s of inbound silence. The Phase 16 `BridgeHealthPoller` fires after 90 s (3 × 30 s) of bridge unreachability.

**Race:** if bridge becomes unreachable AND inbound silence coincides, both could fire. Both ultimately call `_restart_bridge()`. Idempotency of that call matters.

Inspection of `WhatsAppChannel._restart_bridge()` (line 236):
```python
async def _restart_bridge(self) -> None:
    logger.info("[WA] Restarting bridge (code-515 restart-after-pairing)")
    await self.stop()
    asyncio.create_task(self.start())
```

`self.stop()` sets `self._status = "stopped"` and kills the subprocess. Calling it twice back-to-back is SAFE — second call no-ops on `self._proc.returncode is not None`. But `asyncio.create_task(self.start())` twice would start TWO bridge subprocesses simultaneously — **disaster**.

**Mitigation:** add a `_restart_in_progress: asyncio.Event` flag on `WhatsAppChannel`; set it at entry to `_restart_bridge`, clear on completion. Both pollers check the flag and no-op if it's set. ~10 LOC.

### G3. Bridge /health timeout vs heartbeat send timeout

The bridge responds to `GET /health` synchronously (no async I/O). But the `/send` endpoint calls `sock.sendMessage` which CAN block (anti-spam jitter is a 1-3 s `setTimeout`, and sendMessage itself can hang on network).

If a heartbeat send is in-flight, the bridge process is busy — but `/health` responds instantly because Express has a separate request handler. **No contention.** [VERIFIED by reading the Express request handlers in `index.js`]

### G4. Consecutive-failures counter reset semantics

After a bridge restart triggered by failures, when does `_consecutive_failures` reset?

**Options:**
1. Reset to 0 AT restart trigger (my recommendation in the code sketch).
2. Reset to 0 only on FIRST successful poll after restart.

**Trap with Option 1:** if the restart fails (subprocess won't spawn), the poller continues polling, starts failing again, counts up to 3 again, and triggers ANOTHER restart — a restart storm.

**Trap with Option 2:** if the counter never resets (e.g., because the restart took longer than the poll interval and multiple polls were already in flight), could double-trigger.

**Correct approach:** after a restart trigger, SUSPEND polling for a grace period (e.g., 60 s = 2 × poll interval) to give the bridge time to come up. Then resume. If polling during grace period, don't count failures.

```python
async def _trigger_restart(self) -> None:
    self._consecutive_failures = 0
    self._grace_until = time.monotonic() + 60.0  # 2 * interval
    await self._channel._restart_bridge()

async def _loop(self) -> None:
    ...
    if time.monotonic() < self._grace_until:
        continue  # skip this poll
    ...
```

### G5. Heartbeat cycle during `healthState=conflict`

If Phase 14 supervisor has transitioned to `conflict` or `logged-out`, the bridge is intentionally unresponsive — we do NOT want heartbeat sends to be queued up and fail. The heartbeat runner should check `supervisor.stop_reconnect` before sending.

Mitigation: in `_run_cycle()`, guard:
```python
wa = self._channel_registry.get("whatsapp")
if wa is None:
    return
if hasattr(wa, "_supervisor") and wa._supervisor.stop_reconnect:
    _log.info("heartbeat_skip", extra={"reason": "supervisor-halted"})
    return
```

### G6. Bridge /health can return 401 when auth is stale

[VERIFIED] Current `WhatsAppChannel.health_check()` at line 294 already handles a 401 response — `logger.warning("[WA] Health check returned 401 — clearing stale auth cache")`. The gateway poller MUST keep this behavior. A 401 is NOT a "failure to reach the bridge" — it's "bridge is up but session is invalid". Do NOT count 401 as a consecutive-failures hit.

Mitigation: in `poll_once`, `if r.status_code == 401: self._last_health = {"status": "degraded", "error": "auth_expired"}; return True` — treat as "not a poll failure, but degraded".

### G7. `bridge_version` from package.json caching

`require('./package.json').version` is cached at module-load time by Node's require-cache. If we ever update the running bridge's package.json without restarting the subprocess, the `/health` response would still show the old version. This is a non-issue in practice (the subprocess MUST restart to pick up new code anyway) but document it.

### G8. Restarting during in-flight creds.update

Phase 15's `enqueueSaveCreds` queue ensures at most one save per authDir is in-flight, but SIGTERM → `waitForCredsSaveQueueWithTimeout(5000)` guards against lost saves. **The bridge restart path already does SIGTERM before SIGKILL** (`channels/whatsapp.py:225-234` — `terminate()` then `kill()` after 5 s). So Phase 15's timeout (5 s) matches Phase 14/16's kill grace (5 s) exactly. Confirmed safe.

### G9. Windows cp1252 in heartbeat log content

CLAUDE.md gotcha #5: Windows stdout is cp1252. Phase 13's `JsonFormatter(ensure_ascii=True)` handles this for structured logs. The raw `_log.info` calls are safe. But: any `print()` in the heartbeat runner would break. Don't use `print()`. Use `_log.info` exclusively.

### G10. No second dedup path

Plan must NOT add a second dedup at the heartbeat-reply path. `MessageDeduplicator` in `routes/whatsapp.py:81` already catches duplicate heartbeat replies (they're just inbound messages with `message_id`). Adding another layer would mask bugs and complicate debugging.

---

## Code Examples

### Verified OpenClaw patterns (ported inline)

**HEARTBEAT_TOKEN semantics** (Source: `D:/Shorty/openclaw/src/auto-reply/heartbeat.ts:117-178`):

```python
# Python port — stripHeartbeatToken
import re

HEARTBEAT_TOKEN = "HEARTBEAT_OK"
DEFAULT_HEARTBEAT_ACK_MAX_CHARS = 300

def strip_heartbeat_token(raw: str, max_ack_chars: int = DEFAULT_HEARTBEAT_ACK_MAX_CHARS) -> tuple[str, bool]:
    """Return (stripped, should_skip).

    should_skip=True iff the text was entirely the token (possibly wrapped
    in whitespace or ≤4 trailing non-word chars).
    """
    if not raw:
        return "", True
    text = raw.strip()
    if not text:
        return "", True
    if HEARTBEAT_TOKEN not in text:
        return text[:max_ack_chars], False

    tail_re = re.compile(re.escape(HEARTBEAT_TOKEN) + r"[^\w]{0,4}$")
    changed = True
    while changed:
        changed = False
        next_text = text.strip()
        if next_text.startswith(HEARTBEAT_TOKEN):
            text = next_text[len(HEARTBEAT_TOKEN):].lstrip()
            changed = True
            continue
        m = tail_re.search(next_text)
        if m:
            text = next_text[:m.start()].rstrip()
            changed = True

    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:max_ack_chars], not collapsed
```

**Visibility resolution** (Source: `D:/Shorty/openclaw/src/infra/heartbeat-visibility.ts`):

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class HeartbeatVisibility:
    show_ok: bool = False
    show_alerts: bool = True
    use_indicator: bool = True

def resolve_heartbeat_visibility(cfg: SynapseConfig) -> HeartbeatVisibility:
    vis = (cfg.heartbeat or {}).get("visibility", {})
    return HeartbeatVisibility(
        show_ok=bool(vis.get("showOk", False)),
        show_alerts=bool(vis.get("showAlerts", True)),
        use_indicator=bool(vis.get("useIndicator", True)),
    )
```

**runWebHeartbeatOnce core** (Source: `D:/Shorty/openclaw/extensions/whatsapp/src/auto-reply/heartbeat-runner.ts:37-322`, simplified for Synapse single-recipient-per-call):

```python
async def run_heartbeat_once(
    to: str,
    channel,                 # WhatsAppChannel
    cfg: SynapseConfig,
    emitter: PipelineEventEmitter,
    get_reply_fn,            # callable(prompt) -> str (async)  — wraps persona_chat
    dry_run: bool = False,
) -> None:
    mint_run_id()
    visibility = resolve_heartbeat_visibility(cfg)
    to_redacted = redact_identifier(to)
    prompt = (cfg.heartbeat or {}).get("prompt") or "Health check — any updates?"
    ack_max = int((cfg.heartbeat or {}).get("ack_max_chars", DEFAULT_HEARTBEAT_ACK_MAX_CHARS))

    emitter.emit("heartbeat.send_start", {
        "to_redacted": to_redacted,
        "prompt_preview": prompt[:60],
        **({"indicator_type": "sending"} if visibility.use_indicator else {}),
    })

    # Guard: all-silent visibility is a no-op
    if not (visibility.show_alerts or visibility.show_ok or visibility.use_indicator):
        emitter.emit("heartbeat.skipped", {"to_redacted": to_redacted, "reason": "alerts-disabled"})
        return

    try:
        reply = await get_reply_fn(prompt)
        stripped, should_skip = strip_heartbeat_token(reply, max_ack_chars=ack_max)

        if should_skip:
            # HEARTBEAT_OK case — either stay silent or send the literal token
            if visibility.show_ok and not dry_run:
                await channel.send(to, HEARTBEAT_TOKEN)
                emitter.emit("heartbeat.ok_token", {
                    "to_redacted": to_redacted, "silent": False,
                    **({"indicator_type": "ok-token"} if visibility.use_indicator else {}),
                })
            else:
                emitter.emit("heartbeat.ok_token", {
                    "to_redacted": to_redacted, "silent": True,
                })
            return

        if not visibility.show_alerts or dry_run:
            emitter.emit("heartbeat.skipped", {
                "to_redacted": to_redacted, "reason": "alerts-disabled" if not visibility.show_alerts else "dry-run",
            })
            return

        await channel.send(to, stripped)
        emitter.emit("heartbeat.sent", {
            "to_redacted": to_redacted, "chars": len(stripped),
            **({"indicator_type": "sent"} if visibility.use_indicator else {}),
        })

    except Exception as exc:
        # HEART-05: never crash
        _log.warning("heartbeat_failed", extra={"to": to, "error": str(exc)})
        emitter.emit("heartbeat.failed", {
            "to_redacted": to_redacted, "error": str(exc),
            **({"indicator_type": "failed"} if visibility.use_indicator else {}),
        })
        # Intentionally NO re-raise — loop must continue
```

### Bridge-side /health augmentation (JavaScript)

```javascript
// baileys-bridge/index.js — top of file
const BRIDGE_VERSION = require('./package.json').version;
const processStartMs = Date.now();
let lastInboundAtMs = null;
let lastOutboundAtMs = null;

// In messages.upsert handler (line 390), after fromMe filter:
lastInboundAtMs = Date.now();

// In /send handler, after sock.sendMessage succeeds:
lastOutboundAtMs = Date.now();

// In /send-voice handler, after sock.sendMessage succeeds:
lastOutboundAtMs = Date.now();

// Updated /health endpoint:
app.get('/health', (req, res) => {
  const now = Date.now();
  const uptimeSeconds = connectedSince
    ? (now - new Date(connectedSince).getTime()) / 1000
    : 0;
  res.json({
    // Existing fields (keep):
    status: connectionState === 'connected' ? 'ok' : 'degraded',
    connectionState,
    pid: process.pid,
    connectedSince,
    authTimestamp,
    uptimeSeconds: Math.floor(uptimeSeconds),
    restartCount,
    lastDisconnectReason,
    // NEW Phase 16 fields:
    last_inbound_at: lastInboundAtMs ? new Date(lastInboundAtMs).toISOString() : null,
    last_outbound_at: lastOutboundAtMs ? new Date(lastOutboundAtMs).toISOString() : null,
    uptime_ms: now - processStartMs,
    bridge_version: BRIDGE_VERSION,
  });
});
```

### Test example — heartbeat never-crashes

```python
# workspace/tests/test_heartbeat_runner.py
@pytest.mark.asyncio
async def test_heartbeat_never_crashes_after_failures(monkeypatch):
    """HEART-05: 10 consecutive heartbeat failures do not kill the loop."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    failure_count = 0

    async def fake_send_always_fails(chat_id, text):
        nonlocal failure_count
        failure_count += 1
        raise RuntimeError("simulated network failure")

    fake_channel = types.SimpleNamespace(send=fake_send_always_fails)
    fake_registry = types.SimpleNamespace(get=lambda cid: fake_channel)

    cfg = types.SimpleNamespace(heartbeat={
        "enabled": True, "interval_s": 0.05,  # very short for test
        "recipients": ["1234567890@s.whatsapp.net"],
        "prompt": "ping",
    })
    runner = HeartbeatRunner(channel_registry=fake_registry, cfg=cfg, interval_s=0.05)
    await runner.start()
    await asyncio.sleep(0.6)  # allow ~10 cycles
    await runner.stop()

    assert failure_count >= 5  # proves it kept running
    assert not runner._task  # proves clean stop
```

---

## State of the Art

| Domain | Old approach | Current approach | Impact |
|--------|--------------|------------------|--------|
| Heartbeat scheduling | cron + external `curl` scripts | In-process asyncio with `asyncio.create_task(loop())` | Zero-dep, co-located with the channel, correlation-ID-aware via ContextVar |
| Duplicate webhook handling | No guard | TTLCache (`MessageDeduplicator`, 300 s) | Already standard for webhook-driven systems; tested pattern |
| Bridge health contract | Single boolean (`is_running`) | Multi-field `/health` with inbound/outbound activity timestamps | Operators can diagnose "bridge running but stuck" via `last_inbound_at` age |
| Subprocess health via polling | Process signal (SIGCHLD) | Periodic HTTP poll + N-strike threshold | HTTP poll catches application-level stalls (socket alive but Baileys event-loop stuck); SIGCHLD only catches crashes |

**Deprecated/outdated:** `markOnlineOnConnect: true` — known to break push notifications. `baileys@6.x` — explicitly end-of-lifed by maintainer.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The existing `MessageDeduplicator` response shape `{status: "skipped", reason: "duplicate", accepted: True}` satisfies BRIDGE-04 | Webhook Idempotency Design | LOW — REQ only requires `accepted: true, reason: "duplicate"`; additional `status` key is backward-compatible. Tests MUST assert on the REQ subset only. |
| A2 | `bridge_version` reading from `require('./package.json').version` is stable inside the bridge subprocess | Bridge /health Contract | LOW — Node `require` cache is process-local; subprocess is restarted for any code change. |
| A3 | Heartbeat failures will never affect webhook ingestion | Risks — G2 | LOW — heartbeat runner is a separate task; exceptions are caught and swallowed. Worst case is the heartbeat loop exits (then user sees no pings, gateway still works). |
| A4 | `asyncio.create_task` is the right primitive over APScheduler | Scheduler Pattern | LOW — entire Synapse codebase uses this pattern; no APScheduler in dependency tree. |
| A5 | The `OutboundTracker` extension for reply-received correlation is a minimal 20-LOC change | Risks — G1 | MEDIUM — implementation may require adding `message_id` to `OutboundEntry` and a `find_by_message_id(in_reply_to_id)` lookup; still modest. |
| A6 | OpenClaw's `showOk=false, showAlerts=true, useIndicator=true` defaults are the right Synapse defaults | OpenClaw Port Map | MEDIUM — user may want different defaults for a self-hosted bot. Discuss-phase should confirm. |
| A7 | Heartbeat replies flow through the normal `FloodGate → Dedup → Queue → Worker` pipeline without special-casing | Risks — G1 | MEDIUM — may require the bridge to distinguish "user reply" vs "user-initiated conversation" to emit the right inbound event. Reading G1 closely, option 1 (OutboundTracker extension) appears clean. |
| A8 | `bridge.healthPollTimeoutSeconds` (default 5 s) << `bridge.healthPollIntervalSeconds` (default 30 s) so polls don't overlap | Config Shape | LOW — config validation catches timeout >= interval. |
| A9 | 401 responses from bridge `/health` should NOT count as a consecutive-failure hit (treat as "degraded, auth stale") | Risks — G6 | MEDIUM — operator could disagree. Current behavior in `health_check()` already clears auth cache on 401; preserving it for the poller matches existing semantics. |
| A10 | Running the heartbeat in production consumes ≤ 1 LLM call per `interval_s` per recipient | — | LOW — at default 30 min interval with 1 recipient: 48 calls/day. Well within any provider rate limit. |

**All claims in `OpenClaw Port Map` are VERIFIED via direct file read, not assumed.** The constant `HEARTBEAT_TOKEN = "HEARTBEAT_OK"`, visibility defaults `{showOk: false, showAlerts: true, useIndicator: true}`, and strip-token semantics are confirmed from OpenClaw source. Only the precise integration approach for Synapse (which modules host the scheduler, where recipients come from) reflects design decisions.

---

## Open Questions

1. **Heartbeat reply tracking — OutboundTracker extension vs separate tracker?**
   - What we know: OutboundTracker exists and is already called from `channels/whatsapp.py::send()` on 200 OK, and `routes/whatsapp.py:69` already calls `is_echo()` before dedup.
   - What's unclear: Extending OutboundTracker with `message_id` + `source` adds 2 fields to OutboundEntry and a new lookup method. Clean but mixes concerns (echo vs heartbeat-reply). Alternative: separate `HeartbeatMessageTracker` — cleaner separation, ~80 LOC.
   - Recommendation: Plan should pick during Wave 1 design. The test for "N send-events + N response-events" (ROADMAP criterion 1) CAN be implemented either way.

2. **HEARTBEAT.md file — in scope or out?**
   - What we know: `workspace/cli/templates/HEARTBEAT.md` already exists in the repo. It's an OpenClaw-compatible file with tasks/directives for the LLM to process during heartbeats.
   - What's unclear: Is Phase 16 supposed to read + respect HEARTBEAT.md content, or is the heartbeat prompt purely config-driven?
   - Recommendation: Config-only for Phase 16 MVP. HEARTBEAT.md integration (reading tasks, gating on file content) can be a follow-up feature once the infrastructure lands. ROADMAP does not require it.

3. **Per-recipient visibility vs global?**
   - What we know: OpenClaw supports per-account AND per-channel visibility. Synapse Phase 16 is single-account, single-channel (WhatsApp).
   - What's unclear: Should `heartbeat.visibility` be per-recipient (`{"919…": {showOk: true}}`) or global (`{showOk: true}`)?
   - Recommendation: Global for MVP. Multi-account Phase 18 can add per-account scope later.

4. **Dry-run mode exposure?**
   - What we know: OpenClaw's `runWebHeartbeatOnce` has `dryRun` option.
   - What's unclear: Does Synapse need a CLI / HTTP endpoint to manually trigger a dry-run heartbeat?
   - Recommendation: Add a `POST /channels/whatsapp/heartbeat/test` admin endpoint — fires one cycle with `dry_run=true`, returns the events that *would* have fired. Developer-friendly. Optional.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All gateway code | YES | 3.13.6 (per 13-RESEARCH.md) | — |
| asyncio (stdlib) | HeartbeatRunner, BridgeHealthPoller | YES | stdlib | — |
| httpx | Bridge health poll HTTP client | YES (used by WhatsAppChannel already) | ≥0.25 | — |
| Node.js 20+ | Bridge `/health` endpoint extension | YES | v22.18.0 per Phase 15 research | — |
| Express | Bridge HTTP server | YES (already serving `/health`) | ^4.18.3 | — |
| `@whiskeysockets/baileys@7.0.0-rc.9` | Inbound/outbound event hooks for timestamp tracking | YES | 7.0.0-rc.9 pinned by Phase 15 | — |
| pytest + pytest-asyncio | Test framework | YES | present per 13-RESEARCH.md | — |
| Phase 13 observability package | PII redaction + child logger + emit | YES | merged | — |
| Phase 14 supervisor + echo tracker | Restart path + OutboundTracker extension | YES | merged | — |
| Phase 15 atomic creds queue | Safe subprocess restart | YES | merged | — |

**Missing dependencies:** none.
**Missing dependencies with fallback:** none.

---

## Project Constraints (from CLAUDE.md)

Direct directives that constrain Phase 16:

1. **OSS dev hygiene (pre-push)**: No personal data in commits. Heartbeat recipient JIDs in `synapse.json.example` must be placeholder (e.g., `"919000000000@s.whatsapp.net"` — 12 zero-digits, clearly fake). Do NOT commit real numbers.

2. **Code graph first**: Planners MUST query `semantic_search_nodes` / `query_graph` for each file they touch before editing. This applies to `channels/whatsapp.py`, `routes/whatsapp.py`, `api_gateway.py` because they're large files.

3. **Python 3.11 / line-length 100 / ruff + black**: All new Python under `workspace/sci_fi_dashboard/gateway/heartbeat_runner.py` + `channels/bridge_health_poller.py` must pass `ruff check workspace/ && black workspace/`.

4. **asyncio throughout**: CONFIRMED — both new modules use asyncio exclusively.

5. **Windows cp1252 gotcha (gotcha #5)**: Use `_log.info(...)` NOT `print(...)` in Python code. Phase 13's `JsonFormatter(ensure_ascii=True)` handles this automatically.

6. **synapse_config.py has wide blast radius (gotcha #7)**: Adding `heartbeat` and `bridge` fields to `SynapseConfig` must be defensively defaulted (`field(default_factory=dict)`). No existing call site should break.

7. **litellm Router does NOT apply Copilot auth (gotcha #1)**: Heartbeat uses `channel.send()` NOT `llm_router.call()` directly, so this is irrelevant for Phase 16. The `get_reply_fn` passed to `run_heartbeat_once` wraps `persona_chat()` which already routes correctly.

8. **Memory query is shared (gotcha #10)**: Heartbeat cycle calls `persona_chat()` which runs its own MemoryEngine.query. This is fine — one query per heartbeat cycle, no double-query.

9. **BackgroundTask for media (project-wide convention)**: Heartbeat does not send media in Phase 16 scope. Text-only send.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.x + pytest-asyncio 0.23+ (`asyncio_mode = auto` in `workspace/tests/pytest.ini`) |
| Config file | `workspace/tests/pytest.ini` |
| Quick run command | `cd workspace && pytest tests/test_heartbeat_runner.py tests/test_bridge_health_poller.py tests/test_webhook_dedup.py -v` |
| Full suite command | `cd workspace && pytest tests/ -v` |
| Estimated runtime | ~10 seconds (no real network I/O; everything mocked via `httpx.MockTransport` + fake channel) |
| Node-side tests | `cd baileys-bridge && npm test` — add `test/health_endpoint.test.js` for the new `/health` fields |

### Per-Requirement Validation Map

| Req ID | Behavior | Test Type | Test Location | Automated Command |
|--------|----------|-----------|---------------|-------------------|
| HEART-01 | `synapse.json → heartbeat.recipients: ["91…"]` produces a send to that JID | unit (fake send) | `workspace/tests/test_heartbeat_runner.py::test_config_recipient_is_sent` | `cd workspace && pytest tests/test_heartbeat_runner.py::test_config_recipient_is_sent -v` |
| HEART-01 | `resolve_recipients` returns `[]` when `heartbeat.recipients` is absent/empty | unit | `workspace/tests/test_heartbeat_runner.py::test_no_recipients_is_noop` | same |
| HEART-02 | `heartbeat.prompt` from synapse.json overrides default | unit | `workspace/tests/test_heartbeat_runner.py::test_prompt_override` | same |
| HEART-02 | Absent `heartbeat.prompt` falls back to default constant | unit | `workspace/tests/test_heartbeat_runner.py::test_prompt_default` | same |
| HEART-03 | LLM reply == "HEARTBEAT_OK" → `should_skip=True`, outbound suppressed when `showOk=false` | unit | `workspace/tests/test_heartbeat_runner.py::test_token_stripped_silent` | same |
| HEART-03 | LLM reply contains "HEARTBEAT_OK!" (token + trailing punct) → stripped | unit | `workspace/tests/test_heartbeat_runner.py::test_token_with_trailing_punct_stripped` | same |
| HEART-03 | LLM reply == "ping HEARTBEAT_OK" → stripped to "ping" | unit | `workspace/tests/test_heartbeat_runner.py::test_token_prefix_stripped` | same |
| HEART-04 | `showOk=true` + empty reply → sends literal HEARTBEAT_OK | unit | `workspace/tests/test_heartbeat_runner.py::test_show_ok_sends_ok_ping` | same |
| HEART-04 | `showAlerts=false` → content reply is dropped, event emitted | unit | `workspace/tests/test_heartbeat_runner.py::test_show_alerts_false_drops_content` | same |
| HEART-04 | `useIndicator=false` → event omits `indicator_type` field | unit | `workspace/tests/test_heartbeat_runner.py::test_use_indicator_false_omits_field` | same |
| HEART-04 | All three flags independent — 8 combinations valid | unit (table-driven) | `workspace/tests/test_heartbeat_runner.py::test_visibility_flag_matrix` | same |
| HEART-05 | 10 consecutive `channel.send` exceptions — runner loop continues | unit (fault-injection) | `workspace/tests/test_heartbeat_runner.py::test_never_crashes_after_failures` | same |
| HEART-05 | Exception from `get_reply_fn` is caught, next cycle fires on schedule | unit | `workspace/tests/test_heartbeat_runner.py::test_llm_exception_does_not_stop_loop` | same |
| BRIDGE-01 | Node bridge `/health` returns all 4 new fields | Node unit | `baileys-bridge/test/health_endpoint.test.js::test_health_returns_new_fields` | `cd baileys-bridge && node --test test/health_endpoint.test.js` |
| BRIDGE-01 | `last_inbound_at` updates when messages.upsert fires | Node unit | `baileys-bridge/test/health_endpoint.test.js::test_last_inbound_updates` | same |
| BRIDGE-01 | `last_outbound_at` updates when /send succeeds | Node unit | `baileys-bridge/test/health_endpoint.test.js::test_last_outbound_updates` | same |
| BRIDGE-01 | `bridge_version` matches package.json | Node unit | `baileys-bridge/test/health_endpoint.test.js::test_bridge_version_from_pkgjson` | same |
| BRIDGE-02 | Gateway poller fetches /health every 30s (configurable) | unit (fake httpx) | `workspace/tests/test_bridge_health_poller.py::test_poll_cadence` | `cd workspace && pytest tests/test_bridge_health_poller.py::test_poll_cadence -v` |
| BRIDGE-02 | Poll result surfaces at `GET /channels/whatsapp/status.bridge_health` | integration | `workspace/tests/test_bridge_health_poller.py::test_status_surfaces_health` | same |
| BRIDGE-03 | 3 consecutive poll failures → `_restart_bridge()` called | unit (fault-injection) | `workspace/tests/test_bridge_health_poller.py::test_three_failures_trigger_restart` | same |
| BRIDGE-03 | `bridge.healthFailuresBeforeRestart=5` changes threshold | unit | `workspace/tests/test_bridge_health_poller.py::test_threshold_configurable` | same |
| BRIDGE-03 | `supervisor.stop_reconnect=True` blocks restart even after N failures | unit | `workspace/tests/test_bridge_health_poller.py::test_stop_reconnect_blocks_restart` | same |
| BRIDGE-03 | 401 from /health does NOT count as failure | unit | `workspace/tests/test_bridge_health_poller.py::test_401_not_counted_as_failure` | same |
| BRIDGE-03 | After restart, poller enters 60s grace window | unit | `workspace/tests/test_bridge_health_poller.py::test_grace_window_after_restart` | same |
| BRIDGE-04 | Duplicate `message_id` within 300 s → `{accepted: true, reason: "duplicate"}` | integration | `workspace/tests/test_webhook_dedup.py::test_duplicate_returns_accepted_true` | `cd workspace && pytest tests/test_webhook_dedup.py -v` |
| BRIDGE-04 | First-seen `message_id` passes through; second identical is dropped | integration | `workspace/tests/test_webhook_dedup.py::test_first_passes_second_dropped` | same |
| BRIDGE-04 | After 300 s TTL, same `message_id` is accepted again | integration | `workspace/tests/test_webhook_dedup.py::test_ttl_expiry_allows_retransmit` | same |

### Sampling Rate

- **Per task commit:** `cd workspace && pytest tests/test_heartbeat_runner.py tests/test_bridge_health_poller.py tests/test_webhook_dedup.py -v` (<10 s)
- **Per wave merge:** `cd workspace && pytest tests/ -v` + `cd baileys-bridge && npm test`
- **Phase gate:** Full Python suite + Node bridge suite BOTH green + manual checks from `16-MANUAL-VALIDATION.md`.

### Wave 0 Gaps

- [ ] `workspace/tests/test_heartbeat_runner.py` — covers HEART-01..05 (all cases above)
- [ ] `workspace/tests/test_bridge_health_poller.py` — covers BRIDGE-02, BRIDGE-03 (+ 401 handling + grace window)
- [ ] `workspace/tests/test_webhook_dedup.py` — covers BRIDGE-04 (lock the response contract + TTL behavior)
- [ ] `baileys-bridge/test/health_endpoint.test.js` — covers BRIDGE-01 (Node-side)
- [ ] `workspace/tests/conftest.py` — new fixture `fake_channel_with_recorded_sends` returning a `types.SimpleNamespace(send=...)` that records calls (reusable across heartbeat tests)
- [ ] `workspace/tests/fixtures/bridge_health_transport.py` — `httpx.MockTransport` factory returning configurable `/health` responses (success, 401, 500, timeout)

### Manual-only verifications

Some scenarios cannot be fully reproduced in pytest — defer to `16-MANUAL-VALIDATION.md`:

| Behavior | REQ | Why Manual |
|----------|-----|------------|
| Real recipient on real WhatsApp receives scheduled heartbeat | HEART-01 | Requires live Baileys pairing |
| Bridge subprocess is killed mid-run, poller restarts it after 3 failed polls | BRIDGE-03 | Subprocess I/O makes this fragile in pytest; manual "kill -9 pid of node" and observe |
| 440 conflict mid-bridge-poll — stop_reconnect gate prevents restart | BRIDGE-03 | Requires simulated 440 from live WhatsApp |
| Dashboard SSE stream shows heartbeat events live | HEART-04 (useIndicator) | Browser-side rendering — not testable in pytest |

---

## Dimensional Validation Gaps

> Per Dimension 8 (Nyquist/oversampling) — identify what cannot be fully tested WITHOUT real WhatsApp infrastructure, so the validation plan flags them correctly for manual acceptance.

### Gaps requiring real WhatsApp:
1. **End-to-end heartbeat cycle with real recipient reply**: pytest can assert `channel.send` was called; it cannot assert the recipient's phone actually rings and a human types a reply that flows back through the webhook. Manual smoke test required.
2. **HEARTBEAT_TOKEN in recipient reply strips correctly**: pytest can test the `strip_heartbeat_token()` function directly; a real recipient sending `"HEARTBEAT_OK"` as a message and verifying the runner handles it must be done manually (because it exercises the full receive → strip → event path).
3. **Bridge `/health` responds to polling during a live inbound-message flood**: pytest can mock transport; real-world concurrency between Express `/health` and Baileys event-loop saturation is manual.
4. **Subprocess restart does not lose queued outbound sends**: Phase 15's retry queue handles this, but a live verification (send message, kill bridge, confirm message retried after restart) is manual.
5. **Dashboard SSE subscribers see correctly-ordered heartbeat events**: browser-level verification; pytest can assert the emit sequence but not rendering.
6. **Bridge version detected after an in-place `npm install --save baileys@7.0.0-rc.10`**: requires upgrading and restarting — out of scope for pytest.

### Gaps requiring long duration:
1. **300 s webhook-dedup TTL actually expires**: pytest can monkey-patch `time.time()`. Real-clock verification requires 5 minutes of wall time — manual only.
2. **Heartbeat fires hourly for 24 h without crash**: pytest asserts the loop survives N failures; the "does it actually survive for 86400 s?" longevity test is manual (canary deploy).

### Gaps requiring external system cooperation:
1. **WhatsApp group heartbeats**: Phase 16 is scoped to DM recipients per ROADMAP. A `@g.us` JID would technically work but is untested. If the test recipient is a group, WhatsApp's group anti-spam could silently drop messages — not detectable by the bridge alone.

**Each gap above is individually documented in `16-MANUAL-VALIDATION.md` (to be created by the planner's Wave 0 step) with reproduction steps.**

---

## Sources

### Primary (HIGH confidence — directly read during research)

- `D:/Shorty/Synapse-OSS/.planning/ROADMAP.md` Phase 16 block (lines 176-187) — roadmap scope + success criteria
- `D:/Shorty/Synapse-OSS/.planning/REQUIREMENTS.md` lines 52-85 — HEART-01..05 + BRIDGE-01..04 definitions
- `D:/Shorty/Synapse-OSS/.planning/phases/13-structured-observability/13-RESEARCH.md` — full Phase 13 context (runId + emitter + redaction primitives)
- `D:/Shorty/Synapse-OSS/.planning/phases/13-structured-observability/13-00-PLAN.md` through `13-06-PLAN.md` — Phase 13 implementation details (observability surface, emit events)
- `D:/Shorty/Synapse-OSS/.planning/phases/14-supervisor-watchdog-echo-tracker/14-VALIDATION.md` — Phase 14 supervisor contract + validation map
- `D:/Shorty/Synapse-OSS/.planning/phases/15-auth-persistence-baileys-7x/15-RESEARCH.md` lines 1-300 — Baileys 7.x atomic queue + restart behavior
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/channels/whatsapp.py` — `WhatsAppChannel._restart_bridge`, `get_status`, `health_check`
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/channels/supervisor.py` — `WhatsAppSupervisor`, `ReconnectPolicy`, `note_connected/disconnect`, `stop_reconnect`
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/channels/polling_watchdog.py` — asyncio loop reference pattern
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/gateway/dedup.py` — `MessageDeduplicator` (already satisfies BRIDGE-04)
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/gateway/echo_tracker.py` — `OutboundTracker` pattern reference (for heartbeat-reply tracking extension)
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/routes/whatsapp.py` — webhook handler and `/channels/whatsapp/status` surface
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/pipeline_emitter.py` — `PipelineEventEmitter` public API for heartbeat events
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/api_gateway.py` — `lifespan()` — heartbeat runner + poller wire-in point
- `D:/Shorty/Synapse-OSS/workspace/synapse_config.py` — `SynapseConfig` dataclass (adding `heartbeat` + `bridge` fields)
- `D:/Shorty/Synapse-OSS/synapse.json.example` — reference for section placement
- `D:/Shorty/Synapse-OSS/baileys-bridge/index.js` — current `/health` endpoint + Express setup
- `D:/Shorty/Synapse-OSS/baileys-bridge/package.json` — Baileys 7.x pinned version + Node 20 engines
- `D:/Shorty/Synapse-OSS/baileys-bridge/lib/creds_queue.js` — Phase 15's atomic queue (restart-safety context)
- `D:/Shorty/openclaw/extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` — primary port source (`runWebHeartbeatOnce`)
- `D:/Shorty/openclaw/extensions/whatsapp/src/auto-reply/heartbeat-runner.runtime.ts` — dependency surface
- `D:/Shorty/openclaw/extensions/whatsapp/src/heartbeat-recipients.ts` — recipient resolution algorithm
- `D:/Shorty/openclaw/src/auto-reply/heartbeat.ts` — `stripHeartbeatToken`, `HEARTBEAT_PROMPT`, `DEFAULT_HEARTBEAT_ACK_MAX_CHARS`
- `D:/Shorty/openclaw/src/auto-reply/tokens.ts` — `HEARTBEAT_TOKEN = "HEARTBEAT_OK"`
- `D:/Shorty/openclaw/src/infra/heartbeat-runner.ts` — scheduling loop reference (`startHeartbeatRunner`)
- `D:/Shorty/openclaw/src/infra/heartbeat-visibility.ts` — visibility flag resolution with defaults

### Secondary (MEDIUM confidence)

- Phase 13 PII redaction behavior — derived from plan-level reads; the formatter auto-redacts fields named `chat_id`, `user_id`, `jid`, `phone`, `sender_id`. Not directly verified by re-reading `formatter.py`, but the pattern is documented in 13-RESEARCH.md Code Examples.

### Tertiary (LOW confidence) — flagged for validation

- **WhatsApp `quoted_message_id` shape in inbound payload**: Risk G1's option 3 relies on Baileys exposing `msg.key.quotedMessage.id`. Not verified against Baileys 7.x docs this session. The planner SHOULD verify before committing to that option.
- **OpenClaw's `HEARTBEAT_PROMPT` default** (`"Read HEARTBEAT.md if it exists..."`) is specific to OpenClaw's workspace-file pattern. Synapse should adopt a simpler default — `"Health check — any updates?"`. This is a design call, not a port.

### Environment constraint this session

Context7 / Exa / Firecrawl all `false` per `.planning/config.json`. WebSearch not used — not needed, all reference sources are in the local repo. Brave Search `false`.

---

## Metadata

**Confidence breakdown:**
- Dependencies (Phase 13/14/15 reuse surface): HIGH — every primitive was read directly or confirmed via research docs.
- OpenClaw port map: HIGH — source read directly, not inferred from spec.
- Bridge /health contract: HIGH — current shape + target shape both grounded in direct file reads.
- Webhook idempotency: HIGH — `MessageDeduplicator` directly read, existing behavior matches REQ.
- Heartbeat scheduler pattern: HIGH — matches existing Synapse idiom (`PollingWatchdog`).
- Visibility flag semantics: HIGH — OpenClaw source read.
- Risks/gotchas: HIGH — each grounded in read source files.
- Heartbeat-reply correlation mechanism (G1): MEDIUM — three implementation options, planner picks during Wave 1.
- `bridge_version` package.json caching: LOW — non-material given subprocess restart model.

**Research date:** 2026-04-23
**Valid until:** 2026-05-23 (30 days — stable upstream phases; Baileys 7.x may advance but current pin `7.0.0-rc.9` is documented Phase 15 decision).
