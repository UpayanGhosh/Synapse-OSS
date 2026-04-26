# Affect-Aware Memory Design

Date: 2026-04-27

## Goal

Make Synapse replies feel less generic by retrieving not only semantically related memories, but emotionally similar memories: memories with matching mood, tension, user need, and response style.

This design does not drop `atomic_facts`, `atomic_facts_vec`, or any runtime DB data. It adds a safe overlay on top of the existing memory system.

## Current State

Local inspection found:

- `documents`: 10,390 rows.
- `documents.kg_processed = 1`: 136 rows.
- `atomic_facts`: 1,353 rows, partial coverage.
- `entity_links`: 1,019 active rows.
- `emotional_trajectory`: 108 rows in `emotional_trajectory.db`.

Existing architecture:

- `MemoryEngine.add_memory()` writes `documents`, `vec_items`, and LanceDB metadata.
- `MemoryEngine.query()` retrieves by semantic score, recency, and importance.
- SBS tracks realtime mood/sentiment in profile JSON.
- Dual cognition detects present emotional state and records trajectory.
- Emotional trajectory tracks last 72h tension arc.

Gap:

- Emotion is runtime/profile-level, not memory-level.
- Individual `documents` rows do not store mood, sentiment, tension, user need, or response style.
- Retrieval cannot ask "which memory matches this emotional situation?"

## Research Basis

The design follows proven patterns from long-term memory agent work:

- MemoryBank: long-term companion memory benefits from retrieval, update, user personality adaptation, and importance/forgetting style weighting. Source: https://arxiv.org/abs/2305.10250
- Generative Agents: believable behavior depends on storing observations, synthesizing reflections, and dynamically retrieving relevant memories. Source: https://arxiv.org/abs/2304.03442
- MemGPT: long-running chat needs tiered memory management beyond fixed context. Source: https://arxiv.org/abs/2310.08560
- A-MEM: agent memory improves when notes carry structured attributes, keywords, tags, links, and evolving context. Source: https://arxiv.org/abs/2502.12110

Implication for Synapse:

- Raw facts help factual sharpness.
- Affect-tagged memory improves human-feel because it lets Synapse recall emotional patterns, not just topic overlap.

## Recommended Architecture

Add a `memory_affect` overlay table keyed by `documents.id`.

```sql
CREATE TABLE IF NOT EXISTS memory_affect (
    doc_id              INTEGER PRIMARY KEY,
    sentiment           TEXT NOT NULL DEFAULT 'neutral',
    mood                TEXT NOT NULL DEFAULT 'neutral',
    emotional_intensity REAL NOT NULL DEFAULT 0.0,
    tension_type        TEXT NOT NULL DEFAULT 'none',
    user_need           TEXT NOT NULL DEFAULT 'none',
    response_style_hint TEXT NOT NULL DEFAULT 'warm',
    topics_json         TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.0,
    extractor_version   TEXT NOT NULL DEFAULT 'heuristic-v1',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_affect_mood
    ON memory_affect(mood);

CREATE INDEX IF NOT EXISTS idx_memory_affect_tension
    ON memory_affect(tension_type);

CREATE INDEX IF NOT EXISTS idx_memory_affect_need
    ON memory_affect(user_need);
```

## Affect Schema

Fields:

- `sentiment`: `positive`, `negative`, `mixed`, `neutral`.
- `mood`: compact dominant mood such as `calm`, `hurt`, `anxious`, `frustrated`, `lonely`, `excited`, `proud`, `playful`, `focused`, `tired`, `vulnerable`.
- `emotional_intensity`: `0.0` to `1.0`.
- `tension_type`: `none`, `rejection`, `neglect`, `conflict`, `uncertainty`, `pressure`, `boundary`, `growth`, `desire`, `safety`.
- `user_need`: `none`, `reassurance`, `clarity`, `comfort`, `space`, `accountability`, `validation`, `encouragement`, `playfulness`, `directness`, `protection`.
- `response_style_hint`: `warm`, `soft`, `direct`, `playful`, `grounding`, `protective`, `celebratory`, `firm`, `teasing`.
- `topics_json`: short topic list for prompt/debug.
- `confidence`: how reliable the extraction is.

Design rule:

- Keep labels few and stable.
- Prefer neutral/low confidence over over-dramatic tagging.
- The final assistant should use affect as subtle guidance, never announce labels.

## Extractor

Create a focused module, likely `workspace/sci_fi_dashboard/memory_affect.py`.

Responsibilities:

- Ensure schema exists.
- Extract affect from text via deterministic heuristic first.
- Upsert affect row for `doc_id`.
- Score affect match for retrieval.
- Format compact affect signals for prompt injection.

Initial extractor should be local, deterministic, and cheap.

Reason:

- It must run during `add_memory()` without blocking hard on cloud LLMs.
- Heuristic output is testable and stable.
- LLM enrichment can be added later for backfill or high-value memories.

Extraction strategy:

- Keyword/phrase matching for mood, tension, user need, and response hint.
- Sentiment computed from existing style of SBS lexicon plus stronger emotional terms.
- Intensity based on emotional keyword density, punctuation, direct distress phrases, and conflict phrases.
- Confidence increases when multiple signals agree.

