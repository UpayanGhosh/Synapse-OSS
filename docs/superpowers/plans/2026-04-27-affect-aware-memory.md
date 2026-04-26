# Affect-Aware Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add non-destructive affect-aware memory so Synapse retrieves memories by emotional context as well as semantic relevance.

**Architecture:** Create a focused `memory_affect` module that owns schema, deterministic affect extraction, upserts, scoring, and prompt formatting. Wire it into `MemoryEngine.add_memory()`, `MemoryEngine.query()`, chat prompt formatting, and dual cognition memory recall. Keep `atomic_facts` untouched.

**Tech Stack:** Python, SQLite, existing `MemoryEngine`, LanceDB candidate retrieval, pytest, PowerShell commands.

---

## File Structure

- Create: `workspace/sci_fi_dashboard/memory_affect.py`
  - Owns `AffectTags`, schema migration, heuristic extraction, DB upsert/load, affect match scoring, prompt hint formatting.
- Modify: `workspace/sci_fi_dashboard/db.py`
  - Calls `ensure_memory_affect_table()` during fresh DB creation and existing DB migration.
- Modify: `workspace/sci_fi_dashboard/memory_engine.py`
  - Writes affect rows on new memories.
  - Loads affect rows for retrieved candidate docs.
  - Adds affect score to ranking.
  - Returns `affect_hints`.
- Modify: `workspace/sci_fi_dashboard/chat_pipeline.py`
  - Appends affect hints under retrieved memory context.
- Modify: `workspace/sci_fi_dashboard/dual_cognition.py`
  - Adds `MemoryStream.affect_hints`.
  - Injects hints into merge prompt.
- Create: `workspace/scripts/personal/backfill_memory_affect.py`
  - Safe batch backfill with `--dry-run`, `--limit`, `--force`, `--since-id`.
- Create: `workspace/tests/test_memory_affect.py`
  - Unit tests for schema, extractor, scoring, prompt hints, dry-run helper.
- Modify: `workspace/tests/test_schema_migration.py`
  - Verify `memory_affect` migration.
- Modify: `workspace/tests/test_memory_engine.py`
  - Verify add_memory upsert and affect rerank.
- Modify: `workspace/tests/pipeline/test_phase4_dual_cognition.py`
  - Verify dual cognition accepts affect hints.

---

### Task 1: Create Affect Module

**Files:**
- Create: `workspace/sci_fi_dashboard/memory_affect.py`
- Test: `workspace/tests/test_memory_affect.py`

- [ ] **Step 1: Write failing tests for extraction, schema, scoring, prompt hints**

Add tests:

```python
import sqlite3

from sci_fi_dashboard.memory_affect import (
    AffectTags,
    extract_affect,
    ensure_memory_affect_table,
    format_affect_hints,
    score_affect_match,
    upsert_memory_affect,
)


def test_schema_created():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_affect)")}
    assert {"doc_id", "mood", "tension_type", "user_need", "response_style_hint"} <= cols


def test_extract_hurt_neglect():
    tags = extract_affect("I feel unseen and hurt because he forgot again")
    assert tags.sentiment == "negative"
    assert tags.mood == "hurt"
    assert tags.tension_type == "neglect"
    assert tags.user_need in {"validation", "reassurance"}
    assert tags.response_style_hint == "soft"
    assert tags.emotional_intensity > 0.4


def test_extract_pressure_grounding():
    tags = extract_affect("I am stuck and stressed about this work deadline")
    assert tags.mood in {"frustrated", "anxious"}
    assert tags.tension_type == "pressure"
    assert tags.user_need == "clarity"
    assert tags.response_style_hint == "grounding"


def test_upsert_and_format_hints():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)
    upsert_memory_affect(conn, 1, extract_affect("I feel ignored and lonely"))
    row = conn.execute("SELECT mood FROM memory_affect WHERE doc_id=1").fetchone()
    assert row[0] in {"hurt", "lonely"}
    hints = format_affect_hints([
        {"mood": row[0], "tension_type": "neglect", "user_need": "validation", "response_style_hint": "soft"}
    ])
    assert "respond softly" in hints.lower()


def test_affect_match_beats_neutral_only_when_query_emotional():
    query = AffectTags(mood="hurt", sentiment="negative", emotional_intensity=0.8, tension_type="neglect", user_need="validation", response_style_hint="soft", confidence=0.8)
    matching = AffectTags(mood="hurt", sentiment="negative", emotional_intensity=0.7, tension_type="neglect", user_need="validation", response_style_hint="soft", confidence=0.8)
    neutral = AffectTags()
    assert score_affect_match(query, matching) > score_affect_match(query, neutral)
    assert score_affect_match(AffectTags(), matching) == 0.0
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest workspace\tests\test_memory_affect.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-affect
```

