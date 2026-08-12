# Phase 0: Session & Context Persistence - Context

**Gathered:** 2026-04-06 (auto mode — research-driven)
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the already-built `multiuser/` session infrastructure into the WhatsApp chat pipeline.
Every message must build on its conversation history rather than starting fresh with `history=[]`.
This phase is WIRING ONLY — it does not rebuild session storage, transcript format, or compaction.
Those modules are complete and correct.

New capabilities (session analytics UI, cross-channel session linking, manual compaction API)
are out of scope — they belong in future phases.

</domain>

<decisions>
## Implementation Decisions

### The Core Gap (confirmed by research)
- **D-01:** The gap is exactly one function: `process_message_pipeline()` in `pipeline_helpers.py` always passes `history=[]` to `ChatRequest`. Fix this function. Nothing else needs architectural changes.
- **D-02:** The `multiuser/` module (session_store, transcript, context_assembler, compaction, session_key, conversation_cache) is COMPLETE and CORRECT — do not refactor or replace it. Wire it in as-is.
- **D-03:** OpenClaw's session architecture (studied) is functionally identical to what Synapse already has. No new patterns needed.

### Session Key Strategy
- **D-04:** Use `build_session_key()` from `multiuser/session_key.py`. Inputs: `agent_id` from `deps._resolve_target(chat_id)`, `channel="whatsapp"`, `peer_id=chat_id`, `peer_kind="direct"` (group detection via `MessageTask.is_group`), `dm_scope` from `synapse.json → session.dmScope` (currently `"per-channel-peer"`).
- **D-05:** `agent_id` must be the resolved target string (e.g., `"the_creator"`), not the raw `chat_id`. This makes session keys human-readable and consistent.
- **D-06:** For group chats (`MessageTask.is_group = True`), use `peer_kind="group"` — each group gets its own session regardless of `dm_scope`.
- **D-07:** `account_id` and `main_key` can be hardcoded to `"whatsapp"` and `"whatsapp:dm"` respectively for now — multi-account WhatsApp is a future phase.

### ConversationCache Singleton
- **D-08:** Add a single `ConversationCache` instance to `_deps.py` as a module-level singleton (pattern: same as `entity_gate`, `brain`, `llm_router`). `max_entries=200, ttl_s=300` (5 minutes).
- **D-09:** The cache must NOT be instantiated per-request — that defeats the purpose. It is a singleton shared across all `process_message_pipeline()` calls.

### History Load + Append Flow
- **D-10:** Before calling `persona_chat()`, load history via `load_messages(transcript_path, limit=history_limit)`. The `history_limit` config key is `channels.whatsapp.dmHistoryLimit` in `synapse.json` — default to 50 turns if not set.
- **D-11:** After getting the reply, append TWO messages to transcript: `{"role": "user", "content": user_msg}` then `{"role": "assistant", "content": reply}`. Use `transcript.append_message()`.
- **D-12:** Transcript append is fire-and-forget via `asyncio.create_task()` — it must NOT block the reply from being sent. The reply is delivered first, transcript written async.
- **D-13:** Use `conversation_cache.append()` after the in-memory cache to keep it warm without a re-read.

### Compaction
- **D-14:** Check for compaction AFTER transcript append, not before. Use `estimate_tokens(messages)` from `compaction.py`. If estimated tokens > 60% of the model's context window, trigger `compact_session()` as a background task.
- **D-15:** Compaction is always a `asyncio.create_task()` — never awaited in the response path. The user's reply goes out first.
- **D-16:** For compaction, use `deps.llm_router` as the LLM client. The compaction module's `llm_client` contract requires `await llm_client.acompletion(messages=[...])` — verify the LLM router exposes this or wrap it.
- **D-17:** Default context window: 32,000 tokens (safe for all configured models). Future: read from `models_catalog.py` if available.

