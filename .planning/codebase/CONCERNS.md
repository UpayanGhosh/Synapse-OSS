# CONCERNS.md — Technical Debt, Known Issues, and Areas of Concern

Synapse-OSS codebase analysis. All paths are absolute from repo root `D:/Shreya/Synapse-OSS/`.

---

## 1. Known Bugs (Confirmed Runtime Failures)

### 1.1 tools_server.py — NOTE: CLAUDE.md description is stale
**Status: Partially resolved, partially new surface**

CLAUDE.md documents a `TypeError` where `read_file`/`write_file` called `Sentinel().agent_read_file()` incorrectly. The current code in `workspace/sci_fi_dashboard/mcp_servers/tools_server.py` has been updated — `read_file` now calls `_sentinel.check_access()` + `read_file_paged()` correctly, and `write_file` calls `agent_write_file()` from `sbs.sentinel.tools`. However, a residual risk remains: `_sentinel` is a module-level global in `workspace/sci_fi_dashboard/sbs/sentinel/tools.py` initialized to `None`. If `init_sentinel()` was never called (e.g., the tools server is run standalone without the gateway lifespan), every tool invocation raises `RuntimeError("Sentinel not initialized")`. The tools server has no guard that calls `init_sentinel()` on its own startup path.

### 1.2 FlashRank Reranker — `token_type_ids` error
**File:** `workspace/sci_fi_dashboard/memory_engine.py` (line 283)

The `ms-marco-TinyBERT-L-2-v2` reranker model can raise a `token_type_ids` error on some transformers versions. The fallback is implemented (falls back to `scored_fallback` tier, logged as `[WARN] Reranker failed`), but the root cause is a transformers/FlashRank version mismatch that has not been pinned. Every production query that fails the fast gate will silently degrade. There is no alerting or metric distinguishing reranker failure from normal scored fallback.

### 1.3 `_check_rate_limit` in `_deps.py` — Not Implemented
**File:** `workspace/sci_fi_dashboard/_deps.py` (lines 204–206)

```python
def _check_rate_limit(request: "Request | None" = None) -> None:
    """Rate-limit guard (not yet implemented — pass-through)."""
    pass
```

This function is registered as a FastAPI `Depends()` on `POST /chat`, `POST /v1/chat/completions`, and the persona chat endpoint in `workspace/sci_fi_dashboard/routes/chat.py` (lines 13–14, 82, 102). The real rate limiter lives in `workspace/sci_fi_dashboard/middleware.py` (`_check_rate_limit`), but `_deps._check_rate_limit` is a no-op stub. The webhook endpoint therefore has **zero rate limiting**. Any caller can flood it without restriction.

### 1.4 `lru_cache` on Instance Method — Shared Cache Across Instances
**File:** `workspace/sci_fi_dashboard/memory_engine.py` (line 110)

```python
@lru_cache(maxsize=500)  # noqa: B019
def get_embedding(self, text: str) -> tuple:
```

The `# noqa: B019` suppresses the `lru_cache-on-instance-method` warning. `lru_cache` on an instance method uses `self` as part of the cache key, which keeps the instance alive forever (the cache holds a strong reference). On a single-singleton pattern this is harmless, but if `MemoryEngine` is ever instantiated more than once (e.g., in tests), old instances will never be garbage collected. The cache also has no TTL — embeddings computed for deleted memories are cached indefinitely.

---

## 2. Security Issues

### 2.1 CORS — Wildcard Origins in Production
**File:** `workspace/sci_fi_dashboard/api_gateway.py`

The gateway applies `CORSMiddleware`. Inspect at runtime — if `allow_origins=["*"]` is used (the FastAPI default when no list is provided), any web origin can send credentialed requests. No CORS configuration was found in `synapse.json` schema, suggesting this defaults wide open.

### 2.2 Gateway Token Auth — Dev-Mode Bypass
**File:** `workspace/sci_fi_dashboard/middleware.py` (lines 76–77)

```python
if not expected:
    return  # No token configured — skip auth (dev mode)
```