Expected: FAIL because `sci_fi_dashboard.memory_affect` does not exist.

- [ ] **Step 3: Implement module**

Implementation shape:

```python
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field

EXTRACTOR_VERSION = "heuristic-v1"


@dataclass(frozen=True)
class AffectTags:
    sentiment: str = "neutral"
    mood: str = "neutral"
    emotional_intensity: float = 0.0
    tension_type: str = "none"
    user_need: str = "none"
    response_style_hint: str = "warm"
    topics: list[str] = field(default_factory=list)
    confidence: float = 0.0
    extractor_version: str = EXTRACTOR_VERSION
```

Required public functions:

```python
def ensure_memory_affect_table(conn: sqlite3.Connection) -> None: ...
def extract_affect(text: str) -> AffectTags: ...
def upsert_memory_affect(conn: sqlite3.Connection, doc_id: int, tags: AffectTags) -> None: ...
def load_affect_for_doc_ids(conn: sqlite3.Connection, doc_ids: list[int]) -> dict[int, AffectTags]: ...
def score_affect_match(query: AffectTags, memory: AffectTags) -> float: ...
def format_affect_hints(rows: list[dict], limit: int = 3) -> str: ...
```

Extraction must use stable keyword groups:

```python
MOOD_PATTERNS = {
    "hurt": [r"\bhurt\b", r"\bunseen\b", r"\bignored\b", r"\bforgot\b"],
    "anxious": [r"\banxious\b", r"\bworried\b", r"\bscared\b", r"\bpanic\b"],
    "frustrated": [r"\bstuck\b", r"\bfrustrated\b", r"\bstressed\b", r"\bdeadline\b"],
    "lonely": [r"\blonely\b", r"\balone\b", r"\bmissing\b"],
    "excited": [r"\blet'?s go\b", r"\bexcited\b", r"\bworks\b", r"!!+"],
    "proud": [r"\bproud\b", r"\bwon\b", r"\bfinished\b", r"\bshipped\b"],
    "playful": [r"\blol\b", r"\bhaha+\b", r"\btease\b"],
    "tired": [r"\btired\b", r"\bexhausted\b", r"\bsleepy\b"],
    "focused": [r"\bbuild\b", r"\bdebug\b", r"\bimplement\b", r"\barchitecture\b"],
    "vulnerable": [r"\bvulnerable\b", r"\bopened up\b", r"\bcry\b"],
}
```

Scoring rule:

```python
if query.emotional_intensity < 0.25 and query.confidence < 0.35:
    return 0.0
score = 0.0
if query.mood == memory.mood and query.mood != "neutral": score += 0.30
if query.tension_type == memory.tension_type and query.tension_type != "none": score += 0.30
if query.user_need == memory.user_need and query.user_need != "none": score += 0.25
if query.response_style_hint == memory.response_style_hint: score += 0.10
score += 0.05 * (1.0 - abs(query.emotional_intensity - memory.emotional_intensity))
return min(1.0, score * min(1.0, max(query.confidence, memory.confidence)))
```