### SessionStore Location
- **D-18:** `data_root` = `SynapseConfig.load().db_dir.parent` (i.e., `~/.synapse/`). `agent_id` = resolved target (e.g., `"the_creator"`). Session files at: `~/.synapse/state/agents/the_creator/sessions/`.
- **D-19:** `SessionStore` is instantiated once in `process_message_pipeline()` per call (it's lightweight — no I/O in `__init__`). No need to add it to `_deps.py` as a singleton.

### Sessions API
- **D-20:** `routes/sessions.py` already exists with session management endpoints. Verify these work with the new SessionStore + transcript files. If they reference a different session format, update them to use `multiuser/session_store.py`.
- **D-21:** `GET /sessions` should return sessions from the disk store (SessionStore.load()), not from an in-memory dict.

### OSS Safety (carry-forward from pre-work)
- **D-22:** `entities.json` ships as `{}`. EntityGate loads from `knowledge_graph.db` via `graph_store.get_all_node_names()`. This is already committed (e85382) — do not regress it.

### Claude's Discretion
- Exact error handling when transcript file is corrupt (skip and start fresh vs raise)
- Whether to log session_key on each message (useful for debugging)
- Startup cleanup of stale lock files (`clean_stale_lock_files()` — already exists, wire into app startup)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Session Infrastructure (read ALL before planning)
- `workspace/sci_fi_dashboard/multiuser/session_store.py` — SessionStore: atomic JSON, LRU cache, file locking. `update()`, `get()`, `load()`.
- `workspace/sci_fi_dashboard/multiuser/transcript.py` — `append_message()`, `load_messages()`, `transcript_path()`, `limit_history_turns()`, `archive_transcript()`, `repair_orphaned_tool_pairs()`
- `workspace/sci_fi_dashboard/multiuser/context_assembler.py` — `assemble_context()`: session lookup + transcript load + history_limit + system prompt. Shows the full flow.
- `workspace/sci_fi_dashboard/multiuser/compaction.py` — `compact_session()`, `estimate_tokens()`. LLM client contract at top of file.
- `workspace/sci_fi_dashboard/multiuser/session_key.py` — `build_session_key()`: all `dm_scope` variants documented inline.
- `workspace/sci_fi_dashboard/multiuser/conversation_cache.py` — `ConversationCache`: `get()`, `put()`, `append()`, `invalidate()`.

### Integration Points (read before modifying)
- `workspace/sci_fi_dashboard/pipeline_helpers.py` — `process_message_pipeline()` at line 203: the function to modify.
- `workspace/sci_fi_dashboard/_deps.py` — Where singletons live. Add `ConversationCache` here.
- `workspace/sci_fi_dashboard/schemas.py` — `ChatRequest`: `history: list = []` at line 8. No changes needed.
- `workspace/sci_fi_dashboard/gateway/worker.py` — `MessageTask.is_group` field used for peer_kind detection.
- `workspace/sci_fi_dashboard/routes/sessions.py` — Existing sessions API endpoints to verify/update.
- `workspace/sci_fi_dashboard/synapse_config.py` — `SynapseConfig`: `db_dir` for data_root derivation.

### Tests
- `workspace/tests/` — Existing test suite. New tests in `tests/test_session_persistence.py`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `multiuser/session_store.py:SessionStore` — Drop-in. Just instantiate with `agent_id` and `data_root`.
- `multiuser/transcript.py:append_message()` — Async. Takes `Path` and `dict`. One call per message.
- `multiuser/transcript.py:load_messages()` — Async. Takes `Path` and optional `limit`. Returns `list[dict]`.
- `multiuser/transcript.py:transcript_path()` — Pure function. `SessionEntry + data_root + agent_id → Path`.
- `multiuser/conversation_cache.py:ConversationCache` — Thread-safe for single-threaded asyncio. Already handles TTL, LRU eviction.
- `multiuser/session_key.py:build_session_key()` — Pure function. All string inputs, returns string key.
- `multiuser/compaction.py:estimate_tokens()` — Pure function. `list[dict] → int`.
- `multiuser/compaction.py:compact_session()` — Async. 5-min aggregate timeout built in.

### Established Patterns
- Singletons in `_deps.py`: module-level `entity_gate`, `brain`, `llm_router` — `ConversationCache` follows the same pattern.
- `asyncio.create_task()` for fire-and-forget: already used for `AutoContinue` in `pipeline_helpers.py` line ~155.
- `deps._resolve_target(chat_id)` — Already normalizes chat_id to the canonical target string.
- `synapse_config.SynapseConfig.load().db_dir` — Standard way to get the data directory.

### Integration Points
- `process_message_pipeline(user_msg, chat_id, mcp_context)` at `pipeline_helpers.py:203` — Add session logic before and after `persona_chat()` call.
- `_deps.conversation_cache` — New singleton to add.
- `gateway/worker.py:MessageTask` — `chat_id`, `channel_id`, `is_group` fields needed for session key.
- `on_batch_ready()` in `pipeline_helpers.py:219` — Already builds a `session_key` string (different format). May need to unify or pass through.

</code_context>

<specifics>
## Specific Ideas

- "Check how openclaw handles this and then implement the same" — Done. OpenClaw's session architecture (sessions.json + JSONL transcripts + context assembly + compaction) is functionally identical to Synapse's multiuser/ module. The implementation IS the pattern.
- Session keys should be human-readable for debugging: `agent:the_creator:whatsapp:dm:+91xxxxx`
- Transcript files at: `~/.synapse/state/agents/the_creator/sessions/{uuid}.jsonl`
- The compaction runs fully async — user never waits for it
- DM scope is already `"per-channel-peer"` in `synapse.json` — each WhatsApp sender gets their own history

</specifics>

<deferred>
## Deferred Ideas

- Cross-channel session linking (same user on WhatsApp + Telegram shares history) — Phase 3 or later
- Session analytics dashboard (turn counts, token usage per session) — future phase
- Manual compaction API (`POST /sessions/{key}/compact`) — Phase 1 or later
- Session tagging / labeling — future phase
- Per-session model override (this session uses a different LLM) — future phase
- Group chat history (currently groups will have sessions, but persona_chat context may need tuning) — monitor and address if needed

</deferred>

---

*Phase: 00-session-context-persistence*
*Context gathered: 2026-04-06*
