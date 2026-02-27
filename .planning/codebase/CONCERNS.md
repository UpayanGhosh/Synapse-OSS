# Codebase Concerns

**Analysis Date:** 2026-02-27

## Tech Debt

### 1. Model Routing Placeholders

**Issue:** The LLM routing system has multiple placeholder/credit-saver workarounds instead of proper implementation.

**Files:**
- `workspace/sci_fi_dashboard/api_gateway.py` (lines 339-341, 462-490)

**Impact:**
- `MODEL_CODING = "gemini-3-flash"` (line 339) — claims to route to Claude Sonnet 4.5 but actually uses Gemini Flash to save credits
- `MODEL_REVIEW = "gemini-3-pro-high"` (line 341) — claims to route to Claude Opus 4.6 but uses Gemini Pro instead
- Comments state "Placeholder: Routing to Gemini Flash/Pro but using Coding/Review Model ID if credits allowed" (lines 463, 488)
- This creates confusion in logs/output vs actual behavior — the system prints "Routing to Claude" but executes Gemini

**Fix approach:**
1. Replace placeholders with proper conditional routing based on available credits/API keys
2. Update model constant names to reflect actual routing (`MODEL_CODING_FALLBACK`, etc.)
3. Implement credit-aware router that upgrades when credits are available
4. Update print statements to show actual model being used, not desired model

---

### 2. Broad Exception Handling

**Issue:** Multiple locations catch `Exception` generically instead of specific error types.

**Files:**
- `workspace/sci_fi_dashboard/api_gateway.py` (lines 103, 143, 243-244)
- `workspace/sci_fi_dashboard/retriever.py` (lines 56, 67)
- `workspace/sci_fi_dashboard/dual_cognition.py` (various locations)
- `workspace/sci_fi_dashboard/toxic_scorer_lazy.py` (line 85)

**Impact:**
- Masks different failure modes (network timeouts vs invalid JSON vs missing imports)
- Makes debugging harder — can't distinguish between recoverable errors and critical failures
- Silent failures in fallback mode (e.g., embedding model initialization at line 56-68)

**Fix approach:**
1. Replace `except Exception` with specific exceptions: `asyncio.TimeoutError`, `json.JSONDecodeError`, `httpx.HTTPError`, `ImportError`
2. Add targeted logging for each error type with different verbosity levels
3. Implement retry logic only for transient errors (network), fail fast on config errors
4. Propagate critical errors instead of swallowing them silently

---

### 3. Import Path Fallbacks

**Issue:** Multiple modules have brittle try-except import chains to handle different calling contexts.

**Files:**
- `workspace/sci_fi_dashboard/memory_engine.py` (lines 13-24)
- `workspace/sci_fi_dashboard/retriever.py` (lines 19-22)
- `workspace/sci_fi_dashboard/db.py` (implied by memory_engine/retriever patterns)

**Impact:**
- Code works from different directories but is unmaintainable — unclear which import succeeds in production
- Fragile when reorganizing modules or moving code between files
- Makes IDE navigation and type checking difficult

**Fix approach:**
1. Establish single authoritative import strategy (relative imports from package root or absolute imports)
2. Configure `PYTHONPATH` consistently in startup scripts (`synapse_start.sh`, `synapse_onboard.sh`)
3. Replace try-except chains with explicit `__init__.py` exports
4. Add type hints and use `from __future__ import annotations` for forward references

---

## Known Bugs

### 1. Unicode Encoding Error on Windows Startup

**Symptoms:** API Gateway fails to start on Windows with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'`

**Files:** `workspace/sci_fi_dashboard/smart_entity.py` (line 21)

**Trigger:** Starting `uvicorn` without UTF-8 encoding flag on Windows CMD/PowerShell

**Workaround:** Use `python -X utf8` or set `PYTHONUTF8=1` before running uvicorn (documented in `problems_faced.md`)

**Root cause:** Code prints emoji characters (✅, ⚠️) in print statements. Windows console defaults to `cp1252` encoding which cannot represent Unicode emoji.

**Fix approach:**
1. Replace emoji in runtime print statements with ASCII equivalents or remove entirely
2. OR: Create wrapper that safely encodes emoji to emoji-code descriptions
3. Add check in startup scripts to force UTF-8 mode automatically on Windows
4. Update `synapse_start.bat` to include `-X utf8` flag by default

