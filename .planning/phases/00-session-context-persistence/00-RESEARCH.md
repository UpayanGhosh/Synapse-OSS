# Phase 0: Session & Context Persistence - Research

**Researched:** 2026-04-06
**Domain:** Python asyncio wiring — multiuser/ session infrastructure into WhatsApp pipeline
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** The gap is exactly one function: `process_message_pipeline()` in `pipeline_helpers.py` always passes `history=[]` to `ChatRequest`. Fix this function. Nothing else needs architectural changes.
- **D-02:** The `multiuser/` module (session_store, transcript, context_assembler, compaction, session_key, conversation_cache) is COMPLETE and CORRECT — do not refactor or replace it. Wire it in as-is.
- **D-03:** OpenClaw's session architecture (studied) is functionally identical to what Synapse already has. No new patterns needed.
- **D-04:** Use `build_session_key()` from `multiuser/session_key.py`. Inputs: `agent_id` from `deps._resolve_target(chat_id)`, `channel="whatsapp"`, `peer_id=chat_id`, `peer_kind="direct"` (group detection via `MessageTask.is_group`), `dm_scope` from `synapse.json → session.dmScope` (currently `"per-channel-peer"`).
- **D-05:** `agent_id` must be the resolved target string (e.g., `"the_creator"`), not the raw `chat_id`.
- **D-06:** For group chats (`MessageTask.is_group = True`), use `peer_kind="group"`.
- **D-07:** `account_id` and `main_key` can be hardcoded to `"whatsapp"` and `"whatsapp:dm"` respectively for now.
- **D-08:** Add a single `ConversationCache` instance to `_deps.py` as a module-level singleton. `max_entries=200, ttl_s=300` (5 minutes).
- **D-09:** The cache must NOT be instantiated per-request.
- **D-10:** Before calling `persona_chat()`, load history via `load_messages(transcript_path, limit=history_limit)`. Config key: `channels.whatsapp.dmHistoryLimit` in `synapse.json` — default to 50 turns if not set.
- **D-11:** After getting the reply, append TWO messages to transcript: `{"role": "user", "content": user_msg}` then `{"role": "assistant", "content": reply}`. Use `transcript.append_message()`.
- **D-12:** Transcript append is fire-and-forget via `asyncio.create_task()`.
- **D-13:** Use `conversation_cache.append()` after the in-memory cache to keep it warm.
- **D-14:** Check for compaction AFTER transcript append. If estimated tokens > 60% of context window, trigger `compact_session()` as a background task.
- **D-15:** Compaction is always a `asyncio.create_task()` — never awaited.
- **D-16:** For compaction, use `deps.llm_router` as the LLM client. The compaction module's `llm_client` contract requires `await llm_client.acompletion(messages=[...])`.
- **D-17:** Default context window: 32,000 tokens.
- **D-18:** `data_root` = `SynapseConfig.load().db_dir.parent` — wait, see Critical Gotcha #1 below.
- **D-19:** `SessionStore` is instantiated once per call in `process_message_pipeline()` (no I/O in `__init__`). Not a singleton in `_deps.py`.
- **D-20:** `routes/sessions.py` already exists — verify it works with new store format.
- **D-21:** `GET /sessions` should return sessions from disk store (SessionStore.load()), not from an in-memory dict.
- **D-22:** `entities.json` ships as `{}`. EntityGate loads from `knowledge_graph.db`. Do not regress.

### Claude's Discretion

- Exact error handling when transcript file is corrupt (skip and start fresh vs raise)
- Whether to log session_key on each message (useful for debugging)
- Startup cleanup of stale lock files (`clean_stale_lock_files()` — already exists, wire into app startup)

### Deferred Ideas (OUT OF SCOPE)

- Cross-channel session linking (same user on WhatsApp + Telegram shares history)
- Session analytics dashboard (turn counts, token usage per session)
- Manual compaction API (`POST /sessions/{key}/compact`)
- Session tagging / labeling
- Per-session model override
- Group chat history tuning
</user_constraints>

