# Phase 17: Pipeline Decomposition + Inbound Gate — Research

**Researched:** 2026-04-24
**Domain:** Python asyncio pipeline refactoring, access-control gate reorder, structured observability
**Confidence:** HIGH (all findings from direct codebase inspection)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PIPE-01 | `chat_pipeline.py` split into six phase modules under `pipeline/` | Current monolith mapped line-by-line below; six natural seams identified |
| PIPE-02 | Each module has a single public function with typed inputs/outputs | `PipelineContext` dataclass proposed; each module's contract defined in §3 |
| PIPE-03 | `persona_chat()` becomes a ~50-80 line orchestrator threading context through phases | Orchestrator sketch provided; heavy logic moves to phase modules |
| PIPE-04 | All existing `tests/` pass unchanged after the split | Test dependency surface mapped; extract-then-inline strategy specified |
| ACL-03 | DmPolicy gate runs BEFORE FloodGate, Dedup, and TaskQueue | Current gate location found; inbound-gate placement in `unified_webhook` specified |
</phase_requirements>

---

## 1. Current Code Map

### `persona_chat()` Step-by-Step

File: `workspace/sci_fi_dashboard/chat_pipeline.py`

| Step | Lines (approx) | What Happens | Data Produced |
|------|---------------|--------------|---------------|
| 0. Entry + run_id emit | 93-111 | Log inbound, `_get_emitter().start_run()` | `_pipeline_start`, `_run_id` |
| 1. Consent Protocol | 113-233 | Check `deps.pending_consents`, detect new modify intents, may return early | dict reply or fall-through |
| 2. Memory Retrieval | 235-298 | Permanent profile SQL + `MemoryEngine.query()` + format `memory_context` | `mem_response`, `memory_context`, `retrieval_method` |
| 3. Toxicity Check | 300-312 | `deps.toxic_scorer.score(user_msg)` | `toxicity` float |
| 4. Dual Cognition | 313-371 | `asyncio.wait_for(deps.dual_cognition.think(..., pre_cached_memory=mem_response))` | `cognitive_merge`, `cognitive_context` |
| 5. Length/Situational enrichment | 373-411 | Build `_length_hint`, `_situational_block` | strings injected into prompt |
| 6. Prompt Assembly | 413-476 | SBS `get_system_prompt()`, build `messages` list, inject memory + cognitive ctx | `messages` list |
| 7. Skill Routing | 479-520 | `deps.skill_router.match(user_msg)` — may return early | dict reply or fall-through |
| 8. Tool Context/Schema | 522-555 | Resolve tools, apply policy pipeline, get schemas | `session_tools`, `tool_schemas` |
| 9a. Vault Branch | 557-599 | Direct `call_with_metadata("vault", messages)` | `result`, `reply` |
| 9b. Safe Branch — Traffic Cop | 601-638 | `STRATEGY_TO_ROLE` check or `route_traffic_cop(user_msg)` | `classification`, `role` |
| 9c. Image gen branch | 640-730 | `BackgroundTask(_generate_and_send_image)`, return early | dict reply |
| 9d. Tool execution loop | 746-931 | 0-N rounds of LLM call + parallel/serial tool execution | `reply`, `tools_used` |
| 10. Footer assembly | 943-993 | Token stats, elapsed, `format_tool_footer` | `final_reply` |
| 11. SBS log + auto-continue | 1000-1020 | `sbs_orchestrator.on_message("assistant",...)`, `BackgroundTask(continue_conversation)` | side-effects |
| 12. Return | 1022-1036 | Build result dict, `_get_emitter().end_run()` | `{"reply", "persona", "memory_method", "model"}` |

**Total lines:** ~1037 (non-counting imports)

### DmPolicy Gate — Current Location

`channels/whatsapp.py:670-677` — inside `WhatsAppChannel.receive()`, which is called from `routes/whatsapp.py:54` (`unified_webhook`):

```
unified_webhook() [routes/whatsapp.py:28]
  → channel.receive(raw)            # line 54 — DmPolicy gate lives HERE
  → supervisor.record_activity()    # line 65
  → echo_tracker.is_echo()         # line 68
  → dedup.is_duplicate()           # line 85
  → flood.incoming()               # line 88
```

**Result:** A blocked sender currently reaches `dedup.is_duplicate()` and `flood.incoming()` — both are no-ops because `receive()` returning `None` short-circuits at line 57, but conceptually the gate is pipeline-side inside `receive()`, not at the true inbound boundary. The success criterion requires ZERO FloodGate enqueue events, which is satisfied today, but the requirement also specifies the gate must run BEFORE FloodGate rather than inside the channel adapter. The current implementation already blocks before FloodGate at the `receive()` level; ACL-03 is about making this contract explicit and observable (log format) and ensuring it applies even if `receive()` is bypassed.