---

### 2. Memory Leak in LazyToxicScorer Timer

**Issue:** Threading timer may not be properly cancelled on application shutdown.

**Files:** `workspace/sci_fi_dashboard/toxic_scorer_lazy.py` (lines 54-59)

**Symptoms:** Long-running instances may accumulate uncancelled Timer threads

**Current code:**
```python
self._cleanup_timer = threading.Timer(self.idle_timeout, self._unload)
self._cleanup_timer.daemon = True
self._cleanup_timer.start()
```

**Risk:** If API gateway shuts down while timer is pending, daemon thread still holds reference to `_unload()`. Multiple calls to `_schedule_cleanup()` create new timers without cancelling old ones.

**Fix approach:**
1. Always call `self._cleanup_timer.cancel()` before creating new timer
2. Add explicit cleanup method called on application shutdown: `@app.on_event("shutdown")`
3. Track all cleanup timers in a list and cancel all on shutdown
4. Use `asyncio.Task` instead of `threading.Timer` for consistency with FastAPI's async context

---

## Security Considerations

### 1. Path Traversal Validation in Sentinel

**Risk:** While Sentinel gateway has path traversal detection, edge cases may exist.

**Files:** `workspace/sci_fi_dashboard/sbs/sentinel/gateway.py` (lines 89-95)

**Current mitigation:** Path is resolved and checked to be within project boundary with `_is_within_project()` check.

**Potential gaps:**
- Symlink handling not explicitly documented — could a symlink point outside project root?
- Windows path handling (backslashes vs forward slashes) not explicitly tested
- Relative path `../../../etc/passwd` may bypass checks if resolution doesn't handle all cases

**Recommendations:**
1. Add explicit symlink detection: reject all symlinks or resolve and re-check final path
2. Add Windows path normalization tests (UNC paths, short names like `PROGRA~1`)
3. Document exact path resolution algorithm and test edge cases
4. Add fuzzing tests for path traversal with common bypass patterns
5. Log all denied access attempts with full context (agent, operation, original path)

---

### 2. API Key Exposure in Error Messages

**Risk:** Error messages may inadvertently leak API keys or sensitive tokens.

**Files:**
- `workspace/sci_fi_dashboard/api_gateway.py` (various error logging)
- `workspace/sci_fi_dashboard/gateway/sender.py` (if logging response bodies)

**Current state:** Error messages log response bodies from API calls, which could contain sensitive data.

**Example vulnerability:**
```python
print(f"⚠️ Gateway Error ({resp.status_code}): {resp.text}")  # line 317
```

If the error response contains an auth token or API key, it gets logged.

**Recommendations:**
1. Sanitize all error messages before logging — replace known sensitive patterns with `[REDACTED]`
2. Add constant for sensitive key patterns: `API_KEY_PATTERNS = [r"sk-", r"gsk_", r"ghp_"]`
3. Implement `sanitize_error_message(text)` function used by all error handlers
4. Log full error details only at DEBUG level (disabled in production)
5. Audit logs for historical leaks using `grep -r "sk-\|gsk_\|ghp_"` on log files

---

### 3. WhatsApp Sender Target Validation

**Risk:** Phone number validation in `send_via_cli()` is minimal.

**Files:** `workspace/sci_fi_dashboard/api_gateway.py` (lines 66-105)

**Current validation:** Only strips non-digits and adds `+` prefix. Does not validate:
- Country code validity
- Phone number format per region
- Whether the number is actually the authorized user

**Scenario:** An attacker could craft a chat request to send messages to arbitrary phone numbers.

**Recommendations:**
1. Maintain allowlist of authorized recipient phone numbers (load from env or DB)
2. Cross-check `target` against `channels.whatsapp.allowFrom` config
3. Add recipient validation before any `send_via_cli()` call
4. Log all send attempts with sender, target, timestamp to audit trail
5. Implement rate limiting per target (e.g., max 10 messages/hour per number)

---

## Performance Bottlenecks

### 1. Qdrant Vector Search Without Timeout

**Problem:** Vector search queries may hang if Qdrant connection is slow or unavailable.

**Files:** `workspace/sci_fi_dashboard/retriever.py` (vector search code)