---

## Summary

Phase 0 is a pure wiring phase. The `multiuser/` module (6 files, ~1200 lines) is complete and correct. The single gap is in `process_message_pipeline()` at `pipeline_helpers.py:203` — it always passes `history=[]` to `ChatRequest`, discarding all conversation context. The fix: before the `persona_chat()` call, build a session key, load transcript history, pass it to `ChatRequest`; after the reply, fire-and-forget transcript append and optional compaction.

Two integration gotchas require specific attention: (1) `data_root` from the CONTEXT.md decision D-18 has a wrong formula — verified below; (2) `SynapseLLMRouter` does NOT expose `acompletion(messages=[...])` directly — a thin adapter wrapper is required for compaction. Both are confirmed by reading the actual source files.

The existing `routes/sessions.py` reads from an unrelated SQLite `sessions` table (token usage tracking) — it is NOT compatible with the new `SessionStore` (file-based JSON). The decision D-21 to update this endpoint to use `SessionStore.load()` means rewriting that endpoint almost entirely.

**Primary recommendation:** Wire in exactly this order: (1) add `ConversationCache` singleton to `_deps.py`, (2) modify `process_message_pipeline()` signature to accept `is_group` flag, (3) build session key + load history + pass to ChatRequest, (4) fire-and-forget transcript append + cache update + compaction check.

---

## Standard Stack

No new library installations required. All dependencies already present in the project.

| Module | Location | Purpose | API Used |
|--------|----------|---------|---------|
| `SessionStore` | `multiuser/session_store.py` | Per-agent JSON store for session metadata (UUID, timestamps, compaction count) | `update(session_key, patch)`, `get(session_key)`, `load()` |
| `transcript` | `multiuser/transcript.py` | JSONL read/write | `append_message(path, msg)`, `load_messages(path, limit)`, `transcript_path(entry, data_root, agent_id)` |
| `ConversationCache` | `multiuser/conversation_cache.py` | In-memory LRU cache for parsed message lists | `get(key)`, `put(key, msgs)`, `append(key, msg)`, `invalidate(key)` |
| `build_session_key` | `multiuser/session_key.py` | Pure function, builds canonical session key string | `build_session_key(agent_id, channel, peer_id, peer_kind, account_id, dm_scope, main_key, identity_links)` |
| `compact_session` | `multiuser/compaction.py` | Token-triggered transcript compaction | `compact_session(transcript_path, context_window_tokens, llm_client, agent_id, session_key, store_path)` |
| `estimate_tokens` | `multiuser/compaction.py` | Pure chars/4 heuristic | `estimate_tokens(messages) -> int` |

**Installation:**
```bash
# No new installs — filelock is already present (used by session_store.py)
# Verify: pip show filelock
```

---

## Architecture Patterns

### The Single Change Point

`process_message_pipeline()` in `pipeline_helpers.py` is the ONLY file that changes logic. `_deps.py` gets one new singleton.

```
Before:
  process_message_pipeline(user_msg, chat_id, mcp_context)
    → ChatRequest(message=user_msg, history=[])   # always empty
    → persona_chat(chat_req, target, None, mcp_context)

After:
  process_message_pipeline(user_msg, chat_id, mcp_context, is_group=False)
    → build_session_key(...)
    → SessionStore.get() / update()          # get/create session entry
    → transcript_path(entry, data_root, agent_id)
    → conversation_cache.get(key) or load_messages(t_path, limit)
    → ChatRequest(message=user_msg, history=loaded_messages)
    → persona_chat(chat_req, target, None, mcp_context)
    → asyncio.create_task(append user + assistant to transcript)
    → asyncio.create_task(compact if > threshold)
```

### Recommended Project Structure (No New Files)

The only new file is the test file. All wiring is in existing files:

```
workspace/sci_fi_dashboard/
├── _deps.py              # ADD: conversation_cache singleton
├── pipeline_helpers.py   # MODIFY: process_message_pipeline() wiring
├── routes/sessions.py    # REWRITE: use SessionStore instead of SQLite sessions table
tests/
└── test_session_persistence.py  # NEW: all session tests
```

