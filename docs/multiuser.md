# Multiuser Layer

Synapse was built single-user; this layer adds per-user keying without forking the data layer. It lives entirely under `workspace/sci_fi_dashboard/multiuser/` and produces a canonical `session_key` plus a per-key transcript, store entry, and bootstrap-prompt context. Downstream subsystems (memory engine, persona engine, LLM router) continue to operate on the single shared databases — only the keying namespace is per-user.

## Modules

| Module | Responsibility |
|--------|----------------|
| `session_key.py` | Pure stateless builder/parser for canonical session keys (`agent:<id>:<channel>:<peerKind>:<peerId>[:thread:<id>]`). Implements four `dmScope` shapes: `main`, `per-peer`, `per-channel-peer`, `per-account-channel-peer`. Also exposes `is_subagent_key`, `is_cron_key`, `get_subagent_depth`. |
| `identity_linker.py` | Single pure function `resolve_linked_peer_id()` — collapses raw peer IDs from different channels onto a canonical name using `session.identityLinks`. Returns `None` in `main` scope (no substitution). Supports legacy bare-string and list-of-strings link values. |
| `session_store.py` | Atomic per-agent JSON store at `~/.synapse/state/agents/<agent_id>/sessions/sessions.json`. Three-layer locking: `asyncio.Lock` (in-process) → `SynapseFileLock` (cross-process with stale-lock reclaim + watchdog) → `tempfile.mkstemp` + `os.replace` (atomic write). LRU cache (max 200 entries, 45 s TTL via `SYNAPSE_SESSION_CACHE_TTL_MS`). Holds `SessionEntry` records (`session_id`, `updated_at`, `compaction_count`, `memory_flush_*`). |
| `transcript.py` | JSONL transcript I/O with auto-repair. `transcript_path()`, async `append_message()`, async `load_messages()` (skips corrupt lines + applies limit), `limit_history_turns()` (walks backwards by user-turn count), async `archive_transcript()` (renames to `.deleted.<ms>`), and `repair_orphaned_tool_pairs()` / `repair_all_transcripts()` to drop tool_use / tool_result entries left dangling after a mid-exchange compaction split. |
| `conversation_cache.py` | LRU cache (default 100 entries, 60 s TTL) for parsed message lists. TTL slides forward on every `get()` hit so warm sessions stay warm. Single-threaded asyncio; no internal locking. Optional dependency of `assemble_context()`. |
| `memory_manager.py` | Workspace `.md` bootstrap I/O. Loads `BOOTSTRAP_FILES` (`SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `BOOTSTRAP.md`, `MEMORY.md`) for top-level keys and `MINIMAL_BOOTSTRAP_FILES` (first four) for sub-agent / cron keys. 2 MB per-file truncation, case-fallback for `MEMORY.md` / `memory.md`, silent skip on missing files. Also exposes `append_daily_note()` and exclusive-create `seed_workspace()`. |
| `context_assembler.py` | Orchestrates per-turn context assembly: `SessionStore` lookup (creates if absent) → resolve `dmHistoryLimit` from channel config → `load_messages()` (cache-aware via `ConversationCache`) → `load_bootstrap_files()` → `build_system_prompt()` → context-window headroom guard. Raises `ContextWindowTooSmallError` when remaining headroom falls below `CONTEXT_WINDOW_HARD_MIN_TOKENS` (16 000); logs a warning below `CONTEXT_WINDOW_WARN_TOKENS` (32 000). |
| `compaction.py` | Token-driven transcript compaction. When estimated tokens exceed 80 % of the model's window, summarises the first half, keeps the second half verbatim, and rewrites the JSONL atomically. Per-call timeout 120 s, aggregate timeout 300 s — on timeout returns `{"ok": False, "compacted": False, "reason": "timeout"}` rather than raising. Also handles memory-flush daily-note generation via `append_daily_note()`. |
| `tool_loop_detector.py` | Sliding-window detector (default size 50) for runaway tool-calling. Three signals: `generic_repeat` (same `(tool_name, args)` SHA-256 signature N times), `ping_pong` (4+ A-B-A-B alternations), and a global circuit breaker. Levels: `OK` → `WARNING` (10 identical calls — inject diagnostic) → `CRITICAL` (20 — caller aborts) → `ToolLoopError` raised at 30 total calls in window. |

## Request flow

At chat time the layer wires together as follows:

1. **`dmScope` resolution** — `synapse.json → session.dmScope` (default `"main"`) selects one of the four key shapes implemented in `session_key.py`.
2. **`build_session_key()`** — receives raw `(agent_id, channel, peer_id, peer_kind, account_id, dm_scope, main_key, identity_links, thread_id)`. Sanitises every input to `[a-z0-9._-]`.
3. **`identity_linker.resolve_linked_peer_id()`** — invoked inside `build_session_key()` for `direct` peers when `dm_scope != "main"`. Substitutes the canonical name from `session.identityLinks` so the same human across WhatsApp + Telegram resolves to one key.
4. **`context_assembler.assemble_context(session_key, agent_id, data_root, config, context_window_tokens, conversation_cache)`** — the per-turn entry point:
   - `SessionStore.get()` (LRU + disk) — fetches or creates the `SessionEntry`.
   - `transcript.transcript_path()` + `load_messages()` (cache-aware via `ConversationCache`) — loads recent JSONL turns, walks backwards by `dmHistoryLimit` user turns, auto-repairs orphaned tool pairs.
   - `memory_manager.load_bootstrap_files()` — reads workspace `.md` files (full set for top-level keys, minimal set for sub-agent / cron via `is_subagent_or_cron_key()`).
   - `build_system_prompt()` — assembles the system prompt with bootstrap content + agent identity + session key.
   - Headroom guard against `context_window_tokens` — raises `ContextWindowTooSmallError` or warns.
5. **`compaction.should_compact()` / `compact_session()`** — fired when token estimate crosses 80 % of the window. Rewrites the transcript and bumps `SessionEntry.compaction_count`.
6. **`tool_loop_detector.ToolLoopDetector`** — wraps tool-bearing flows (proactive / MCP-driven), independent of `persona_chat()` since persona chat does not expose tools to the LLM.

The output `{"system_prompt": str, "messages": list[dict]}` is what the LLM router consumes — every other Synapse subsystem (MemoryEngine, SBS, DualCognitionEngine) continues to read from the shared `~/.synapse/workspace/db/` databases regardless of the active session key.

## See also

- [ARCHITECTURE.md](../ARCHITECTURE.md) — full request flow including FloodGate, MemoryEngine, DualCognitionEngine, and LLM routing.
- [CLAUDE.md](../CLAUDE.md) — `session.dmScope` / `session.identityLinks` config reference and project-wide conventions.
