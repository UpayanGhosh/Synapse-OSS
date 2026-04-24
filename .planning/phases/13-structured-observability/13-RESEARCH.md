# Phase 13: Structured Observability — Research

**Researched:** 2026-04-21
**Domain:** Python structured logging + async correlation-ID propagation
**Confidence:** HIGH (stdlib patterns), MEDIUM (third-party version pins)

## Summary

Phase 13 ports OpenClaw's `getChildLogger({module, runId})` + `redactIdentifier()` pattern into Synapse so every log line for a given inbound message shares a stable `runId` from webhook receipt through outbound `channel.send()`, and no raw phone number or WhatsApp JID ever lands on disk.

Synapse already has two pieces of half-built infrastructure that make this tractable:

1. **`pipeline_emitter.start_run()`** already mints a 12-hex-char `run_id` for the dashboard SSE stream (`workspace/sci_fi_dashboard/pipeline_emitter.py:78`). It is called once in `chat_pipeline.persona_chat()` but stored on a singleton (`self._current_run_id`) — a race condition under concurrent requests that Phase 13 must fix while reusing the ID convention.
2. **`workspace/config/redaction.py`** exists but only redacts config snapshots (`api_key`, `token`, `secret`). It is **not** suitable for JID/phone redaction in logs — a new helper is needed.

The full pipeline is 7 hops: `route → FloodGate → Dedup → TaskQueue → MessageWorker → persona_chat → llm_router → channel.send`. Two of those hops cross `asyncio.create_task` boundaries (FloodGate flush-callback + TaskQueue worker). Correlation across task boundaries is solved by Python's stdlib `contextvars.ContextVar`, which `asyncio` propagates automatically across `create_task()` and `asyncio.run()` — but **not** across `loop.run_in_executor()` without manual `contextvars.copy_context()`.

**Primary recommendation:** Add `workspace/sci_fi_dashboard/observability/` package with four modules — `context.py` (ContextVar + `get_run_id()`/`set_run_id()`), `redact.py` (HMAC-SHA256 salted identifier redaction), `logger_factory.py` (`get_child_logger(module, **extra)` wrapping `logging.LoggerAdapter`), `config.py` (reads `logging.modules.<name>: LEVEL` from `synapse.json` and applies post-`SynapseConfig.load()`). Emit structured JSON via a custom `logging.Formatter` subclass — no third-party dependency required, though `python-json-logger>=2.0.7` is a drop-in upgrade if desired later. Wire ContextVar at the two async-boundary handoffs (`routes/whatsapp.py::unified_webhook` + `gateway/worker.py::MessageWorker._run`). Leave all 493 existing `logger.info()` calls unchanged — `get_child_logger()` is additive; the stdlib logger continues to work.

## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for Phase 13 (standalone research run, discuss-phase was not executed). The roadmap entry (`.planning/ROADMAP.md:121-130`) and four requirement IDs (OBS-01..04 from `.planning/REQUIREMENTS.md`) are the sole input constraints.

### Locked Decisions
- **OpenClaw pattern**: `getChildLogger({module, runId})` behavior + `redactIdentifier()` helper — ported from openclaw to synapse (roadmap line 123).
- **runId stability**: same `runId` on every log line for one inbound message, receipt → outbound send (OBS-01).
- **Structured format**: JSON or key=value with `module / runId / level / chat_id_redacted` fields (OBS-03).
- **Per-module log levels**: configurable via `synapse.json` (OBS-04).

### Claude's Discretion
- JSON vs key=value structure choice.
- HMAC-SHA256 vs simple truncation for `redact_identifier()`.
- Whether to adopt `python-json-logger` or write a stdlib `Formatter` subclass.
- How to handle pre-`SynapseConfig.load()` logger calls (startup window).
- Integration approach with existing `pipeline_emitter.start_run()`.

### Deferred Ideas (OUT OF SCOPE)
- OpenTelemetry / distributed tracing.
- Log shipping to external sinks (Datadog / Loki / ELK).
- PII redaction for message *content* (only identifiers are in scope — OBS-02 says "phone numbers / JIDs").
- Migrating the 493 existing `logger.info()` calls to `get_child_logger` (backward-compat — additive only).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-01 | Every log line for a given inbound message carries the same `runId` from receipt through outbound `channel.send()` | ContextVar propagation across asyncio hops; wiring points at `routes/whatsapp.py:unified_webhook` (mint) + `gateway/worker.py:MessageWorker._run` (restore after queue handoff); reuse `pipeline_emitter.start_run()` 12-hex convention |
| OBS-02 | Phone numbers and JIDs in logs are redacted via a single `redact_identifier()` helper | HMAC-SHA256 with salt stored at `~/.synapse/state/logging_salt` (auto-generated on first boot); output format `chat_***a7f3`; applied at formatter boundary so existing `logger.info("[WA] DM from %s", cm.user_id)` call sites don't need editing |
| OBS-03 | Structured format with `module / runId / level / chat_id_redacted` fields | Custom `logging.Formatter` subclass emitting JSON; stdlib-only path — no new dep; fields auto-populated from ContextVar + LoggerAdapter `extra` dict |
| OBS-04 | Per-module levels configurable via `synapse.json` | New `logging` section in `SynapseConfigSchema`; apply levels at FastAPI `lifespan()` after `SynapseConfig.load()`; note `dual_cognition.py` anomaly — uses `logging.getLogger("dual_cognition")` not `logging.getLogger(__name__)` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `logging` | stdlib 3.11 | Logger hierarchy, handlers, formatters, adapters | [VERIFIED: Python 3.13.6 installed on dev host]. Universal Python logging primitive. Every existing logger call already uses it. |
| `contextvars` | stdlib 3.11 | Async-safe per-task correlation storage | [VERIFIED: stdlib since 3.7]. Asyncio-native; propagates across `create_task()` automatically. Zero-dep correlation. |
| `hmac` + `hashlib` | stdlib 3.11 | Stable PII hashing for redaction helper | [VERIFIED: stdlib]. SHA-256 is cryptographically stable for look-alike correlation without reversibility. |
| `secrets` | stdlib 3.11 | Generate per-install `logging_salt` on first boot | [VERIFIED: stdlib since 3.6]. CSPRNG source for salt generation. |