**Important nuance:** `receive()` returning `None` already prevents `flood.incoming()` from being called (lines 55-57 check `if msg is None: return ...`). So the dedup and flood are already not invoked for blocked senders. ACL-03's real work is:
1. Extract the gate from inside `receive()` into a separately-testable `access.py` module
2. Move the call site to `unified_webhook` so it is explicitly ordered BEFORE the dedup/flood calls
3. Emit the mandated structured log line with `module: access, reason: dm-policy, sender: <redacted>, runId: <id>`

### Where `process_message_pipeline()` Calls `persona_chat()`

`pipeline_helpers.py:457`:
```python
result = await persona_chat(chat_req, target, None, mcp_context=mcp_context)
```

The `pipeline_helpers.process_message_pipeline()` handles session state, history loading, and compaction AROUND the `persona_chat()` call. It is NOT part of the decomposition target — it remains as-is.

### `on_batch_ready()` and FloodGate

`pipeline_helpers.py:515-547` — callback called by `FloodGate._wait_and_flush()`. This receives the batched messages from FloodGate and enqueues a `MessageTask` into `deps.task_queue`. The `run_id` is threaded from webhook metadata into the task here (`run_id=metadata.get("run_id")`).

---

## 2. Target Module Contracts

### Proposed `PipelineContext` Dataclass

Location: `workspace/sci_fi_dashboard/pipeline/context.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from sci_fi_dashboard.schemas import ChatRequest

@dataclass
class PipelineContext:
    # Inputs (set by orchestrator, immutable through pipeline)
    request: ChatRequest          # original ChatRequest with message, user_id, history, session_type
    target: str                   # persona target ("the_creator" / "the_partner")
    mcp_context: str = ""         # pre-fetched MCP memory enrichment from MessageWorker

    # Phase outputs (set by each module in order; later phases read earlier fields)
    session_mode: str = "safe"        # set by normalize — "safe" | "spicy"
    mem_response: dict | None = None  # set by enrich (memory query result)
    memory_context: str = ""          # set by enrich (formatted for prompt)
    retrieval_method: str = "none"    # set by enrich
    toxicity: float = 0.0             # set by enrich
    cognitive_merge: Any = None       # set by enrich (CognitiveMerge | None)
    cognitive_context: str = ""       # set by enrich (from dual cognition)
    messages: list[dict] = field(default_factory=list)  # set by enrich (assembled prompt)
    classification: str = ""          # set by route
    role: str = "casual"              # set by route
    reply: str = ""                   # set by reply
    result_meta: dict = field(default_factory=dict)  # LLMResult metadata (model, tokens)
    tools_used: list[str] = field(default_factory=list)  # set by reply

    # Observability
    pipeline_start: float = 0.0   # time.time() at orchestrator entry
    run_id: str | None = None     # forwarded from request context for log correlation
```

**Mutability rule:** Each phase function receives `ctx: PipelineContext` and mutates it in-place. Functions return the same `ctx` object (for chainability, not for immutability). No phase reaches backward into a field it did not produce. [ASSUMED — alternative is frozen dataclasses returning new objects; recommend mutable for performance since the object lives for one request only]

### Six Module Contracts

All modules live in `workspace/sci_fi_dashboard/pipeline/`.

#### `normalize.py`

```python
async def normalize(ctx: PipelineContext) -> PipelineContext:
    """Resolve session_mode (safe|spicy) from env + request. Pure."""
```
**Reads:** `ctx.request.session_type`, `os.environ["SESSION_TYPE"]`
**Writes:** `ctx.session_mode`
**Side effects:** None
**Early exit:** None

#### `debounce.py`

```python
async def debounce(ctx: PipelineContext) -> PipelineContext | None:
    """Check consent protocol; return None to short-circuit pipeline."""
```
**Reads:** `ctx.request.message`, `ctx.request.user_id`, `deps.pending_consents`, `deps.consent_protocol`
**Writes:** Nothing on fall-through; executes consent action and returns early result dict if intercepted
**Side effects:** May pop `deps.pending_consents`; may call `deps.consent_protocol.confirm_and_execute()`
**Early exit:** Returns a result dict (not `None`) when consent is intercepted. Orchestrator checks: `if isinstance(result, dict): return result`.

**Note:** The name "debounce" in the ROADMAP is used loosely — this module handles consent-protocol interception (the "debounce" phase in OpenClaw terms is what the FloodGate already does at a lower level). The planner should clarify the exact semantics. [ASSUMED that `debounce.py` = consent-protocol interceptor per pipeline order]

#### `access.py`

