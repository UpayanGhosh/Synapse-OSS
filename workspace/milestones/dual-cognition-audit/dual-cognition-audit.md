# Dual Cognition Engine — Architecture Audit

> Audited: 2026-04-01 | Scope: `workspace/sci_fi_dashboard/dual_cognition.py` + gateway integration

## Executive Summary

**Will Dual Cognition auto-start?** YES — singleton instantiated at module load, called on every message in `persona_chat()`.

**Will it work correctly?** MOSTLY — the architecture is sound, but 4 crash-risk edge cases and zero tests mean production incidents waiting to happen. Adds 5-15s latency per message on standard/deep paths.

**Test coverage?** ZERO — no Dual Cognition-specific tests exist.

---

## How Dual Cognition Works (When It Works)

```
Every Message (persona_chat)
  │
  ├─ api_gateway.py:644 — dual_cognition.think()
  │   ├─ classify_complexity(message, history)
  │   │   ├─ FAST: message in FAST_PHRASES (51 entries) OR ≤3 words → 0 LLM calls
  │   │   ├─ STANDARD: default → 2-3 LLM calls
  │   │   └─ DEEP: code/analysis/multi-topic signals → 3-4 LLM calls
  │   │
  │   ├─ FAST PATH → returns CognitiveMerge with empty fields (instant)
  │   │
  │   ├─ STANDARD PATH:
  │   │   ├─ asyncio.gather(_analyze_present(), _recall_memory()) [parallel]
  │   │   └─ _merge_streams() [sequential after]
  │   │
  │   └─ DEEP PATH:
  │       ├─ _extract_search_intent() [sequential first — BUG: should be parallel]
  │       ├─ asyncio.gather(_analyze_present(), _recall_memory()) [parallel]
  │       └─ _merge_streams(use_cot=True) [sequential after]
  │
  ├─ api_gateway.py:650 — build_cognitive_context(merge)
  │   └─ Returns ~200 token string injected into system prompt
  │
  └─ LLM call with cognitive context included
```

**Scope:** Only active on `/chat/the_creator` and `/chat/the_partner`. NOT used on `/chat` (webhook), `/v1/chat/completions`, or WebSocket endpoint.

---

## CRITICAL BUGS (2)

### C1: Zero Test Coverage

**Severity:** CRITICAL — no safety net for any other bugs

```bash
find workspace/tests -name "*dual*" -o -name "*cognition*" -o -name "*cognitive*"
# Returns: NOTHING
```

No tests for:
- `classify_complexity()` with FAST_PHRASES, deep signal detection, word count edge cases
- `think()` exception handling paths
- `_analyze_present()` JSON parsing and fallback behavior
- `_recall_memory()` with empty/failing memory engine
- `_merge_streams()` CoT vs non-CoT paths
- Full integration: message in → CognitiveMerge out

---

### C2: No Timeout Wrapper — Gateway Hangs on LLM Stall

**File:** `api_gateway.py:644`
**Severity:** CRITICAL — entire request hangs if any LLM call stalls

```python
# CURRENT (BROKEN):
cognitive_merge = await dual_cognition.think(
    user_message=user_msg, ...
)
# If LLM hangs, this awaits forever — no timeout, no cancellation

# CORRECT:
try:
    cognitive_merge = await asyncio.wait_for(
        dual_cognition.think(user_message=user_msg, ...),
        timeout=synapse_config.raw.get("session", {}).get("dual_cognition_timeout", 5.0)
    )
except asyncio.TimeoutError:
    print(f"[WARN] Dual cognition timed out, using empty context")
    cognitive_merge = CognitiveMerge()
```

**Impact:** litellm has a 60s timeout internally, but it's per-call. On DEEP path (3-4 calls), a stall on any call means 60s+ of gateway blocking with no response to the user.

---

## MAJOR BUGS (6)

### M1: History Corruption Crash

**File:** `dual_cognition.py:224` and `:391`
**Severity:** HIGH — TypeError crash, not graceful degradation

