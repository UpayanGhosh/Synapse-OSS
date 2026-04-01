# SBS Architecture Audit — Fixes

> Priority-ordered fixes for all issues found in the SBS audit.
> Each fix includes: what to change, where, and the exact code diff.

---

## Priority 1: Data Corruption Fixes (Do First)

### Fix C1: JSONL Newline Bug

**File:** `workspace/sci_fi_dashboard/sbs/ingestion/logger.py`
**Line:** 69

```python
# BEFORE:
f.write(message.model_dump_json() + "\\n")

# AFTER:
f.write(message.model_dump_json() + "\n")
```

**Effort:** 1 line. **Risk:** None.

---

### Fix C3: SQLite Explicit Commits

**File:** `workspace/sci_fi_dashboard/sbs/ingestion/logger.py`
**Lines:** 33 and 96

```python
# Fix _init_db() — add commit after schema creation:
def _init_db(self):
    with sqlite3.connect(self.db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages ...""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_timestamp ...""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_session ...""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_role ...""")
        conn.commit()  # ADD THIS

# Fix log() — add commit after insert:
with sqlite3.connect(self.db_path) as conn:
    conn.execute("INSERT OR REPLACE INTO messages ...", (...))
    conn.commit()  # ADD THIS
```

**Effort:** 2 lines. **Risk:** None.

---

## Priority 2: Data Path Fix (Do Second)

### Fix C2: SBS_DATA_DIR Should Use SynapseConfig

**File:** `workspace/sci_fi_dashboard/api_gateway.py`
**Line:** 261

```python
# BEFORE:
SBS_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synapse_data")

# AFTER:
from synapse_config import SynapseConfig as _SynCfg
_sbs_cfg = _SynCfg.load()
SBS_DATA_DIR = str(_sbs_cfg.sbs_dir)
```

**Then update `sbs_registry` creation (line 300-303) if needed** — it already uses `SBS_DATA_DIR`, so just fixing the variable is enough.

**Effort:** 3 lines. **Risk:** Medium — need to ensure `sbs_dir` in SynapseConfig points to the right place and that the directory structure is created.

**Verify:** Check `workspace/synapse_config.py` to confirm `sbs_dir` is correctly defined. It should be:
```python
sbs_dir = data_root / "sbs"  # or similar
```

---

### Fix C5: Sentinel Manifest for User Data Directory

**File:** `workspace/sci_fi_dashboard/sbs/sentinel/manifest.py`
**Lines:** 83-92

This fix depends on C2. Once SBS data moves to `~/.synapse/`, Sentinel's writable zones need to include that path.

**Option A (recommended): Make Sentinel accept absolute paths in writable zones**

```python
# In manifest.py, add:
import os
USER_DATA_WRITABLE = {
    os.path.expanduser("~/.synapse/sbs/"),
}

# In gateway.py Sentinel initialization, pass additional writable zones
```

**Option B: Skip Sentinel for SBS data directory**

Since SBS data is outside the project root, Sentinel (which is project-scoped) doesn't need to govern it. The ProfileManager already has its own guards (core_identity immutability). This may be the simpler approach.

**Effort:** 5-10 lines. **Risk:** Low if using Option B.

---

## Priority 3: Wiring Fixes (Do Third)

### Fix C4 + M5: Realtime Results Persisted to SQLite

**File:** `workspace/sci_fi_dashboard/sbs/orchestrator.py`
**Lines:** 81-87

```python
# BEFORE (broken order + missing persistence):
self.logger.log(message)
rt_results = self.realtime.process(message)

# AFTER (correct order + persistence):
rt_results = self.realtime.process(message)
message.rt_sentiment = rt_results.get("rt_sentiment")
message.rt_language = rt_results.get("rt_language")
message.rt_mood_signal = rt_results.get("rt_mood_signal")
self.logger.log(message)
```

**This fixes two issues at once:**
- C4: Realtime results are now IN the message when logged → SQLite has values
- M5: Processing happens before logging → correct order

**Effort:** 5 lines (reorder + 3 assignments). **Risk:** Low.

---

### Fix M4: Compute Missing Message Metadata

**File:** `workspace/sci_fi_dashboard/sbs/orchestrator.py`
**In `on_message()`, after creating RawMessage (lines 65-78):**

```python
# ADD after RawMessage creation:
import re

message.has_emoji = bool(re.search(
    r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF]',
    content
))
message.is_question = content.rstrip().endswith("?")
```

**Effort:** 4 lines. **Risk:** None.

---

## Priority 4: Reliability Fixes (Do Fourth)

### Fix M1: Batch Processing with Error Handling

**File:** `workspace/sci_fi_dashboard/sbs/orchestrator.py`
**Lines:** 112-114 (message threshold trigger) and 53 (startup trigger)

```python
# BEFORE:
threading.Thread(target=self.batch.run).start()

# AFTER — Option A (minimal fix, keep threading):
def _run_batch_safe(self):
    try:
        self.batch.run()
    except Exception as e:
        import logging
        logging.getLogger("sbs").error(f"Batch processing failed: {e}", exc_info=True)

# Replace both Thread calls:
threading.Thread(target=self._run_batch_safe, daemon=True).start()

# AFTER — Option B (better, use asyncio):
async def _run_batch_async(self):
    try:
        await asyncio.to_thread(self.batch.run)
    except Exception as e:
        logger.error(f"Batch processing failed: {e}", exc_info=True)

# In on_message (which is called from async persona_chat):
asyncio.create_task(self._run_batch_async())
```

