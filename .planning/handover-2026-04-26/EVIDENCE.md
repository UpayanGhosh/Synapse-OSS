# Evidence Pack — Synapse-OSS Fix Handover (2026-04-26)

> Raw data captured during diagnosis. Every phase doc cites specific entries here. Use this file to **verify** before changing code, and to **reproduce** the symptoms on a fresh checkout.

---

## How to reproduce the queries below

```bash
cd ~/.synapse/workspace/db
python -c "
import sqlite3
conn = sqlite3.connect('memory.db')
cur = conn.cursor()
# ... paste query from sections below
"
```

For Windows cp1252 issues with WhatsApp emoji content, wrap any printed string in:

```python
def safe(s):
    return str(s).encode('ascii', errors='replace').decode('ascii') if s is not None else 'None'
```

---

## E1 — Memory subsystem is partially frozen

### E1.1 — Documents table composition (snapshot 2026-04-26 06:50)

```
SELECT filename, COUNT(*) FROM documents GROUP BY filename ORDER BY COUNT(*) DESC LIMIT 20;
```

| Count | filename |
|---|---|
| 6,453 | `WhatsApp Chat with Shreya (Boumuni).txt` |
| 3,359 | `WhatsApp Chat with Babe ????.txt` (emojis) |
| 476 | `_archived_memories/Communication_with_GF_archived_20260210_095927.json` |
| 29 | `archive_migration_Chat_with_Upayan_LLM.md` |
| **18** | **`skill_execution`** ← **POLLUTION (now cleaned)** |
| 10 | `relationship_memory` |
| 6 | `archive_migration_Chat_with_Shreya_LLM.md` |
| 5 | `session` |
| 5 | `memory_distillation` |
| 4 | `sentiment_logs` |
| 4 | `career_opportunity` |
| 3 | `personal_updates` |
| 1 each | `work_context`, `user_profiles`, `test`, `system_updates`, `system_milestones`, `system_logs`, `personal_preferences`, `personal_growth` |

**Total:** 10,401 rows pre-cleanup → **10,383 rows post-cleanup** (after 18 `skill_execution` rows were deleted).

> 99.6% of memory.db is the WhatsApp bulk import from 2026-02. Bot's day-to-day ingestion has produced **~30-50 rows total** since then.

### E1.2 — `documents.kg_processed` is 0 for ALL rows

```
SELECT kg_processed, COUNT(*) FROM documents GROUP BY kg_processed;
-- → kg_processed=0: 10401 (post-cleanup: 10383)
```

There are no rows with `kg_processed=1`. The flag has never been set at runtime. Only `workspace/scripts/personal/kg_bulk_extract.py:750` sets it (manual bulk script), and the bulk script has not been run on this DB.

### E1.3 — `atomic_facts` table is dead since 2026-02-13

```
SELECT id, entity, content, source_doc_id, created_at FROM atomic_facts ORDER BY created_at DESC LIMIT 5;
```

| id | entity | content | source_doc_id | created_at |
|---|---|---|---|---|
| 740 | NULL | "I was invisible to him despite my efforts." | 6445 | 2026-02-13 21:43:33 |
| 739 | NULL | "He complained about my effort." | 6445 | 2026-02-13 21:43:33 |
| 738 | NULL | "I studied for 8-9 hours straight." | 6445 | 2026-02-13 21:43:33 |
| 737 | NULL | "She's emotionally tired from trying and not feeling emotionally safe enough." | 6444 | 2026-02-13 21:43:19 |
| 736 | NULL | "She misses you." | 6444 | 2026-02-13 21:43:19 |

NULL/total breakdown:

```
SELECT
  SUM(CASE WHEN entity IS NULL THEN 1 ELSE 0 END) AS null_entity,
  SUM(CASE WHEN entity IS NOT NULL THEN 1 ELSE 0 END) AS not_null_entity,
  SUM(CASE WHEN category IS NULL THEN 1 ELSE 0 END) AS null_category,
  COUNT(*) AS total
FROM atomic_facts;
-- → null_entity=529, not_null_entity=211, null_category=529, total=740
```

72% of facts have `entity IS NULL AND category IS NULL`. Nothing has been added since 2026-02-13.