```python
# CURRENT (line 224):
recent_context = "\n".join(f"{m['role']}: {m['content'][:100]}" for m in last_3)
# If history contains None or dicts missing 'role'/'content' → TypeError

# CURRENT (line 391 in _extract_search_intent):
recent = "\n".join(f"{m['role']}: {m['content'][:80]}" for m in (history or [])[-3:])
# Same risk

# CORRECT:
last_3 = [m for m in (history or [])[-3:] if isinstance(m, dict) and 'role' in m and 'content' in m]
```

**Impact:** Any malformed message in history (corruption, schema change, bug elsewhere) causes dual cognition to raise TypeError, which bubbles to api_gateway's outer try-except and returns a blank cognitive context. Silent data loss.

---

### M2: JSON Extraction IndexError from Malformed LLM Response

**File:** `dual_cognition.py:257` and `:365`
**Severity:** MEDIUM — fragile but fallback is mostly safe

```python
# CURRENT (line 257 in _analyze_present):
if "```" in text:
    text = text.split("```")[1].replace("json", "").strip()
    #                          ^ IndexError if only ONE ``` in response
```

**Test case:** LLM returns `"Here's the analysis: ```json\n{...}"` (opening fence, no closing)
- `text.split("```")` → `["Here's the analysis: ", "json\n{...}"]` ✓ (works)
- LLM returns `"```"` alone → `split("```")` → `["", ""]` → `[1] = ""` → fine
- LLM returns `"Note: use backtick ` for code"` → `split("```")` → only 1 element → **IndexError**

**Fix:**
```python
if "```" in text:
    parts = text.split("```")
    if len(parts) > 1:
        text = parts[1].replace("json", "").strip()
```

Also applies identically at line 365 in `_merge_streams()`.

---

### M3: Double Memory Query — 2x Latency

**File:** `dual_cognition.py:278` AND `api_gateway.py:612`
**Severity:** MEDIUM — performance, not correctness

```python
# dual_cognition._recall_memory() — line 278:
results = self.memory.query(message, limit=5, with_graph=True)

# api_gateway.persona_chat() — line 612 (SEPARATE query):
memory_response = memory_engine.query(user_msg, limit=3)
```

Both query the same SQLite+Qdrant databases for the same message, seconds apart.

**Fix:** Pass memory results into dual_cognition instead of re-querying:
```python
# In api_gateway.py, query once:
memory_response = memory_engine.query(user_msg, limit=5, with_graph=True)

# Pass to dual_cognition:
cognitive_merge = await dual_cognition.think(
    user_message=user_msg,
    pre_cached_memory=memory_response,  # NEW PARAM
    ...
)
```

---

### M4: DEEP Path Sequential When It Could Be Parallel

**File:** `dual_cognition.py:185-194`
**Severity:** MEDIUM — wastes 2-3s on every DEEP message

```python
# CURRENT (sequential then parallel):
recall_query = await self._extract_search_intent(...)  # LINE 185 — sequential FIRST
present, memory = await asyncio.gather(               # Then parallel
    self._analyze_present(...),
    self._recall_memory(recall_query or message, ...),
)

# OPTIMIZED (all 3 parallel):
search_intent, present, _ = await asyncio.gather(
    self._extract_search_intent(user_message, conversation_history, llm_fn),
    self._analyze_present(user_message, conversation_history, llm_fn),
    asyncio.sleep(0),  # placeholder
)
# Then recall memory with resolved search intent
memory = await self._recall_memory(search_intent or user_message, chat_id, target)
```

Or, since `_recall_memory` doesn't need search intent for the DB query (just uses it to improve the query), a simpler fix is to run all three in parallel and use the message as fallback:

```python
search_task = asyncio.create_task(self._extract_search_intent(...))
present, memory = await asyncio.gather(
    self._analyze_present(...),
    self._recall_memory(user_message, chat_id, target),  # use message as initial query
)
search_intent = await search_task  # probably already done
```

---

### M5: No Disable Flag in Config

**File:** `api_gateway.py:644`
**Severity:** MEDIUM — can't disable without code change

No way to turn off dual cognition for debugging, cost reduction, or fast-path scenarios.

```python
# BEFORE (no check):
cognitive_merge = await dual_cognition.think(...)