**Option A effort:** 5 lines. **Option B effort:** 8 lines.
**Recommendation:** Option A for now — Option B requires making `on_message()` async.

---

### Fix M3: Graceful SBS Shutdown

**File:** `workspace/sci_fi_dashboard/api_gateway.py`
**In lifespan shutdown (line ~1052):**

```python
# ADD to shutdown sequence:
for persona_id, sbs in sbs_registry.items():
    try:
        sbs.profile_manager.snapshot_version(f"shutdown_{datetime.now().isoformat()}")
    except Exception as e:
        print(f"[SBS] Shutdown snapshot failed for {persona_id}: {e}")
```

**Effort:** 5 lines. **Risk:** None — best-effort snapshot.

---

## Priority 5: Feature Completion (Do Last)

### Fix M6: Implement Praise/Rejection Feedback

**File:** `workspace/sci_fi_dashboard/sbs/feedback/implicit.py`
**Lines:** 135-143

```python
# BEFORE:
elif signal_type == "praise":
    pass

elif signal_type == "rejection":
    pass

# AFTER:
elif signal_type == "praise":
    # Reinforce current linguistic settings by narrowing variance
    linguistic = self.profile_manager.load_layer("linguistic")
    style = linguistic.get("current_style", {})
    # Mark current ratios as "confirmed good" — reduce drift on next batch
    style["confirmed_at"] = datetime.utcnow().isoformat()
    style["praise_count"] = style.get("praise_count", 0) + 1
    self.profile_manager.save_layer("linguistic", linguistic)

elif signal_type == "rejection":
    # Flag that current style needs review on next batch
    meta = self.profile_manager.load_layer("meta")
    meta["rejection_pending"] = True
    meta["last_rejection"] = datetime.utcnow().isoformat()
    self.profile_manager.save_layer("meta", meta)
```

**Effort:** 12 lines. **Risk:** Low.

---

### Fix M2: Add SBS Config to synapse.json Schema

**File:** `workspace/synapse_config.py`
**Add SBS config parsing:**

```python
# In SynapseConfig.load(), add:
sbs_config = raw.get("sbs", {})

# Expose as:
@dataclass(frozen=True)
class SBSConfig:
    batch_threshold: int = 50           # messages before batch trigger
    batch_window_hours: int = 6         # hours before startup batch
    max_profile_versions: int = 30      # archive retention
    vocabulary_decay: float = 0.5       # weight decay threshold
    prompt_max_chars: int = 6000        # compiler budget
    exemplar_pairs: int = 14            # max few-shot pairs
```

**synapse.json example:**
```json
{
  "sbs": {
    "batch_threshold": 50,
    "batch_window_hours": 6,
    "max_profile_versions": 30
  }
}
```

**Then update hardcoded values in:**
- `orchestrator.py:34` → use `config.batch_threshold`
- `orchestrator.py:42` → use `config.batch_window_hours`
- `manager.py:156` → use `config.max_profile_versions`
- `compiler.py:15` → use `config.prompt_max_chars`

**Effort:** ~30 lines across 5 files. **Risk:** Low.

---

## Priority 6: Test Coverage

### Fix C7: Create SBS Test Suite

**File:** `workspace/tests/test_sbs.py` (CREATE)

Minimum test coverage needed:

```python
# Test categories:
class TestProfileManager:
    def test_create_default_layers(self): ...
    def test_load_save_layer(self): ...
    def test_core_identity_immutable(self): ...
    def test_snapshot_and_rollback(self): ...

class TestConversationLogger:
    def test_log_creates_jsonl_and_sqlite(self): ...
    def test_jsonl_has_proper_newlines(self): ...  # Regression for C1
    def test_update_realtime_fields(self): ...

class TestRealtimeProcessor:
    def test_sentiment_positive(self): ...
    def test_sentiment_negative(self): ...
    def test_language_detection_banglish(self): ...
    def test_mood_detection(self): ...

class TestBatchProcessor:
    def test_vocabulary_census(self): ...
    def test_linguistic_update(self): ...

class TestPromptCompiler:
    def test_compile_under_budget(self): ...
    def test_trimming_priority_order(self): ...

class TestSBSOrchestrator:
    def test_on_message_logs_and_processes(self): ...
    def test_batch_trigger_at_threshold(self): ...
    def test_get_system_prompt_returns_string(self): ...

class TestImplicitFeedback:
    def test_detect_formal_correction(self): ...
    def test_detect_casual_correction(self): ...
    def test_apply_feedback_modifies_profile(self): ...
```

**Effort:** ~200 lines. **Risk:** None — pure additions.

---

## Fix Summary

| # | Fix | File(s) | Lines Changed | Priority |
|---|-----|---------|---------------|----------|
| C1 | JSONL newline | logger.py | 1 | P1 |
| C3 | SQLite commits | logger.py | 2 | P1 |
| C2 | SBS_DATA_DIR | api_gateway.py | 3 | P2 |
| C5 | Sentinel paths | manifest.py | 5-10 | P2 |
| C4+M5 | Realtime persist + order | orchestrator.py | 5 | P3 |
| M4 | Message metadata | orchestrator.py | 4 | P3 |
| M1 | Batch error handling | orchestrator.py | 5 | P4 |
| M3 | Graceful shutdown | api_gateway.py | 5 | P4 |
| M6 | Praise/rejection | implicit.py | 12 | P5 |
| M2 | SBS config | synapse_config.py + 4 files | 30 | P5 |
| C7 | Test suite | tests/test_sbs.py (new) | 200 | P6 |

**Total: ~270 lines of changes across 8 files.**
**Estimated effort: 1-2 focused sessions.**