- [ ] **Step 4: Run tests and verify pass**

Run same command. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add workspace\sci_fi_dashboard\memory_affect.py workspace\tests\test_memory_affect.py
git commit -m "feat: add memory affect extraction"
```

---

### Task 2: Add Schema Migration

**Files:**
- Modify: `workspace/sci_fi_dashboard/db.py`
- Modify: `workspace/tests/test_schema_migration.py`

- [ ] **Step 1: Write failing schema migration test**

Add import:

```python
from sci_fi_dashboard.db import _ensure_memory_affect_schema
```

Add test:

```python
def test_memory_affect_schema_created(self):
    conn = _make_fresh_db()
    _ensure_memory_affect_schema(conn)
    cols = _column_names(conn, "memory_affect")
    self.assertIn("doc_id", cols)
    self.assertIn("mood", cols)
    self.assertIn("tension_type", cols)
```

- [ ] **Step 2: Run test and verify fail**

Run:

```powershell
pytest workspace\tests\test_schema_migration.py::TestMigrationAddsColumns::test_memory_affect_schema_created -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-schema-affect
```

Expected: FAIL because `_ensure_memory_affect_schema` missing.

- [ ] **Step 3: Implement migration wrapper**

In `db.py`:

```python
def _ensure_memory_affect_schema(conn: sqlite3.Connection) -> None:
    from sci_fi_dashboard.memory_affect import ensure_memory_affect_table
    ensure_memory_affect_table(conn)
```

Call `_ensure_memory_affect_schema(conn)` in both fresh and existing DB paths after `_ensure_kg_processed_column`.

- [ ] **Step 4: Run schema tests**

Run:

```powershell
pytest workspace\tests\test_schema_migration.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-schema-affect
```

Expected: PASS or unrelated pre-existing failures documented.

- [ ] **Step 5: Commit**

```powershell
git add workspace\sci_fi_dashboard\db.py workspace\tests\test_schema_migration.py
git commit -m "feat: migrate memory affect schema"
```

---

### Task 3: Wire Write Path and Query Rerank

**Files:**
- Modify: `workspace/sci_fi_dashboard/memory_engine.py`
- Modify: `workspace/tests/test_memory_engine.py`

- [ ] **Step 1: Write failing add_memory test**

Patch `upsert_memory_affect` and assert called:

```python
with patch("sci_fi_dashboard.memory_engine.upsert_memory_affect") as mock_upsert:
    result = engine.add_memory("I feel unseen and hurt", "test_cat")
    mock_upsert.assert_called_once()
```

Expected result should match current implementation:

```python
assert result.get("status") == "stored"
assert result.get("id") == 42
```

- [ ] **Step 2: Write failing query rerank test**

Use mocked LanceDB candidates:

```python
engine.vector_store.search.return_value = [
    {"id": 1, "score": 0.70, "metadata": {"text": "old neutral work note", "unix_timestamp": time.time(), "importance": 5}},
    {"id": 2, "score": 0.65, "metadata": {"text": "felt ignored and hurt", "unix_timestamp": time.time(), "importance": 5}},
]
```

Patch `load_affect_for_doc_ids` to return neutral for 1 and hurt/neglect for 2. Query `"I feel ignored"` should rank doc 2 first.

- [ ] **Step 3: Run tests and verify fail**

Run:

```powershell
pytest workspace\tests\test_memory_engine.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-memory-affect
```

Expected: fail on new tests.

- [ ] **Step 4: Implement write path**

Import:

```python
from sci_fi_dashboard.memory_affect import (
    extract_affect,
    format_affect_hints,
    load_affect_for_doc_ids,
    score_affect_match,
    upsert_memory_affect,
)
```

After doc insert in `add_memory()`:

```python
try:
    upsert_memory_affect(conn, doc_id, extract_affect(content))
except Exception as affect_err:
    print(f"[WARN] memory_affect upsert failed for doc {doc_id}: {affect_err}")