If `SYNAPSE_GATEWAY_TOKEN` is not set and `gateway.token` is absent from `synapse.json`, all protected endpoints are completely unauthenticated. This is documented as "dev mode" but there is no startup warning logged that auth is disabled. A misconfigured production deploy would be open.

### 2.3 WebSocket Gateway — Optional Auth
**File:** `workspace/sci_fi_dashboard/gateway/ws_server.py`

The WebSocket endpoint uses `SYNAPSE_GATEWAY_TOKEN` for auth, but the same dev-mode bypass applies. The WebSocket exposes `chat.send`, `sessions.reset`, and `models.list` without mandatory authentication when no token is configured.

### 2.4 Execution MCP Server — Allowlist Can Be Disabled
**File:** `workspace/sci_fi_dashboard/mcp_servers/execution_server.py` (lines 53–54)

```python
_ALLOWED_COMMANDS: set[str] | None = {
    ...
}
# Set to None to disable allowlist (NOT recommended for prod).
```

The comment documents that setting `_ALLOWED_COMMANDS = None` disables the allowlist entirely. This is a code-level footgun — a future contributor might do this for convenience and expose arbitrary shell execution. There is no config-level enforcement preventing this.

### 2.5 `SESSION_TYPE` Hemisphere Read from Environment
**File:** `workspace/sci_fi_dashboard/chat_pipeline.py` (line 109)

```python
env_session = os.environ.get("SESSION_TYPE", "safe")
```

The hemisphere (safe vs. spicy) falls back to an environment variable if not in the request. If the environment is incorrectly set to `"spicy"`, all requests will route through the Vault (local Ollama) regardless of caller intent. This is a misconfiguration risk with no validation at startup.

### 2.6 Sentinel Initialized to Gateway Module's `parent` — Wrong Root
**File:** `workspace/sci_fi_dashboard/_deps.py` (line 151)

```python
init_sentinel(project_root=Path(__file__).parent)
```

`__file__` is `sci_fi_dashboard/_deps.py`, so `parent` is the `sci_fi_dashboard/` directory. This makes Sentinel's project root the dashboard subdirectory, not the repo root or workspace root. Paths in the Sentinel manifest that reference top-level dirs like `synapse.json` or `workspace/` will resolve incorrectly.

---

## 3. Performance Bottlenecks

### 3.1 Toxic-BERT Loaded on Every Message in Safe Mode
**File:** `workspace/sci_fi_dashboard/chat_pipeline.py` (line 165), `workspace/sci_fi_dashboard/toxic_scorer_lazy.py`

`LazyToxicScorer.score()` is called synchronously on every message. The model loads into memory on first call (~600MB), but model loading happens inside a `threading.Lock` which blocks the asyncio event loop for the duration of model load (several seconds on cold start). There is no `asyncio.to_thread()` wrapper around the blocking load. Additionally, the model only supports Apple Silicon MPS acceleration — on Windows/Linux, it runs on CPU.

### 3.2 `SynapseConfig.load()` Called Inside Request Handlers
**File:** `workspace/sci_fi_dashboard/middleware.py` (lines 70, 106)

```python
_cfg = SynapseConfig.load()
```

`SynapseConfig.load()` reads and parses `synapse.json` from disk on every invocation. It is called inside `_require_gateway_auth()` and `validate_api_key()` which run on every protected request. This is a per-request file read with no caching. With 60 req/min rate limit this is 60 disk reads per minute just for auth checks.

### 3.3 Memory Query Not Shared Between `persona_chat` and `_recall_memory` When `llm_fn` Provided
**File:** `workspace/sci_fi_dashboard/dual_cognition.py` (line 344)

```python
results = pre_cached_memory if pre_cached_memory else self.memory.query(...)
```

The `pre_cached_memory` sharing is implemented correctly for the standard and deep paths. However, the `_extract_search_intent` method (line 457) performs a separate LLM call that is **never used** — the method exists but is never called in the current deep path (comment on line 221 states "L-01: Removed _extract_search_intent — result was never used downstream"). Dead code that may confuse future contributors into adding a second memory query.

