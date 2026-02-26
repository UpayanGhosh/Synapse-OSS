# Dual Cognition v2 — Implementation Plan

> **Hardware constraint:** M1 MacBook Air, 8GB RAM
> **Token constraint:** Consumer-grade — don't burn tokens on simple messages
> **Core principle:** Dynamic cognitive routing — think hard only when it matters

---

## Problem → Solution Map

### Problem 1: Every Message Burns the Full 3-Step Pipeline

**Current behavior:** Even "hi bhai" triggers: analyze present → recall memory → merge → generate. That's **3 LLM calls** before the response LLM even starts. For a "hi", that's wasted latency and tokens.

**Research basis:** CoT paper (Q3.1) — CoT on simple tasks yields "negative or very small performance improvements." CoALA framework (QX.3) — "fix a rigid search budget" is architecturally sub-optimal. Kahneman (Q1.1) — System 1 handles routine, familiar inputs automatically.

**Solution: Cognitive Complexity Gate**

Add a fast, **zero-LLM** pre-classifier before the dual cognition pipeline. This runs on pure heuristics — no API call, no tokens burned.

```python
# In dual_cognition.py — new method
def classify_complexity(self, message: str, history: list = None) -> str:
    """Zero-LLM complexity triage. Returns: 'fast' | 'standard' | 'deep'"""
    msg_lower = message.lower().strip()
    word_count = len(msg_lower.split())

    # FAST PATH: greetings, acknowledgments, single emojis
    fast_patterns = ["hi", "hello", "hey", "ok", "thanks", "good morning",
                     "good night", "bye", "hmm", "haha", "lol", "👍", "❤️"]
    if word_count <= 3 or msg_lower in fast_patterns:
        return "fast"

    # DEEP PATH: vague references, denials, emotional distress, contradictions
    ambiguity_signals = ["that thing", "what we", "you know", "remember when"]
    denial_signals = ["didn't", "never", "haven't", "i don't"]
    distress_signals = ["help", "stuck", "frustrated", "can't", "failed", "stressed"]

    has_ambiguity = any(s in msg_lower for s in ambiguity_signals)
    has_denial = any(s in msg_lower for s in denial_signals)
    has_distress = any(s in msg_lower for s in distress_signals)

    if has_ambiguity or (has_denial and word_count > 5) or has_distress:
        return "deep"

    # STANDARD PATH: everything else
    return "standard"
```

**Routing behavior:**

| Path               | LLM Calls Before Response                          | When                                 |
| ------------------ | -------------------------------------------------- | ------------------------------------ |
| **Fast**     | 0 (skip dual cognition entirely)                   | Greetings, acks, emojis              |
| **Standard** | 2 (present + merge, skip pre-retrieval extraction) | Normal conversation                  |
| **Deep**     | 3 (full pipeline with CoT merge)                   | Contradictions, vague refs, distress |

**Token savings:** ~60-70% of WhatsApp messages are casual. Skipping cognition for those saves ~600-800 tokens per message.

#### Files to modify:

- [dual_cognition.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/dual_cognition.py) — add `classify_complexity()`, modify `think()` to route based on result
- [api_gateway.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/api_gateway.py) — wrap `dual_cognition.think()` call in complexity gate (around line 552)

---

### Problem 2: PresentStream Ignores Conversation History

**Current behavior:** `_analyze_present()` accepts a `history` parameter but never uses it. The LLM sees only the current message in isolation.

**Research basis:** Kahneman (Q1.1) — humans process messages in context of recent conversation. The "affect heuristic" shows that mood from previous turns bleeds into interpretation of current turn.

**Solution: Inject last 3 messages as context**

For the **standard** and **deep** paths only, include the last 3 messages from history in the analysis prompt. Add a `conversational_pattern` field to detect escalation/repetition.

```python
# Modified _analyze_present prompt (standard/deep path only)
recent_context = ""
if history and len(history) > 0:
    last_3 = history[-3:]
    recent_context = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in last_3])

prompt = f"""Analyze this message IN CONTEXT. Return JSON only.

Recent conversation:
{recent_context}

Current message: "{message}"

Return:
{{
  "sentiment": "positive|negative|neutral",
  "intent": "question|statement|request|venting|bragging|deflecting",
  "claims": ["factual claims user is making"],
  "emotional_state": "calm|excited|defensive|vulnerable|evasive|guilty",
  "topics": ["key topics"],
  "conversational_pattern": "none|escalating|de-escalating|repetitive|avoidant|contradicting_self"
}}

JSON only:"""
```