```

- [ ] **Step 5: Implement query rerank**

After `q_results` is fetched:

```python
query_affect = extract_affect(text)
doc_ids = [int(r["id"]) for r in q_results if str(r.get("id", "")).isdigit()]
affect_by_doc = {}
try:
    conn = get_db_connection()
    affect_by_doc = load_affect_for_doc_ids(conn, doc_ids)
    conn.close()
except Exception as affect_err:
    print(f"[WARN] memory_affect load failed: {affect_err}")
```

For each candidate:

```python
affect = affect_by_doc.get(int(r["id"]))
affect_score = score_affect_match(query_affect, affect) if affect else 0.0
r["affect_score"] = affect_score
r["combined_score"] = (
    (r["score"] * 0.35)
    + (self._temporal_score(ts) * 0.20)
    + (importance / 10 * 0.20)
    + (affect_score * 0.25)
)
```

Add to return dicts:

```python
"affect": {
    "mood": affect.mood,
    "tension_type": affect.tension_type,
    "user_need": affect.user_need,
    "response_style_hint": affect.response_style_hint,
    "score": affect_score,
}
```

At response level:

```python
"affect_hints": format_affect_hints([...])
```

- [ ] **Step 6: Run tests**

Run:

```powershell
pytest workspace\tests\test_memory_engine.py workspace\tests\test_memory_affect.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-memory-affect
```

Expected: PASS or unrelated pre-existing failures documented.

- [ ] **Step 7: Commit**

```powershell
git add workspace\sci_fi_dashboard\memory_engine.py workspace\tests\test_memory_engine.py
git commit -m "feat: rerank memory by affect"
```

---

### Task 4: Prompt and Dual Cognition Integration

**Files:**
- Modify: `workspace/sci_fi_dashboard/chat_pipeline.py`
- Modify: `workspace/sci_fi_dashboard/dual_cognition.py`
- Modify: `workspace/tests/pipeline/test_phase4_dual_cognition.py`

- [ ] **Step 1: Write failing dual cognition test**

Add:

```python
@pytest.mark.asyncio
async def test_think_passes_affect_hints_to_merge(pipeline_graph, mock_llm_fn):
    mock_mem = MagicMock()
    pre_cached = {
        "results": [{"content": "felt ignored before", "score": 0.9, "source": "lancedb_scored"}],
        "tier": "scored_fallback",
        "entities": [],
        "graph_context": "",
        "affect_hints": "[EMOTIONAL MEMORY SIGNALS]\\n- Matching pattern: respond softly.",
    }
    engine = DualCognitionEngine(memory_engine=mock_mem, graph=pipeline_graph)
    await engine.think("I feel ignored again", "chat1", llm_fn=mock_llm_fn, pre_cached_memory=pre_cached)
    prompts = "\\n".join(str(call.args[0]) for call in mock_llm_fn.call_args_list)
    assert "EMOTIONAL MEMORY SIGNALS" in prompts
```

- [ ] **Step 2: Run test and verify fail**

Run:

```powershell
pytest workspace\tests\pipeline\test_phase4_dual_cognition.py::test_think_passes_affect_hints_to_merge -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-dual-affect
```

Expected: FAIL.

- [ ] **Step 3: Update dual cognition**

Add field:

```python
affect_hints: str = ""
```

In `_recall_memory()`:

```python
memory.affect_hints = str(results.get("affect_hints", "") or "")
```

In `_merge_streams()` prompt after memory facts:

```python
  Emotional memory signals: {memory.affect_hints[:500] if memory.affect_hints else "None"}
```

- [ ] **Step 4: Update chat prompt formatting**

In `_format_memory_context_for_tier()`, append:

```python
if mem_response.get("affect_hints"):
    parts.append(str(mem_response.get("affect_hints")))