### E1.4 — `entity_links` IS alive but orphaned

```
SELECT COUNT(*) FROM entity_links WHERE created_at > datetime('now', '-1 day');  -- 111
SELECT COUNT(*) FROM entity_links WHERE created_at > datetime('now', '-7 days'); -- 178
SELECT COUNT(*) FROM entity_links;                                                -- 794
```

5 most recent triples (2026-04-25 23:23:23):

| subject | relation | object |
|---|---|---|
| user | interested_in | python |
| user | uses | memory.db |
| assistant | related_to | google |
| user | interested_in | llm inference |
| user | knows | shreya |

**All 178 recent triples have `source_fact_id = 0`** (placeholder). They're not linked to any real `atomic_facts` row.

### E1.5 — `sessions` table tracks tokens, NOT content

```
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 5;
```

| id | session_id | role | model | input_tokens | output_tokens | total_tokens | created_at |
|---|---|---|---|---|---|---|---|
| 363 | 29f6be28… | code | claude-sonnet-4-6 | 1 | 2 | 3 | 2026-04-26 00:50:31 |
| 362 | 4469082d… | casual | gemini-3-flash-preview | 16,361 | 52 | 16,719 | 2026-04-26 00:44:37 |
| 361 | 44fea8c4… | casual | gemini-3-flash-preview | 684 | 81 | 2,180 | 2026-04-25 23:54:38 |
| 360 | 1fe6de2a… | casual | gemini-3-flash-preview | 19,399 | 185 | 19,584 | 2026-04-25 23:49:19 |
| 359 | b28e8b95… | casual | gemini-3-flash-preview | 20,398 | 152 | 20,550 | 2026-04-25 23:46:22 |

The chat content for these sessions is NOT in `documents` — only the token-counter is recorded. That's the gap.

### E1.6 — Active session JSONL has 56 unflushed messages

```bash
ls -la ~/.synapse/state/agents/the_creator/sessions/cecb9c73-22bc-4cd9-9984-30c167032814.jsonl
# -rw-r--r-- 1 Shorty0_0 197121 22432 Apr 26 05:19 cecb9c73-...jsonl
wc -l ~/.synapse/state/agents/the_creator/sessions/cecb9c73-22bc-4cd9-9984-30c167032814.jsonl
# 56
```

Sample lines (first + last):

```json
{"role":"user","content":"What model I'm currently using?"}
{"role":"assistant","content":"You're currently using **GPT-4o** (via GitHub Copilot)... \n**Model:** gemini-3-flash-preview\n**Tokens:** 14,779 in / 32 out / 14,811 total\n**Response Time:** 4.1s"}
...
{"role":"user","content":"[FLASH TEST] Bhai one more — what's the failure mode you most worry about for me? Not the obvious one. The blind spot. Be uncomfortable."}
{"role":"assistant","content":"The blind spot? You'll use Synapse as an **emotional sandbox** instead of a bridge. ..."}
```

These are TODAY's chats. They have NOT been ingested into `documents` / `atomic_facts` / `entity_links` because no `/new` command was issued.

### E1.7 — Last `/new` archive succeeded but vector-path FAILED

```bash
ls -la ~/.synapse/state/agents/the_creator/sessions/*deleted*
```

```
17fef763-…-eb4792a8c100.jsonl.deleted.1777064543761  (2026-04-25 02:27, 2.1 KB)
66668af3-…-687c4fda2d5b.jsonl.deleted.1777078248806  (2026-04-25 06:20, 14.1 KB)
```

The 06:20 archive triggered `_ingest_session_background` (`workspace/sci_fi_dashboard/pipeline_helpers.py:325-332`).

Outcome:
- **Vector path (add_memory → documents)**: FAILED — most recent `filename='session'` doc is from 2026-04-25 00:51, BEFORE the 06:20 /new.
- **KG path (entity_links)**: SUCCEEDED — 178 new triples in the 7 days following.

`session_ingest.py:148` catches `Exception` and logs to `log.error(...)`, then continues to KG extraction. The error is swallowed.

### E1.8 — Pollution evidence (resolved, kept here for forensics)