### Pattern 1: ConversationCache Singleton in `_deps.py`

```python
# Source: [VERIFIED: workspace/sci_fi_dashboard/_deps.py pattern reading]
# Add after line 107 (after dual_cognition = DualCognitionEngine(...))

from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache  # noqa: E402

conversation_cache = ConversationCache(max_entries=200, ttl_s=300)
```

**Critical:** Module-level assignment, same pattern as `brain`, `gate`, `dual_cognition`. NOT inside any function or class.

### Pattern 2: Session Key Construction

```python
# Source: [VERIFIED: workspace/sci_fi_dashboard/multiuser/session_key.py]
from sci_fi_dashboard.multiuser.session_key import build_session_key

cfg = SynapseConfig.load()
session_cfg = cfg.session  # dict from synapse.json → "session" key
dm_scope = session_cfg.get("dmScope", "per-channel-peer")
identity_links = session_cfg.get("identityLinks", {})

session_key = build_session_key(
    agent_id=target,           # "the_creator" or "the_partner"
    channel="whatsapp",
    peer_id=chat_id,           # raw phone number / group ID
    peer_kind="group" if is_group else "direct",
    account_id="whatsapp",     # hardcoded for now (D-07)
    dm_scope=dm_scope,
    main_key="whatsapp:dm",    # hardcoded for now (D-07)
    identity_links=identity_links,
)
# Result example: "agent:the_creator:whatsapp:dm:+91xxxxx"
```

### Pattern 3: Session Entry Get/Create

```python
# Source: [VERIFIED: workspace/sci_fi_dashboard/multiuser/session_store.py]
from sci_fi_dashboard.multiuser.session_store import SessionStore
from sci_fi_dashboard.multiuser.transcript import transcript_path

data_root = SynapseConfig.load().data_root   # See Critical Gotcha #1
store = SessionStore(agent_id=target, data_root=data_root)

entry = await store.get(session_key)
if entry is None:
    entry = await store.update(session_key, {})

t_path = transcript_path(entry, data_root, target)
```

### Pattern 4: History Load with Cache

```python
# Source: [VERIFIED: workspace/sci_fi_dashboard/multiuser/conversation_cache.py]
# Source: [VERIFIED: workspace/sci_fi_dashboard/multiuser/transcript.py]
from sci_fi_dashboard.multiuser.transcript import load_messages

cfg = SynapseConfig.load()
history_limit = (
    cfg.channels.get("whatsapp", {}).get("dmHistoryLimit", 50)
)

messages = deps.conversation_cache.get(session_key)
if messages is None:
    messages = await load_messages(t_path, limit=history_limit)
    deps.conversation_cache.put(session_key, messages)
```

### Pattern 5: Post-Reply Fire-and-Forget

```python
# Source: [VERIFIED: pipeline_helpers.py:~155 AutoContinue pattern]
user_msg_dict = {"role": "user", "content": user_msg}
assistant_msg_dict = {"role": "assistant", "content": reply}

async def _append_and_compact():
    from sci_fi_dashboard.multiuser.transcript import append_message
    from sci_fi_dashboard.multiuser.compaction import estimate_tokens, compact_session

    await append_message(t_path, user_msg_dict)
    await append_message(t_path, assistant_msg_dict)
    deps.conversation_cache.append(session_key, user_msg_dict)
    deps.conversation_cache.append(session_key, assistant_msg_dict)

    # Compaction check (D-14: 60% threshold per decision, but module default is 80%)
    all_msgs = deps.conversation_cache.get(session_key) or []
    context_window = 32_000  # D-17
    if estimate_tokens(all_msgs) > context_window * 0.6:
        await compact_session(
            transcript_path=t_path,
            context_window_tokens=context_window,
            llm_client=_LLMClientAdapter(deps.synapse_llm_router),
            agent_id=target,
            session_key=session_key,
            store_path=store._path,
        )
        deps.conversation_cache.invalidate(session_key)

asyncio.create_task(_append_and_compact())
```