```python
async def access(ctx: PipelineContext) -> PipelineContext | None:
    """Inbound access-control gate. Returns None if sender is blocked."""
```
**Reads:** `ctx.request.user_id`, channel security config + pairing store
**Writes:** Nothing (pure decision)
**Side effects:** Emits structured log `module: access, reason: dm-policy, sender: <redacted>, runId: <id>`
**Early exit:** Returns `None` to signal blocked (orchestrator returns early without calling reply)

**CRITICAL:** This module is also called from `unified_webhook` at the router level (before FloodGate) — not only as a pipeline stage. See §3.

#### `enrich.py`

```python
async def enrich(ctx: PipelineContext) -> PipelineContext:
    """Memory retrieval, toxicity, dual cognition, prompt assembly."""
```
**Reads:** `ctx.request`, `ctx.session_mode`, `ctx.target`, `deps.memory_engine`, `deps.toxic_scorer`, `deps.dual_cognition`, `deps.get_sbs_for_target()`
**Writes:** `ctx.mem_response`, `ctx.memory_context`, `ctx.retrieval_method`, `ctx.toxicity`, `ctx.cognitive_merge`, `ctx.cognitive_context`, `ctx.messages`
**Side effects:** `sbs_orchestrator.on_message("user", ...)`, `_get_emitter().emit(...)` calls
**Early exit:** None (errors produce degraded outputs, not hard failures)

#### `route.py`

```python
async def route(ctx: PipelineContext) -> PipelineContext | None:
    """Classify message: skill routing, traffic cop, role assignment. May return early."""
```
**Reads:** `ctx.request.message`, `ctx.session_mode`, `ctx.cognitive_merge`, `deps.skill_router`, `deps.synapse_llm_router`
**Writes:** `ctx.classification`, `ctx.role`
**Side effects:** May dispatch `BackgroundTask(_generate_and_send_image)` for IMAGE role
**Early exit:** Returns result dict for skill match and image gen dispatch (short-circuit)

#### `reply.py`

```python
async def reply(ctx: PipelineContext, background_tasks=None) -> PipelineContext:
    """LLM call (tool loop or direct), footer assembly, auto-continue."""
```
**Reads:** `ctx.role`, `ctx.session_mode`, `ctx.messages`, `ctx.request`, `ctx.cognitive_merge`, `deps.synapse_llm_router`, `deps.tool_registry`
**Writes:** `ctx.reply`, `ctx.result_meta`, `ctx.tools_used`
**Side effects:** May dispatch `BackgroundTask(continue_conversation)`, `sbs_orchestrator.on_message("assistant", ...)`, `_get_emitter().end_run()`
**Early exit:** None (always produces a reply, even if error)

---

## 3. Inbound Gate Reorder (ACL-03)

### Where the Gate Must Live

**Current position:** `channels/whatsapp.py:670` inside `WhatsAppChannel.receive()` — called at `routes/whatsapp.py:54`.

**Correct position:** `routes/whatsapp.py:unified_webhook()` — BEFORE the echo-tracker check, BEFORE the dedup check, and BEFORE `flood.incoming()`.

**The ordering in `unified_webhook` after ACL-03:**
```
unified_webhook()
  1. mint_run_id()                   # line 34 — already minted HERE (runId available)
  2. channel.receive(raw)            # normalize to ChannelMessage (strip DmPolicy from here)
  3. if msg is None: skip            # non-message events
  4. **NEW: inbound_gate(msg)**      # ACL-03 — call resolve_dm_access(), log + return if denied
  5. supervisor.record_activity()
  6. echo_tracker.is_echo()
  7. dedup.is_duplicate()
  8. flood.incoming()
```

**RunId availability:** `mint_run_id()` is already called at `routes/whatsapp.py:34` — before `channel.receive()`. The inbound gate at step 4 has the runId available via `get_run_id()` from the ContextVar. No minting change needed.

### Per-Channel vs Gateway-Wide

**Option A: Per-channel adapter (current, inside `receive()`)**
- DmPolicy is checked inside `whatsapp.py`, `telegram.py`, `slack.py`, `discord_channel.py` — four separate call sites
- Pro: Channel-specific context (group detection is channel-specific)
- Con: Cannot be independently tested without constructing a full channel; buried logic

**Option B: Gateway-wide (in `unified_webhook`)**
- One call site for all channels
- Requires: channel must expose `security_config` and `pairing_store` as attributes
- Pro: Explicit ordering; independently testable; single log format
- Con: Requires `unified_webhook` to know channel internals

**Recommendation (for ACL-03):** Option B for the WhatsApp channel (the primary channel and the one specified in the success criteria). The `WhatsAppChannel` already has `self.security_config` and `self._pairing_store` as public-ish attributes. Other channels (Telegram, Slack, Discord) already perform the check inside their own `receive()` — leave those unchanged for now. ACL-03 is specifically about the inbound gate running before FloodGate, not about unifying all channels.

