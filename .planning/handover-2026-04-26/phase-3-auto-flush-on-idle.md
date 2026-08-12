# Phase 3 — Auto-flush session on idle / message-count threshold

## TL;DR
Add an automatic trigger that calls `_handle_new_command` for any session whose JSONL has crossed an idle-time or message-count threshold, so users never have to type `/new` to ingest their conversations.

## Goal
After this phase: a fresh OSS install produces `documents` rows organically as the user chats, without requiring any manual command. The 22 KB / 56-message sessions documented in E1.6 cannot accumulate unflushed for hours. Manual `/new` continues to work unchanged for users who want explicit control.

## Severity & Effort
- **Severity:** P2 (functional gap — ingestion only fires on manual command, defeats the "passive memory companion" product premise)
- **Effort:** M (~4 hr — design 30 min, scanner 1 hr, trigger wiring 1 hr, config 30 min, tests 1 hr)
- **Blocks:** None directly, but blocks the "ingestion grows organically" sign-off criterion.
- **Blocked by:** Phase 2 (auto-firing a broken vector path would amplify silent failures across hundreds of sessions)

## Why this matters (with evidence)

Per **E1.6**, today's active session JSONL `cecb9c73-22bc-4cd9-9984-30c167032814.jsonl` is 22,432 bytes / 56 lines, containing live chat from 2026-04-26. None of it is in `documents`, `entity_links`, or `atomic_facts`. The user did not type `/new`, so `_ingest_session_background` never fired. This is the dominant pattern, not an outlier — per **E1.1** only 5 rows ever exist with `filename='session'`, and per **E1.5** the token-counter `sessions` table has 363 rows. That's a 70:1 ratio of conversations-that-happened to conversations-that-got-ingested.

The product premise of Synapse is "memory companion that remembers everything you say." The current behaviour is "memory companion that remembers everything you say *if you remember to type /new*." That's a leaky abstraction the user shouldn't have to maintain.

The mechanics for triggering ingestion already exist:
- `_handle_new_command` (`pipeline_helpers.py:293-348`) does archive + clear cache + rotate session ID + fire `_ingest_session_background`.
- Session metadata lives in `~/.synapse/state/agents/<agent_id>/sessions.json` with `updated_at` timestamps (`session_store.py:370`, `:380`, `:478`).
- JSONL files live at `~/.synapse/state/agents/<agent_id>/sessions/<session_id>.jsonl`.
- `gentle_worker.py` (`workspace/sci_fi_dashboard/gentle_worker.py:13-50`) already runs periodic maintenance and gates on power+CPU.

What's missing is a scanner: walk the sessions, decide which ones cross the threshold, fire `_handle_new_command` for them.

The ROADMAP §"Sign-off criteria" makes this explicit: "`memory.db` `documents` table grows organically as user chats — no manual `/new` required for ingestion to fire." This is the phase that ships that property.

## Open design questions (Codex MUST resolve before coding)

The brief says: "have Codex stop and ask." These four questions need user input before implementation:

1. **Trigger semantics** — idle-only, count-only, or OR-combined?
   - Recommendation: **OR-combined**. Fires whenever EITHER condition is true. Most robust against pathological cases (60-message dump in 30 sec; 3-message conversation that sits for 12 hours).
2. **Default thresholds**:
   - Idle: 30 min? 60 min? Sessions that genuinely die (laptop closes, user leaves) should flush within an hour. Conversations that pause briefly (user gets coffee) should NOT flush. Recommendation: **30 min idle**.
   - Count: 50 messages? 100? E1.6 shows 56 messages already feeling "long" by user perception; today's bulk WhatsApp imports were one-shot, so this is purely about live-chat behaviour. Recommendation: **50 messages** (so a typical work session flushes once before going stale).