### Pattern 6: LLM Adapter for Compaction (CRITICAL — see Gotcha #2)

```python
# Source: [VERIFIED: workspace/sci_fi_dashboard/llm_router.py — no acompletion method on SynapseLLMRouter]
# Source: [VERIFIED: workspace/sci_fi_dashboard/multiuser/compaction.py — contract doc at top]

class _LLMClientAdapter:
    """Thin adapter: exposes acompletion(messages=[...]) from SynapseLLMRouter.call()."""
    def __init__(self, router: SynapseLLMRouter) -> None:
        self._router = router

    async def acompletion(self, messages: list[dict]):
        # compaction.py accesses resp.choices[0].message.content
        # SynapseLLMRouter._do_call() returns the raw litellm response object
        # We need the raw response, not the extracted string from call()
        return await self._router._do_call("casual", messages)
```

**Note:** `_do_call` is a private method (single underscore). Alternatively, define the adapter to call `self._router._router.acompletion(...)` (the underlying litellm.Router). See Pitfall 2 for details.

### Anti-Patterns to Avoid

- **Calling `SynapseConfig.load()` on every message:** Load config once per `process_message_pipeline` call (it is not cached internally). Better: access from `deps._synapse_cfg` which is already loaded at module startup.
- **Awaiting compaction in the response path:** Compaction must be `asyncio.create_task()`. Never `await compact_session()` before returning the reply.
- **Instantiating `ConversationCache` per-request:** Defeats the purpose entirely. Must be module-level singleton in `_deps.py`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-process file locking | custom lock files | `SynapseFileLock` in `session_store.py` | Already handles stale-lock reclaim, PID recycling, atexit cleanup |
| Transcript repair after compaction | custom cleanup | `repair_orphaned_tool_pairs()` in `transcript.py` | Handles tool_use/tool_result orphan pairs left by compaction split |
| Token estimation | tiktoken or similar | `estimate_tokens()` in `compaction.py` | Already used throughout — keeps heuristic consistent |
| History window slicing | manual list slicing | `limit_history_turns()` in `transcript.py` | Counts user turns backwards correctly, handles tool messages |
| Session key formatting | string f-formatting | `build_session_key()` in `session_key.py` | Handles all 4 dm_scope variants, identity links, sanitization |

**Key insight:** Every hard problem in this domain (locking, atomicity, token counting, repair) already has a solution in `multiuser/`. The phase is wiring only.

---

## Common Pitfalls

### Pitfall 1: Wrong `data_root` Formula in D-18

**What goes wrong:** D-18 says `data_root = SynapseConfig.load().db_dir.parent`. This is WRONG.

**Verification:** `db_dir = data_root / "workspace" / "db"` (from `synapse_config.py:123`). So `db_dir.parent = data_root / "workspace"`, NOT `data_root`.

**How to avoid:** Use `SynapseConfig.load().data_root` directly. This is the `~/.synapse/` root. Already available in `_deps.py` as `_synapse_cfg = SynapseConfig.load()` at line 249 — so in `pipeline_helpers.py`, use `SynapseConfig.load().data_root` or pass it from the cached `deps._synapse_cfg.data_root`.

**Correct formula:**
```python
data_root = SynapseConfig.load().data_root  # → ~/.synapse/
# SessionStore path: ~/.synapse/state/agents/<agent_id>/sessions/sessions.json
# Transcript path:   ~/.synapse/state/agents/<agent_id>/sessions/<uuid>.jsonl
```

### Pitfall 2: SynapseLLMRouter Has No `acompletion()` Method

**What goes wrong:** D-16 says "use `deps.llm_router` as the LLM client" and compaction requires `await llm_client.acompletion(messages=[...])`. But `SynapseLLMRouter` has NO `acompletion()` method — verified by grep. Its public API is `call(role, messages)`, `call_with_metadata()`, `call_model()`, `call_with_tools()`.