**Cause:** Qdrant API calls use default timeout which may be very long.

**Impact:** If Qdrant is slow, entire message processing stalls, blocking the async queue.

**Improvement path:**
1. Add explicit timeout to all Qdrant operations: `timeout=2.0` for search, `timeout=5.0` for index operations
2. Implement circuit breaker: if Qdrant is down, fall back to FTS-only for first 30s, then retry connection
3. Add metric: track vector search latency per query type
4. Implement graceful degradation: if search takes >3s, return FTS results instead of waiting

---

### 2. FlashRank Reranking On Every Query

**Problem:** FlashRank model loads and runs on every query even when confidence is high.

**Files:** `workspace/sci_fi_dashboard/retriever.py` (reranking logic)

**Current optimization:** Fast gate returns immediately if `score > 0.80`, but this only applies when initial results are highly confident.

**Issue:** On lower-confidence queries, FlashRank loads, encodes all candidates, and reranks — this is expensive for queries with 50+ candidates.

**Improvement path:**
1. Implement two-tier reranking: first pass (fast) reranks top-5, second pass (slow) full rerank only if tie-breaking needed
2. Lazy-load FlashRank model similar to `ToxicScorer` — keep loaded between queries, unload after idle
3. Cache reranked results by query embedding to avoid recomputing for similar queries
4. Add metric: track rerank latency and % of queries that hit fast gate

---

### 3. SBS Batch Processing Blocks on Large Conversation Logs

**Problem:** Batch processor reads entire conversation log into memory and processes line-by-line.

**Files:** `workspace/sci_fi_dashboard/sbs/processing/batch.py` (lines 1-100)

**Trigger:** When conversation log exceeds 10MB, processing becomes slow and memory-intensive.

**Impact:** If batch processing runs while a user sends a message, that message may be delayed waiting for profile rebuild.

**Improvement path:**
1. Implement streaming log processor: read in chunks, process incrementally
2. Use separate thread/process for batch processing so it doesn't block message handling
3. Cache intermediate results (e.g., sentiment per 100-message window) to avoid recomputing
4. Add checkpoint system: save processing state every 500 messages so restart doesn't reprocess

---

## Fragile Areas

### 1. Database Connection Management

**Files:** `workspace/sci_fi_dashboard/sqlite_graph.py` (lines 16-26), `workspace/sci_fi_dashboard/memory_engine.py`

**Why fragile:** Each `_conn()` call creates a new connection, relies on garbage collection to close. No connection pooling.

**Safe modification:**
- Always use context managers: `with self._conn() as conn:`
- Consider implementing a simple connection pool (max 5 concurrent connections)
- Add test that verifies no connection leaks: track open connections before/after 1000 operations
- Test coverage gaps: no tests verify WAL mode actually works, no tests for concurrent writes

---

### 2. Async Worker Queue Interaction

**Files:** `workspace/sci_fi_dashboard/gateway/worker.py`, `api_gateway.py` (worker initialization)

**Why fragile:** Two async workers share a single queue but there's no deadlock detection. If one worker crashes, the other continues but messages stay in queue.

**Safe modification:**
- Add health check for worker status every 30s
- Implement automatic worker restart if crash detected
- Add lock around task status updates to prevent race conditions
- Test coverage gaps: no stress test with worker crashing mid-process

---

### 3. Sentinel Manifest Integrity Check

**Files:** `workspace/sci_fi_dashboard/sbs/sentinel/gateway.py` (lines 75-80)

**Why fragile:** Integrity check is critical (raises `SentinelError` on failure) but manifest hash is computed once at init. If manifest file is modified between checks, tampering detection might lag.

**Safe modification:**
- Re-verify manifest hash periodically (every 100 operations or every 5 minutes)
- Implement manifest versioning: increment version when changing protection levels
- Store manifest hash in separate read-only file that application doesn't write to
- Test coverage gaps: no tests that modify manifest and verify tampering is detected

---

## Scaling Limits

### 1. In-Memory Task History

**Resource:** Task queue stores all task history in memory.

**Current capacity:** `max_history = 500` tasks (line 37 in `gateway/queue.py`)