### 3.4 LanceDB IVF_PQ Index Only Built After 256 Rows
**File:** `workspace/sci_fi_dashboard/vector_store/lancedb_store.py` (line 27)

```python
_INDEX_THRESHOLD = 256  # rows required before building IVF_PQ index
```

Below 256 rows, brute-force ANN search is used. For small deployments or after a fresh install, all vector queries are O(n) brute force. This is documented but not surfaced in health checks — users won't know they're in degraded index mode.

### 3.5 Emotion Trajectory and Cognitive Context Built on Every Message
**File:** `workspace/sci_fi_dashboard/chat_pipeline.py` (lines 316–325)

The full 72-hour emotional trajectory summary is computed and injected as a system message block on every single request, even fast-path "hi" messages. This adds to token count without a bypass for the `fast` complexity path.

---

## 4. Technical Debt

### 4.1 Dual Import Path Pattern Repeated Across Many Files
**Files:** `workspace/sci_fi_dashboard/memory_engine.py` (lines 13–33), `workspace/sci_fi_dashboard/retriever.py` (lines 14–26)

Nearly every module contains try/except import blocks for both `from .module import X` and `from module import X` with sys.path manipulation. This pattern repeats at least 8 times across the codebase and is a symptom of the package not being properly installed (editable install). Running as a raw script vs. as a package gives different import behavior. The correct fix is a consistent editable install via `pip install -e .`.

```python
try:
    from .db import get_db_connection
except ImportError:
    try:
        from db import get_db_connection
    except ImportError:
        import os, sys
        sys.path.append(os.path.dirname(__file__))
        from db import get_db_connection
```

### 4.2 `synapse_config.py` Wide Blast Radius
**File:** `workspace/synapse_config.py`

Imported by 50+ files per CLAUDE.md. `SynapseConfig` is a frozen dataclass but `load()` is not cached — every call reads disk. Any change to this file requires careful regression testing across the entire codebase. There is no integration test that exercises `SynapseConfig.load()` with various `synapse.json` configurations.

### 4.3 `WhatsAppSender` Kept as Deprecated Compatibility Shim
**File:** `workspace/sci_fi_dashboard/gateway/worker.py` (lines 10–11, 49)

```python
from .sender import (
    WhatsAppSender,  # kept for backwards-compat constructor param; Phase 4 removes it
)
```

Phase 4 was supposed to remove `WhatsAppSender` but it remains as a deprecated path. The `sender` parameter in `MessageWorker.__init__` is accepted but documented as deprecated. Dead code in the production worker.

### 4.4 `_extract_search_intent` — Dead Method
**File:** `workspace/sci_fi_dashboard/dual_cognition.py` (lines 457–498)

`_extract_search_intent` is a fully implemented async method that is never called. The comment on line 221 explains it was removed from the deep path. The method remains in the file adding ~40 lines of dead code that will confuse maintainers.

### 4.5 Session Management Placeholder in WebSocket Server
**Files:** `workspace/sci_fi_dashboard/gateway/ws_server.py` (lines 342–350)

```python
async def _handle_sessions_list(self, params: dict) -> dict:
    """Return queue stats as a minimal session list (placeholder)."""

async def _handle_sessions_reset(self, params: dict) -> dict:
    """Reset session state (placeholder -- session management is future work)."""
    return {"ok": True}
```

Both WebSocket session management methods are stubs. `sessions.reset` always returns `{"ok": True}` without actually resetting anything. This is a silent no-op that callers may depend on.

### 4.6 Phase-Based TODO Comments in `scripts/sentinel.py` — Never Updated
**File:** `workspace/scripts/sentinel.py` (lines 26, 87, 196, 219)

```python
SYNAPSE_PROCESS_NAME = "synapse gateway"  # TODO Phase 4: update to Synapse bridge process name
# TODO Phase 4: replace with Synapse bridge start command
```

Phase 4 was completed (Baileys bridge is live) but these TODOs remain. The `sentinel.py` script monitors the wrong process name and would fail to restart the bridge on crash.