**Root cause:** `SynapseLLMRouter.call()` returns a plain `str` (extracted text). Compaction needs `resp.choices[0].message.content` — i.e., the raw litellm response object.

**How to avoid:** Write a `_LLMClientAdapter` class (Pattern 6 above) that wraps `SynapseLLMRouter`. Two options:
  - Option A: Call `self._router._do_call("casual", messages)` — returns raw litellm response, matches contract. Uses private method.
  - Option B: Call `self._router._router.acompletion(model=..., messages=messages)` — the underlying `litellm.Router` object. Requires knowing the model string.
  - **Recommendation:** Option A (simpler, model selection handled by role mapping). Document the private access as intentional adapter code.

### Pitfall 3: `process_message_pipeline` Has No `is_group` Parameter

**What goes wrong:** The worker calls `process_fn(task.user_message, chat_id, task.mcp_context)` — 3 positional args max. `is_group` from `MessageTask` is NOT passed through. The worker inspects signature length to decide whether to pass `mcp_context`.

**Root cause:** `MessageWorker._process_fn_accepts_mcp` checks `len(sig.parameters) >= 3`. Adding a 4th parameter (`is_group`) would still be detected as "accepts mcp", but the worker only calls with 3 args — the 4th would use the default.

**How to avoid:** Add `is_group: bool = False` as a keyword-only argument with default. The worker continues calling with 3 positional args, `is_group` defaults to `False` (DM). This is correct for the vast majority of WhatsApp messages. Group support can be addressed in a future phase. **Do NOT change the worker signature.**

```python
async def process_message_pipeline(
    user_msg: str, chat_id: str, mcp_context: str = "", *, is_group: bool = False
) -> str:
```

### Pitfall 4: `routes/sessions.py` Uses SQLite `sessions` Table, Not `SessionStore`

**What goes wrong:** The existing `GET /api/sessions` reads from the SQLite `sessions` table in `memory.db` — this is token-usage tracking from `llm_router.py`, not conversation session metadata. The CONTEXT.md decisions (D-20, D-21) say to update this endpoint to use `SessionStore`, but the two data sources are completely different schemas.

**How to avoid:** Rewrite `GET /api/sessions` to scan `SessionStore.load()` per agent. Keep the SQLite-based token tracking as a separate endpoint if needed, or remove it. Do NOT try to merge the two data sources.

### Pitfall 5: `compact_session()` Checks `should_compact()` Internally

**What goes wrong:** If you check the threshold BEFORE calling `compact_session()`, and compaction checks it again internally (with an 80% threshold), you have a threshold mismatch. D-14 says 60%, but `compaction.py:should_compact()` defaults to 80%.

**How to avoid:** Either call `compact_session()` unconditionally (it internally checks and returns `{"ok": True, "compacted": False}` if below threshold), OR call `should_compact()` / `estimate_tokens()` with your chosen threshold first as a gate. Consistent approach: call `estimate_tokens()` and check against 60% as a pre-gate before even spawning the background task.

### Pitfall 6: `asyncio.create_task()` Scope

**What goes wrong:** `asyncio.create_task()` requires a running event loop and will silently fail (or raise) if called outside an async context. The task is also garbage-collected if no reference is held.

**How to avoid:** Store the task reference or use the pattern already established in the codebase (AutoContinue in `pipeline_helpers.py:~155`):
```python
task = asyncio.create_task(_append_and_compact())
# Prevent GC before task completes
asyncio.get_event_loop().call_soon(lambda: None)  # or use background_tasks set
```
Better: maintain a `_background_tasks: set = set()` module-level set, add tasks to it, add a done-callback that removes them (pattern from Python asyncio docs).

### Pitfall 7: `ConversationCache.append()` is a No-Op on Cache Miss

**What goes wrong:** After appending to the transcript, calling `conversation_cache.append(session_key, msg)` on a key that hasn't been loaded yet is a no-op (by design — avoids partial state). The first `put()` must happen before any `append()` calls.