3. **Where to host the scanner**:
   - Option A: extend `gentle_worker.py` — already has power+CPU gating, fits the "low-friction maintenance" pattern. But that gating is wrong for this use case: an idle laptop is exactly when we want to flush, but if it's on battery (`gentle_worker.py:40-41`), the worker skips. We'd need to bypass the gating for this specific task.
   - Option B: dedicated background task on the FastAPI lifespan startup (e.g. inside the `lifespan` context in `api_gateway.py`). Always runs whenever the gateway is up. Simpler model, no gating mismatch.
   - Recommendation: **Option B**. Auto-flush should be tied to gateway uptime, not to laptop power state. Gentle worker is for VACUUMs and graph pruning where battery cost matters; auto-flush is one short DB write per session and is essentially free.
4. **Backwards compat with manual `/new`**:
   - Recommendation: **keep both**. The auto-flush scanner respects an internal `last_auto_flush_at` timestamp it writes to the session entry. Manual `/new` always works and rotates the session immediately regardless of threshold state. The scanner only acts on sessions that have NOT been manually flushed in the past N seconds (deduplication).

These four answers determine the design. **Codex should write a 2-paragraph "Design Decisions" header to the PR description with the four resolved values before coding.** If the user (Upayan) disagrees, revise before implementing.

## Current state — what's there now

**The trigger today** — `workspace/sci_fi_dashboard/pipeline_helpers.py:293-348`:

```python
async def _handle_new_command(
    session_key: str,
    agent_id: str,
    data_root: "Path",
    session_store,
    hemisphere: str = "safe",
) -> str:
    ...
    # Fire-and-forget: full memory loop (vector + KG) in background
    if archived_path is not None:
        task = asyncio.create_task(
            _ingest_session_background(...)
        )
        _session_ingest_tasks.add(task)
        task.add_done_callback(_session_ingest_tasks.discard)
        ...
    return "Session archived! I'll remember everything. Starting fresh now."
```

It's exposed only as the `/new` slash-command at `pipeline_helpers.py:428`.

**Session metadata model** — `workspace/sci_fi_dashboard/multiuser/session_store.py:365-385`:

```python
@dataclass
class SessionEntry:
    session_id: str
    updated_at: float            # ← already tracks last activity
    session_file: str | None = None
    compaction_count: int = 0
    memory_flush_at: float | None = None
    memory_flush_compaction_count: int | None = None
```

`memory_flush_at` already exists — **reuse it** as the auto-flush dedup field instead of inventing a parallel one.

**Gentle worker structure** — `workspace/sci_fi_dashboard/gentle_worker.py:13-50`:

```python
def check_conditions(self):
    # 1. Check Power
    try:
        battery = psutil.sensors_battery()
        if battery is not None and not battery.power_plugged:
            return False, f"[BATTERY] On Battery ({battery.percent}%)"
    ...
    # 2. Check CPU Load
    cpu_load = psutil.cpu_percent(interval=1)
    if cpu_load > 20:
        return False, f"[FIRE] CPU Busy ({cpu_load}%)"
    return True, "[OK] System Idle & Plugged In"
```

The power-plugged gate is wrong for auto-flush — that's why Option B (lifespan task) is preferred.

**Existing config keys** — `synapse.json.example` lines 119-122:

```json
"session": {
  "dual_cognition_enabled": true,
  "dual_cognition_timeout": 5.0
}
```

The `session` block already exists; new keys go here.

**Session store API surface** — `session_store.SessionStore` exposes `get/update/delete/list` (referenced via `pipeline_helpers.py:308-321`). Listing all sessions across all agents requires walking `~/.synapse/state/agents/*/sessions.json` since the store is per-agent.

## Target state — what it should do after

1. A new `SessionAutoFlusher` class (`workspace/sci_fi_dashboard/auto_flush.py` — new file) runs in the FastAPI lifespan. Every `auto_flush_check_interval_seconds` (default 60) it:
   - walks `~/.synapse/state/agents/*/sessions.json` for every registered agent
   - for each entry, computes `idle_seconds = now - updated_at` and `message_count = count_lines(session_file_jsonl)`
   - if `(idle_seconds >= idle_threshold OR message_count >= count_threshold) AND last_auto_flush_at is older than dedupe_window`: fires `_handle_new_command(session_key, agent_id, data_root, session_store, hemisphere)`
   - records `memory_flush_at = now` after firing (via `session_store.update`)
