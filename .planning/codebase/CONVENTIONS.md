# Synapse-OSS Code Conventions

## Toolchain & Formatter Config

- **Python version:** 3.11+
- **Formatter:** `black` — line length 100, target `py311`
- **Linter:** `ruff` — line length 100, target `py311`
- **Config source:** `pyproject.toml` (root)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.black]
line-length = 100
target-version = ["py311"]
```

Legacy scripts under `workspace/scripts/`, `workspace/skills/`, and several utility files
(`monitor.py`, `change_tracker.py`, etc.) are excluded from ruff entirely via
`per-file-ignores` in `pyproject.toml`.

---

## Module Layout

```
workspace/
  main.py                          # CLI entry point
  synapse_config.py                # Single source of truth for all paths/config
  sci_fi_dashboard/
    api_gateway.py                 # FastAPI app + lifespan; thin orchestrator
    _deps.py                       # Shared singleton registry (imported as `deps`)
    schemas.py                     # Pydantic request/response models
    chat_pipeline.py               # persona_chat() core logic
    llm_router.py                  # SynapseLLMRouter (litellm.Router wrapper)
    memory_engine.py               # Hybrid RAG pipeline
    dual_cognition.py              # Inner-monologue engine
    sqlite_graph.py                # SQLite-backed knowledge graph
    db.py                          # DatabaseManager + get_db_connection()
    pipeline_emitter.py            # SSE event bus singleton
    gateway/                       # flood.py, dedup.py, queue.py, worker.py, ...
    channels/                      # base.py, security.py, whatsapp.py, telegram.py, ...
    sbs/                           # Soul-Brain Sync subsystem
    mcp_servers/                   # MCP tool servers
    routes/                        # FastAPI APIRouter modules
    media/                         # Media pipeline
    embedding/                     # Embedding providers
    vector_store/                  # LanceDB store
    cron/                          # Cron types, store, schedule, service
    multiuser/                     # Multi-user session, compaction, context assembler
  tests/                           # All tests (see TESTING.md)
```

---

## Naming Conventions

### Files
- All Python files: `snake_case.py`
- Test files: `test_<module_name>.py` (mirror the module they cover)
- Sub-modules with extended tests: `test_<module_name>_extended.py`, `test_<module_name>_gaps.py`

### Classes
- `PascalCase` throughout
- Dataclasses named as nouns: `MessageTask`, `LLMResult`, `CognitiveMerge`, `ChannelMessage`
- ABC bases named with `Base` suffix: `BaseChannel`
- Enum subclasses named as nouns: `TaskStatus`, `DmPolicy`
- Singleton accessors use `get_<name>()` factory pattern: `get_emitter()`, `get_provider()`

### Functions / Methods
- `snake_case` throughout
- Private helpers prefixed with `_`: `_ensure_db()`, `_recall_memory()`, `_get_db_path()`
- Async functions follow the same naming — no `async_` prefix convention used
- Class-level private helpers: `_conn()`, `_init_schema()`, `_broadcast()`

### Constants
- `UPPER_SNAKE_CASE`: `EMBEDDING_DIMENSIONS`, `FAST_PHRASES`, `DB_PATH`, `RERANK_MODEL_NAME`
- Frozensets used for membership lookup sets: `FAST_PHRASES = frozenset([...])`

### Loggers
Every module creates a module-level logger immediately after imports:
```python
logger = logging.getLogger(__name__)
```
Sub-loggers for specific concerns use dot notation:
```python
_tool_logger = logging.getLogger(__name__ + ".tools")
```
The `logging` module is used exclusively — no `print()` in production paths
(startup banners use `print()` for pre-logger visibility only).

---

## Async/Await Patterns

- **asyncio throughout** — no Redis, no Celery, no threads for business logic
- All I/O-bound operations are `async def` and `await`-ed
- `asyncio.gather()` used for parallel independent coroutines:
  ```python
  present, memory = await asyncio.gather(
      self._analyze_present(...),
      self._recall_memory(...),
  )
  ```
- `asyncio.create_task()` used for fire-and-forget background work (FloodGate debounce)
- `asyncio.wait_for(coro, timeout=n)` wraps any latency-sensitive LLM call
  (e.g., `dual_cognition.think()`)
- `contextlib.suppress(ValueError)` used to absorb expected non-fatal errors
  (e.g., `asyncio.Queue.task_done()` double-call guard in `queue.py`)
- `@asynccontextmanager` used for FastAPI lifespan in `api_gateway.py`

---

## Dataclasses

Dataclasses are the primary data-transfer mechanism throughout. Key patterns:

```python
from dataclasses import dataclass, field