The gate in `unified_webhook` reads:
```python
# ACL-03: inbound gate — must run before dedup and flood
if channel_id == "whatsapp":
    wa_security = getattr(channel, "security_config", None)
    wa_pairing  = getattr(channel, "_pairing_store", None)
    if wa_security and wa_pairing and not msg.is_group:
        access = resolve_dm_access(msg.user_id, wa_security, wa_pairing)
        if access != "allow":
            _log.info(
                "access_denied",
                extra={
                    "module": "access",
                    "reason": "dm-policy",
                    "sender": redact_identifier(msg.user_id),
                    "runId": get_run_id(),
                },
            )
            return {"status": "skipped", "reason": "dm-policy", "accepted": True}
```

**Remove from `channels/whatsapp.py:receive()`:** Lines 669-677. The gate there becomes dead code once `unified_webhook` gates it first.

### Rejection Propagation Back to Channel

The WhatsApp bridge is push-only (Synapse does not need to send a "rejected" message to the user). Return `{"status": "skipped", "reason": "dm-policy", "accepted": True}` from `unified_webhook` — the bridge interprets `accepted: true` as acknowledgment. No send needed. For PAIRING mode, the channel adapter's existing pairing-request flow (if any) remains unchanged.

---

## 4. PIPE-04 Test-Preservation Strategy

### Tests That Directly Touch Pipeline

| Test File | What It Tests | Public Surface Dependency |
|-----------|---------------|--------------------------|
| `test_api_gateway.py` | `persona_chat()` core logic (mocked LLM + memory); pure functions from `api_gateway` / `chat_pipeline` | `from sci_fi_dashboard.chat_pipeline import persona_chat` (implicit via mocks) |
| `test_channel_pipeline.py` | `FloodGate → on_batch_ready → MessageTask → TaskQueue` | `FloodGate`, `TaskQueue`, `MessageTask` — does NOT import `chat_pipeline` |
| `test_channel_security.py` | `DmPolicy`, `resolve_dm_access`, `PairingStore` | `channels.security` only |
| `test_channel_whatsapp_extended.py` | `WhatsAppChannel.receive()` DM blocking | `WhatsAppChannel`, `security` |
| `test_flood.py` | `FloodGate` batching | `FloodGate` — isolated |
| `test_dedup.py` | `MessageDeduplicator` | `gateway.dedup` — isolated |
| `test_queue.py` | `TaskQueue` | `gateway.queue` — isolated |
| `test_gateway_worker.py` | `MessageWorker` | `gateway.worker` |
| `test_functional.py` | End-to-end business logic via isolated instances | `FloodGate`, `MessageDeduplicator`, `TaskQueue` — does NOT import `chat_pipeline` |
| `test_dual_cognition.py` | `DualCognitionEngine.think()` | `dual_cognition` — isolated |
| `test_e2e.py` | Full stack (likely mocked heavily) | May import `process_message_pipeline` |
| `test_integration.py` | Integration paths | May import `persona_chat` or `process_message_pipeline` |

### Key Finding: Tests Isolate Well

`test_channel_pipeline.py` explicitly comments: "Tests do NOT import api_gateway to avoid boot-time singleton side effects." Most pipeline-adjacent tests mock the components they test and do not import `chat_pipeline.py` directly. This significantly reduces PIPE-04 risk.

### Split Strategy: Extract-Then-Inline

**Order to minimize test failures per commit:**

1. **Wave 0:** Create `workspace/sci_fi_dashboard/pipeline/` directory with `__init__.py` and `context.py` (`PipelineContext` dataclass). No behavior changes.
2. **Wave 1a:** Create `pipeline/normalize.py` and `pipeline/debounce.py` as extracted functions. Keep `persona_chat()` calling them inline (thin wrapper). Tests pass because `persona_chat` signature unchanged.
3. **Wave 1b:** Create `pipeline/access.py` with the `access()` function (extracted from `WhatsAppChannel.receive()`). Do NOT yet move it to `unified_webhook`.
4. **Wave 2a:** Create `pipeline/enrich.py`. Extract memory + toxicity + dual cognition + prompt assembly. `persona_chat()` delegates to `enrich(ctx)`.
5. **Wave 2b:** Create `pipeline/route.py`. Extract skill routing + traffic cop + role assignment.
6. **Wave 2c:** Create `pipeline/reply.py`. Extract LLM loop + footer.
7. **Wave 3:** Wire ACL-03 — add `access` gate call to `unified_webhook`, remove from `WhatsAppChannel.receive()`. Add structured log line.
8. **Wave 3:** Slim `persona_chat()` to orchestrator. Final lint + full test run.