### 4.7 `latency_watcher.py` — Phase 4 Send Call Never Updated
**File:** `workspace/scripts/latency_watcher.py` (line 24)

```python
# TODO Phase 4: replace with Synapse WhatsApp bridge (Baileys) send call
```

The latency watcher script uses a placeholder send path instead of the real Baileys HTTP bridge. The script is non-functional for production alerting.

---

## 5. Fragile Areas

### 5.1 FloodGate — No Message Count Limit Per Window
**File:** `workspace/sci_fi_dashboard/gateway/flood.py`

The `FloodGate` batches messages but has no cap on how many messages can accumulate in a single batch window. A rapid-fire sender can stuff hundreds of messages into one batch, creating a single combined message of unbounded length that hits the LLM with no token budget guard. The `_buffers` dict also grows unboundedly if `_wait_and_flush` tasks are cancelled before they fire.

### 5.2 MessageDeduplicator — In-Memory Only, No Restart Persistence
**File:** `workspace/sci_fi_dashboard/gateway/dedup.py`

The `seen` dict is purely in-memory. Gateway restarts reset the dedup window. If the gateway crashes and restarts within the 5-minute TTL window, previously-seen message IDs will be reprocessed. For WhatsApp webhooks that retry on failure, this means duplicate responses.

### 5.3 `_chat_generations` Dict — Unbounded Growth
**File:** `workspace/sci_fi_dashboard/gateway/worker.py` (line 70)

```python
self._chat_generations: dict[str, int] = {}
```

The chat generation tracker grows a new entry for every unique `chat_id` ever seen. There is no eviction. Over a long-running session with many different senders, this dict grows without bound. In practice, integer counters are small, but it is still a memory leak for long-running deployments.

### 5.4 `SBSOrchestrator` Batch Trigger — Blocking SQLite in Startup
**File:** `workspace/sci_fi_dashboard/sbs/orchestrator.py` (line 59)

```python
self._check_startup_batch()
```

This is called synchronously in `__init__`, which runs during module import in `_deps.py`. `_check_startup_batch` likely queries SQLite to check the last batch timestamp. This is a blocking I/O operation executed before the asyncio event loop is fully running, during the import chain of `_deps.py`.

### 5.5 Baileys Bridge — `MAX_RESTARTS=5` Hard Cap with No Reset
**File:** `workspace/sci_fi_dashboard/channels/whatsapp.py` (line 65)

```python
MAX_RESTARTS: int = 5
```

After 5 bridge crashes, the supervisor stops restarting and WhatsApp goes permanently offline until the gateway itself is restarted. There is no reset mechanism after a period of stability. A bridge that crashes 5 times in one bad day will not recover for the rest of the day even if the underlying issue resolves.

### 5.6 Audio Processing Depends on Groq Cloud — No Local Fallback
**Architecture (CLAUDE.md)**

Voice messages use Groq Whisper-Large-v3 for transcription with no local fallback. If Groq is unavailable or the API key is exhausted, all voice messages silently fail (or raise an exception). There is no graceful degradation message to the user ("voice messages temporarily unavailable").

---

## 6. Error Handling Gaps

### 6.1 Mass `except Exception: pass` in Pipeline Emitter Calls
**Files:** `workspace/sci_fi_dashboard/dual_cognition.py` (13 instances), `workspace/sci_fi_dashboard/memory_engine.py` (8 instances), `workspace/sci_fi_dashboard/sbs/orchestrator.py` (3 instances)

Pipeline emitter calls (`_get_emitter().emit(...)`) are wrapped in `try/except Exception: pass` throughout the codebase. This is intentional to keep the emitter non-fatal, but the pattern silently swallows all exceptions including emitter logic bugs. When the emitter itself has a bug, it will appear as if events simply aren't being emitted rather than raising a visible error.

### 6.2 Vault Path — No User Feedback When Ollama Unreachable
**File:** `workspace/sci_fi_dashboard/chat_pipeline.py` (lines 422–437)

