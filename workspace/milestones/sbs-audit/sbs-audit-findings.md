# SBS Architecture Audit — Findings

> Audited: 2026-04-01 | Scope: All files in `workspace/sci_fi_dashboard/sbs/` + gateway integration

## Executive Summary

**Will SBS auto-start?** YES — it initializes at module load and processes every message.

**Will it work correctly?** NO — 7 critical bugs cause data corruption, data loss, and broken wiring. The core architecture is sound, but the plumbing has holes.

**Test coverage?** ZERO — no SBS-specific tests exist.

---

## How SBS Currently Works (When It Works)

```
Gateway Boot
  │
  ├─ api_gateway.py:300-303 — sbs_registry created (one SBSOrchestrator per persona)
  ├─ Each SBSOrchestrator.__init__() runs:
  │   ├─ ProfileManager → creates/loads 8 JSON profile layers
  │   ├─ ConversationLogger → dual-write JSONL + SQLite
  │   ├─ RealtimeProcessor → sentiment, mood, language detection
  │   ├─ BatchProcessor → deep analysis (vocabulary, style, domains)
  │   ├─ ImplicitFeedbackDetector → correction pattern matching
  │   ├─ PromptCompiler → profile → system prompt segment
  │   └─ _check_startup_batch() → spawns batch thread if >6h since last run
  │
  ▼
Every Message (persona_chat)
  │
  ├─ api_gateway.py:668 — sbs_orchestrator.on_message("user", msg)
  │   ├─ Creates RawMessage with metadata
  │   ├─ ConversationLogger.log() → writes JSONL + SQLite
  │   ├─ RealtimeProcessor.process() → sentiment, mood, language
  │   ├─ Hot-updates emotional_state profile layer
  │   ├─ Increments _unbatched_count
  │   └─ If count >= 50 → spawns batch thread
  │
  ├─ api_gateway.py:673 — sbs_orchestrator.get_system_prompt()
  │   └─ PromptCompiler.compile() → 8 profile layers → ~1500 token prompt segment
  │
  ├─ LLM call with SBS-injected system prompt
  │
  └─ api_gateway.py:775 — sbs_orchestrator.on_message("assistant", reply)
      └─ Same pipeline as user message
```

---

## CRITICAL BUGS (7)

### C1: JSONL Newline Bug — Data Corruption

**File:** `sbs/ingestion/logger.py:69`
**Severity:** CRITICAL — corrupts entire message archive

```python
# CURRENT (BROKEN):
f.write(message.model_dump_json() + "\\n")   # writes literal backslash-n

# CORRECT:
f.write(message.model_dump_json() + "\n")    # writes actual newline
```

**Impact:** JSONL file becomes a single line of concatenated JSON with literal `\n` strings between them. Every JSONL parser will fail. BatchProcessor's `_fetch_all_user_messages()` queries SQLite instead, so batch processing still works — but the JSONL archive (the "persistent log") is useless for recovery or migration.

---

### C2: SBS_DATA_DIR Hardcoded to Source Tree

**File:** `api_gateway.py:261`
**Severity:** CRITICAL — data stored in wrong location

```python
# CURRENT (BROKEN):
SBS_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synapse_data")
# Points to: D:\Shreya\Synapse-OSS\workspace\sci_fi_dashboard\synapse_data\

# CORRECT:
_synapse_cfg = SynapseConfig.load()
SBS_DATA_DIR = str(_synapse_cfg.sbs_dir)
# Points to: ~/.synapse/workspace/sci_fi_dashboard/synapse_data/
```

**Impact:**
- Profile data lives inside the source tree instead of user data directory
- `git clean` or uninstall deletes all persona data
- Multiple users on same machine share profiles (security issue)
- `synapse_config.py:69` defines `sbs_dir` but it's never used

---

### C3: SQLite Missing Commits

**File:** `sbs/ingestion/logger.py:33` and `:96`
**Severity:** CRITICAL — data loss on Windows

```python
# _init_db() — line 33:
def _init_db(self):
    with sqlite3.connect(self.db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages ...""")
        conn.execute("""CREATE INDEX IF NOT EXISTS ...""")
        # MISSING: conn.commit()

# log() — line 96:
with sqlite3.connect(self.db_path) as conn:
    conn.execute("INSERT OR REPLACE INTO messages ...", (...))
    # MISSING: conn.commit()
```