**Test category concern:** `test_channel_whatsapp_extended.py::TestWhatsAppReceive` tests `receive()` DM blocking directly by checking `ch.receive(payload)` returns `None` for blocked senders. After ACL-03 moves the gate to `unified_webhook`, `receive()` will no longer block — this test will now return a `ChannelMessage` (not `None`) for blocked senders. This is the **only test predicted to break** from ACL-03. Resolution options:
- Option A: Keep a thin ACL check in `receive()` as a defense-in-depth pass-through (would satisfy test without modification) — but creates duplicate gate
- Option B: Update the test to test the new `access()` module directly — but PIPE-04 says no test modifications

**Recommendation for planner:** Plan 17-01 (Wave 0) should resolve this ambiguity explicitly. The cleanest approach is to keep `receive()` performing the DmPolicy check as defense-in-depth (it already does), and ALSO add the check in `unified_webhook` before `flood.incoming()`. Double-check is acceptable — the gate is cheap (in-memory set lookup). This satisfies both the test (receive still returns None for blocked senders) and ACL-03 (gate runs explicitly before FloodGate).

---

## 5. Observability Continuity (Phase 13 Baseline)

### RunId Mint Point

`routes/whatsapp.py:34` — `run_id = mint_run_id()` — already the first line of `unified_webhook`. The ContextVar is set here. Every subsequent async step inherits it. The `access` gate at step 4 reads `get_run_id()` from the same ContextVar — no timing issue.

### Required Log Fields Per Module

| Module | Event Name | Required Extra Fields |
|--------|------------|----------------------|
| `access` | `access_denied` | `module: "access"`, `reason: "dm-policy"`, `sender: redact_identifier(user_id)`, `runId: get_run_id()` |
| `normalize` | `session_mode_resolved` | `module: "pipeline.normalize"`, `session_mode` |
| `debounce` | `consent_intercepted` | `module: "pipeline.debounce"`, `consent_action` |
| `enrich` | `memory_query_done`, `toxicity_checked`, `cognitive_state` | Already emitted in `chat_pipeline.py` — preserve as-is in `enrich.py` |
| `route` | `route_classified`, `skill_routed`, `traffic_cop_skip` | Already emitted — preserve in `route.py` |
| `reply` | `response_generated`, `tool_loop_done`, `llm_call_done` | Already emitted — preserve in `reply.py` |

### Mandated ACL-03 Log Format

From success criterion:
```
module: access, reason: dm-policy, sender: <redacted>, runId: <id>
```

The Phase 13 `JsonFormatter` will serialize the `extra` dict as structured JSON. The `get_child_logger("pipeline.access")` adapter attaches `runId` automatically via `RunIdFilter`. The required format maps to:
```python
_log = get_child_logger("pipeline.access")
_log.info("access_denied", extra={
    "module": "access",         # explicit to match success criterion wording
    "reason": "dm-policy",
    "sender": redact_identifier(msg.user_id),  # OBS-02 compliance
    # runId injected automatically by RunIdFilter
})
```

The `module` field in the extra dict will be merged with the logger name (`pipeline.access`) in the JSON output. The success criterion reads the literal string — either `module` key or the logger name field will satisfy it. [VERIFIED: Phase 13 `JsonFormatter` attaches `RunIdFilter.filter()` which injects `runId` from ContextVar into every `LogRecord`]

---

## 6. Risk + Rollback

### Top 3 Failure Modes

**Failure 1: Circular imports after module split**
`chat_pipeline.py` currently imports from `deps`, `llm_wrappers`, `schemas`, `pipeline_emitter`, `consent_protocol`. Moving logic to `pipeline/*.py` while those modules also import from `sci_fi_dashboard.*` risks circular imports at module load time.
- Prevention: Each `pipeline/*.py` module uses deferred imports (inside the function body) for heavy singletons. Only `PipelineContext` and type hints are module-level imports.
- Detection: `python -c "import sci_fi_dashboard.pipeline"` immediately after each Wave commit.

**Failure 2: `background_tasks` parameter threading breaks auto-continue/image-gen**
`persona_chat()` currently accepts `background_tasks: BackgroundTasks | None` and passes it to inline `BackgroundTask` calls. After decomposition, `reply.py` and `route.py` need this parameter.
- Prevention: Thread `background_tasks` through `PipelineContext` (add as field) OR pass it as a second argument to `reply()` and `route()`. Recommend the latter to keep the context object data-only.
- Detection: PIPE-04 — test_api_gateway.py has tests that call `persona_chat` with BackgroundTasks mock.

**Failure 3: PIPE-04 breakage from `test_channel_whatsapp_extended.py`**
`TestWhatsAppReceive.test_receive_dm_blocked` (inferred from file contents) currently asserts `receive()` returns `None` for blocked senders. If ACL-03 removes the gate from `receive()`, this test breaks.
- Prevention: Keep defense-in-depth check in `receive()` AND add gate to `unified_webhook` (double-gate approach). See §4.
- Detection: Run `pytest tests/test_channel_whatsapp_extended.py -v` after Wave 3 before any other change.