When the vault (local Ollama) fails, the user receives:
```
"I'm unable to process this request right now -- the local Vault model is unavailable..."
```
This error message is sent back through the channel. However, there is no retry, no fallback (intentionally, per air-gap policy), and no admin notification. A misconfigured Ollama will silently fail for all spicy-session users with no diagnostics.

### 6.3 `persona_chat` — Memory Error Silently Degrades to Amnesia
**File:** `workspace/sci_fi_dashboard/chat_pipeline.py` (lines 159–162)

```python
except Exception as e:
    print(f"[WARN] Memory Engine Error: {e}")
    memory_context = "(Memory retrieval unavailable)"
    retrieval_method = "failed"
```

Any exception in the memory retrieval path results in the LLM receiving `"(Memory retrieval unavailable)"` as its context. The user gets a reply with no personal memory. This is non-fatal but represents a significant degradation that is only surfaced as a `print()` statement with no structured logging or alerting.

### 6.4 `conn.close()` Called Manually Instead of Context Manager
**File:** `workspace/sci_fi_dashboard/memory_engine.py` (lines 318–368), `workspace/sci_fi_dashboard/retriever.py`

Multiple places call `conn = get_db_connection()` then `conn.close()` at the end of a try block. If an exception is raised mid-function before `conn.close()`, the connection leaks. The pattern should use `with get_db_connection() as conn:` (context manager) to guarantee cleanup.

---

## 7. Windows / Platform-Specific Issues

### 7.1 Windows cp1252 Emoji Encoding
**Documented in CLAUDE.md, Gotcha #5**

Preview strings printed to the console must be ASCII-encoded. The fix (`.encode("ascii", errors="replace").decode()`) is applied in `chat_pipeline.py` (line 779) and `gateway/worker.py` (line 227), but only for specific preview strings. Any `print()` call elsewhere that includes emoji or non-ASCII from user messages will raise `UnicodeEncodeError` on Windows. There is no global stdout encoder set at startup.

### 7.2 `torch.backends.mps.is_available()` Called on Windows
**File:** `workspace/sci_fi_dashboard/toxic_scorer_lazy.py` (lines 35, 51, 70)

MPS is Apple Silicon only. On Windows, `torch.backends.mps.is_available()` always returns False, so the code falls through to CPU correctly. But the device selection logic checks `mps` before defaulting to CPU — there is no CUDA check. On a Windows machine with an Nvidia GPU (likely given "benchmark_gpu.py" in the workspace), Toxic-BERT will run on CPU instead of CUDA, making it significantly slower.

### 7.3 `WindowsProactorEventLoopPolicy` Set at Module Import Time
**File:** `workspace/sci_fi_dashboard/channels/whatsapp.py` (lines 45–46)

```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
```

This is set unconditionally at import time when the `whatsapp` module is loaded. This affects the entire process event loop policy. If any other component (e.g., a test framework) has already set a different policy, this silently overrides it. The comment in the file acknowledges this must run before uvicorn starts.

---

## 8. Configuration and Operational Concerns

### 8.1 No `synapse.json` Schema Enforcement at Startup
**File:** `workspace/synapse_config.py`

`_try_validate(raw)` is called during `SynapseConfig.load()` but validation failures are non-fatal — the config is returned anyway with `validated_schema=None`. A completely malformed `synapse.json` will silently produce a config with empty/default values for all fields rather than failing fast at startup.

### 8.2 `EMBEDDING_DIMENSIONS = 768` Hardcoded in Two Places
**Files:** `workspace/sci_fi_dashboard/db.py` (line 9), `workspace/sci_fi_dashboard/vector_store/lancedb_store.py` (via schema)

If the embedding model changes (e.g., switching from `nomic-embed-text` 768-dim to `text-embedding-3-small` 1536-dim), both the SQLite `vec_items` virtual table schema AND the LanceDB schema would need to be updated along with the constant. The comment in `db.py` documents this risk but there is no migration tool for the dimension change.

### 8.3 litellm Router vs. litellm.acompletion for GitHub Copilot
**Documented in CLAUDE.md, Gotcha #1**