@dataclass
class MessageTask:
    task_id: str
    chat_id: str
    user_message: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.QUEUED
    response: str | None = None   # Python 3.10+ union syntax
```

- `field(default_factory=...)` always used for mutable defaults (list, dict, datetime)
  — raw `= []` or `= {}` defaults are explicitly avoided (documented in comments where
  relevant; see `ChannelMessage.raw` in `channels/base.py`)
- `frozen=True` used for immutable config objects: `SynapseConfig`, `SBSConfig`,
  `KGExtractionConfig`
- Dataclasses used as DTOs: `LLMResult`, `ToolCall`, `LLMToolResult`, `PresentStream`,
  `MemoryStream`, `CognitiveMerge`, `ChannelMessage`, `MsgContext`

---

## Enums

- `StrEnum` (Python 3.11+) for string-valued enums used in JSON/config contexts:
  ```python
  from enum import StrEnum
  class DmPolicy(StrEnum):
      PAIRING = "pairing"
      ALLOWLIST = "allowlist"
  ```
- Standard `Enum` for internal state tracking:
  ```python
  from enum import Enum
  class TaskStatus(Enum):
      QUEUED = "queued"
      PROCESSING = "processing"
  ```

---

## Import Style

### Ordering
Standard Python import order enforced by ruff `"I"` (isort rules):
1. Standard library
2. Third-party (`fastapi`, `litellm`, `pytest`, ...)
3. Local (`sci_fi_dashboard.*`, `synapse_config`, ...)

### Path bootstrap pattern
Tests and modules that may run standalone insert the workspace root manually:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```
Some modules use `Path`:
```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Relative vs absolute imports
- Within `sci_fi_dashboard/` package: relative imports preferred:
  ```python
  from .db import get_db_connection
  from .security import ChannelSecurityConfig
  ```
- Cross-package or top-level: absolute imports:
  ```python
  from sci_fi_dashboard.gateway.flood import FloodGate
  from synapse_config import SynapseConfig
  ```

### Conditional / guarded imports
Heavy optional deps use try/except at module level:
```python
try:
    from sci_fi_dashboard.tool_registry import ToolRegistry
except ImportError:
    pass
```
Feature availability is then tested with `if TYPE_CHECKING:` guards or runtime isinstance checks.

### `from __future__ import annotations`
Used in modules that need PEP 563 deferred evaluation (forward references in type hints):
`channels/base.py`, `channels/security.py`, `pipeline_emitter.py`, `gateway/queue.py`, etc.

---

## Error Handling Patterns

### Broad exception suppression with logging
Used in pipeline-critical paths to prevent one failure from killing the whole request:
```python
try:
    _get_emitter().emit("cognition.classify", {...})
except Exception:
    pass
```
The `dual_cognition.py` module has numerous inline `try/except Exception: pass` blocks
for emitter calls specifically — emitter failures must never interrupt cognition.

### Specific exception handling
Preferred when the error type is known:
```python
except (OSError, json.JSONDecodeError):
    pass   # return empty default
```
```python
except sqlite3.OperationalError as e:
    if "locked" in str(e).lower():
        ...  # retry
    raise
```

### Retry decorator pattern
SQLite write contention uses a decorator with exponential backoff (in `memory_engine.py`):
```python
def with_retry(retries: int = 3, delay: float = 0.5):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        time.sleep(delay * (2 ** i))
                        continue
                    raise
            raise last_err
        return wrapper
    return decorator
```

### Graceful fallback returns
Methods return empty/safe defaults rather than propagating:
```python
def load_conflicts(self):
    if os.path.exists(self.conflicts_file):
        try:
            with open(self.conflicts_file) as f:
                ...
        except (OSError, json.JSONDecodeError):
            pass
    return []