**Token cost:** ~150 extra input tokens per message (only on standard/deep path). Worthwhile tradeoff for pattern detection.

#### Files to modify:

- [dual_cognition.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/dual_cognition.py) — modify `_analyze_present()` prompt, add `conversational_pattern` to `PresentStream` dataclass

---

### Problem 3: Memory Recall Searches Raw Vague Messages

**Current behavior:** If user says "I aced that thing we talked about yesterday," the system does a vector search on that exact vague sentence. Results are often irrelevant.

**Research basis:** Kahneman (Q1.2) — users unknowingly "substitute" specific memories with vague references. The AI must act as the "objective observer" and push back. Generative Agents (Q2.1) — retrieval should combine recency + importance + relevance.

**Solution: Two-part approach (deep path only)**

1. **For deep-path queries only:** Add a lightweight LLM call to extract search terms before memory retrieval
2. **For all paths:** Add confidence scores to memory results passed to the merge

```python
# Only on deep path — extract what the user is actually referring to
async def _extract_search_intent(self, message: str, history: list, llm_fn) -> list:
    recent = "\n".join([f"{m['role']}: {m['content'][:80]}" for m in (history or [])[-3:]])
    prompt = f"""What specific topics/events is the user referring to?
Recent conversation:
{recent}
Message: "{message}"
Return 1-3 specific search terms as JSON array. JSON only:"""

    result = await llm_fn([{"role": "user", "content": prompt}],
                          temperature=0.0, max_tokens=100)
    # parse and return search terms
    ...
```

For standard path, continue using direct vector search (current behavior) — it's fast and good enough for clear messages.

**Token cost:** ~200 tokens for extraction call. Only triggered on ~10-15% of messages (deep path).

#### Files to modify:

- [dual_cognition.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/dual_cognition.py) — add `_extract_search_intent()`, modify `_recall_memory()` on deep path
- [memory_engine.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/memory_engine.py) — include `combined_score` in result dicts returned by `query()`

---

### Problem 4: Hardcoded Denial Patterns (Lines 211-250)

**Current behavior:** Brittle keyword list including Bengali Romanized strings. Only catches DSA-related denials. Already caused one bug (conversation aa7f5341).

**Research basis:** Generative Agents (Q2.4) — their agents have NO contradiction detection and are "highly susceptible to suggestion." Your system is already ahead of Stanford's paper here. Kahneman — LLMs are "gullible and biased to believe" by default (WYSIATI). The contradiction detection is *critical* — but the implementation must be robust.

**Solution: Move contradiction detection INTO the merge prompt**

Remove the hardcoded patterns. Instead, on **standard and deep** paths, the merge prompt itself handles contradiction detection. Add a `"thought"` key at the top of the JSON schema (per Q3.3) so the LLM reasons before classifying.

```python
# New merge prompt (replaces current _merge_streams prompt)
prompt = f"""You are the inner thinking process of a close friend AI.

WHAT THEY JUST SAID:
  Message: "{present.raw_message}"
  Intent: {present.intent}
  Claims: {json.dumps(present.claims)}
  Emotional state: {present.emotional_state}
  Conversational pattern: {present.conversational_pattern}

WHAT I REMEMBER (with confidence scores):
  {json.dumps([{"fact": f, "confidence": s} for f, s in zip(memory.relevant_facts[:5], memory.confidence_scores[:5])])}
  Relationship context: {memory.relationship_context[:400] if memory.relationship_context else "None"}

INSTRUCTIONS:
1. First, think step by step about whether the user's claims contradict any memories
2. Then decide your response strategy

Return JSON only:
{{
  "thought": "Your step-by-step reasoning about contradictions and emotional state (2-3 sentences)",
  "tension_level": 0.0 to 1.0,
  "tension_type": "none|mild_inconsistency|pattern_break|direct_contradiction|growth",
  "contradictions": ["list any contradictions between claims and memories"],
  "response_strategy": "acknowledge|challenge|support|redirect|quiz|celebrate",
  "suggested_tone": "warm|playful|concerned|firm|proud|teasing",
  "inner_monologue": "1-2 sentences of what you're THINKING (not saying)"
}}"""
```

**Why this works:**

- The `"thought"` key forces the LLM to reason *before* classifying (CoT inside JSON, per Q3.3)
- Contradiction detection is now language-agnostic — works in English, Bengali, Banglish, sarcasm
- Zero maintenance cost — no new patterns to hardcode ever again