`litellm.Router` does not apply Copilot auth headers. The workaround in `workspace/sci_fi_dashboard/llm_router.py` rewrites `github_copilot/` prefix to `openai/` + injects `api_base` + `extra_headers`. The `ghu_` tokens are short-lived and the auto-refresh on 403 is implemented in `_do_call()`. This is a permanent workaround against upstream litellm behavior — if litellm adds native Copilot support, the workaround could conflict.

### 8.4 Copilot Token Expiry Not Trusted
**Documented in CLAUDE.md, Gotcha #2**

`ghu_` Copilot tokens can be revoked before their `expires_at` timestamp. The system handles this via 403 auto-refresh, but the refresh itself requires a local token file at `~/.config/litellm/github_copilot/api-key.json`. If this file is absent or corrupted, the refresh silently fails and the Copilot provider becomes permanently unavailable for that session.

### 8.5 `DB_PATH` Computed at Module Import Time
**File:** `workspace/sci_fi_dashboard/db.py` (line 20), `workspace/sci_fi_dashboard/memory_engine.py` (line 77)

```python
DB_PATH = _get_db_path()
```

This calls `SynapseConfig.load()` at module import time. If `SYNAPSE_HOME` is set after module import (e.g., in tests), the path is already frozen. This makes the DB path non-patchable in tests without careful sys.modules manipulation.

### 8.6 `entities.json` and `conflicts.json` Paths Are Relative
**File:** `workspace/sci_fi_dashboard/_deps.py` (lines 104–105)

```python
gate = EntityGate(entities_file="entities.json")
conflicts = ConflictManager(conflicts_file="conflicts.json")
```

These use relative paths, resolving against whatever the current working directory is at startup. If the gateway is started from a directory other than `workspace/sci_fi_dashboard/`, these files will not be found. The correct approach is to use `Path(__file__).parent / "entities.json"`.

---

## 9. Missing Tests and Test Coverage Gaps

### 9.1 No Integration Tests for the Full `persona_chat` Pipeline
The test suite in `workspace/tests/` covers individual components (flood, dedup, dual cognition, SBS) but there are no end-to-end integration tests that exercise `persona_chat()` with a real (mocked) LLM call through the full pipeline.

### 9.2 No Tests for Auth Paths
The auth middleware functions (`_require_gateway_auth`, `validate_bridge_token`, `validate_api_key`) have no unit tests. A regression in auth could silently open or close endpoints.

### 9.3 MCP Servers Have No Tests
None of the MCP servers in `workspace/sci_fi_dashboard/mcp_servers/` have corresponding test files. The `tools_server.py` Sentinel integration is untested.

---

## Summary Priority Matrix

| Severity | Issue | File |
|----------|-------|------|
| HIGH | `_check_rate_limit` is a no-op stub on webhook endpoint | `_deps.py:204` |
| HIGH | Sentinel initialized with wrong project root | `_deps.py:151` |
| HIGH | `scripts/sentinel.py` monitors wrong process name | `scripts/sentinel.py:26` |
| HIGH | Toxic-BERT load blocks asyncio event loop | `toxic_scorer_lazy.py:63` |
| HIGH | No CUDA support in Toxic-BERT on Windows GPU | `toxic_scorer_lazy.py:70` |
| MEDIUM | `SynapseConfig.load()` on every auth request (disk read) | `middleware.py:70,106` |
| MEDIUM | FloodGate has no per-window message count cap | `gateway/flood.py` |
| MEDIUM | Connection leak pattern (no context manager) | `memory_engine.py:318` |
| MEDIUM | `_chat_generations` dict grows unboundedly | `gateway/worker.py:70` |
| MEDIUM | Baileys MAX_RESTARTS with no reset after stability | `channels/whatsapp.py:65` |
| MEDIUM | Duplicate import path anti-pattern across 8+ files | various |
| LOW | Dead `_extract_search_intent` method | `dual_cognition.py:457` |
| LOW | Deprecated `WhatsAppSender` shim never removed | `gateway/worker.py:49` |
| LOW | WebSocket session management stubs | `gateway/ws_server.py:342` |
| LOW | `entities.json` relative path | `_deps.py:104` |