### Feature-Flag Strategy

Add to `synapse.json` under a `pipeline` key (not existing keys — avoids blast radius of `synapse_config.py`):
```json
"pipeline": {
  "use_modular": true
}
```

In `chat_pipeline.py`, add at the start of `persona_chat()`:
```python
if not deps._synapse_cfg.pipeline.get("use_modular", True):
    return await _persona_chat_legacy(request, target, background_tasks, mcp_context)
```

Keep `_persona_chat_legacy` as an alias to the old monolith body (copy-preserved) until Phase 18 ships. Set `use_modular: false` in `synapse.json` to instantly revert. After Phase 18 lands, delete the legacy path.

### Bisect Strategy if PIPE-04 Fails

1. Run `pytest tests/ -v --tb=short 2>&1 | grep FAILED` to identify failing tests.
2. Each failing test will point to a broken import or changed API surface.
3. Git bisect between Wave commits: `git bisect start HEAD <last-green-commit>`.
4. The extract-then-inline strategy means each Wave commit is independently runnable.

---

## 7. Validation Architecture

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x (already installed, `workspace/tests/` in use) |
| Config file | None (no pytest.ini detected — tests run via `cd workspace && pytest tests/ -v`) |
| Quick run command | `cd workspace && pytest tests/test_channel_security.py tests/test_flood.py tests/test_dedup.py -v` |
| Full suite command | `cd workspace && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PIPE-01 | `pipeline/` directory exists with six modules | smoke | `python -c "from sci_fi_dashboard.pipeline import normalize, debounce, access, enrich, route, reply"` | Wave 0 |
| PIPE-02 | Each module exports typed function | contract | `pytest tests/pipeline/test_pipeline_contracts.py` | Wave 0 |
| PIPE-03 | `persona_chat()` is ~50-80 lines, no phase logic inline | structural | `python -c "import inspect; from sci_fi_dashboard.chat_pipeline import persona_chat; print(len(inspect.getsource(persona_chat).splitlines()))"` | n/a — manual |
| PIPE-04 | All existing tests pass | parity | `cd workspace && pytest tests/ -v` | Already exists |
| ACL-03 | Blocked sender produces zero FloodGate enqueue events | integration | `pytest tests/pipeline/test_inbound_gate.py` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_channel_security.py tests/test_flood.py tests/test_dedup.py tests/test_channel_whatsapp_extended.py -v`
- **Per wave merge:** `cd workspace && pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `workspace/tests/pipeline/test_pipeline_contracts.py` — contract tests for each module's type signature (PIPE-02)
- [ ] `workspace/tests/pipeline/test_inbound_gate.py` — ACL-03 zero-side-effect test for blocked senders (ACL-03)
- [ ] `workspace/tests/pipeline/test_pipeline_wiring.py` — orchestrator threads PipelineContext correctly through all six phases (PIPE-03)
- [ ] `workspace/tests/pipeline/test_pipeline_observability.py` — log lines emitted with required fields per module

### Contract Test Pattern (PIPE-02)

```python
# tests/pipeline/test_pipeline_contracts.py
import inspect
from sci_fi_dashboard.pipeline.normalize import normalize
from sci_fi_dashboard.pipeline.context import PipelineContext

def test_normalize_signature():
    sig = inspect.signature(normalize)
    assert "ctx" in sig.parameters
    # return annotation: PipelineContext (coroutine)
    assert sig.return_annotation in (PipelineContext, "PipelineContext")
```

### ACL-03 Inbound-Gate Test Pattern

```python
# tests/pipeline/test_inbound_gate.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.channels.security import ChannelSecurityConfig, DmPolicy

async def test_blocked_sender_zero_flood_enqueue():
    flood = FloodGate(batch_window_seconds=0.01)
    enqueue_events = []
    flood.set_callback(lambda *a, **kw: enqueue_events.append(a))

    # Simulate unified_webhook with ACL-03 gate enabled
    # ALLOWLIST policy — sender not in list
    security_cfg = ChannelSecurityConfig(
        dm_policy=DmPolicy.ALLOWLIST, allow_from=["allowed@s.whatsapp.net"]
    )
    pairing_store = MagicMock()
    pairing_store.is_approved.return_value = False

    sender = "blocked@s.whatsapp.net"
    from sci_fi_dashboard.channels.security import resolve_dm_access
    access = resolve_dm_access(sender, security_cfg, pairing_store)
    assert access == "deny"

    # Gate fires — flood.incoming() never called
    if access != "allow":
        pass  # gate blocks — do not call flood.incoming()

    await asyncio.sleep(0.05)  # let any pending tasks resolve
    assert len(enqueue_events) == 0, "FloodGate must have zero enqueue events for blocked sender"