**How to avoid:** On the first message to a session (cache miss → load from disk → cache miss still if new session → empty list), call `conversation_cache.put(session_key, [])` before appending the first message. Or: always use `put()` after loading, even if the message list is empty.

---

## Code Examples

### Full Wiring Sketch for `process_message_pipeline()`

```python
# Source: [VERIFIED — assembled from reading all referenced source files]
async def process_message_pipeline(
    user_msg: str, chat_id: str, mcp_context: str = "", *, is_group: bool = False
) -> str:
    from sci_fi_dashboard.chat_pipeline import persona_chat
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import transcript_path, load_messages, append_message
    from sci_fi_dashboard.multiuser.compaction import estimate_tokens, compact_session

    target = deps._resolve_target(chat_id)
    cfg = SynapseConfig.load()
    data_root = cfg.data_root
    session_cfg = cfg.session
    dm_scope = session_cfg.get("dmScope", "per-channel-peer")
    identity_links = session_cfg.get("identityLinks", {})

    session_key = build_session_key(
        agent_id=target,
        channel="whatsapp",
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id="whatsapp",
        dm_scope=dm_scope,
        main_key="whatsapp:dm",
        identity_links=identity_links,
    )

    store = SessionStore(agent_id=target, data_root=data_root)
    entry = await store.get(session_key)
    if entry is None:
        entry = await store.update(session_key, {})

    t_path = transcript_path(entry, data_root, target)

    history_limit = int(cfg.channels.get("whatsapp", {}).get("dmHistoryLimit", 50))
    messages = deps.conversation_cache.get(session_key)
    if messages is None:
        messages = await load_messages(t_path, limit=history_limit)
        deps.conversation_cache.put(session_key, messages)

    chat_req = ChatRequest(
        message=user_msg,
        user_id=chat_id,
        session_type="safe",
        history=messages,           # <-- the fix
    )
    result = await persona_chat(chat_req, target, None, mcp_context=mcp_context)
    reply = result.get("reply", "")

    # Fire-and-forget: append + compact
    user_dict = {"role": "user", "content": user_msg}
    asst_dict = {"role": "assistant", "content": reply}

    async def _save():
        await append_message(t_path, user_dict)
        await append_message(t_path, asst_dict)
        deps.conversation_cache.append(session_key, user_dict)
        deps.conversation_cache.append(session_key, asst_dict)
        # Compaction pre-gate
        cached = deps.conversation_cache.get(session_key) or []
        ctx_window = 32_000
        if estimate_tokens(cached) > ctx_window * 0.6:
            await compact_session(
                transcript_path=t_path,
                context_window_tokens=ctx_window,
                llm_client=_LLMClientAdapter(deps.synapse_llm_router),
                agent_id=target,
                session_key=session_key,
                store_path=store._path,
            )
            deps.conversation_cache.invalidate(session_key)

    asyncio.create_task(_save())
    return reply
```

### Updated `GET /sessions` Endpoint

```python
# Source: [VERIFIED — routes/sessions.py current is SQLite-based; new version uses SessionStore]
@router.get("/api/sessions", dependencies=[Depends(_require_gateway_auth)])
async def get_sessions():
    """Return all sessions from disk store for all agents."""
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard import _deps as deps

    cfg = SynapseConfig.load()
    data_root = cfg.data_root
    results = []
    for agent_id in deps.sbs_registry:
        store = SessionStore(agent_id=agent_id, data_root=data_root)
        sessions = await store.load()
        for key, entry in sessions.items():
            results.append({
                "sessionKey": key,
                "agentId": agent_id,
                "sessionId": entry.session_id,
                "updatedAt": entry.updated_at,
                "compactionCount": entry.compaction_count,
            })
    return sorted(results, key=lambda x: x["updatedAt"], reverse=True)
```

---

## Runtime State Inventory

> Phase 0 is a wiring phase, not a rename/refactor. However, documenting what state gets CREATED matters for the planner.