Polluting rows had:

```
filename = 'skill_execution'
content  = "[Skill: <MagicMock name='mock.skill_router.match().name' id=...>]
            User: <message>
            Assistant: I tried to use the '<MagicMock ...>' skill but it
            encountered an error: TypeError: object MagicMock can't be used
            in 'await' expression. The conversation can continue normally."
created_at: 2026-04-25 13:55:47 — 13:56:11 (~24 seconds, 18 rows)
hemisphere_tag: 'safe'
importance: 3
kg_processed: 0
```

Source: `workspace/tests/pipeline/test_phase6_end_to_end.py::test_10_turn_conversation_no_crash` (line 418-446). It used the `pipeline_memory_engine` fixture (`workspace/tests/pipeline/conftest.py:252`) which constructs a real `MemoryEngine`. The fixture's docstring explicitly noted `add_memory` was unpatched. When the 10-turn loop hit `chat_pipeline.py:782` (skill error path), real `add_memory` wrote to prod `memory.db`.

**Already fixed** in commit `26556e8`:

```python
# workspace/tests/pipeline/conftest.py:296-300 (after fix)
from unittest.mock import MagicMock as _MagicMock
engine.add_memory = _MagicMock(return_value=None)
```

Backup file before deletion: `~/.synapse/workspace/db/memory.db.bak_1777166450`.

---

## E2 — Tool-loop convergence (W6 P0 BLOCKING)

### E2.1 — Symptom from session log

`api_gateway.py` chat path fires up to **12 immediate retries on 429** with no backoff. From the user's notes during 2026-04-26 dual-cognition test:

> **T3 — Tool execution (`bash_exec` via tool loop)**: 27.5s → ✗ Tool loop fires 12 immediate retries on 429.

Burns through Pro Flash quota (10 RPM) in ~28 seconds. With analysis=`pro-high` (1 RPM), even one chat is fatal.

### E2.2 — Where to look in code

| File | What's there |
|---|---|
| `workspace/sci_fi_dashboard/api_gateway.py` | `persona_chat` orchestrates calls; tool loop is here |
| `workspace/sci_fi_dashboard/chat_pipeline.py` | `call_with_tools` invocations |
| `workspace/sci_fi_dashboard/llm_router.py` | `call_with_tools()` method |

Search:

```bash
grep -n "MAX_TOOL_ROUNDS\|max_rounds\|tool_loop\|RateLimitError\|429" \
  workspace/sci_fi_dashboard/*.py
```

### E2.3 — OpenClaw reference for retry pattern

```
D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts
```

OpenClaw parses `Retry-After` header, jitters backoff, caps total wait. Pattern:

```ts
// pseudo, see actual file
async function withRetry(fn, opts) {
  for (let attempt = 0; attempt < opts.maxAttempts; attempt++) {
    try { return await fn(); }
    catch (e) {
      if (e.status === 429) {
        const retryAfter = parseRetryAfter(e.headers) || jitteredBackoff(attempt);
        if (retryAfter > opts.maxWaitMs) throw e;
        await sleep(retryAfter);
        continue;
      }
      throw e;
    }
  }
}
```

### E2.4 — Current `synapse.json` model picks (relevant to tool-loop budget)

```json
"model_mappings": {
  "casual":   { "model": "google_antigravity/gemini-3-flash" },
  "code":     { "model": "google_antigravity/gemini-3-pro-low",  "fallback": "google_antigravity/gemini-3-flash" },
  "analysis": { "model": "google_antigravity/gemini-3-pro-high", "fallback": "google_antigravity/gemini-3-pro-low" },
  "review":   { "model": "google_antigravity/gemini-3-pro-high", "fallback": "google_antigravity/gemini-3-pro-low" }
}
```

`pro-high` = 1 RPM. Tool loop x 12 retries = instant exhaustion.

---

## E3 — Dual cognition off antigravity (W7)

### E3.1 — Current state

```json
// ~/.synapse/synapse.json
"session": {
  "dual_cognition_enabled": false,    ← workaround active
  "dual_cognition_timeout": 5.0
}
```

