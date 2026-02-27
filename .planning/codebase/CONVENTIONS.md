# Coding Conventions

**Analysis Date:** 2026-02-27

## Naming Patterns

**Files:**
- Snake_case for all Python files: `api_gateway.py`, `memory_engine.py`, `toxic_scorer_lazy.py`
- Test files follow pattern: `test_<module>.py` (e.g., `test_queue.py`, `test_flood.py`)
- Modules organized hierarchically: `sci_fi_dashboard/gateway/queue.py`, `sbs/processing/batch.py`

**Classes:**
- PascalCase for all classes: `MessageTask`, `TaskQueue`, `SQLiteGraph`, `MessageWorker`, `FloodGate`
- Descriptive names tied to responsibility: `DatabaseManager`, `MessageDeduplicator`, `ConflictManager`
- Enum classes use PascalCase: `TaskStatus` enum with UPPERCASE members (`QUEUED`, `PROCESSING`, `COMPLETED`)

**Functions:**
- Snake_case for all functions: `get_db_connection()`, `_init_embedder()`, `get_embedding()`
- Leading underscore for private/internal functions: `_init_schema()`, `_handle_task()`, `_worker_loop()`
- Async functions use `async def` prefix but no special naming: `async def enqueue()`

**Variables:**
- Snake_case: `max_size`, `batch_window_seconds`, `processing_started`, `_active_tasks`
- Constants in UPPERCASE: `DB_PATH`, `MAX_DB_SIZE_MB`, `EMBEDDING_MODEL_OLLAMA`
- Private attributes prefixed with underscore: `_initialized`, `_queue`, `_embed_mode`, `_ranker_lock`

**Type Hints:**
- Modern Python 3.11+ union syntax used: `str | None`, `list | None` instead of `Optional[str]`
- Union types in function signatures: `def get_embedding(text: str) -> list | None`
- Dataclass fields use type hints with defaults: `status: TaskStatus = TaskStatus.QUEUED`

## Code Style

**Formatting:**
- Tool: `ruff` (linter) and `black` (formatter)
- Line length: 100 characters (enforced by both tools)
- Target Python version: 3.11

**Linting Rules (ruff):**
- Rules enabled: `E` (pycodestyle errors), `F` (Pyflakes), `W` (pycodestyle warnings), `I` (isort imports), `N` (pep8-naming), `UP` (pyupgrade), `B` (flake8-bugbear), `C4` (flake8-comprehensions), `SIM` (flake8-simplify)
- Rule ignored: `E501` (line too long) — black handles this instead
- Configuration: `pyproject.toml` lines 29-35

**Docstring Style:**
- Triple-quoted docstrings at module level (required)
- Module docstrings describe purpose and scope:
  ```python
  """
  Test Suite: Async Task Queue
  ===========================
  Tests the TaskQueue class which manages message processing tasks
  with async operations, status tracking, and history management.
  """
  ```
- Class and method docstrings are optional but used for public APIs
- Single-line docstrings when brief: `"""Create a fresh TaskQueue."""`

## Import Organization

**Order (consistent across all files):**
1. Standard library: `import asyncio`, `import os`, `import sys`, `import time`, `from datetime import datetime`
2. Third-party: `from pydantic import BaseModel`, `from fastapi import FastAPI`, `import httpx`
3. Local imports: `from .gateway.queue import TaskQueue`, `from sci_fi_dashboard.db import get_db_connection`

**Pattern observed in `workspace/sci_fi_dashboard/gateway/worker.py`:**
```python
import asyncio
import contextlib
import time
import traceback

from .queue import MessageTask, TaskQueue
from .sender import WhatsAppSender
```

**Pattern observed in `workspace/sci_fi_dashboard/db.py`:**
```python
import os
import sqlite3

import sqlite_vec
```

**Relative vs. Absolute:**
- Relative imports used within packages: `from .queue import MessageTask` in `gateway/worker.py`
- Absolute imports used at package level: `from sci_fi_dashboard.db import get_db_connection`
- Fallback imports used when module locations vary: Try/except with multiple import paths in `memory_engine.py` and `retriever.py`

**Path Aliases:**
- Not detected in configuration; standard Python import paths used throughout

## Error Handling

**Patterns:**
- **Try-except with specific exceptions:** Lock contention in `memory_engine.py` uses `except sqlite3.OperationalError as e` with conditional handling
- **Try-finally for resource cleanup:** Database connections always wrapped: `try: ... finally: conn.close()`
- **Broad exception catching with logging:** Worker loop catches all exceptions and prints traceback: `except Exception as e: print(f"[WORKER-{worker_id}] Loop error: {e}"); traceback.print_exc()`
- **Contextlib.suppress for expected cancellations:** `with contextlib.suppress(asyncio.CancelledError): await typing_task`
- **Exponential backoff for retries:** Decorator `with_retry()` in `memory_engine.py` uses `time.sleep(delay * (2**i))` for SQLite lock contention