### Supporting (optional — not required for MVP)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-json-logger` | `>=2.0.7` [ASSUMED — could not verify via registry this session] | Drop-in JSON formatter | If team later wants to swap custom formatter for a maintained one. Current version 2.0.7 as of mid-2024 per training knowledge. Verify via `pip index versions python-json-logger` before adopting. |
| `structlog` | `>=24.1.0` [ASSUMED — could not verify] | Full structured-logging replacement | Defer — would require migrating all 493 call sites. Not justified for Phase 13 scope. Phase 14+ option. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom JSON `Formatter` | `python-json-logger` | Adds dep, saves ~40 lines. No functional gain for Phase 13. Skip. |
| `contextvars.ContextVar` | Pass `run_id` explicitly through every function | Explicit is nice but would touch 100+ function signatures. ContextVar gives zero-edit correlation. |
| HMAC-SHA256 redaction | Truncation (`+91****5678`) | Truncation is simpler but leaks country/area code. HMAC gives stable correlation without any structural info leak. HMAC wins. |
| Singleton `pipeline_emitter._current_run_id` (status quo) | ContextVar-backed runId | Singleton is racey across concurrent requests (WA + WebSocket + cron overlap). ContextVar fixes this AND keeps pipeline_emitter compatible by backfeeding from ContextVar at `start_run()`. |

**Installation:**
```bash
# MVP path — zero new deps
# (all imports are Python 3.11 stdlib)

# Optional upgrade path (defer until justified):
# pip install python-json-logger>=2.0.7
```

**Version verification:** Before committing any new dep, confirm current version:
```bash
pip index versions python-json-logger 2>/dev/null | head -3
```
Current `requirements.txt` has no structured-logging library, so MVP introduces zero new pins.

## Architecture Patterns

### Recommended Project Structure
```
workspace/sci_fi_dashboard/observability/
├── __init__.py           # public API: get_child_logger, redact_identifier, run_id_ctx
├── context.py            # ContextVar[str | None] + helpers
├── redact.py             # HMAC-SHA256 identifier redaction + salt bootstrap
├── logger_factory.py     # get_child_logger() factory using LoggerAdapter
├── formatter.py          # JsonFormatter(logging.Formatter) emitting OBS-03 fields
├── config.py             # apply_logging_config(cfg: SynapseConfig) — called from lifespan()
└── filters.py            # RunIdFilter injects ContextVar value into LogRecord
```

### Pattern 1: ContextVar-Backed RunId
**What:** A module-level `ContextVar[str | None]` holds the current runId for the duration of one request. Async tasks spawned from inside the handler inherit the context automatically.

**When to use:** Every inbound webhook handler (`routes/whatsapp.py`, `routes/chat.py`, `routes/pipeline.py`) mints a runId at entry. Every outbound-side module reads via `get_run_id()`.

**Example:**
```python
# observability/context.py
from __future__ import annotations
import contextvars
import uuid

_run_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "synapse_run_id", default=None
)

def mint_run_id() -> str:
    """Mint a new 12-hex runId matching pipeline_emitter convention."""
    rid = uuid.uuid4().hex[:12]  # 12 chars matches pipeline_emitter.start_run()
    _run_id_ctx.set(rid)
    return rid

def set_run_id(run_id: str) -> contextvars.Token:
    """Set runId (returns token for reset in finally blocks)."""
    return _run_id_ctx.set(run_id)

def get_run_id() -> str | None:
    return _run_id_ctx.get()
```

**Wiring point 1 — inbound (route layer):**
```python
# routes/whatsapp.py::unified_webhook — line 22, BEFORE channel.receive()
from sci_fi_dashboard.observability.context import mint_run_id

@router.post("/channels/{channel_id}/webhook")
async def unified_webhook(channel_id: str, request: Request):
    run_id = mint_run_id()  # NEW — mint at the earliest boundary
    # ... existing body unchanged ...
    # When calling deps.flood.incoming(...), pass run_id in metadata:
    await deps.flood.incoming(
        chat_id=msg.chat_id,
        message=msg.text,
        metadata={
            "run_id": run_id,  # NEW — carries across the FloodGate debounce window
            "message_id": msg.message_id,
            "sender_name": msg.sender_name,
            "channel_id": msg.channel_id,
        },
    )
```

**Wiring point 2 — worker boundary (restore context after queue handoff):**
```python
# gateway/worker.py::MessageWorker._run — around line 128
from sci_fi_dashboard.observability.context import set_run_id

async def _run(self, task: MessageTask):
    token = None
    if task.run_id:  # NEW field on MessageTask
        token = set_run_id(task.run_id)
    try:
        # ... existing body unchanged ...
    finally:
        if token:
            _run_id_ctx.reset(token)
```