2. The scanner is **safe to no-op** when there are no sessions, no agents, or the gateway is starting up. It catches its own exceptions and logs them rather than crashing the lifespan.
3. New `~/.synapse/synapse.json → session` keys:
   ```json
   "session": {
     "dual_cognition_enabled": true,
     "dual_cognition_timeout": 5.0,
     "auto_flush_enabled": true,
     "auto_flush_idle_seconds": 1800,
     "auto_flush_message_count": 50,
     "auto_flush_check_interval_seconds": 60,
     "auto_flush_min_messages": 5
   }
   ```
   `auto_flush_min_messages` is a floor — never auto-flush a session with fewer than 5 messages; too short to be useful and creates `documents` clutter.
4. A new metric in Phase 1's `/memory_health`: `last_auto_flush_at` and `auto_flushes_last_24h`.
5. Manual `/new` continues to work unchanged. After a manual `/new`, the auto-flush scanner skips that session for the dedup window.
6. `~/.synapse/synapse.json.example` documents the new keys.

## Tasks (ordered)

- [ ] **Task 3.0** — Resolve the four design questions in the "Open design questions" section above. Document the decisions in the PR description and update this phase doc with the chosen values before coding. **Stop and ask the user if any answer differs from the recommendation.**

- [ ] **Task 3.1** — Add config schema. Files: `workspace/synapse_config.py`. Either:
  - extend the existing `session` dict on `SynapseConfig` (`synapse_config.py:100`) with new accessor properties, OR
  - add a typed `SessionConfig` dataclass alongside `KGExtractionConfig` (`synapse_config.py:57-76`) for stronger typing.
  Recommendation: typed dataclass, matching the `KGExtractionConfig` precedent. Defaults: `auto_flush_enabled=True`, `auto_flush_idle_seconds=1800`, `auto_flush_message_count=50`, `auto_flush_check_interval_seconds=60`, `auto_flush_min_messages=5`. Read from `raw.get("session", {})` in `SynapseConfig.load()`.

- [ ] **Task 3.2** — Implement `SessionAutoFlusher`. Files: create `workspace/sci_fi_dashboard/auto_flush.py`. Class skeleton:
  ```python
  class SessionAutoFlusher:
      def __init__(self, *, data_root: Path, session_stores: dict[str, SessionStore],
                   handle_new_command, idle_threshold: float, count_threshold: int,
                   min_messages: int, check_interval: float):
          self._data_root = data_root
          self._stores = session_stores
          self._handle_new = handle_new_command
          self._idle = idle_threshold
          self._count = count_threshold
          self._min = min_messages
          self._interval = check_interval
          self._stop = asyncio.Event()
          self._task: asyncio.Task | None = None

      async def start(self) -> None: ...
      async def stop(self) -> None: ...
      async def _loop(self) -> None: ...
      async def _scan_once(self) -> int: ...  # returns count of sessions flushed
      async def _should_flush(self, agent_id: str, key: str, entry: SessionEntry) -> bool: ...
      async def _flush_one(self, agent_id: str, key: str, entry: SessionEntry) -> None: ...
  ```
  - `_scan_once` enumerates `(agent_id, store)` pairs, calls `store.list()` (or equivalent), and per entry checks the threshold.
  - `_should_flush` reads `entry.updated_at` for idle, counts JSONL lines for messages, applies dedupe via `entry.memory_flush_at`.
  - `_flush_one` calls `await self._handle_new(session_key, agent_id, data_root, session_store, hemisphere="safe")`. Hemisphere defaults to `"safe"`; spicy sessions are explicit and the user controls those manually.
  - Counts JSONL lines via `sum(1 for _ in open(path, "r", encoding="utf-8"))` — cheap on 22 KB files.
  - Wraps the loop body in `try/except Exception as exc: log.error(...)` — no failure can kill the scanner.