**Limit:** At 1KB per task JSON, 500 tasks = 500KB overhead. At 100 messages/day = 50 days before clearing. OK for now, but if peak traffic hits 1000 msg/day, history fills in 5 days.

**Scaling path:**
1. Persist task history to SQLite instead of in-memory list
2. Keep only last 1000 tasks in memory, page older tasks to disk on query
3. Implement circular buffer: when `_task_history` hits limit, write to DB and clear memory

---

### 2. SQLite Concurrent Writes

**Resource:** Both memory and knowledge graph databases use SQLite with WAL mode.

**Limit:** SQLite WAL supports multiple readers but only one writer at a time. At peak: 2 workers writing simultaneously = contention.

**Current mitigation:** Retry decorator with exponential backoff (memory_engine.py lines 27-47).

**Scaling path:**
1. For knowledge graph: implement sharded graph (split nodes A-M vs N-Z) so writes don't contend
2. For memory: implement write queue that serializes inserts instead of parallel writes
3. Monitor lock contention: log when `sqlite3.OperationalError` retries > 2 times
4. Consider migration to PostgreSQL if contention becomes severe (>100ms per write)

---

### 3. Qdrant Memory Usage for Large Collections

**Resource:** Qdrant holds all vectors in memory (default config).

**Current:** If 10,000 documents with 768-dim embeddings = 10K × 768 × 4 bytes = ~30MB. Safe.

**Limit:** At 1M documents = ~3GB in-memory VRAM. On Mac Air with 8GB RAM, leaves little headroom.

**Scaling path:**
1. Monitor Qdrant memory usage in health check endpoint
2. Implement cleanup job: archive vectors older than 1 year, delete if storage hits 80% threshold
3. Consider Qdrant disk storage mode if collection grows beyond 100K documents
4. Add metric to predict when archive/cleanup is needed

---

## Dependencies at Risk

### 1. Qdrant Python Client

**Risk:** `qdrant-client>=1.6.0` is pinned to v1.x but v2.0 is likely breaking.

**Files:** `requirements.txt` (line 33), `memory_engine.py` (qdrant_handler import)

**Impact:** When qdrant-client v2.0 is released, import statements or API calls will break.

**Migration plan:**
1. Add `qdrant-client<2.0.0` to requirements.txt now to prevent auto-upgrade
2. In parallel, test v2.0 in a separate branch by updating imports
3. Timeline: migrate before qdrant-client v1.x reaches end-of-life
4. Add migration notes to CONTRIBUTING.md

---

### 2. Transformers & Torch

**Risk:** `transformers>=4.35.0` and `torch>=2.0.0` have frequent releases with breaking changes.

**Files:** `requirements.txt` (lines 29-30), `toxic_scorer_lazy.py` (line 29)

**Impact:** Toxic-BERT model loading may fail if transformers/torch change internal APIs. Hardware compatibility (CPU vs MPS vs GPU) is fragile.

**Migration plan:**
1. Pin minor versions: `transformers>=4.35,<4.40` and `torch>=2.0,<2.3`
2. Test regularly on target hardware (Mac Air M1, Windows PC with Ollama)
3. Add test that verifies Toxic-BERT loads and runs at least once on startup
4. Monitor transformers/torch releases for critical security patches

---

### 3. FastAPI/Uvicorn

**Risk:** `fastapi>=0.104.0` and `uvicorn>=0.24.0` are bleeding-edge versions.

**Files:** `requirements.txt` (lines 7-8), `api_gateway.py` (FastAPI usage)

**Impact:** Newer versions may change async/await behavior or WebSocket handling.

**Migration plan:**
1. Pin to stable versions: `fastapi>=0.104,<0.110` and `uvicorn>=0.24,<0.25`
2. Test API endpoints on each FastAPI/Uvicorn upgrade
3. Monitor FastAPI security releases and apply within 1 week

---

## Missing Critical Features

### 1. No Request Rate Limiting

**Problem:** API endpoints have no rate limiting. A malicious user could spam `/chat` or `/whatsapp/enqueue`.

**Blocks:** Can't safely expose API to multiple users without DDoS protection.