```

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
pytest workspace\tests\pipeline\test_phase4_dual_cognition.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-dual-affect
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add workspace\sci_fi_dashboard\chat_pipeline.py workspace\sci_fi_dashboard\dual_cognition.py workspace\tests\pipeline\test_phase4_dual_cognition.py
git commit -m "feat: inject affect hints into cognition"
```

---

### Task 5: Backfill Script

**Files:**
- Create: `workspace/scripts/personal/backfill_memory_affect.py`
- Modify: `workspace/tests/test_memory_affect.py`

- [ ] **Step 1: Add script tests**

Add helper-level tests for dry-run and candidate selection if functions are exposed:

```python
from workspace.scripts.personal.backfill_memory_affect import select_documents_without_affect


def test_select_documents_without_affect_excludes_existing():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)
    conn.execute("INSERT INTO documents (id, content) VALUES (1, 'hurt'), (2, 'neutral')")
    upsert_memory_affect(conn, 1, extract_affect("hurt"))
    rows = select_documents_without_affect(conn, limit=10, since_id=0)
    assert [r["id"] for r in rows] == [2]
```

- [ ] **Step 2: Implement script**

Script structure:

```python
def resolve_memory_db() -> Path:
    from synapse_config import SynapseConfig
    return SynapseConfig.load().db_dir / "memory.db"

def select_documents_without_affect(conn, limit: int, since_id: int = 0) -> list[dict]: ...
def backfill(db_path: Path, limit: int, dry_run: bool, force: bool, since_id: int = 0) -> dict: ...
def main() -> int: ...
```

Backup policy:

```python
backup = db_path.with_name(f"{db_path.name}.bak_affect_{int(time.time())}")
shutil.copy2(db_path, backup)
```

Only create backup when `dry_run` is false and at least one row will be written.

- [ ] **Step 3: Run tests**

Run:

```powershell
pytest workspace\tests\test_memory_affect.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-backfill-affect
```

Expected: PASS.

- [ ] **Step 4: Smoke dry-run**

Run:

```powershell
python workspace\scripts\personal\backfill_memory_affect.py --dry-run --limit 5
```

Expected: prints candidate count and no backup/write.

- [ ] **Step 5: Commit**

```powershell
git add workspace\scripts\personal\backfill_memory_affect.py workspace\tests\test_memory_affect.py
git commit -m "feat: add memory affect backfill"
```

---

### Task 6: Final Verification

**Files:**
- All touched source/test files.

- [ ] **Step 1: Run focused suite**

```powershell
pytest workspace\tests\test_memory_affect.py workspace\tests\test_schema_migration.py workspace\tests\test_memory_engine.py workspace\tests\pipeline\test_phase4_dual_cognition.py -q -o cache_dir=.codex-tmp\.pytest_cache --basetemp=.codex-tmp\pytest-affect-final
```

- [ ] **Step 2: Run lint/compile smoke**

```powershell
python -m py_compile workspace\sci_fi_dashboard\memory_affect.py workspace\sci_fi_dashboard\db.py workspace\sci_fi_dashboard\memory_engine.py workspace\sci_fi_dashboard\dual_cognition.py workspace\scripts\personal\backfill_memory_affect.py
```

- [ ] **Step 3: Check git diff**

```powershell
git diff --stat
git status --short --branch
```

- [ ] **Step 4: Final commit if pending**

If previous task commits already captured all changes, no extra commit. Otherwise:

```powershell
git add workspace\sci_fi_dashboard workspace\tests workspace\scripts\personal\backfill_memory_affect.py
git commit -m "feat: add affect-aware memory"
```

---

## Rollback Plan

- Code rollback: revert commits from this feature.
- DB rollback: no destructive schema change. `memory_affect` can remain unused safely.
- Backfill rollback: restore from `memory.db.bak_affect_<timestamp>` if needed.

## Non-Goals

- Do not drop `atomic_facts`.
- Do not regenerate all atomic facts.
- Do not call cloud LLMs from `add_memory()`.
- Do not expose internal affect labels in final user-visible replies.