| Category | Items Created | Action Required |
|----------|--------------|-----------------|
| Stored data | `~/.synapse/state/agents/<agent_id>/sessions/sessions.json` | Created on first message — no migration |
| Stored data | `~/.synapse/state/agents/<agent_id>/sessions/<uuid>.jsonl` | Created on first message — no migration |
| Stored data | Lock files: `sessions.json.lock`, `sessions.json.lock.meta` | Cleaned by `clean_stale_lock_files()` at startup |
| Live service config | None — no external service config changes | — |
| OS-registered state | None | — |
| Secrets/env vars | None — uses existing `session.dmScope` in synapse.json | — |
| Build artifacts | None | — |

**Pre-existing state concern:** If prior conversations happened without session persistence (they all did — history was always []), there are no transcripts to migrate. Fresh start is correct behavior.

---

## Environment Availability

| Dependency | Required By | Available | Fallback |
|------------|------------|-----------|----------|
| `filelock` | `session_store.py` | Already installed (used by session_store) | None — required |
| `asyncio` | All async patterns | Built-in Python 3.11 | — |
| `~/.synapse/` directory | SessionStore, transcript | Created by SynapseConfig at startup | Created automatically by `mkdir(parents=True)` |

**Missing dependencies:** None — all dependencies already present.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing in workspace/) |
| Config file | `workspace/pytest.ini` or inferred |
| Quick run command | `cd workspace && pytest tests/test_session_persistence.py -v` |
| Full suite command | `cd workspace && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SESS-P0-01 | History loads from transcript on message N | integration | `pytest tests/test_session_persistence.py::test_history_loads -v` | No — Wave 0 |
| SESS-P0-02 | Server restart preserves transcript | integration | `pytest tests/test_session_persistence.py::test_restart_persistence -v` | No — Wave 0 |
| SESS-P0-03 | Two senders get separate histories | unit | `pytest tests/test_session_persistence.py::test_session_isolation -v` | No — Wave 0 |
| SESS-P0-04 | Compaction triggers after 50 turns | unit | `pytest tests/test_session_persistence.py::test_compaction_trigger -v` | No — Wave 0 |
| SESS-P0-05 | GET /sessions returns sessions | integration | `pytest tests/test_session_persistence.py::test_get_sessions -v` | No — Wave 0 |
| SESS-P0-06 | POST /sessions/{key}/reset clears history | integration | `pytest tests/test_session_persistence.py::test_session_reset -v` | No — Wave 0 |

### Wave 0 Gaps

- [ ] `tests/test_session_persistence.py` — all 6 test cases above
- [ ] May need `tests/conftest.py` fixture for `tmp_path`-based `SYNAPSE_HOME` override (pattern already used in `tests/test_sessions.py`)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No — session wiring uses existing auth | Existing `_require_gateway_auth` |
| V3 Session Management | Yes — new persistent sessions | File locking + atomic writes (already in SessionStore) |
| V4 Access Control | No — no new access surfaces | — |
| V5 Input Validation | Partial — `chat_id` sanitized by `build_session_key` | `_sanitize()` in session_key.py |
| V6 Cryptography | No — sessions are not encrypted at rest | Out of scope for this phase |

### Known Threat Patterns for File-Based Session Store

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via malformed `chat_id` | Tampering | `_sanitize()` in `session_key.py` strips non-`[a-z0-9._-]` chars |
| Stale lock files blocking session writes | Denial of Service | `clean_stale_lock_files()` at startup + `SynapseFileLock` auto-reclaim |
| Corrupt JSON in sessions.json | Denial of Service | `_load_store_sync` catches `JSONDecodeError`, returns `{}` (start fresh) |
| Concurrent compaction + append race | Tampering | Compaction rewrites JSONL atomically via `os.replace()`; append uses `"a"` mode |

---

## Open Questions

1. **`_do_call()` is private — is that acceptable for the LLM adapter?**
   - What we know: `SynapseLLMRouter` has no public `acompletion()`. `_do_call()` is the method that returns the raw litellm response object that compaction needs.
   - What's unclear: Whether the team prefers adding a public method to `SynapseLLMRouter` (e.g., `acompletion(role, messages)`) vs the adapter using the private method.
   - Recommendation: Add a thin public method `acompletion(messages, role="casual")` to `SynapseLLMRouter` in the same commit. This is a 3-line change and avoids private method access.

2. **Should `POST /sessions/{key}/reset` exist for Phase 0?**
   - What we know: ROADMAP success criteria item 6 mentions it. It is not in current `routes/sessions.py`.
   - What's unclear: Whether to implement it in Phase 0 (Plan 00-03) or defer.
   - Recommendation: Implement in Plan 00-03 alongside the sessions endpoint rewrite. Requires `archive_transcript()` from `transcript.py` and deleting the session entry from the store.

3. **Should `SynapseConfig.load()` be called once per `process_message_pipeline` or cached?**
   - What we know: `_deps.py` already has `_synapse_cfg = SynapseConfig.load()` at line 249. It is NOT exported/accessible from `pipeline_helpers.py` directly (private underscore name).
   - Recommendation: Call `SynapseConfig.load()` once per pipeline call (it reads from disk, ~1ms). Or expose `deps._synapse_cfg` as a public attribute.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SynapseConfig.load()` is safe to call on every `process_message_pipeline` invocation (not too expensive) | Architecture Patterns | If expensive (disk read + parsing), add caching or use `deps._synapse_cfg` |