- [ ] **Task 3.3** — Wire into the FastAPI lifespan. Files: `workspace/sci_fi_dashboard/api_gateway.py`. Find the `lifespan` async context manager (or equivalent startup hook). Add:
  ```python
  flusher = SessionAutoFlusher(
      data_root=cfg.data_root,
      session_stores=deps.session_stores,  # or however stores are exposed
      handle_new_command=pipeline_helpers._handle_new_command,
      idle_threshold=cfg.session_auto_flush.idle_seconds,
      count_threshold=cfg.session_auto_flush.message_count,
      min_messages=cfg.session_auto_flush.min_messages,
      check_interval=cfg.session_auto_flush.check_interval_seconds,
  )
  if cfg.session_auto_flush.enabled:
      await flusher.start()
  app.state.auto_flusher = flusher
  try:
      yield
  finally:
      await flusher.stop()
  ```
  Use `_deps.py` injection if that's the existing pattern.

- [ ] **Task 3.4** — Telemetry. Files: `workspace/sci_fi_dashboard/auto_flush.py` + `workspace/sci_fi_dashboard/routes/health.py`. After each successful `_flush_one`, write a row to Phase 1's `ingest_failures` table with `phase='auto_flush_triggered'`, `session_key`, `agent_id`, and `exception_*` NULL. Extend `/memory_health` with:
  - `last_auto_flush_at`
  - `auto_flushes_last_24h` — count of `phase='auto_flush_triggered'` rows in the past 24 hr
  - `auto_flush_enabled` — boolean from config

- [ ] **Task 3.5** — Update `synapse.json.example`. Files: `D:/Shorty/Synapse-OSS/synapse.json.example`. Add to the `session` block:
  ```json
  "session": {
    "dual_cognition_enabled": true,
    "dual_cognition_timeout": 5.0,
    "_auto_flush_comment": "Auto-flush idle/long sessions into memory.db without requiring manual /new. Disable with auto_flush_enabled=false.",
    "auto_flush_enabled": true,
    "auto_flush_idle_seconds": 1800,
    "auto_flush_message_count": 50,
    "auto_flush_check_interval_seconds": 60,
    "auto_flush_min_messages": 5
  }
  ```

- [ ] **Task 3.6** — Tests. Files: create `workspace/tests/test_auto_flush.py`. Test cases:
  1. `test_idle_threshold_triggers_flush` — fixture session with `updated_at = now - 3600`, 10 messages. Mock `_handle_new_command`. Assert it's called once after one `_scan_once()` cycle.
  2. `test_message_count_triggers_flush` — `updated_at = now - 60`, 60 messages. Assert called once.
  3. `test_below_min_messages_skipped` — 3 messages, idle 1 hour. Assert NOT called.
  4. `test_dedup_window_skips_recent_flush` — `memory_flush_at = now - 30`, idle 1 hour. Assert NOT called.
  5. `test_disabled_via_config` — `auto_flush_enabled=False`. Scanner does not call `_handle_new_command` even when thresholds are met.
  6. `test_scanner_swallows_per_session_exception` — patch `_handle_new_command` for one session to raise; assert other sessions still get flushed.
  7. `test_manual_new_then_auto_skips` — fire `/new` manually, then run scanner. Scanner should observe `memory_flush_at` and skip.

  Per ROADMAP execution rule 7, mock `MemoryEngine.add_memory` in any test that exercises the chat-pipeline import surface. The auto-flush tests above only mock `_handle_new_command` (the entry point) so they shouldn't hit `add_memory` at all — but verify by adding a fake-session-store fixture that doesn't import `chat_pipeline`.

- [ ] **Task 3.7** — Integration smoke. Manual reproduction:
  ```bash
  # Send 50 messages quickly to bot, do NOT type /new
  # Wait 60-120 seconds (one scan cycle)
  # Verify documents grew
  before=$(sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*) FROM documents WHERE filename='session';")
  # ... send 50 messages via curl ...
  sleep 120
  after=$(sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*) FROM documents WHERE filename='session';")
  echo "before=$before after=$after"
  ```

- [ ] **Task 3.8** — CLAUDE.md update. Add a new "Configuration" subsection documenting the auto-flush keys and their defaults. Note that `gentle_worker_loop` is NOT the home for this task (intentional — battery-state should not gate ingestion).