# AFTER:
if synapse_config.raw.get("session", {}).get("dual_cognition_enabled", True):
    cognitive_merge = await dual_cognition.think(...)
else:
    cognitive_merge = CognitiveMerge()
```

**synapse.json addition:**
```json
{
  "session": {
    "dual_cognition_enabled": true,
    "dual_cognition_timeout": 5.0
  }
}
```

---

### M6: Dual Cognition Doesn't Inform Traffic Cop

**File:** `api_gateway.py:643-690`
**Severity:** MEDIUM — missed optimization, not a bug

Traffic Cop runs after dual cognition but ignores its output:

```python
cognitive_merge = await dual_cognition.think(...)   # has tension_level, response_strategy
# ...
classification = await route_traffic_cop(user_msg)  # separate LLM call, ignores merge
```

The `CognitiveMerge.response_strategy` field ("be_direct", "explore_with_care", "analytical") maps naturally to Traffic Cop roles. Could skip the Traffic Cop LLM call ~50% of the time:

```python
# Map cognitive strategy → role (skip traffic cop)
STRATEGY_TO_ROLE = {
    "be_direct": "casual",
    "analytical": "analysis",
    "explore_with_care": "analysis",
}
if cognitive_merge.response_strategy in STRATEGY_TO_ROLE:
    classification = STRATEGY_TO_ROLE[cognitive_merge.response_strategy]
else:
    classification = await route_traffic_cop(user_msg)  # fallback only
```

Saves 1 LLM call ~50% of messages.

---

## MINOR ISSUES (4)

### m1: toxic_scorer Passed But Never Used
`dual_cognition.py:32` — `self.toxic_scorer = toxic_scorer` is stored but never called in any method. Either remove it or use it in `_analyze_present()` to filter toxic content before sentiment analysis.

### m2: All Logging via print()
No structured logging. `print(f"[WARN] Present stream failed: {e}")` at multiple locations. Should use `logging.getLogger("dual_cognition")`. Makes it hard to filter or suppress noise.

### m3: No Distinction Between Memory Miss vs Memory Error
`_recall_memory()` logs the same `[WARN]` whether memory DB is locked (real error) or user has no memories (expected). Confusing in fresh installs.

### m4: emotional_trajectory Wired But Rarely Present
`dual_cognition.py:301` uses `emotional_trajectory` if available, but api_gateway never passes it (line 644-650). The parameter exists but is always `None` in practice.

---

## WHAT WORKS WELL

| Component | Status | Notes |
|-----------|--------|-------|
| classify_complexity() | Solid | FAST_PHRASES frozenset, clean signal detection |
| Standard path parallel | Solid | `asyncio.gather()` for present+memory runs simultaneously |
| JSON parsing fallback | Solid | All fields have safe `.get()` defaults |
| Graceful degradation | Solid | Every method returns safe defaults on any exception |
| FAST path | Solid | 51 phrases bypass all LLM calls instantly |
| build_cognitive_context() | Solid | Clean string assembly from merge fields |

---

## PRIORITIZED FIXES

### Priority 1: Stability (Do First)

**Fix C2: Add timeout wrapper**
```python
# api_gateway.py — replace dual_cognition.think() call (line 644):
try:
    dc_timeout = synapse_config.raw.get("session", {}).get("dual_cognition_timeout", 5.0)
    cognitive_merge = await asyncio.wait_for(
        dual_cognition.think(
            user_message=user_msg,
            conversation_history=messages,
            chat_id=chat_id,
            target=target,
            llm_fn=call_gemini_flash,
        ),
        timeout=dc_timeout,
    )
except asyncio.TimeoutError:
    print(f"[WARN] Dual cognition timed out after {dc_timeout}s")
    cognitive_merge = CognitiveMerge()
except Exception as e:
    print(f"[WARN] Dual cognition failed: {e}")
    cognitive_merge = CognitiveMerge()