**Note:** Python's `sqlite3` context manager (`with`) does auto-commit on `__exit__` if no exception occurred. So this may work in practice. However, relying on implicit behavior is fragile — explicit commits are safer, especially on Windows where SQLite locking is stricter.

---

### C4: Realtime Results Never Persisted to SQLite

**File:** `sbs/orchestrator.py:81-84`
**Severity:** CRITICAL — data inconsistency

```python
# CURRENT: RealtimeProcessor computes results but they're not written to SQLite
rt_results = self.realtime.process(message)
# rt_results = {rt_sentiment: 0.3, rt_language: "banglish", rt_mood_signal: "focused"}

# ConversationLogger HAS the method:
# logger.update_realtime_fields(msg_id, sentiment, language, mood)
# But it's NEVER CALLED.

# The RawMessage is logged BEFORE realtime processing:
self.logger.log(message)          # line 87 — rt_* fields are still None
rt_results = self.realtime.process(message)  # line 81 — computed AFTER logging
```

**Impact:** The `messages` SQLite table always has `NULL` for `rt_sentiment`, `rt_language`, `rt_mood_signal`. BatchProcessor queries this table — it sees no sentiment data. The emotional_state profile layer IS updated (via hot-update in RealtimeProcessor), but the per-message record in SQLite is blank.

**Fix requires two changes:**
1. Move realtime processing BEFORE logging, or
2. Call `update_realtime_fields()` after realtime processing

---

### C5: Sentinel Manifest Paths Don't Match SBS Data Paths

**File:** `sbs/sentinel/manifest.py:83-92`
**Severity:** CRITICAL — protection breaks when C2 is fixed

```python
# Sentinel writable zones are relative to project_root (source tree):
WRITABLE_ZONES = {
    "data/raw/",
    "data/indices/",
    "data/profiles/current/",
    "data/temp/",
    "data/exports/",
    "generated/",
    "logs/",
}
```

When SBS_DATA_DIR is corrected to `~/.synapse/...` (fixing C2), these relative paths no longer match. Sentinel will DENY writes to the actual profile directory.

**Fix:** Either make Sentinel aware of the user data root, or add absolute writable zone entries for `~/.synapse/`.

---

### C6: ImplicitFeedbackDetector Wired But Not Connected

**File:** `sbs/orchestrator.py:27-29` (instantiated) vs `sbs/orchestrator.py:92-100` (called)
**Severity:** CRITICAL — partially wired

**Clarification from audit:** Agent 1 found the detector IS instantiated and IS called in `on_message()` (lines 92-100) for user messages. However, Agent 2 found it's not wired into the RealtimeProcessor pipeline — it runs separately.

**Actual issue:** The `apply_feedback()` method modifies profile layers directly but:
- `praise` and `rejection` categories are stubs (`pass` — no action taken)
- No versioning or rollback if feedback is wrong
- Applied immediately without batch confirmation

**Revised severity:** MAJOR (not critical — it does run, but incompletely)

---

### C7: Zero Test Coverage

**Severity:** CRITICAL — no safety net for any of the above bugs

```bash
# Search results for SBS tests:
find workspace/tests -name "*sbs*" -o -name "*orchestrator*" -o -name "*batch*" -o -name "*realtime*"
# Returns: NOTHING
```

No tests for:
- SBSOrchestrator initialization or message processing
- RealtimeProcessor sentiment/mood detection
- BatchProcessor profile generation
- ConversationLogger dual-write
- PromptCompiler output format
- ImplicitFeedbackDetector pattern matching
- ProfileManager layer CRUD

---

## MAJOR BUGS (6)

### M1: Batch Processing in Unsupervised Thread

**File:** `sbs/orchestrator.py:112-114`

```python
import threading
threading.Thread(target=self.batch.run).start()  # fire and forget
```

- No exception handling — batch errors are completely silent
- No integration with asyncio event loop (gateway is async)
- No thread tracking — can't cancel on shutdown
- Race condition: batch writes to profile while realtime also writes

---

### M2: No SBS Configuration in synapse.json

All SBS parameters are hardcoded:

| Parameter | Hardcoded Value | Location |
|-----------|----------------|----------|
| Batch threshold | 50 messages | orchestrator.py:34 |
| Startup batch window | 6 hours | orchestrator.py:42 |
| Max profile versions | 30 | manager.py:156 |
| Vocabulary decay | 0.5 weight | batch.py:178 |
| Prompt token budget | 6000 chars (~1500 tokens) | compiler.py:15 |
| Exemplar pairs | 14 max | compiler.py:89 |

Users cannot customize SBS behavior without editing source code.

---

### M3: No Graceful SBS Shutdown

**File:** `api_gateway.py:1052` (lifespan shutdown)

The gateway lifespan shuts down channels and workers, but:
- Batch threads are not tracked or cancelled
- In-flight profile writes may be interrupted
- No profile snapshot on shutdown (could lose last batch)

---

### M4: Message Metadata Not Computed

**File:** `sbs/ingestion/schema.py`

`RawMessage` schema defines `char_count`, `word_count`, `has_emoji`, `is_question` — but these default to `0`/`False` and are never computed at ingestion time. The orchestrator's `on_message()` only sets `char_count` and `word_count` (lines 71-72), but NOT `has_emoji` or `is_question`.

---

### M5: Realtime Processing Order Bug

**File:** `sbs/orchestrator.py:81-87`

```python
# CURRENT ORDER:
self.logger.log(message)              # Step 1: Log with rt_* = None
rt_results = self.realtime.process(message)  # Step 2: Compute rt_*
# rt_results are returned but never written back to the log
```

Should be:
```python
rt_results = self.realtime.process(message)  # Step 1: Compute
message.rt_sentiment = rt_results["rt_sentiment"]  # Step 2: Update message
message.rt_language = rt_results["rt_language"]
message.rt_mood_signal = rt_results["rt_mood_signal"]
self.logger.log(message)              # Step 3: Log with values
```

---

### M6: Praise/Rejection Feedback Not Implemented

**File:** `sbs/feedback/implicit.py:135-143`

```python
elif signal_type == "praise":
    pass  # TODO: reinforce current behavior

elif signal_type == "rejection":
    pass  # TODO: trigger rollback?
```

Detection works, but action is a no-op. User says "perfect, exactly like that" — nothing happens.

---

## MINOR ISSUES (4)

### m1: Token Estimation Conservative
`compiler.py:15` uses 4 chars/token. Actual tokenization is ~3.5 chars/token for English, ~2.5 for Banglish. May waste 10-20% of prompt budget.

### m2: Limited Language Patterns
`feedback/language_patterns.yaml` only has English patterns. Comments suggest adding Banglish but none present.

### m3: Exemplar Format Fragile
`compiler.py` assumes exemplars dict has `{"pairs": [...]}` with exact structure. No schema validation — malformed exemplar JSON silently breaks prompt compilation.

### m4: RealtimeProcessor Recomputes Metrics
`realtime.py:100` does `words = text.split()` instead of using `message.word_count`. Redundant computation.

---

## WHAT WORKS WELL

| Component | Status | Notes |
|-----------|--------|-------|
| ProfileManager | Solid | All 8 layers, versioning, archive, rollback |
| PromptCompiler | Solid | Priority-based compilation, token budget, trimming |
| BatchProcessor.run() | Solid | 6-stage analysis, vocabulary decay, exemplar selection |
| RealtimeProcessor | Solid | Sentiment lexicon, mood detection, language classification |
| ImplicitFeedbackDetector | Partial | Detection works, application partial (praise/rejection stubs) |
| Sentinel Protection | Solid | core_identity immutable, CRITICAL files locked |
| Module initialization order | Safe | No circular imports, lazy imports prevent cycles |

---

## Architecture Assessment

**The SBS architecture is well-designed.** The separation of concerns (ingestion → realtime → batch → compilation → injection) is clean. The 8-layer profile system is elegant. The PromptCompiler's priority-based trimming is production-quality.

**The bugs are all in the plumbing, not the architecture.** Every issue is a wiring problem: wrong newline char, wrong directory, missing function call, missing commit. The core logic in each component is correct.

**Estimated fix effort:** 1-2 sessions to fix all critical + major bugs. Most are 1-5 line changes.