Examples:

- "I feel unseen and hurt" -> mood `hurt`, tension `neglect`, need `validation`, style `soft`.
- "I am stuck and stressed about work" -> mood `frustrated`, tension `pressure`, need `clarity`, style `grounding`.
- "Let's go, this works" -> mood `excited`, tension `growth`, need `encouragement`, style `celebratory`.

## Write Path

`MemoryEngine.add_memory()` flow becomes:

1. Insert `documents` row.
2. Insert embeddings into `vec_items` and LanceDB as today.
3. Compute affect with heuristic extractor.
4. Upsert `memory_affect(doc_id=inserted_id, ...)`.
5. Commit once.

Failure policy:

- Affect extraction failure must not fail memory storage.
- Log warning and continue.
- Missing affect row means neutral affect at query time.

## Query Path

Current score:

```text
semantic * 0.4 + temporal * 0.3 + importance * 0.3
```

New score:

```text
semantic * 0.35 + temporal * 0.20 + importance * 0.20 + affect_match * 0.25
```

Affect match:

- Detect query affect using same extractor on user message, no DB write.
- For each candidate result, read `memory_affect` by `doc_id`.
- Match mood, tension type, user need, and response style.
- Boost emotional match only when query intensity is meaningful.
- If query is neutral, affect score should not dominate.

Guardrails:

- Factual questions should not be hijacked by emotional memories.
- If user asks "what was X", semantic and graph relevance remain primary.
- For short emotional messages like "I feel ignored", affect match can strongly influence retrieval.

## Prompt Injection

Add compact block to the memory context, not verbose labels everywhere.

Example:

```text
[EMOTIONAL MEMORY SIGNALS]
- Matching pattern: user has felt unseen/neglected before; respond softly, validate first.
- Current need likely: reassurance + clarity.
```

Rules:

- Do not expose "memory_affect", "tension_type", or internal labels.
- Do not say "I checked my memory".
- Use affect to guide tone, specificity, and what to avoid.

## Dual Cognition Integration

Extend `MemoryStream` with optional affect hints:

```python
affect_hints: list[str] = field(default_factory=list)
```

`_recall_memory()` should read `affect_hints` from `mem_response`.

`_merge_streams()` should include:

```text
EMOTIONAL MEMORY SIGNALS:
...
```

This helps merge choose tone/strategy from persistent emotional patterns, not only current message and raw facts.

## Backfill

Add a non-destructive script:

`workspace/scripts/personal/backfill_memory_affect.py`

Behavior:

- Creates backup before first write.
- Reads documents without affect rows.
- Processes in batches.
- Default limit: 100.
- Supports `--dry-run`, `--limit`, `--force`, `--since-id`.
- Uses heuristic extractor first.
- Marks progress by existence of `memory_affect` row, not new column.

No cloud LLM required for initial version.

Possible later option:

- `--backend copilot --model gpt-5-mini` for richer tags on high-importance docs.
- Not part of first implementation.

## Atomic Facts Decision

Do not drop `atomic_facts` in this feature.

Reason:

- User explicitly wanted recreation/coverage earlier.
- Destructive Phase 4 needs separate approval.
- Affect-aware memory is orthogonal and safer.

Possible later:

- Keep `atomic_facts` for factual sharpness.
- Clean and canonicalize entities separately.
- Decide deprecate vs revive after affect layer is live and measurable.

## Observability

Emit lightweight events:

- `memory.affect_extracted`
- `memory.affect_rerank`
- `memory.affect_backfill_progress`

Include counts and labels, not raw private content.

## Tests

Minimum tests:

- Schema migration creates `memory_affect` and indexes.
- Extractor classifies known emotional phrases.
- `add_memory()` writes affect row for inserted doc.
- Query rerank boosts emotionally matching memory when query is emotional.
- Neutral/factual query does not get dominated by affect.
- Dual cognition receives affect hints without exposing internals.
- Backfill dry-run writes nothing.

## Rollout

Phase 1:

- Schema + extractor + tests.

Phase 2:

- Write-path integration with `add_memory()`.

Phase 3:

- Query rerank + prompt affect block.

Phase 4:

- Dual cognition affect hints.

Phase 5:

- Backfill script, default 100 docs per run.

Phase 6:

- Manual evaluation against real conversation prompts.

## Success Criteria

Functional:

- New memories get affect rows automatically.
- Old memories can be backfilled safely.
- Emotional queries retrieve emotionally relevant context.
- Factual queries still retrieve factual context.

Behavioral:

- Replies sound more personally aware without becoming melodramatic.
- Synapse recalls recurring emotional patterns without explicitly saying it used memory.
- Response strategy improves for hurt, anxious, conflict, pressure, and celebration contexts.

Safety:

- No destructive DB operations.
- Affect extraction failure never blocks memory storage.
- No private raw content in logs.

## Open Follow-Up

After this lands, measure actual ROI with a small evaluation set:

- 10 factual prompts.
- 10 emotional prompts.
- 10 mixed prompts.
- Compare current branch vs affect branch for specificity, tone fit, hallucination, and emotional continuity.