**Example from `workspace/sci_fi_dashboard/memory_engine.py` (lines 27-47):**
```python
def with_retry(retries: int = 3, delay: float = 0.5):
    """Simple decorator for retrying SQLite writes on lock contention."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        last_err = e
                        time.sleep(delay * (2**i))
                        continue
                    raise
            raise last_err
        return wrapper
    return decorator
```

**Example from `workspace/sci_fi_dashboard/gateway/worker.py` (lines 54-113):**
```python
try:
    # STEP 1-6: Processing pipeline
    response = await self.process_fn(task.user_message, chat_id)
    # ... validation and send logic
except Exception as e:
    error_msg = str(e)
    # Handle error appropriately
    self.queue.fail(task, error_msg)
```

## Logging

**Framework:** `print()` statements with emoji prefixes (no traditional logging library)

**Patterns observed:**
- Status indicators with emoji: `✅`, `⚠️`, `❌`, `🚀`, `📦`, `[WORKER-n]` prefixes for worker identification
- Informational output: `print(f"📦 First boot: Creating memory database at {DB_PATH}")`
- Warning/alert output: `print(f"⚠️ WARNING: Database size ({size_mb:.1f}MB) exceeds target")`
- Worker progress: `print(f"[WORKER-{worker_id}] gen={task.generation} Processing: ...")`

**Key locations:**
- `workspace/sci_fi_dashboard/db.py` — Database initialization and diagnostics
- `workspace/sci_fi_dashboard/gateway/worker.py` — Task processing lifecycle
- `workspace/sci_fi_dashboard/retriever.py` — Embedding model selection
- `workspace/main.py` — System verification output

## Comments

**When to Comment:**
- Rare; code is generally self-documenting through descriptive names
- Comments used for non-obvious logic or architectural decisions
- Comments mark significant state transitions or TODO items

**Example from `workspace/sci_fi_dashboard/gateway/worker.py` (lines 58-68):**
```python
# INCREASE GENERATION TO INDICATE NEWEST LATEST TASK
async with self._gen_lock:
    current = self._chat_generations.get(chat_id, 0)
    new_gen = current + 1
    self._chat_generations[chat_id] = new_gen
    task.generation = new_gen
```

**Example from `workspace/sci_fi_dashboard/memory_engine.py` (lines 84-85):**
```python
# SHARED — not duplicated
self.graph_store = graph_store
```

**JSDoc/TSDoc:** Not used; Python uses regular docstrings instead

## Function Design

**Size:**
- Functions keep to single responsibility
- Async functions range 30-100 lines (e.g., `_worker_loop()` is ~50 lines)
- Helper functions are shorter (10-20 lines)

**Parameters:**
- Named parameters preferred: `def __init__(self, max_size: int = 100, max_history: int = 500)`
- Type hints on all parameters (enforced by code organization)
- Defaults provided for optional parameters

**Return Values:**
- Functions return typed values with explicit `| None` annotations when applicable
- Async functions properly await: `async def dequeue(self) -> MessageTask`
- Methods return `self` for chaining (not observed; no builder pattern used)

**Example from `workspace/sci_fi_dashboard/gateway/queue.py` (lines 43-51):**
```python
async def enqueue(self, task: MessageTask):
    self._active_tasks[task.task_id] = task
    await self._queue.put(task)

async def dequeue(self) -> MessageTask:
    task = await self._queue.get()
    task.status = TaskStatus.PROCESSING
    task.processing_started = datetime.now()
    return task
```

## Module Design

**Exports:**
- Modules export public classes and functions naturally (no explicit `__all__`)
- Gateway module uses barrel file: `workspace/sci_fi_dashboard/gateway/__init__.py` (lines 1-5):
  ```python
  from .dedup import MessageDeduplicator
  from .flood import FloodGate
  from .queue import MessageTask, TaskQueue
  from .sender import WhatsAppSender
  from .worker import MessageWorker
  ```

**Barrel Files:**
- Used selectively in `gateway/` package for convenience imports
- Not used everywhere; most modules imported directly from their source files

## Concurrency Patterns

**Async/Await:**
- All async operations use `asyncio` exclusively (no threads except for locks)
- Async context managers with `@asynccontextmanager` for resource management
- Background tasks via `asyncio.create_task()` with explicit cleanup

**Locks and Synchronization:**
- `asyncio.Lock()` for async-safe operations: `async with self._gen_lock: ...`
- `threading.Lock()` used only for non-async operations (e.g., lazy model loading)
- No distributed locking; single-process design

**Database Access:**
- SQLite WAL mode for concurrent read/write
- Connection pooling not used; connections created per-operation
- Atomic transactions with explicit `conn.commit()` calls

---

*Convention analysis: 2026-02-27*