## Dependencies
- **Hard:** Phase 2 (auto-firing a broken vector path would amplify silent failures across hundreds of sessions). Verify Phase 2's success criteria are all green before merging Phase 3.
- **Soft:** Phase 1 (the `/memory_health` extensions in Task 3.4 are nice but not required). If Phase 1 is not merged, ship Phase 3 without the new metrics and add them in a follow-up.
- **Provides:** the OSS sign-off property "documents grows organically without manual /new".

## Success criteria (must all be true before claiming done)
- [ ] Open design decisions documented in PR description with values matching either user input or recommendations from this doc.
- [ ] `SessionAutoFlusher` runs on gateway startup when `auto_flush_enabled=true`.
- [ ] Scanner does NOT run when `auto_flush_enabled=false` (verify by setting it false, restarting, and confirming no flushes after thresholds are crossed).
- [ ] All 7 unit tests pass.
- [ ] Integration smoke (Task 3.7) shows `documents` rows increase after a synthetic 50-message session without manual `/new`.
- [ ] Pre-existing `/new` smoke (Phase 2's Task 2.6) still passes — manual `/new` continues to flush immediately.
- [ ] No `MagicMock` strings in `documents.content` after the test suite (regression guard from E1.8).
- [ ] `synapse.json.example` updated; loading a fresh config picks up sane defaults.
- [ ] Scanner exception in one session does NOT block others (Task 3.6 test 6).
- [ ] CLAUDE.md updated with the new config keys.
- [ ] No regressions in `pytest tests/ -m unit` or `pytest tests/ -m integration`.

## Verification recipe (how Codex proves it works)

```bash
# 0. Branch from develop. Phase 2 must be merged.
git checkout develop
git pull
git checkout -b fix/phase-3-auto-flush-on-idle

# Sanity: confirm Phase 2 vector path is healthy
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT phase, COUNT(*) FROM ingest_failures
   WHERE created_at > datetime('now','-1 hour') GROUP BY phase;"
# expect: phase='completed' present, phase='vector' absent.

# 1. Resolve design questions (Task 3.0). Stop and confirm with user before continuing.

# 2. Run unit tests
cd workspace && pytest tests/test_auto_flush.py -v

# 3. Manual smoke: drive 50 messages without /new
pkill -f "uvicorn api_gateway" || true
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload &
sleep 5
before=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE filename='session';")
for i in $(seq 1 50); do
  curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"smoke test $i\"}" \
    http://127.0.0.1:8000/chat/the_creator > /dev/null
done
# Wait for the scanner cycle (default 60s) + the ingest task (BATCH_SLEEP_S × N batches)
sleep 180
after=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE filename='session';")
echo "after auto-flush: before=$before after=$after"
test "$after" -gt "$before" || echo "FAIL: auto-flush did not produce documents"

# 4. Telemetry sanity (if Phase 1 is merged)
curl -s -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  http://127.0.0.1:8000/memory_health | python -m json.tool | grep auto_flush

# 5. Disable check
# Edit ~/.synapse/synapse.json: session.auto_flush_enabled = false
# Restart gateway. Send 50 more messages. Confirm documents do NOT grow after 180s.

# 6. Manual /new still works (Phase 2 regression)
curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "/new"}' http://127.0.0.1:8000/chat/the_creator
sleep 15
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT MAX(created_at) FROM documents WHERE filename='session';"

# 7. Pollution regression
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%';"
# expected: 0

# 8. Lint
ruff check workspace/sci_fi_dashboard/auto_flush.py \
  workspace/synapse_config.py \
  workspace/sci_fi_dashboard/api_gateway.py \
  workspace/tests/test_auto_flush.py
black --check workspace/
```

## Risks & gotchas

- **Avoid double-flush via session_id rotation race.** `_handle_new_command` calls `session_store.delete(key)` then `session_store.update(key, {"compaction_count": 0})` — this rotates the session_id. The scanner must look up the entry fresh inside `_should_flush` (after acquiring the per-key lock if exposed), not act on a stale `entry` value. Reuse `session_store.get(key)` immediately before calling `_handle_new_command`.
- **Concurrency with chat traffic.** A user could be actively typing while the scanner decides to flush. The scanner reads `updated_at` from the persisted store, but a message arriving during the scan would update `updated_at` after the read. This is acceptable: the worst case is one extra flush of 1-2 messages, which is harmless. Do NOT introduce a chat-side mutex — that's worse than an occasional spurious flush.
- **Multi-account scope.** Per CLAUDE.md "Configuration → `synapse.json` → `session.dmScope`", session keys can be `"main"`, `"per-peer"`, `"per-channel-peer"`, or `"per-account-channel-peer"`. The scanner enumerates all keys it finds; no special handling needed beyond the store list. Verify on a multi-channel install.
- **Hemisphere defaults.** Auto-flush always uses `hemisphere="safe"`. Spicy sessions are explicit and the user controls them with `/new` directly. Do NOT try to infer hemisphere from session metadata — too risky.
- **JSONL line counting.** A 56-line file is cheap (`open + sum 1 for _`) but on a multi-account install with 50 active sessions × 1000 lines each, scanning every 60s is 50 × file open + read. Still trivial (<10ms total) but document the scaling note in CLAUDE.md.
- **Scanner exception isolation.** If a single session raises (e.g. corrupt JSONL), the scanner must log and continue — not abort the entire scan. Wrap `_flush_one` with `try/except Exception as exc: log.error(...)`.
- **Tests must not pollute prod DB.** Test suite per E6.1 — `pipeline_memory_engine` fixture mocks `add_memory`. Auto-flush tests should mock at the `_handle_new_command` level so they don't reach `add_memory` at all. If the test does instantiate a real `MemoryEngine`, apply the canonical mock from `conftest.py:296-300`.
- **Gentle worker overlap.** `gentle_worker_loop` runs VACUUM every 30 min and graph pruning every 10 min. Auto-flush + VACUUM on the same DB are both write workloads. SQLite WAL handles this, but be aware: a long auto-flush during a VACUUM may block briefly. Acceptable.
- **Empty sessions.** Sessions with 0 messages or only system messages should not flush. Use `auto_flush_min_messages` (default 5) as the floor.

## Out of scope (DO NOT do these in this phase)

- Backfilling the ~30-50 lost historical sessions. Separate decision.
- Surfacing auto-flush events to the user (e.g. "I just saved your last session"). Could be future, not now.
- Per-channel auto-flush rules (e.g. flush WhatsApp every 30 min, Telegram every 60 min). Single global rule for now; per-channel can come later if needed.
- Replacing `gentle_worker_loop` or moving its tasks. The gentle worker stays exactly as-is; auto-flush is independent.
- Optimizing JSONL line counting via cached counts in `SessionEntry`. Not needed at current scale.

## Evidence references

- **E1.1** (documents composition) — only 5 `filename='session'` rows ever; product premise leaks without auto-flush.
- **E1.5** (sessions table token-only) — 363 token-counter rows but only 5 vector rows. The scanner closes that gap.
- **E1.6** (active session has 56 unflushed messages) — direct evidence the user accumulates content without flushing. Threshold of 50 messages would have caught this session.
- **E8** (code paths) — `pipeline_helpers.py:293-348` is the trigger point this phase reuses.

## Files touched (expected)

- `workspace/sci_fi_dashboard/auto_flush.py` — new file with `SessionAutoFlusher` (Task 3.2).
- `workspace/sci_fi_dashboard/api_gateway.py` — wire scanner into lifespan (Task 3.3).
- `workspace/synapse_config.py` — new `SessionAutoFlushConfig` dataclass (Task 3.1).
- `workspace/sci_fi_dashboard/routes/health.py` — extend `/memory_health` if Phase 1 merged (Task 3.4).
- `D:/Shorty/Synapse-OSS/synapse.json.example` — document new keys (Task 3.5).
- `workspace/tests/test_auto_flush.py` — new test file with 7 tests (Task 3.6).
- `CLAUDE.md` — document the auto-flush config keys (Task 3.8).