**Risk mitigation:** Keep the old hardcoded patterns as a **silent fallback** for 2 weeks. Log when the LLM-based detection disagrees with the old heuristic. After validation, remove the old code.

#### Files to modify:

- [dual_cognition.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/dual_cognition.py) — rewrite `_merge_streams()` prompt, add `"thought"` key parsing, keep old denial patterns as commented fallback

---

### Problem 5: No Emotional Trajectory Across Sessions

**Current behavior:** Jarvis knows "he seems stressed right now" but has no concept of "he's been stressed all week about interviews."

**Research basis:** Kahneman (Q1.3) — the "Remembering Self" uses the Peak-End Rule, not uniform weighting. Memories are emotionally compressed. Generative Agents (Q2.2) — reflection triggers when cumulative importance exceeds 150. Park uses importance-weighted thresholds, not timers.

**Solution: Lightweight SQLite emotional log + Peak-End weighting**

After every `CognitiveMerge`, log the emotional snapshot. Before the merge, retrieve recent trajectory and inject it.

```python
# New file: emotional_trajectory.py
import sqlite3, time, os

DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/emotional_trajectory.db")

class EmotionalTrajectory:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS trajectory (
            id INTEGER PRIMARY KEY,
            timestamp REAL,
            emotional_state TEXT,
            tension_level REAL,
            tension_type TEXT,
            topic TEXT,
            is_peak INTEGER DEFAULT 0
        )""")
        conn.commit()
        conn.close()

    def record(self, merge: CognitiveMerge, topics: list):
        """Called after every merge. Mark peaks automatically."""
        conn = sqlite3.connect(DB_PATH)
        is_peak = 1 if merge.tension_level > 0.6 else 0
        conn.execute(
            "INSERT INTO trajectory (timestamp, emotional_state, tension_level, tension_type, topic, is_peak) VALUES (?,?,?,?,?,?)",
            (time.time(), merge.suggested_tone, merge.tension_level,
             merge.tension_type, ",".join(topics[:3]), is_peak)
        )
        conn.commit()
        conn.close()

    def get_trajectory(self, hours: int = 72, limit: int = 10) -> str:
        """Get recent emotional trajectory, Peak-End weighted."""
        conn = sqlite3.connect(DB_PATH)
        cutoff = time.time() - (hours * 3600)

        # Get peaks + most recent entries (Peak-End Rule)
        rows = conn.execute("""
            SELECT emotional_state, tension_level, tension_type, topic, timestamp
            FROM trajectory WHERE timestamp > ?
            ORDER BY is_peak DESC, timestamp DESC LIMIT ?
        """, (cutoff, limit)).fetchall()
        conn.close()

        if not rows:
            return ""

        lines = []
        for r in rows:
            age_hrs = (time.time() - r[4]) / 3600
            lines.append(f"- {age_hrs:.0f}h ago: {r[0]} (tension={r[1]:.1f}, type={r[2]}, topic={r[3]})")

        return "EMOTIONAL TRAJECTORY (last 72h, peaks highlighted):\n" + "\n".join(lines)
```

**Injection:** On **standard and deep** paths, add the trajectory string to the merge prompt between "WHAT I REMEMBER" and "INSTRUCTIONS".

**Memory cost:** SQLite DB, ~50 bytes per entry. Even at 100 messages/day for a year, that's ~1.8MB. Negligible.

**Token cost:** ~100 extra tokens in the merge prompt. Only on standard/deep paths.

#### Files to create:

- [emotional_trajectory.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/emotional_trajectory.py) — new file

#### Files to modify:

- [dual_cognition.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/dual_cognition.py) — accept `EmotionalTrajectory` in `__init__`, call `record()` after merge, call `get_trajectory()` and inject into merge prompt
- [api_gateway.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/api_gateway.py) — instantiate `EmotionalTrajectory`, pass to `DualCognitionEngine`

---

### Problem 6: No Memory Importance Scoring

**Current behavior:** All memories are treated equally. "Upayan likes spicy food" and "Upayan broke up with his girlfriend" have the same retrieval weight.

**Research basis:** Generative Agents (Q2.1) — they use an LLM to rate importance 1-10 at ingestion time. Formula: `score = recency + importance + relevance` (all min-max normalized, equal weights). Your code is missing the `importance` factor entirely.

**Solution: Hybrid heuristic + LLM importance scoring**

Use a **two-tier approach** at ingestion time:

1. **Tier 1 (every memory, zero tokens):** Fast keyword heuristic assigns a preliminary score 1-10
2. **Tier 2 (only ambiguous memories, ~150 tokens):** If the heuristic score lands in the "uncertain zone" (4-7), call the LLM for a precise rating

This way ~80% of memories get scored for free (clearly mundane = 1-3, clearly important = 8-10), and only the ~20% in the grey zone trigger an LLM call.

```python
# In memory_engine.py — two-tier importance scorer
def _score_importance_heuristic(self, content: str) -> int:
    """Tier 1: Fast keyword heuristic. Zero tokens."""
    score = 3  # baseline
    content_lower = content.lower()

    # Emotional content = important
    emotional_words = ["love", "hate", "angry", "sad", "happy", "excited",
                       "scared", "proud", "ashamed", "miss", "breakup",
                       "fight", "sorry", "grateful", "cry", "depressed"]
    score += sum(1 for w in emotional_words if w in content_lower) * 2

    # Life events = important
    life_events = ["interview", "job", "exam", "result", "hospital",
                   "birthday", "anniversary", "moving", "travel",
                   "married", "died", "born", "graduated", "fired", "hired"]
    score += sum(1 for w in life_events if w in content_lower) * 2

    # Short/mundane = less important
    if len(content.split()) < 5:
        score -= 2

    return max(1, min(10, score))

async def _score_importance_llm(self, content: str, llm_fn=None) -> int:
    """Tier 2: LLM-rated importance for ambiguous memories. ~150 tokens."""
    if not llm_fn:
        return 5  # fallback to neutral

    prompt = f"""Rate the importance of this memory on a scale of 1 to 10.
1 = mundane (e.g., "ate lunch", "said hi")
5 = moderately notable (e.g., "started a new book")
10 = life-altering (e.g., "got into a fight", "received exam results")

Memory: "{content}"

Return ONLY a single integer 1-10:"""

    try:
        result = await llm_fn(
            [{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=5
        )
        return max(1, min(10, int(result.strip())))
    except Exception:
        return 5  # fallback

async def score_importance(self, content: str, llm_fn=None) -> int:
    """Hybrid: heuristic first, LLM only for grey zone (4-7)."""
    heuristic = self._score_importance_heuristic(content)

    # Clear-cut cases: skip LLM entirely
    if heuristic <= 3 or heuristic >= 8:
        return heuristic

    # Grey zone: ask the LLM for a precise rating
    return await self._score_importance_llm(content, llm_fn)
```

**Then in `query()`:** Factor importance into the combined score:

```python
combined_score = (vector_score * 0.4) + (temporal_score * 0.3) + (importance_score / 10 * 0.3)
```

**Token cost breakdown:**

- ~80% of memories: 0 tokens (heuristic handles clearly mundane/important)
- ~20% of memories: ~150 tokens (LLM call, `max_tokens=5` so output is tiny)
- Average: **~30 tokens per memory ingested**

**Migration:** Add `importance INTEGER DEFAULT 5` column to `documents` table. Existing memories get default 5.

#### Files to modify:

- [memory_engine.py](file:///Users/shorty/.openclaw/workspace/sci_fi_dashboard/memory_engine.py) — add `_score_importance_heuristic()`, `_score_importance_llm()`, `score_importance()`, modify `add_memory()` to store importance, modify `query()` to use 3-factor scoring

---

## Token Budget Analysis

| Message Type                         | % of Traffic | Current LLM Calls        | New LLM Calls              | Token Savings             |
| ------------------------------------ | ------------ | ------------------------ | -------------------------- | ------------------------- |
| Casual ("hi", "ok", emojis)          | ~40%         | 3 cognition + 1 response | 0 cognition + 1 response   | **~800 tokens/msg** |
| Normal conversation                  | ~45%         | 3 cognition + 1 response | 2 cognition + 1 response   | **~300 tokens/msg** |
| Complex (contradictions, vague refs) | ~15%         | 3 cognition + 1 response | 3-4 cognition + 1 response | +200 tokens (worth it)    |

**Net effect:** ~40-50% reduction in total token consumption across all messages.

---

## RAM Budget Analysis (M1 Air 8GB)

| Component                              | Current RAM | After Changes      |
| -------------------------------------- | ----------- | ------------------ |
| Qdrant vector store                    | ~200MB      | ~200MB (unchanged) |
| SQLite graph                           | ~1MB        | ~1MB (unchanged)   |
| FlashRank reranker                     | ~50MB       | ~50MB (unchanged)  |
| Ollama embeddings                      | ~500MB      | ~500MB (unchanged) |
| **New: emotional_trajectory.db** | 0           | **~2MB**     |
| **New: importance column**       | 0           | **~0.1MB**   |
| Total                                  | ~751MB      | ~753MB             |

No new models loaded. No new embeddings. All changes are prompt-level and SQLite-level. Safe for 8GB.

---

## Implementation Order

| # | Change                                                     | Risk   | Tokens Impact                                          | Dependency         |
| - | ---------------------------------------------------------- | ------ | ------------------------------------------------------ | ------------------ |
| 1 | Cognitive Complexity Gate                                  | Low    | Saves ~800/msg for 40% of traffic                      | None               |
| 2 | PresentStream uses history                                 | Low    | +150 tokens (standard/deep only)                       | None               |
| 3 | Merge prompt rewrite (CoT + contradiction detection)       | Medium | ~same tokens, better accuracy                          | None               |
| 4 | Remove hardcoded denial patterns (after 2-week validation) | Low    | -100 tokens                                            | After #3 validated |
| 5 | Importance scoring in memory                               | Low    | ~30 tokens avg (hybrid: heuristic + LLM for grey zone) | None               |
| 6 | Emotional trajectory                                       | Low    | +100 tokens (standard/deep only)                       | None               |
| 7 | Pre-retrieval intent extraction (deep path only)           | Medium | +200 tokens (~15% of messages)                         | After #1           |

**Recommendation:** Start with #1 (Complexity Gate) — it's the highest-impact, lowest-risk change and immediately cuts token costs.

---



The Cognitive Complexity Gate can **replace the Traffic Cop for simple messages** and  **upgrade the thinking model for complex ones** :

| Complexity                    | Thinking Model (cognition)                   | Response Model                                  | Traffic Cop?                           |
| ----------------------------- | -------------------------------------------- | ----------------------------------------------- | -------------------------------------- |
| **Fast** ("hi", emojis) | *None — skip cognition*                   | Gemini Flash (hardcoded, no Traffic Cop needed) | **Skipped** — saves ~100 tokens |
| **Standard**            | Gemini Flash (current behavior)              | Traffic Cop decides (current behavior)          | Yes                                    |
| **Deep**                | **Gemini 3 Pro** (upgraded from Flash) | Traffic Cop decides, but biased toward Pro/Opus | Yes                                    |

The key insight: **on the fast path, you save TWO LLM calls** — both the Traffic Cop and the dual cognition. On the deep path, you spend more on thinking but get dramatically better contradiction detection and emotional reasoning.

Want me to update the implementation plan with this MoA integration? Specifically:

1. **Fast path:** Skip both Traffic Cop AND dual cognition → straight to ![](vscode-file://vscode-app/Applications/Antigravity.app/Contents/Resources/app/extensions/theme-symbols/src/icons/files/python.svg)

   call_gemini_flash for response
2. **Deep path:** Use ![](vscode-file://vscode-app/Applications/Antigravity.app/Contents/Resources/app/extensions/theme-symbols/src/icons/files/python.svg)

   call_ag_oracle (Gemini 3 Pro) for the merge/thinking step instead of Flash
3. Keep standard path as-is (Flash for thinking, Traffic Cop for response routing)

This would make the fast path go from  **4 LLM calls → 1** , and give the deep path Pro-grade reasoning where it actually matters.

## Verification Plan

### Automated Tests

1. **Complexity gate test:** Feed 50 sample messages (mix of greetings, normal, complex) and verify correct routing
2. **Contradiction detection test:** Feed 10 denial scenarios in English, Bengali, and sarcasm — verify the new merge prompt catches all of them without the hardcoded patterns
3. **Emotional trajectory test:** Simulate 5 sessions over 3 days, verify trajectory injection correctly shows peaks and recent mood

### Manual Testing

1. Send "hi" via WhatsApp → verify response time is faster (no cognition delay)
2. Have a multi-turn conversation with escalating frustration → verify inner monologue reflects awareness
3. Deny a DSA problem you've solved → verify bot challenges you (without hardcoded patterns)
4. Use vague reference ("that thing from yesterday") → verify bot either resolves it correctly or asks a clarifying question

### Monitoring

- Log `complexity_class` for every message for 1 week to validate the gate distribution
- Log token counts per message before/after to verify savings
- Log when LLM-based contradiction detection disagrees with old hardcoded detection (during 2-week fallback period)