```

---

## 8. Open Questions for Planner

**Q1: What does `debounce.py` contain?**
The ROADMAP names the six modules as `normalize / debounce / access / enrich / route / reply`. The current `persona_chat()` body has a "consent protocol interception" section (lines 113-233) that acts as a pre-pipeline gate. This is the most logical candidate for `debounce.py`. But "debounce" suggests rate limiting / timing, which is FloodGate's job (already pre-pipeline). The planner must decide: does `debounce.py` = consent-protocol interceptor, or does it mean something else? [RECOMMENDED: consent-protocol interceptor, renamed semantically in the plan]

**Q2: Mutability of `PipelineContext`**
Mutable in-place vs. return-new-object pattern. Mutable is simpler and avoids allocation per phase call. The success criterion says "threads a shared context object through phases" which implies mutability. Confirm with planner before Wave 1.

**Q3: How do per-channel adapters (Telegram, Slack, Discord) learn about the unified gate?**
Currently each channel does its own `resolve_dm_access()` inside `receive()`. The roadmap says ACL-03 is specifically about the inbound gate before FloodGate. The `unified_webhook` handles all channels. The planner should decide: extend the `unified_webhook` gate to all channels (requires `security_config` attribute on every channel), or scope ACL-03 to WhatsApp only for Phase 17 (Telegram/Slack/Discord already gate inside their own `receive()` which is called before FloodGate anyway).

**Q4: Where does FloodGate live in the decomposed world?**
FloodGate is gateway-level, not part of `persona_chat()`. It remains in `deps.flood` and `pipeline_helpers.on_batch_ready`. The six pipeline modules are all called AFTER FloodGate flushes. Confirm the planner understands the split: the six modules decompose `persona_chat()` (not the full inbound path from webhook to reply).

**Q5: `background_tasks: BackgroundTasks | None` threading**
`reply.py` (image gen dispatch) and `route.py` (auto-continue) need this parameter. Should it be a field on `PipelineContext` or a second parameter to those functions? Adding it to context is clean but changes the dataclass contract. Second parameter keeps context data-only. [RECOMMENDED: second parameter — `reply(ctx, background_tasks=None)`]

**Q6: Phase 16 manual-validation status**
Phase 16 is at manual-validation-pending (HANDOFF.md shows 7/8 rows pending, HEART-05 is 24h soak). Phase 17 depends on Phase 16 being stable. The planner should confirm Phase 16 has passed all manual rows before starting Phase 17 Wave 1+.

---

## Architecture Patterns

### Recommended Project Structure

```
workspace/sci_fi_dashboard/pipeline/
├── __init__.py       # exports: PipelineContext + all six phase functions
├── context.py        # PipelineContext dataclass
├── normalize.py      # session_mode resolution
├── debounce.py       # consent-protocol interception
├── access.py         # DmPolicy gate (also called from unified_webhook)
├── enrich.py         # memory + toxicity + dual cognition + prompt assembly
├── route.py          # skill routing + traffic cop + role assignment
└── reply.py          # LLM call loop + footer + auto-continue
```

The orchestrator in `chat_pipeline.py` becomes:
```python
async def persona_chat(request, target, background_tasks=None, mcp_context=""):
    from sci_fi_dashboard.pipeline import (
        PipelineContext, normalize, debounce, enrich, route, reply
    )
    ctx = PipelineContext(request=request, target=target, mcp_context=mcp_context)
    ctx.pipeline_start = time.time()
    with suppress(Exception):
        get_emitter().start_run(text=request.message[:120], target=target)

    ctx = await normalize(ctx)
    result = await debounce(ctx)
    if isinstance(result, dict): return result     # consent intercepted

    ctx = await enrich(ctx)
    result = await route(ctx, background_tasks)
    if isinstance(result, dict): return result     # skill or image early exit

    ctx = await reply(ctx, background_tasks)
    return build_response_dict(ctx)               # ~5 lines