`DualCognitionEngine.think()` fires 2 calls to the analysis role per chat. Each call is a separate LLM round. Disabling it works around the 1 RPM problem but loses inner-monologue depth.

### E3.2 — Where to fix

| File | Function | Issue |
|---|---|---|
| `workspace/sci_fi_dashboard/llm_wrappers.py:42` | `call_ag_oracle` | Currently routes via `analysis` role (= pro-high). Should route to a dedicated cheap role (e.g. `oracle` → `gemini-3-flash-lite` with `thinkingLevel: LOW`, or local Ollama) |
| `workspace/sci_fi_dashboard/dual_cognition.py` | `DualCognitionEngine.think` | Or: consolidate stream + merge into one prompt (single LLM call, two output sections) |

### E3.3 — Long-term option (architectural)

Use Gemini 3 Pro's native `thoughtSignature` instead of a separate LLM call. Reference:

```
D:/Shorty/openclaw/src/agents/google-transport-stream.ts:134-139
```

OpenClaw extracts the thought-signature from a single Gemini response. No second roundtrip. Cleaner.

---

## E4 — `gpt-5-mini` residue in traffic_cop (W8)

### E4.1 — Symptom

Telegram first-message context block on 2026-04-26:

```
**Context Usage:** 15.6% / 1,048,576 ... **Model:** gpt-5-mini       ← traffic_cop classifier
**Context Usage:** 19,205 / 1,048,576 (1.8%) ... **Model:** gemini-3-flash-preview  ← actual reply
```

Two model entries. `gpt-5-mini` is the legacy traffic-cop classifier model from when GitHub Copilot was the primary provider. With Copilot detached, this should fall back to a configured antigravity/local model.

### E4.2 — Where to fix

```bash
grep -rn "gpt-5-mini\|gpt5-mini\|route_traffic_cop" workspace/sci_fi_dashboard/
```

The hardcoded reference is in `route_traffic_cop` (search `api_gateway.py`).

### E4.3 — Cost impact

`gpt-5-mini` is OpenAI billing. If user's `OPENAI_API_KEY` env is set, every chat fires this classifier silently. Verifies as $$$/chat. If env is unset, the call fails and traffic_cop returns the default role — also silent.

---

## E5 — Capability-tier auto-detect (W5)

### E5.1 — Background

Synapse's prompt-tier system (`small`, `mid_open`, `frontier`) is currently set per-role manually in `synapse.json`. Last item from `MODEL-AGNOSTIC-ROADMAP.md` is to auto-detect a model's tier from its name/provider and warn if the user's choice is undersized for the role's prompt complexity.

### E5.2 — Where the tiering lives

| File | Role |
|---|---|
| `workspace/sci_fi_dashboard/prompt_compiler.py` (or similar) | Tier-aware prompt assembly |
| `workspace/sci_fi_dashboard/models_catalog.py` | `ModelsCatalog` — Ollama discovery, context window guard |
| `workspace/synapse_config.py` | `model_mappings.<role>.prompt_tier` |

### E5.3 — Reference

```bash
grep -rn "prompt_tier\|small\|mid_open\|frontier" workspace/sci_fi_dashboard/
```

Specifically: Phase 1's tier-aware compilation was wired earlier this week (commit `37a1dea feat(runtime): wire tier-aware prompt compilation into chat pipeline`). W5 builds on it with auto-detection.

---

## E6 — Test isolation pattern (regression guard)

### E6.1 — Canonical pattern (post-fix)

```python
# workspace/tests/pipeline/conftest.py:252-300 (excerpt)
@pytest.fixture(scope="session")
def pipeline_memory_engine(pipeline_lancedb, pipeline_graph):
    ...
    engine = MemoryEngine(graph_store=pipeline_graph)
    engine.vector_store = pipeline_lancedb
    engine._embed_provider = fake_provider
    engine.get_embedding = _fake_get_embedding

    # CRITICAL: stub add_memory to a no-op so tests can't pollute prod DB
    from unittest.mock import MagicMock as _MagicMock
    engine.add_memory = _MagicMock(return_value=None)

    yield engine
```

### E6.2 — Tests known to exercise the path