**Quick fix:** Add `slowapi` (FastAPI rate limiter):
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)
@app.post("/chat")
@limiter.limit("10/minute")
async def chat(...): ...
```

---

### 2. No Request Authentication (API endpoints)

**Problem:** `/chat`, `/ingest`, `/add`, `/query` endpoints accept any request without authentication.

**Blocks:** Sensitive operations (ingest facts, query private knowledge) are open to anyone.

**Quick fix:** Implement API key check:
```python
def verify_api_key(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != os.environ.get("API_TOKEN"):
        raise HTTPException(401, "Invalid token")
```

---

### 3. No Audit Logging for Memory Operations

**Problem:** Adding facts to knowledge graph (`/ingest`, `/add`) is not logged.

**Blocks:** Can't trace who added false information or when sensitive facts entered the system.

**Quick fix:** Add JSONL audit log before DB writes:
```python
def log_operation(operation, user, target, payload):
    with open("logs/operations.jsonl", "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "user": user,
            "target": target,
            "payload_hash": hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        }) + "\n")
```

---

## Test Coverage Gaps

### 1. No E2E Tests for Message Processing Pipeline

**What's not tested:** Full flow from WhatsApp webhook → FloodGate → Dedup → Queue → Worker → LLM call → response send.

**Files:** `workspace/tests/test_e2e.py` exists but is limited to single-component tests.

**Risk:** A regression in one component (e.g., deduplicator) could break production without failing tests.

**Priority:** High — this is the critical path.

**Test case to add:**
```python
@pytest.mark.e2e
async def test_full_message_flow_from_webhook_to_send():
    # 1. POST to /whatsapp/enqueue with test message
    # 2. Verify task enqueued with correct status
    # 3. Verify deduplicator blocks duplicate within 5 mins
    # 4. Poll /whatsapp/status/{id} until completed
    # 5. Verify response was sent via mock CLI
    # 6. Verify message was logged to SBS
```

---

### 2. No Concurrency Tests for Database

**What's not tested:** Multiple workers writing to knowledge_graph.db simultaneously.

**Files:** `workspace/tests/test_integration.py` has basic graph tests but no concurrent write tests.

**Risk:** Race condition in graph writes could silently lose data or corrupt indexes.

**Priority:** High — affects data integrity.

**Test case to add:**
```python
@pytest.mark.asyncio
async def test_concurrent_graph_writes():
    graph = SQLiteGraph()

    # 10 concurrent workers adding nodes
    async def add_many(prefix):
        for i in range(100):
            graph.add_node(f"{prefix}_node_{i}")

    await asyncio.gather(*[add_many(f"worker_{i}") for i in range(10)])

    # Verify all 1000 nodes added (no silent failures)
    assert graph.count_nodes() == 1000
```

---

### 3. No Tests for Toxic-BERT Model Unload

**What's not tested:** `LazyToxicScorer` actually unloads after idle timeout.

**Files:** `workspace/tests/` — no test for `toxic_scorer_lazy.py` behavior.

**Risk:** Memory leak if unload timer is cancelled unexpectedly or timer doesn't fire.

**Priority:** Medium — affects memory usage on long-running instances.

**Test case to add:**
```python
def test_toxic_scorer_unloads_after_timeout():
    scorer = LazyToxicScorer(idle_timeout=0.1)

    # Load model
    score = scorer.score("test message")
    assert scorer.is_loaded()

    # Wait for unload
    time.sleep(0.2)
    assert not scorer.is_loaded()
```

---

### 4. No Windows Path Handling Tests

**What's not tested:** Sentinel path resolution on Windows (backslashes, UNC paths, short names).

**Files:** `workspace/tests/` — tests assume Unix paths.

**Risk:** Sentinel bypass on Windows where `C:\..\..\etc\hosts` might not be caught.

**Priority:** High for Windows deployment.

**Test case to add:**
```python
@pytest.mark.windows
def test_sentinel_blocks_windows_path_traversal():
    sentinel = Sentinel(Path("C:/project"))

    # Backslash traversal
    with pytest.raises(SentinelError):
        sentinel.check_access("..\\..\\windows\\system32", "read")

    # UNC path escape
    with pytest.raises(SentinelError):
        sentinel.check_access("\\\\server\\share\\..\\..\\", "read")

    # Short filename
    with pytest.raises(SentinelError):
        sentinel.check_access("PROGRA~1/dangerous", "read")
```

---

*Concerns audit: 2026-02-27*