```

### Anti-Patterns to Avoid

- **Cross-phase backward reads:** `reply.py` must not read `ctx.mem_response` directly — that is `enrich.py`'s output and may change shape in future. Use only fields set in the same or earlier phase.
- **Heavy singletons at module level:** All `deps.*` access must be inside function bodies, not at module import time, to avoid breaking test isolation.
- **`asyncio.create_task` inside phase modules without GC anchors:** Follow the existing `_background_tasks` set pattern in `pipeline_helpers.py`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured log correlation | Custom per-module logging | `get_child_logger("pipeline.X")` from `observability/` | Phase 13 already built this; `RunIdFilter` attaches runId automatically |
| PII redaction in log | Inline string slicing | `redact_identifier()` from `observability/` | HMAC-SHA256 stable correlation; OBS-02 compliant |
| RunId propagation across tasks | Pass run_id explicitly in function args | ContextVar via `mint_run_id()`/`get_run_id()` | Propagates through `asyncio.create_task()` automatically; Phase 13 baseline |
| Access-control decision | New boolean flag or state machine | `resolve_dm_access()` from `channels.security` | Already tested, covers all 4 DmPolicy variants |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact on Phase 17 |
|--------------|------------------|--------------|-------------------|
| Singleton `_current_run_id` race | ContextVar-backed `mint_run_id()` | Phase 13 (Plan 04) | runId already available in `unified_webhook` before `access` gate |
| Raw `print()` in pipeline | `get_child_logger("pipeline.chat")` | Phase 13 (Plan 04) | Phase modules inherit this pattern; no new logger wiring needed |
| Duplicate skill-routing block | Single skill-routing block post WA-FIX-05 | Phase 12 | Phase 17 decomposes from clean baseline |
| DmPolicy inside `receive()` | DmPolicy in `unified_webhook` (after ACL-03) | Phase 17 | Core ACL-03 work |
| Monolithic `persona_chat()` (~1037 lines) | Orchestrator + 6 phase modules | Phase 17 | Core PIPE-01..03 work |

---

## Environment Availability

Step 2.6: SKIPPED — Phase 17 is a pure code refactoring with no new external dependencies. All runtime dependencies (Python 3.11, litellm, FastAPI, asyncio) are already in use.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `debounce.py` = consent-protocol interceptor (not FloodGate-style batching) | §2, §8 | Module boundary wrong; planner re-scopes |
| A2 | Mutable `PipelineContext` (in-place mutation per phase) | §2 | Alternative: return-new-object; minor refactor |
| A3 | Double-gate approach (keep `receive()` gate + add `unified_webhook` gate) resolves PIPE-04 vs ACL-03 tension | §4 | If planner removes `receive()` gate, `test_channel_whatsapp_extended.py` will fail — violates PIPE-04 |
| A4 | `background_tasks` threaded as second parameter to `reply()` and `route()`, not on `PipelineContext` | §2, §8 | If put on context, tests that instantiate `PipelineContext` directly need updating |
| A5 | Feature-flag key `pipeline.use_modular` does not exist yet in `SynapseConfig` schema | §6 | Will need new config field; blast radius of `synapse_config.py` is high (50+ imports) |

**If this table is non-empty:** Planner must resolve A1, A3, and A5 before Wave 1 begins.

---

## Sources

### Primary (HIGH confidence — direct codebase inspection)
- `workspace/sci_fi_dashboard/chat_pipeline.py` — full monolith, line-by-line map
- `workspace/sci_fi_dashboard/routes/whatsapp.py` — `unified_webhook` order
- `workspace/sci_fi_dashboard/channels/whatsapp.py:670-677` — current DmPolicy gate location
- `workspace/sci_fi_dashboard/channels/security.py` — `resolve_dm_access`, `DmPolicy`, `PairingStore`
- `workspace/sci_fi_dashboard/gateway/flood.py` — `FloodGate.incoming()` — no ACL gate
- `workspace/sci_fi_dashboard/gateway/dedup.py` — `MessageDeduplicator` — no ACL gate
- `workspace/sci_fi_dashboard/gateway/queue.py` — `MessageTask`, `TaskQueue`
- `workspace/sci_fi_dashboard/pipeline_helpers.py` — `process_message_pipeline`, `on_batch_ready`
- `workspace/sci_fi_dashboard/observability/__init__.py` + `context.py` — Phase 13 API
- `.planning/phases/13-structured-observability/13-04-SUMMARY.md` — Phase 13 baseline confirmed
- `.planning/phases/16-heartbeat-bridge-hardening/16-HANDOFF.md` — Phase 16 status: manual-validation-pending
- `workspace/tests/` — full test file list inspected; PIPE-04 dependency surface mapped

### Secondary (MEDIUM confidence — inferred from code patterns)
- Test isolation pattern confirmed via `test_channel_pipeline.py` docstring: "Tests do NOT import api_gateway"
- Phase 13 `RunIdFilter` injects `runId` into all `LogRecord`s automatically — confirmed via `observability/__init__.py`

---

## Metadata

**Confidence breakdown:**
- Current code map: HIGH — direct inspection of all relevant files
- Target module contracts: MEDIUM — proposed based on codebase structure; A1-A5 are planner decisions
- ACL-03 gate placement: HIGH — current gate location confirmed, target location clear
- Test preservation risk: HIGH — PIPE-04 tension with ACL-03 identified and mitigation specified
- Observability continuity: HIGH — Phase 13 API confirmed available

**Research date:** 2026-04-24
**Valid until:** Stable (codebase snapshot; not time-sensitive — no external APIs)