- `workspace/tests/pipeline/test_phase6_end_to_end.py::test_10_turn_conversation_no_crash`
- `workspace/tests/test_chat_pipeline_skill_routing.py::TestSkillRouting::test_skill_fires_exactly_once`
- `workspace/tests/test_skill_pipeline.py::TestSkillPipelineIntegration::*`

Any new test that imports `chat_pipeline.persona_chat` MUST mock `memory_engine.add_memory`.

### E6.3 — Backup/forensics path

If you discover a similar pollution in any DB:

```bash
cp ~/.synapse/workspace/db/memory.db ~/.synapse/workspace/db/memory.db.bak_$(date +%s)
# THEN diagnose, THEN delete
```

Existing backups available:

- `memory.db.bak_1777166450` (2026-04-26 06:50, 226 MB, post-jarvis-arch session)
- `memory.db.bak_1777066874` (2026-04-25 02:48, 3.5 MB, older)

---

## E7 — Useful sqlite query recipes

```python
# 1. Health check: are docs being ingested?
"SELECT filename, MAX(created_at) FROM documents GROUP BY filename ORDER BY MAX(created_at) DESC LIMIT 10"

# 2. Are tests polluting?
"SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%' OR content LIKE '%<Mock %' OR filename = 'skill_execution'"

# 3. Is KG extraction firing?
"SELECT COUNT(*) FROM entity_links WHERE created_at > datetime('now', '-1 day')"

# 4. Is vector path firing?
"SELECT COUNT(*) FROM documents WHERE filename = 'session' AND created_at > datetime('now', '-1 day')"

# 5. atomic_facts decay status
"SELECT MAX(created_at), COUNT(*) FROM atomic_facts"
```

These should become the basis of a `/memory_health` endpoint in Phase 1.

---

## E8 — Index of relevant code paths

| Concern | File | Line(s) |
|---|---|---|
| Skill error → memory write | `chat_pipeline.py` | 780-785 |
| `add_memory` impl | `memory_engine.py` | 368-432 |
| `_ingest_session_background` | `session_ingest.py` | 47-200+ |
| `_handle_new_command` (entry to ingest) | `pipeline_helpers.py` | 293-348 |
| Session JSONL transcript I/O | `multiuser/transcript.py` | (read/write) |
| KG extractor | `conv_kg_extractor.py` | 432, 803 (writes) |
| Tool loop | `api_gateway.py` + `llm_router.py:call_with_tools` | search `MAX_TOOL_ROUNDS` |
| Dual cognition | `dual_cognition.py`, `llm_wrappers.py:42` | `call_ag_oracle` |
| Traffic cop | `api_gateway.py` | search `route_traffic_cop` |
| Test isolation pattern | `tests/pipeline/conftest.py` | 252-300 |
| Bulk KG script (only place that sets `kg_processed=1`) | `scripts/personal/kg_bulk_extract.py` | 750 |

---

## E9 — Recent commit history (for context)

```
c4bcdb7 docs(handoff): close out 2026-04-26 part 2 — claude_cli + review + push to origin
26556e8 fix(tests): patch pipeline_memory_engine to stub add_memory in fixture
9cfc610 fix(claude_cli+antigravity): unbreak OSS onboarding for both providers
2a03b45 merge: feat/jarvis-architecture — antigravity + claude_cli + OSS wiring
39b7b9c feat(claude_cli): wire into onboarding wizard for OSS-distributable setup
7a4c2c0 fix(claude_cli): replace default system prompt instead of appending
689b62d feat(router): replace claude_max direct-API path with claude_cli subprocess
9186001 fix(claude_cli): pass system prompt via temp file to dodge Win32 32k arg cap
6ba9e03 docs(handoff): close out antigravity provider session
ba3d663 test(antigravity): align with OpenClaw + cover new envelope/refresh paths
b73fce1 feat(antigravity): engage paid tier via enabled_credit_types
e0e0d06 fix(antigravity): correct CodeAssist v1internal envelope + OAuth resilience
f47400e feat(provider): add Google Antigravity (Gemini 3 via OAuth) as 20th provider
```

`develop` is at `c4bcdb7` on `origin`. Phase fixes branch off `develop`, merge back via PR.