Source: [Python docs — contextvars in asyncio](https://docs.python.org/3/library/contextvars.html). Confirmed in CPython 3.11+ that `asyncio.Task` snapshots context at creation time — no manual plumbing needed for `asyncio.create_task()` or `background_tasks.add_task()`.

### Pattern 2: Child Logger Factory with Extra Fields
**What:** `get_child_logger(module="llm_router", extra={"provider": "gemini"})` returns a `logging.LoggerAdapter` whose every record has `module` + any caller-supplied extras attached. The formatter reads ContextVar at emit time and stitches `runId` in.

**When to use:** In any new observability-aware site. Backward compat: existing `logger = logging.getLogger(__name__)` keeps working — the filter injects runId into every record regardless of how the logger was created.

**Example:**
```python
# observability/logger_factory.py
import logging

def get_child_logger(module: str, **extra) -> logging.LoggerAdapter:
    """OpenClaw-style child logger with sticky extra fields."""
    base = logging.getLogger(module)
    return logging.LoggerAdapter(base, {"module": module, **extra})

# usage:
log = get_child_logger("channel.whatsapp")
log.info("DM received", extra={"chat_id": chat_id})  # chat_id gets redacted by formatter
```

### Pattern 3: Redaction-at-Formatter Boundary
**What:** Rather than ask every call site to `log.info("from %s", redact_identifier(user_id))`, redact inside the formatter based on field names. Any LogRecord extra field ending in `_id`, or named `chat_id` / `user_id` / `jid` / `phone`, gets replaced with `redact_identifier(value)` before serialization.

**When to use:** Default behavior for every log line. Explicit call sites (`redact_identifier(user_id)` in the format arg) are also supported for positional-arg logs like `logger.info("[WA] DM from %s", cm.user_id)`.

**Example:**
```python
# observability/redact.py
import hmac
import hashlib
import secrets
from pathlib import Path

_SALT_PATH = Path.home() / ".synapse" / "state" / "logging_salt"

def _load_or_mint_salt() -> bytes:
    if _SALT_PATH.exists():
        return _SALT_PATH.read_bytes()
    _SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    _SALT_PATH.write_bytes(salt)
    _SALT_PATH.chmod(0o600)
    return salt

_SALT = _load_or_mint_salt()

def redact_identifier(value: str | None) -> str:
    """HMAC-SHA256 redaction -- stable across a process, opaque between installs."""
    if not value:
        return "<none>"
    digest = hmac.new(_SALT, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"id_{digest[:8]}"  # e.g. "id_a7f3b2c1"
```

### Pattern 4: JSON Formatter Emitting OBS-03 Fields
```python
# observability/formatter.py
import json
import logging
from sci_fi_dashboard.observability.context import get_run_id
from sci_fi_dashboard.observability.redact import redact_identifier

_SENSITIVE_FIELDS = {"chat_id", "user_id", "jid", "phone", "sender_id"}

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": getattr(record, "module_name", record.name),
            "runId": get_run_id(),  # NEW — from ContextVar
            "msg": record.getMessage(),
        }
        # Inject adapter extras, redacting sensitive fields
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("_") or key in logging.LogRecord.__dict__:
                continue
            if key in _SENSITIVE_FIELDS:
                payload[f"{key}_redacted"] = redact_identifier(str(value))
            elif key not in {"args", "msg", "message"}:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)  # ensure_ascii for Windows cp1252
```

### Pattern 5: Per-Module Config Application
```python
# observability/config.py
import logging
from synapse_config import SynapseConfig

DEFAULT_LEVEL = "INFO"

def apply_logging_config(cfg: SynapseConfig) -> None:
    """Apply logging.modules.<name>: LEVEL from synapse.json. Called from lifespan()."""
    log_cfg = (getattr(cfg, "logging", {}) or {})
    modules = log_cfg.get("modules", {})
    root_level = log_cfg.get("level", DEFAULT_LEVEL)
    logging.getLogger().setLevel(root_level)
    for module_name, level in modules.items():
        logging.getLogger(module_name).setLevel(level.upper())
```

**synapse.json schema addition:**
```json
{
  "logging": {
    "level": "INFO",
    "format": "json",
    "modules": {
      "channel.whatsapp": "DEBUG",
      "llm_router": "WARNING",
      "dual_cognition": "INFO"
    }
  }
}
```

**CRITICAL ordering:** `apply_logging_config()` must run inside `lifespan()` AFTER `SynapseConfig.load()`. Any logger call before `lifespan()` (e.g., module-level imports) uses the default INFO level.

### Anti-Patterns to Avoid
- **Explicit `run_id` parameters on every function** — touches 100+ signatures. Use ContextVar.
- **Logging raw JIDs and then filtering at the sink** — filter at formatter boundary, never disk.
- **Replacing `pipeline_emitter.start_run()`** — backfeed it instead (see Pipeline Integration below).
- **`logging.basicConfig()` in `api_gateway.py`** — it silently no-ops if any handler is already attached. Use explicit `logging.getLogger().addHandler(...)`.
- **Wrapping `logger.getLogger(__name__)` with an adapter at import time** — modules load before config is applied; bind adapter at runtime via `get_child_logger()` call, not module-level.
- **Sending JSON-formatted records to stdout AND the dashboard SSE stream through the same handler** — split handlers (one JSON formatter → stdout, one dict emitter → SSE).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Correlation-ID propagation across `asyncio.create_task()` | Thread-local + manual context serialization | `contextvars.ContextVar` | stdlib, zero-dep, handles asyncio correctly since 3.7. Thread-local breaks on asyncio. |
| Salt storage and rotation | Re-seeding salt per process (breaks cross-log correlation) | Persistent salt at `~/.synapse/state/logging_salt`, chmod 600 | Stable correlation across restarts. Delete file to rotate — simple operator story. |
| JSON serialization of LogRecord | `str(record.__dict__)` or manual field extraction | Subclass `logging.Formatter` with `json.dumps()` | Formatter is the right seam — respects levels, filters, and exception info. |
| Masking identifiers in format strings | `logger.info("from %s", user_id[:4] + "****")` at every call site | Redact at formatter, using field-name convention | Additive — existing 493 call sites need no edits. |
| Per-module log level config | Hard-coded `logging.getLogger("llm_router").setLevel(WARNING)` at import time | Driven from `synapse.json → logging.modules` | Operators tune without code changes. Matches OBS-04. |

**Key insight:** Every primitive this phase needs ships in Python 3.11 stdlib. The only reason to reach for `python-json-logger` or `structlog` is maintenance overhead of a custom Formatter class — which is ~40 lines. Stay stdlib, write the 40 lines, revisit dep choice in Phase 14+ if the formatter becomes a burden.

## Runtime State Inventory

Not applicable — this is a greenfield feature phase (no rename / refactor / data migration). One modest state artifact is introduced:

| Artifact | Location | Migration needed |
|----------|----------|------------------|
| Per-install HMAC salt | `~/.synapse/state/logging_salt` | None — auto-generated on first boot by `_load_or_mint_salt()`. Operators may delete to rotate. |

The existing `pipeline_emitter._current_run_id` singleton is in-process only (no disk state), so "migration" is simply: read-once-from-ContextVar at `emit()` time instead of writing to `self._current_run_id`. Covered under Pipeline Integration below.

## Pipeline Integration (runId flow across 7 hops)

| Hop | Module | File | Action |
|-----|--------|------|--------|
| 1 | Route | `routes/whatsapp.py:22` (`unified_webhook`) and `routes/chat.py:19` (`chat_webhook`) | **Mint** `run_id = mint_run_id()` at entry. Pass in `metadata` dict to `deps.flood.incoming()`. |
| 2 | FloodGate | `gateway/flood.py` | `incoming(chat_id, message, metadata)` — no logger today; add `logger.debug("flood_enqueue", extra={"chat_id": chat_id})`. ContextVar is inherited automatically since FloodGate is called with `await`. |
| 3 | FloodGate batch flush | `pipeline_helpers.py:515` (`on_batch_ready`) | [VERIFIED from `gateway/flood.py` full read]: FloodGate stores `{"messages": [...], "metadata": metadata}` and **overwrites metadata on each new message** (`flood.py:23`). After 3s debounce, `_wait_and_flush` calls `self._callback(chat_id, combined_message, buffer_data["metadata"])` — so the callback receives ONLY the last inbound message's `run_id`. Decision: the `on_batch_ready` callback uses `metadata["run_id"]` as the batch's runId (treating last-arrival-wins as good enough — aligns with "most recent message dominates the response"). Log the fact that earlier messages in the batch had different runIds only if operators complain; no `parent_run_ids[]` array needed for MVP. |
| 4 | Queue | `gateway/queue.py:MessageTask` | Add `run_id: str \| None = None` field to `MessageTask` dataclass so it travels across the queue.put → queue.get boundary (the context is *not* preserved across `asyncio.Queue` because the worker task was created before the producer). [VERIFIED: `gateway/queue.py` `MessageTask` has no `run_id` field today — must be added.] In `pipeline_helpers.py:536`, populate `run_id=metadata.get("run_id")` when constructing `MessageTask`. |
| 5 | Worker | `gateway/worker.py:MessageWorker._run` (~line 128) | Restore: `token = set_run_id(task.run_id); try: ...; finally: reset(token)`. |
| 6 | Persona chat | `chat_pipeline.py:persona_chat` (line 92, `_run_id` already minted at line 103) | **Reuse** existing `run_id` from ContextVar instead of minting new one. Update `_get_emitter().start_run(run_id=get_run_id(), text=..., target=...)` so the pipeline-emitter SSE stream uses the same ID. |
| 7 | LLM router + outbound | `llm_router.py`, `channels/whatsapp.py:WhatsAppChannel.send` | Read-only — loggers pick up runId from ContextVar automatically. |

**Backfeed pipeline_emitter:** at `pipeline_emitter.py:78`, change:
```python
rid = run_id or uuid.uuid4().hex[:12]
```
to:
```python
from sci_fi_dashboard.observability.context import get_run_id, mint_run_id
rid = run_id or get_run_id() or mint_run_id()
```
Same output shape, but now honors ContextVar first and mints a fresh ID only as last resort. Fixes the singleton race: `self._current_run_id` may still be written for back-compat readers, but every caller that goes through `observability.context` gets the request-scoped value.

## Logging Surface Inventory

Baseline counts from grep (top 20 files shown earlier; full scan available):

- **Total `logger.*()` calls across workspace:** ~493 (grep across `*.py`). Top offenders:
  - `channels/whatsapp.py` — 26 calls (HIGHEST PII RISK)
  - `api_gateway.py` — 21 calls
  - `chat_pipeline.py` — 18 calls
  - `conv_kg_extractor.py` — 14 calls
  - `cron_service.py` — 11 calls
  - `sbs_profile_init.py` — 11 calls
- **`logging.getLogger` creation sites:** 23 occurrences, 20 files. All but one use `__name__`.
- **Non-standard logger:** `dual_cognition.py:17` — `logger = logging.getLogger("dual_cognition")`. Matters for OBS-04: the user config key must be literal `"dual_cognition"`, not `"sci_fi_dashboard.dual_cognition"`. Document in the config schema.
- **`print()` calls alongside loggers:** `chat_pipeline.py:99` — `print(f"[MAIL] [{target.upper()}] Inbound: {user_msg[:80]}...")` — this bypasses logging entirely and **cannot be redacted**. Phase 13 should migrate at least the `[MAIL]` print to `logger.info(...)` so it goes through the formatter.
- **Third-party loggers in play:** `uvicorn`, `uvicorn.error`, `uvicorn.access`, `litellm`, `httpx`, `sqlite_vec`, `fastembed`. `litellm` is the noisiest (can emit 20+ INFO lines per call). Per-module taming: set `modules.litellm: WARNING` by default in the shipped `synapse.json`.

### PII Leak Sites Identified (must redact)
| File:Line | Current log | Leaked field |
|-----------|-------------|--------------|
| `channels/whatsapp.py:571` | `logger.info("[WA] DM from %s blocked (%s)", cm.user_id, access)` | raw JID |
| `routes/whatsapp.py:40` | `logger.debug("[gateway] WhatsApp event type=%s chat=%s", event_type, raw.get("chat_id", ""))` | raw JID |
| `gateway/worker.py:128` | `logger.info('Worker-%d gen=%d Processing: "%.60s..." from %s', worker_id, task.generation, task.user_message, task.sender_name)` | sender_name + 60 chars of message |
| `chat_pipeline.py:99` | `print(f"[MAIL] [{target.upper()}] Inbound: {user_msg[:80]}...")` | 80 chars of message via `print` |
| `channels/whatsapp.py:675` | `logger.debug("[WA-BRIDGE] %s", line.decode(errors="replace").rstrip())` | passthrough of Baileys stderr — may contain JIDs |

All five can be fixed by the formatter-side redaction (patterns 3 and 4 above) once `cm.user_id`, `chat_id`, `sender_name` are moved from positional args into `extra={}` — OR by wrapping call sites in `redact_identifier()`. Planner picks the approach per site.

## Common Pitfalls

### Pitfall 1: ContextVar does NOT propagate across `run_in_executor`
**What goes wrong:** You call `await loop.run_in_executor(None, sync_fn)` and inside `sync_fn` the logger emits a record with `runId=None`.
**Why it happens:** `run_in_executor` dispatches to a `ThreadPoolExecutor`; threads don't inherit asyncio context automatically.
**How to avoid:** Wrap with `contextvars.copy_context()`:
```python
import contextvars
ctx = contextvars.copy_context()
result = await loop.run_in_executor(None, ctx.run, sync_fn, *args)
```
**Warning signs:** JSON logs where runId is present for the async wrapper line but `null` for lines from the wrapped callable. Grep logs for runId flips.

### Pitfall 2: FastAPI `BackgroundTasks` do preserve context — but `asyncio.create_task` inside them does not (in 3.10-)
**What goes wrong:** In Python <3.11, `asyncio.create_task()` without explicit context capture misses the current context.
**Why it happens:** Pre-3.11 `create_task` did not snapshot context. Python 3.11 added the `context=` parameter and defaulted to current context.
**How to avoid:** Synapse targets 3.11+ (confirmed via `pyproject.toml` + `ruff target-version = py311`), so this is safe **on supported versions**. Still: whenever explicitly creating a task, pass `context=contextvars.copy_context()` to be future-proof.
**Warning signs:** Logs from spawned tasks show `runId=null`.

### Pitfall 3: `pipeline_emitter._current_run_id` race condition (EXISTING BUG)
**What goes wrong:** Two concurrent requests (e.g., WhatsApp webhook + WebSocket chat) both call `start_run()` — the singleton's `_current_run_id` is overwritten, so `emit("pipeline.llm_start")` from request A may carry request B's runId.
**Why it happens:** `_current_run_id` is a class attribute, not ContextVar.
**How to avoid:** Phase 13 migration described in Pipeline Integration section — have `pipeline_emitter` read from ContextVar first, fall back to its own attribute only as compatibility shim.
**Warning signs:** Dashboard SSE events mix data from two concurrent runs. Today this is silently happening under load.

### Pitfall 4: `dual_cognition.py` uses a non-`__name__` logger name
**What goes wrong:** Operator sets `synapse.json → logging.modules.sci_fi_dashboard.dual_cognition: DEBUG` — has no effect because the actual logger is named `"dual_cognition"`.
**Why it happens:** Historical artifact; `dual_cognition.py:17` uses `logging.getLogger("dual_cognition")`.
**How to avoid:** Option A (recommended): change to `logging.getLogger(__name__)` in `dual_cognition.py` as part of Phase 13 — consistent with 22 of 23 other modules. Option B: document the exception in `synapse.json` comments and support both paths in `apply_logging_config`.
**Warning signs:** Per-module config silently ignored for dual_cognition.

### Pitfall 5: Windows cp1252 stdout breaks JSON serializer with non-ASCII logged content
**What goes wrong:** Logging an emoji-bearing message on Windows raises `UnicodeEncodeError: 'charmap' codec can't encode character`.
**Why it happens:** Default `sys.stdout` on Windows is cp1252; CLAUDE.md explicitly flags this at gotcha #5.
**How to avoid:**
1. Pass `ensure_ascii=True` to `json.dumps()` in `JsonFormatter` (escapes non-ASCII as `\uXXXX`).
2. Configure `StreamHandler` with `stream=open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False)` as a second safety net.
3. Never rely on emoji markers in log text; use ASCII tags like `[WA]`, `[CLEAN]` (matches existing convention).
**Warning signs:** Startup crash on Windows when a single non-ASCII char appears in a log.

### Pitfall 6: Third-party loggers flood output
**What goes wrong:** `litellm` emits ~20 INFO lines per LLM call; operators' signal-to-noise ratio collapses.
**Why it happens:** litellm is verbose by default.
**How to avoid:** Ship `synapse.json` with sensible defaults: `logging.modules.litellm: WARNING`, `logging.modules.httpx: WARNING`, `logging.modules.uvicorn.access: WARNING`.
**Warning signs:** Operators complain about log volume.

### Pitfall 7: Formatter runs AFTER LogRecord is discarded by level filter
**What goes wrong:** You set `module=channel.whatsapp` level to WARNING, but still see INFO-level records from it.
**Why it happens:** Handler-level filter vs. logger-level filter confusion. `logging.getLogger("channel.whatsapp").setLevel(WARNING)` blocks at the logger. If a handler is attached with level=DEBUG and propagation crosses the hierarchy... records can sneak through parent handlers.
**How to avoid:** Set `propagate=False` on the named logger when assigning a handler, OR apply levels only on loggers never on handlers. Document the chosen convention.
**Warning signs:** Per-module setting doesn't take effect.

### Pitfall 8: `print()` bypasses logging entirely
**What goes wrong:** `chat_pipeline.py:99` uses `print()`, which never hits the formatter and leaks 80 chars of user message to stdout uncredicted.
**Why it happens:** Legacy code — `print` was faster to write.
**How to avoid:** Migrate each `print` to `logger.info(...)` in-scope for Phase 13. Limit to the PII-leaking ones (`[MAIL]`, `[WA]`, `[BATCH]`). Leave pure-status prints (`[TEST] Toxic-BERT loaded in 2.3s`) alone for now.
**Warning signs:** grep for `print\(f"\[` in `workspace/sci_fi_dashboard/` returns 20+ sites — pick the PII ones.

### Pitfall 9: FloodGate metadata overwrite loses early-batch runIds (VERIFIED, not theoretical)
**What goes wrong:** If a user sends 3 messages within 3s, each inbound webhook mints a different runId, but FloodGate's `self._buffers[chat_id]["metadata"] = metadata` (flood.py:23) overwrites earlier metadata. The batch callback sees ONLY the last message's runId. Messages 1 and 2 have orphaned runIds in the route-layer logs but no downstream correlation.
**Why it happens:** FloodGate is aggregation-heavy and was built before correlation-IDs were a concern. Metadata overwrite is semantically correct for "latest message's channel_id/sender_name win" but accidentally drops correlation data.
**How to avoid:** Three options for the planner to pick:
1. **Last-wins (simplest, MVP path)**: accept that only the last inbound message's runId is preserved through the pipeline. Log the orphan runIds at the route-layer only. Most operators won't care.
2. **Append runIds to buffer**: change `flood.py` to keep a `run_ids: list[str]` alongside messages. Batch callback emits `run_id = run_ids[-1]`, `parent_run_ids = run_ids[:-1]`.
3. **Propagate ContextVar through `asyncio.create_task`**: FloodGate's `_wait_and_flush` is created via `create_task` — Python 3.11 propagates the context of the FIRST `incoming()` call. Later `incoming()` calls don't overwrite the task's snapshot. Verify behavior in a unit test before committing.
**Recommendation:** Start with option 1 (simplest), add option 2 only if operators complain.
**Warning signs:** Rapid-fire user messages (< 3s apart) show runIds from the LAST message only in downstream logs.

## Code Examples

### `get_child_logger` usage (OpenClaw port)
```python
# Before (existing code):
import logging
logger = logging.getLogger(__name__)
logger.info("[WA] DM from %s blocked (%s)", cm.user_id, access)

# After (additive, backward-compatible):
from sci_fi_dashboard.observability import get_child_logger
log = get_child_logger("channel.whatsapp")
log.info("DM blocked", extra={"user_id": cm.user_id, "access": access})
# Formatter output (JSON):
# {"ts":"2026-04-21T18:30:12","level":"INFO","module":"channel.whatsapp",
#  "runId":"a7f3b2c19876","msg":"DM blocked","user_id_redacted":"id_a7f3b2c1","access":"deny"}
```

### Minting runId at webhook entry
```python
# routes/whatsapp.py — add at top of unified_webhook body
from sci_fi_dashboard.observability.context import mint_run_id
from sci_fi_dashboard.observability import get_child_logger

log = get_child_logger("route.whatsapp")

@router.post("/channels/{channel_id}/webhook")
async def unified_webhook(channel_id: str, request: Request):
    run_id = mint_run_id()
    log.info("webhook_received", extra={"channel_id": channel_id})
    # ... rest unchanged ...
```

### Restoring runId in worker
```python
# gateway/worker.py — inside MessageWorker._run
from sci_fi_dashboard.observability.context import set_run_id, _run_id_ctx

async def _run(self, task: MessageTask):
    token = set_run_id(task.run_id) if task.run_id else None
    try:
        # ... existing worker body ...
    finally:
        if token is not None:
            _run_id_ctx.reset(token)
```

### Assert runId continuity in tests
```python
# tests/test_observability_correlation.py
import json
import pytest

@pytest.mark.asyncio
async def test_run_id_propagates_end_to_end(capsys, monkeypatch):
    # send one webhook, capture stdout JSON lines
    from sci_fi_dashboard import api_gateway
    # ... invoke full pipeline with single message ...
    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    run_ids = {line["runId"] for line in lines if line.get("runId")}
    assert len(run_ids) == 1, f"runId not stable across pipeline: {run_ids}"
    assert len(lines) >= 5, "expected at least 5 log lines across pipeline hops"
```

Source: patterns synthesized from Python stdlib `logging` docs + CPython 3.11 asyncio contextvars semantics.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Thread-local correlation IDs | `contextvars.ContextVar` | Python 3.7 (Dec 2018); asyncio-aware propagation | Thread-local breaks under asyncio; ContextVar is the only correct stdlib primitive for async correlation. |
| `logging.basicConfig()` one-shot setup | Explicit handler + formatter wiring at lifespan | Always more correct; basicConfig no-ops after first handler attaches | Lifespan-based wiring is required when multiple entry points share the process (uvicorn, pytest, CLI). |
| Singleton run_id on emitter objects | ContextVar-backed per-request run_id | Applies to Synapse: fixes race in `pipeline_emitter._current_run_id` | No more cross-request contamination under concurrent load. |
| Truncation-based PII redaction (`+91****5678`) | HMAC-SHA256 salted digest (`id_a7f3b2c1`) | OWASP guidance since ~2019 | Stable correlation without structural info leak (no country code exposure, no length hints). |

**Deprecated/outdated:**
- `logging.Logger.addFilter()` for correlation: still works, but filters can't add fields to LogRecord easily across adapters. Adapters + formatter-field-reading is cleaner.
- Pre-3.7 `threading.local()` for async request IDs: broken under asyncio. Never use in this codebase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `python-json-logger>=2.0.7` is current (mid-2024) | Standard Stack — Supporting | LOW — this library is optional for MVP; version pin verified at adoption time, not now. |
| A2 | `structlog>=24.1.0` is current | Standard Stack — Supporting | LOW — deferred to Phase 14+; re-verify then. |
| A3 | OBS-04 per-module config applies at `lifespan()` startup with no hot reload | Pattern 5 | LOW — roadmap doesn't mention hot reload; punt to Phase 14+ if needed. |
| A4 | `pipeline_emitter._current_run_id` race condition affects production under concurrent WhatsApp + WebSocket traffic | Pitfall 3 | LOW — the structure of the code guarantees the race; not a hypothesis. |
| A5 | All 493 `logger.*()` calls can be left unchanged under additive strategy | Summary | MEDIUM — five PII-leaking calls (listed) still need migration or wrapping. "Unchanged" applies to 488 of them. |
| A6 | `python-json-logger` and `structlog` versions cited are current as of April 2026 | Standard Stack | MEDIUM — WebSearch / Context7 were unavailable this session (400 errors on the "effort" parameter); both pins are from training knowledge (~2024). Verify via `pip index versions` before adopting. |
| A7 | Python 3.11 `asyncio.Task` context-snapshot behavior applies to FloodGate's `_wait_and_flush` task — meaning the task snapshots whichever caller's context triggered the first `create_task`, not subsequent `incoming()` calls | Pitfall 9 option 3 | MEDIUM — dictates whether option 3 is viable; planner should write a unit test to prove or disprove before choosing an approach. |

**Previously-assumed claims now VERIFIED (moved out of this table):**
- FloodGate batch callback semantics — verified by direct read of `gateway/flood.py` (38 lines): metadata is overwritten per-message (line 23); callback fires once per debounce window with the LAST message's metadata only. See Pipeline Integration row 3 and Pitfall 9.
- `MessageTask` has no `run_id` field today — verified by direct read of `gateway/queue.py` lines 16-37. Must be added as part of Phase 13.
- `dual_cognition.py:17` uses literal `"dual_cognition"` not `__name__` — verified by direct read.
- `workspace/config/redaction.py` is for config-snapshot redaction only (fields: `api_key`, `token`, `secret`, `password`, `access_token`, `refresh_token`) — verified by direct read. Not suitable for PII/JID redaction in logs.

## Open Questions (RESOLVED)

1. **Should `redact_identifier()` handle the "already redacted" case?**
   - What we know: Redacting `"id_a7f3b2c1"` (an already-redacted string) would produce a new, different digest — confusing if logs pipeline through twice.
   - What's unclear: Does any code path log an already-redacted value?
   - Recommendation: Make `redact_identifier()` idempotent — detect `id_` prefix + 8 hex chars and return as-is.

2. **Dashboard SSE vs. stdout JSON — two outputs from one LogRecord?**
   - What we know: `pipeline_emitter` has its own dict-based emit to SSE. Phase 13 adds a stdout JSON formatter.
   - What's unclear: Should both streams share the same serialization? Or stay separate (dict to SSE, JSON string to stdout)?
   - Recommendation: Keep separate. `pipeline_emitter` stays dict-based (lower overhead for its SSE consumer); stdout gets JSON via Formatter. Bridge: `pipeline_emitter.emit()` reads `runId` from ContextVar for consistency.

3. **Log rotation + disk sink**
   - What we know: Current production config logs to stdout only; uvicorn may redirect.
   - What's unclear: Should Phase 13 add `RotatingFileHandler` to `~/.synapse/logs/synapse.jsonl`?
   - Recommendation: Defer. Phase 13 writes structured lines to stdout; operators redirect via `synapse_start.sh`. Rotation is an operator concern.

4. **FloodGate batch runId strategy**
   - What we know (VERIFIED from flood.py read): metadata is overwritten per-message; batch callback sees only the last runId.
   - What's unclear: Do operators actually care about tracing rapid-fire messages, or is "last message wins" good enough in practice?
   - Recommendation: ship with last-wins (option 1 of Pitfall 9), add `parent_run_ids[]` escalation only on operator request. Wave-0 decision.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | `contextvars.Task` context propagation | YES | 3.13.6 (verified via `python --version`) | — |
| stdlib `logging` | Core pattern | YES | bundled with Python | — |
| stdlib `contextvars` | runId propagation | YES | stdlib since 3.7 | — |
| stdlib `hmac` + `hashlib` | `redact_identifier()` | YES | stdlib | — |
| `jq` CLI | Roadmap success criterion 4 validation (`jq 'select(.runId == "<id>")'`) | NO | — | Use Python `json.loads` + `select` in pytest instead. See Validation Architecture below. |
| `pytest` + `pytest-asyncio` | Tests | YES | pytest>=7.4.0, pytest-asyncio>=0.23.0 per `requirements-dev.txt` | — |
| `python-json-logger` | Optional drop-in formatter | NO | — | Write stdlib `Formatter` subclass (MVP path; ~40 lines). |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:**
- `jq` — replace CLI-based success-criterion check with Python-level assertion in integration test. `jq` is a manual-smoke convenience; automation uses Python.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.4.0 + pytest-asyncio 0.23+ (`asyncio_mode = auto`) |
| Config file | `workspace/tests/pytest.ini` (NOT `workspace/pyproject.toml` — verified; pyproject has no pytest section) |
| Quick run command | `cd workspace && pytest tests/test_observability_*.py -x` |
| Full suite command | `cd workspace && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OBS-01 | runId stable across 7 pipeline hops for single inbound message | integration | `cd workspace && pytest tests/test_observability_correlation.py::test_run_id_propagates_end_to_end -x` | NO - Wave 0 |
| OBS-01 | `contextvars` survives `asyncio.create_task` boundary | unit | `cd workspace && pytest tests/test_observability_context.py::test_contextvar_survives_create_task -x` | NO - Wave 0 |
| OBS-01 | Worker restores runId from `MessageTask.run_id` | unit | `cd workspace && pytest tests/test_observability_context.py::test_worker_restores_run_id -x` | NO - Wave 0 |
| OBS-01 | FloodGate batch callback carries last-message's runId (VERIFIED semantics) | unit | `cd workspace && pytest tests/test_observability_context.py::test_flood_batch_carries_last_run_id -x` | NO - Wave 0 |
| OBS-01 | `pipeline_emitter.start_run()` honors ContextVar runId when provided | unit | `cd workspace && pytest tests/test_observability_context.py::test_emitter_honors_contextvar -x` | NO - Wave 0 |
| OBS-02 | `redact_identifier("1234567890@s.whatsapp.net")` produces stable `id_XXXXXXXX` | unit | `cd workspace && pytest tests/test_observability_redact.py::test_redact_golden -x` | NO - Wave 0 |
| OBS-02 | `redact_identifier()` idempotent — `redact(redact(x)) == redact(x)` | unit | `cd workspace && pytest tests/test_observability_redact.py::test_redact_idempotent -x` | NO - Wave 0 |
| OBS-02 | 1000 random JIDs logged, grep for `[0-9]{10}@` in output returns 0 matches | fuzz / integration | `cd workspace && pytest tests/test_observability_redact.py::test_no_raw_jids_in_logs -x` | NO - Wave 0 |
| OBS-02 | Salt persists across process restarts (`~/.synapse/state/logging_salt`) | unit | `cd workspace && pytest tests/test_observability_redact.py::test_salt_persistence -x` | NO - Wave 0 |
| OBS-02 | Salt file permissions are chmod 600 (no world-read) on POSIX | unit | `cd workspace && pytest tests/test_observability_redact.py::test_salt_permissions_posix -x` | NO - Wave 0 |
| OBS-03 | JSON output contains `module / runId / level / chat_id_redacted` fields | unit | `cd workspace && pytest tests/test_observability_formatter.py::test_json_fields_present -x` | NO - Wave 0 |
| OBS-03 | `ensure_ascii=True` — emoji in log content does not crash on Windows cp1252 | unit | `cd workspace && pytest tests/test_observability_formatter.py::test_non_ascii_handled -x` | NO - Wave 0 |
| OBS-03 | Each emitted line is independently `json.loads()`-parseable | unit | `cd workspace && pytest tests/test_observability_formatter.py::test_every_line_parseable -x` | NO - Wave 0 |
| OBS-03 | Exception tracebacks are captured in `exc` field (not lost) | unit | `cd workspace && pytest tests/test_observability_formatter.py::test_exception_captured -x` | NO - Wave 0 |
| OBS-04 | `logging.modules.llm_router: WARNING` in synapse.json blocks INFO records from `llm_router` | integration | `cd workspace && pytest tests/test_observability_config.py::test_per_module_level_applied -x` | NO - Wave 0 |
| OBS-04 | `logging.modules.dual_cognition: DEBUG` matches the literal logger name (not `sci_fi_dashboard.dual_cognition`) | integration | `cd workspace && pytest tests/test_observability_config.py::test_dual_cognition_anomaly -x` | NO - Wave 0 |
| OBS-04 | Default synapse.json ships with `litellm: WARNING, httpx: WARNING` baseline | integration | `cd workspace && pytest tests/test_observability_config.py::test_noisy_defaults_tamed -x` | NO - Wave 0 |
| OBS-04 | Missing `logging` section in synapse.json → defaults apply, no crash | unit | `cd workspace && pytest tests/test_observability_config.py::test_missing_section_defaults -x` | NO - Wave 0 |

### Sampling Rate
- **Per task commit:** `cd workspace && pytest tests/test_observability_*.py -x` (only observability tests, <10s)
- **Per wave merge:** `cd workspace && pytest tests/ -v` (full suite regression)
- **Phase gate:** Full suite green + manual smoke (send one WhatsApp message through local gateway, grep `~/.synapse/logs/synapse.jsonl` for single `runId` present in 5+ records).

### Wave 0 Gaps
- [ ] `workspace/tests/test_observability_context.py` — covers OBS-01 (ContextVar unit tests, FloodGate batch semantics, emitter-ContextVar bridge)
- [ ] `workspace/tests/test_observability_redact.py` — covers OBS-02 (redaction unit + fuzz tests, salt persistence + permissions)
- [ ] `workspace/tests/test_observability_formatter.py` — covers OBS-03 (JSON formatter tests, parseability, exception capture, Windows cp1252 safety)
- [ ] `workspace/tests/test_observability_config.py` — covers OBS-04 (per-module level tests, dual_cognition anomaly, default-section fallback)
- [ ] `workspace/tests/test_observability_correlation.py` — covers OBS-01 end-to-end integration test across 7 pipeline hops
- [ ] `workspace/tests/fixtures/observability/` — shared fixtures: `fake_synapse_json` with `logging` section, `captured_json_logs` fixture using `capsys`, `tmp_salt_path` fixture with monkeypatched `~/.synapse/state/logging_salt`
- [ ] `workspace/tests/conftest.py` — add `autouse` fixture that clears `_run_id_ctx` between tests (prevent context leakage across test runs)

**No framework install needed** — pytest + pytest-asyncio already in `requirements-dev.txt`.

## Security Domain

Applicable (observability touches PII redaction + audit logging).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 13 does not touch auth |
| V3 Session Management | no | — |
| V4 Access Control | no | Logs are file-read — OS-level ACLs govern access |
| V5 Input Validation | yes | Any log field from external input (JIDs, chat IDs, user messages) must be treated as untrusted; JSON serializer must not interpret strings as code; use `json.dumps` with `ensure_ascii=True` |
| V6 Cryptography | yes | HMAC-SHA256 for redaction — **never hand-roll**; use stdlib `hmac.new(salt, data, hashlib.sha256)`. Salt is CSPRNG (`secrets.token_bytes(32)`), chmod 600, persist at `~/.synapse/state/logging_salt`. |
| V7 Error Handling & Logging | **yes — primary domain** | ASVS 7.1.1: "Log all authentication decisions" — runId enables this. ASVS 7.3.1: "Do not log sensitive data" — redaction enforces this. ASVS 7.3.3: "Logs tamper-resistant" — out of scope (deferred to operator tooling). |
| V8 Data Protection | partial | PII redaction in logs satisfies V8.2.1 ("Application-level logging does not store sensitive data"). |

### Known Threat Patterns for Python async FastAPI

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Log injection via user-controlled message content | Tampering | `json.dumps(ensure_ascii=True)` escapes newlines, control chars — prevents log-forging attacks. Never string-concatenate user input into log format string. |
| PII exposure in error tracebacks | Information Disclosure | Strip `args` from `logger.exception()` output if they contain PII fields. For Phase 13: redaction filter runs on LogRecord **before** formatting — covers exceptions too. |
| Salt leak via memory dump | Information Disclosure | Salt is 32 bytes of process memory. Not a meaningful threat in single-user self-host context. Chmod 600 on disk is sufficient. |
| Correlation ID prediction enabling session fixation | Tampering | runId is 12 hex chars from `uuid.uuid4()` — unpredictable. Not used for auth, only for log correlation, so prediction has no impact. |
| Cross-tenant log leakage via shared singleton | Information Disclosure | **THIS IS THE EXISTING BUG** — `pipeline_emitter._current_run_id` is process-wide. Phase 13 fixes via ContextVar. |

## Project Constraints (from CLAUDE.md)

Direct extraction of directives from `D:\Shorty\Synapse-OSS\CLAUDE.md` that constrain Phase 13:

1. **OSS development hygiene (pre-push)**: No personal data, tokens, keys in commits. Phase 13 salt file lives at `~/.synapse/state/logging_salt` — must be in `.gitignore`, never shipped with repo.
2. **Code graph first**: Use `semantic_search_nodes` / `query_graph` tools before Grep/Glob/Read. Planner should query graph for each file it touches.
3. **Python 3.11 / line-length 100 / ruff + black**: All new code in `workspace/sci_fi_dashboard/observability/` must pass `ruff check workspace/ && black workspace/` with the existing config.
4. **asyncio throughout**: No Redis/Celery. ContextVar-based correlation fits this constraint.
5. **Windows cp1252 gotcha (gotcha #5)**: All preview strings must be ASCII. JSON output must use `ensure_ascii=True`. StreamHandler should force UTF-8.
6. **synapse_config.py has wide blast radius (gotcha #7)**: Adding a `logging` section to `SynapseConfigSchema` requires care. Make the new section optional with a sane default so no existing install breaks.
7. **Traffic cop / dual cognition coupling (gotcha #8-10)**: Phase 13 must not change pipeline timing. `apply_logging_config()` must complete in <10ms during startup; redaction must add <1ms per log line (HMAC-SHA256 over 20-byte identifier is well under).
8. **`print()` alongside loggers**: CLAUDE.md does not explicitly forbid, but Phase 13 goals imply migrating the PII-leaking prints to `logger.info()`.

## Sources

### Primary (HIGH confidence)
- Python 3 stdlib docs — `logging`, `contextvars`, `hmac`, `secrets` (training knowledge; stdlib APIs are stable across 3.7+)
- `D:\Shorty\Synapse-OSS\CLAUDE.md` (read directly) — OSS workflow rules, gotchas, architecture
- `D:\Shorty\Synapse-OSS\.planning\REQUIREMENTS.md` (read directly) — OBS-01..04 requirements
- `D:\Shorty\Synapse-OSS\.planning\ROADMAP.md` (read directly) — Phase 13 scope + success criteria
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\pipeline_emitter.py:78-88` (read directly) — existing runId convention + race condition
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\gateway\flood.py` (read directly, full 38 lines) — FloodGate metadata-overwrite semantics, `_wait_and_flush` callback shape
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\gateway\queue.py` (read directly) — `MessageTask` schema confirms no `run_id` field today
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\gateway\worker.py:120-138` (read directly) — PII leak site at line 128
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\pipeline_helpers.py:515-546` (read directly) — `on_batch_ready` + `MessageTask` construction site
- `D:\Shorty\Synapse-OSS\workspace\sci_fi_dashboard\dual_cognition.py:14-17` (read directly) — non-standard logger name confirmed
- `D:\Shorty\Synapse-OSS\workspace\config\redaction.py` (read directly, full) — confirms scope limited to config snapshots; no PII redaction available today
- `D:\Shorty\Synapse-OSS\workspace\tests\pytest.ini` (read directly) — test framework config: pytest-asyncio auto mode, markers
- `D:\Shorty\Synapse-OSS\requirements-dev.txt` (read directly) — pytest>=7.4.0, pytest-asyncio>=0.23.0 present
- `D:\Shorty\Synapse-OSS\.planning\phases\12-p0-bug-fixes\12-VALIDATION.md` — format template

### Secondary (MEDIUM confidence)
- `python-json-logger` version `>=2.0.7` — training knowledge, last verified ~2024; verify via `pip index versions` at adoption time.
- `structlog` version `>=24.1.0` — training knowledge; deferred dependency.
- OpenClaw `getChildLogger`/`redactIdentifier` pattern shape — inferred from roadmap description; no direct source read this session. Reasonable assumption based on standard Python logging patterns.

### Tertiary (LOW confidence) — flagged for validation
- Exact OpenClaw repo structure / lineage — not verified; treat pattern as a naming reference, implement fresh.
- `asyncio.Task` context-snapshot behavior for FloodGate's `_wait_and_flush` — Python 3.11 docs imply snapshot-at-creation, but FloodGate cancels+recreates the task on each new `incoming()` call, which means each restart snapshots the caller's context at THAT moment. Planner should write a unit test to confirm before committing to option 3 of Pitfall 9.

### Environment constraint this session
- Context7, WebSearch, WebFetch all returned `API Error: 400 ... "effort" parameter not supported` — external verification was unavailable. Version pins and third-party library assertions are based on training knowledge (last stable: late 2024). Planner should run `pip index versions <pkg>` before adopting any new dep, and may re-run research if external tools recover.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all primitives are Python 3.11 stdlib, verified available on dev host.
- Architecture patterns: HIGH — ContextVar / Formatter / Filter patterns are stable stdlib API surface.
- Pitfalls: HIGH — items 1-5 all grounded in read source files or verified docs; items 6-8 are common engineering knowledge; item 9 is VERIFIED from direct flood.py read.
- Pipeline integration: HIGH — all 7 hops have corresponding source files directly read this session.
- Optional deps (python-json-logger, structlog) version pins: MEDIUM — training-knowledge based; verify at adoption.
- OpenClaw lineage reference: LOW — pattern shape assumed from roadmap wording.

**Research date:** 2026-04-21
**Valid until:** 2026-05-21 (30-day window — Python stdlib is stable, but third-party pins may drift within the month).