```

### asyncio.wait_for for timeouts
LLM-backed coroutines that may hang are timeout-wrapped at the call site
(not inside the coroutine), keeping the coroutine itself clean:
```python
result = await asyncio.wait_for(engine.think(...), timeout=dual_cognition_timeout)
```

---

## SQLite Patterns

- WAL mode enabled on every connection:
  ```python
  conn.execute("PRAGMA journal_mode=WAL")
  conn.execute("PRAGMA synchronous=NORMAL")
  ```
- `conn.row_factory = sqlite3.Row` for dict-like row access
- `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` — all DDL is idempotent
- `executescript()` for multi-statement DDL blocks
- Persistent connection with liveness check in `SQLiteGraph`:
  ```python
  def _conn(self):
      try:
          self._persistent_conn.execute("SELECT 1")
      except (sqlite3.ProgrammingError, sqlite3.OperationalError):
          self._persistent_conn = self._create_conn()
      return self._persistent_conn
  ```
- `check_same_thread=False` used with explicit threading guards where needed

---

## Config / Singleton Patterns

- `SynapseConfig` is a frozen dataclass loaded via `SynapseConfig.load()` — not cached
  at module level (env var can differ between calls)
- Module-level singletons use a private `_var: Type | None = None` + accessor function:
  ```python
  _emitter: PipelineEventEmitter | None = None

  def get_emitter() -> PipelineEventEmitter:
      global _emitter
      if _emitter is None:
          _emitter = PipelineEventEmitter()
      return _emitter
  ```
- Shared singletons (`MemoryEngine`, `SQLiteGraph`, `SynapseLLMRouter`, etc.) live in
  `sci_fi_dashboard/_deps.py` and are imported as `from sci_fi_dashboard import _deps as deps`

---

## Type Annotations

- Python 3.10+ union syntax used: `str | None`, `list[str]`, `dict[str, Any]`
- `from typing import Any, TYPE_CHECKING, Literal` for complex annotations
- `TYPE_CHECKING` blocks for circular-import-safe type hints:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from .security import ChannelSecurityConfig
  ```
- Return type annotations present on public methods; internal helpers often unannotated
- `collections.abc.Callable` preferred over `typing.Callable`

---

## Docstring Style

- Module-level docstrings: brief purpose statement + major class/function list
- Class docstrings: explain the role and any lifecycle notes
- Method docstrings: one-line summary; multi-line for non-obvious args or side effects
- No enforced NumPy/Google style — plain English paragraphs
- Examples:
  ```python
  """Singleton event bus. Call get_emitter() to access."""
  ```
  ```python
  """Create a new configured SQLite connection."""
  ```

---

## FastAPI Conventions (`sci_fi_dashboard/routes/`)

- Each route domain gets its own `APIRouter` module under `routes/`
- Routers imported and included in `api_gateway.py`
- Pydantic models defined in `schemas.py` (not inline in route functions)
- `BackgroundTasks` used for fire-and-forget work (auto-continue, media cleanup)
- Lifespan managed via `@asynccontextmanager async def lifespan(app)` — not deprecated
  `on_event` hooks

---

## Key File Paths (for reference)

| Purpose | Path |
|---------|------|
| Linter/formatter config | `pyproject.toml` |
| Root config dataclass | `workspace/synapse_config.py` |
| FastAPI app | `workspace/sci_fi_dashboard/api_gateway.py` |
| Singleton registry | `workspace/sci_fi_dashboard/_deps.py` |
| LLM router | `workspace/sci_fi_dashboard/llm_router.py` |
| Dual cognition | `workspace/sci_fi_dashboard/dual_cognition.py` |
| Memory engine | `workspace/sci_fi_dashboard/memory_engine.py` |
| DB manager | `workspace/sci_fi_dashboard/db.py` |
| Knowledge graph | `workspace/sci_fi_dashboard/sqlite_graph.py` |
| Channel base ABC | `workspace/sci_fi_dashboard/channels/base.py` |
| DM security | `workspace/sci_fi_dashboard/channels/security.py` |
| Gateway queue | `workspace/sci_fi_dashboard/gateway/queue.py` |
| Flood gate | `workspace/sci_fi_dashboard/gateway/flood.py` |
| Pipeline emitter | `workspace/sci_fi_dashboard/pipeline_emitter.py` |