| A2 | `deps.synapse_llm_router._do_call("casual", messages)` returns an object with `.choices[0].message.content` | Pitfall 2 / Pattern 6 | If `_do_call` signature changes, adapter breaks |
| A3 | The existing `filelock` package is installed (used by session_store.py) | Environment | If absent, `pip install filelock` needed |

---

## Sources

### Primary (HIGH confidence — VERIFIED by reading source files this session)

- `workspace/sci_fi_dashboard/pipeline_helpers.py` — process_message_pipeline() current implementation (lines 203-216)
- `workspace/sci_fi_dashboard/_deps.py` — singleton patterns, existing exports (full file read)
- `workspace/sci_fi_dashboard/multiuser/session_store.py` — SessionStore API, SessionEntry dataclass (full file read)
- `workspace/sci_fi_dashboard/multiuser/transcript.py` — append_message, load_messages, transcript_path signatures (full file read)
- `workspace/sci_fi_dashboard/multiuser/compaction.py` — compact_session signature, llm_client contract doc, estimate_tokens (full file read)
- `workspace/sci_fi_dashboard/multiuser/session_key.py` — build_session_key signature and all dm_scope variants (full file read)
- `workspace/sci_fi_dashboard/multiuser/conversation_cache.py` — ConversationCache API: get/put/append/invalidate (full file read)
- `workspace/sci_fi_dashboard/multiuser/context_assembler.py` — full context assembly flow reference (full file read)
- `workspace/sci_fi_dashboard/routes/sessions.py` — current sessions endpoint (reads SQLite, not SessionStore) (full file read)
- `workspace/sci_fi_dashboard/gateway/worker.py` — MessageWorker process_fn call pattern, 3-arg limit (full file read)
- `workspace/sci_fi_dashboard/gateway/queue.py` — MessageTask fields: chat_id, channel_id, is_group, mcp_context (full file read)
- `workspace/sci_fi_dashboard/llm_router.py` — SynapseLLMRouter methods confirmed (grep + partial read — NO acompletion on public API)
- `workspace/synapse_config.py` — SynapseConfig: data_root, db_dir derivation formula (partial read)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all modules exist and APIs verified from source
- Architecture: HIGH — exact method signatures confirmed, integration path clear
- Pitfalls: HIGH — confirmed by reading actual source code, not assumptions
- Gotchas (data_root formula, acompletion absence): HIGH — VERIFIED by code inspection

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable codebase — no external dependencies)