```
**Effort:** 5 lines. **Risk:** None.

**Fix M1: Guard history iteration**
```python
# dual_cognition.py — lines 222-224 and 391:
# BEFORE:
last_3 = history[-3:]
# AFTER:
last_3 = [m for m in (history or [])[-3:] if isinstance(m, dict) and 'role' in m and 'content' in m]
```
**Effort:** 2 lines (both locations). **Risk:** None.

**Fix M2: Safe JSON extraction**
```python
# dual_cognition.py — lines 257 and 365:
# BEFORE:
text = text.split("```")[1].replace("json", "").strip()
# AFTER:
parts = text.split("```")
if len(parts) > 1:
    text = parts[1].replace("json", "").strip()
```
**Effort:** 3 lines per location. **Risk:** None.

---

### Priority 2: Performance (Do Second)

**Fix M3: Eliminate double memory query**

Pass memory results from the gateway into dual cognition instead of re-querying. Requires adding a `pre_cached_memory` parameter to `think()` and `_recall_memory()`.

**Effort:** ~10 lines. **Risk:** Low.

**Fix M4: Parallelize DEEP path**

Move `_extract_search_intent()` to run concurrently with `_analyze_present()`. Saves 2-3s on deep analysis messages.

**Effort:** ~8 lines. **Risk:** Low.

---

### Priority 3: Configuration (Do Third)

**Fix M5: Add disable flag**
```json
// synapse.json:
{
  "session": {
    "dual_cognition_enabled": true,
    "dual_cognition_timeout": 5.0
  }
}
```
```python
// api_gateway.py — gate the think() call:
if synapse_config.raw.get("session", {}).get("dual_cognition_enabled", True):
    cognitive_merge = await asyncio.wait_for(dual_cognition.think(...), timeout=dc_timeout)
else:
    cognitive_merge = CognitiveMerge()
```
**Effort:** 5 lines. **Risk:** None.

---

### Priority 4: Integration (Do Fourth)

**Fix M6: Use cognitive response_strategy to skip Traffic Cop**

Map `CognitiveMerge.response_strategy` to a role directly, falling back to Traffic Cop only when needed.

**Effort:** ~10 lines. **Risk:** Low — Traffic Cop remains as fallback.

---

### Priority 5: Test Coverage (Do Last)

**Create `workspace/tests/test_dual_cognition.py`:**

```python
class TestClassifyComplexity:
    def test_fast_phrase_returns_fast(self): ...
    def test_short_message_returns_fast(self): ...
    def test_code_signal_returns_deep(self): ...
    def test_long_message_returns_deep(self): ...
    def test_normal_message_returns_standard(self): ...

class TestThink:
    def test_fast_path_no_llm_calls(self): ...
    def test_standard_path_returns_cognitive_merge(self): ...
    def test_none_history_safe(self): ...
    def test_malformed_history_safe(self): ...
    def test_llm_exception_returns_fallback(self): ...
    def test_llm_timeout_returns_fallback(self): ...

class TestAnalyzePresent:
    def test_json_parsing_success(self): ...
    def test_malformed_json_returns_defaults(self): ...
    def test_incomplete_markdown_fence_safe(self): ...

class TestBuildCognitiveContext:
    def test_empty_merge_returns_empty_string(self): ...
    def test_populated_merge_returns_string(self): ...
```

**Effort:** ~150 lines. **Risk:** None.

---

## Fix Summary

| # | Fix | File(s) | Lines | Priority |
|---|-----|---------|-------|----------|
| C2 | Timeout wrapper | api_gateway.py | 10 | P1 |
| M1 | History guard | dual_cognition.py (×2) | 4 | P1 |
| M2 | JSON extraction safe | dual_cognition.py (×2) | 6 | P1 |
| M3 | Eliminate double memory | dual_cognition.py, api_gateway.py | 10 | P2 |
| M4 | Parallelize DEEP path | dual_cognition.py | 8 | P2 |
| M5 | Config disable flag | api_gateway.py, synapse.json | 5 | P3 |
| M6 | Skip traffic cop via strategy | api_gateway.py | 10 | P4 |
| C1 | Test suite | tests/test_dual_cognition.py (new) | 150 | P5 |

**Total: ~200 lines across 3 files + 1 new test file.**
**Estimated effort: 1 focused session.**
