# Synapse-OSS Testing Patterns

## Test Framework

- **Framework:** `pytest`
- **Async support:** `pytest-asyncio` with `asyncio_mode = auto` (no per-test decorator needed
  for most tests; `@pytest.mark.asyncio` still accepted where explicit)
- **Config file:** `workspace/tests/pytest.ini`
- **conftest:** `workspace/tests/conftest.py`

---

## How to Run Tests

```bash
# Run all tests (from workspace/)
cd workspace && pytest tests/ -v

# Filter by marker
pytest tests/ -m unit
pytest tests/ -m integration
pytest tests/ -m smoke
pytest tests/ -m e2e
pytest tests/ -m acceptance
pytest tests/ -m performance

# Single file
pytest tests/test_flood.py -v

# Single test
pytest tests/test_flood.py::TestFloodGate::test_batch -v

# Include slow tests (skipped by default)
pytest tests/ --run-slow

# With coverage (requires pytest-cov)
pytest tests/ --cov=sci_fi_dashboard --cov-report=html
```

---

## pytest.ini Configuration

Located at `workspace/tests/pytest.ini`:

```ini
[pytest]
python_files = test_*.py
python_classes = Test*
python_functions = test_*

addopts =
    -v
    --strict-markers
    --tb=short
    --asyncio-mode=auto

asyncio_mode = auto
testpaths = tests

log_cli = false
log_cli_level = INFO
```

- `--strict-markers`: any undefined marker causes an error — all markers must be registered
- `--tb=short`: compact tracebacks for faster scanning
- `--asyncio-mode=auto`: all `async def test_*` functions are automatically treated as
  async tests; no `@pytest.mark.asyncio` decorator required (though it is still used
  in older test files for clarity)

---

## Test Markers

Defined in both `pytest.ini` and `conftest.py` (`pytest_configure`):

| Marker | Purpose | Examples |
|--------|---------|---------|
| `unit` | Single class/function in isolation | `test_config.py`, `test_channel_security.py` |
| `integration` | Two or more modules interacting | `test_integration.py`, `test_db.py` |
| `functional` | Business logic, end-to-end within process | `test_functional.py` |
| `e2e` | Full user flows, may touch real filesystem | `test_e2e.py` |
| `acceptance` | Requirements verification | `test_acceptance.py` |
| `performance` | Load/stress/throughput | `test_performance.py` |
| `smoke` | Fast sanity checks, no heavy deps | `test_smoke.py` |
| `slow` | Long-running; skipped unless `--run-slow` | Tagged individually |

`slow` tests are skipped via `pytest_collection_modifyitems` unless `--run-slow` is passed.

---

## Test File Structure

### Naming Convention
- Test files mirror source modules: `test_<module>.py`
- Extended coverage files: `test_<module>_extended.py`
- Gap/edge-case files: `test_<module>_gaps.py`
- Example pairs: `test_flood.py` covers `gateway/flood.py`

### Class Structure
All test files organize tests into classes:
```python
class TestFloodGate:
    """Test cases for message batching logic."""

    @pytest.fixture
    def flood_gate(self):
        return FloodGate(batch_window_seconds=1.0)

    async def test_single_message_batched(self, flood_gate):
        ...
```

Each class has a focused scope — one component or one aspect of a component.
Multiple classes per file are common when covering different aspects:
```
TestDmPolicy
TestChannelSecurityConfig
TestPairingStore
TestResolveDmAccess
```

### Module-level docstring
Every test file opens with a docstring explaining coverage targets:
```python
"""
Test Suite: FloodGate Batching
==============================
Tests the FloodGate class which batches rapid-fire messages
from the same user within a configurable time window.
...
"""
```

---

## conftest.py — Shared Fixtures

Located at `workspace/tests/conftest.py`. Key fixtures:

### `event_loop` (scope=session)
```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```
Single event loop for the entire test session — avoids loop-reuse warnings with
pytest-asyncio in auto mode.

### `temp_dir`
```python
@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
```
Creates a throwaway directory and cleans it up. Used everywhere that touches the filesystem.

### `temp_db`
```python
@pytest.fixture
def temp_db(temp_dir):
    return os.path.join(temp_dir, "test.db")
```
Returns a path string for a SQLite DB inside `temp_dir`.

### `github_copilot_fake_auth` (autouse=True)
```python
@pytest.fixture(autouse=True)
def github_copilot_fake_auth(tmp_path):
    """Write a fake GitHub Copilot token to prevent OAuth device-code flow."""
    token_dir = tmp_path / "github_copilot"
    ...
    os.environ["GITHUB_COPILOT_TOKEN_DIR"] = str(token_dir)
    yield
    # restores original env var
```
Applied to every test automatically. Prevents `litellm.Router` initialization from
triggering the real Copilot OAuth flow during unit tests.

### `sample_message`
```python
@pytest.fixture
def sample_message():
    return {
        "message_id": "wa_test_001",
        "from": "+1234567890",
        "chat_id": "chat_001",
        "body": "Hello Synapse",
        "timestamp": 1234567890,
    }
```

### `sample_task`
```python
@pytest.fixture
def sample_task():
    from sci_fi_dashboard.gateway.queue import MessageTask
    return MessageTask(
        task_id="test_001",
        chat_id="chat_001",
        user_message="Test message",
        message_id="wa_001",
        sender_name="Test User",
    )
```

### `mock_acompletion`
```python
@pytest.fixture
def mock_acompletion():
    mock_response = unittest.mock.MagicMock()
    mock_response.choices = [unittest.mock.MagicMock()]
    mock_response.choices[0].message.content = "Hello from mock LLM"
    ...
    with unittest.mock.patch("litellm.acompletion", new_callable=unittest.mock.AsyncMock) as mock:
        mock.return_value = mock_response
        yield mock
```
Pre-configured mock for LLM call tests. Simulates a valid litellm completion response.

---

## Mocking Approaches

### `unittest.mock` (preferred, no pytest-mock dependency)
The codebase uses `unittest.mock` directly — not `pytest-mock`:
```python
from unittest.mock import patch, MagicMock, AsyncMock
```

### `MagicMock` for sync objects
```python
mock_memory = MagicMock()
mock_memory.query.return_value = {"results": [...], "graph_context": "..."}
```

### `AsyncMock` for coroutines
```python
llm_fn = AsyncMock()
llm_fn.return_value = json.dumps({"sentiment": "positive", ...})
```
`AsyncMock` is used wherever the production code does `await fn(...)`.

### `patch()` for module-level patching
```python
with patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"):
    with patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False):
        from sci_fi_dashboard.memory_engine import MemoryEngine
        engine = MemoryEngine()
```
Patching at the module path where the name is looked up (not where it is defined).

### `patch.dict("sys.modules", {...})` for heavy deps
Used to prevent import-time side effects from optional heavy dependencies:
```python
@pytest.fixture(autouse=True)
def mock_heavy_deps():
    with patch.dict("sys.modules", {"flashrank": MagicMock()}):
        yield
```

### `monkeypatch` (pytest built-in)
Used in config tests for env var isolation:
```python
def test_synapse_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = SynapseConfig.load()
    assert config.data_root == tmp_path.resolve()
```

### `tmp_path` (pytest built-in)
Preferred for pytest-managed temp directories (auto-cleaned):
```python
def test_creates_db_on_first_boot(self, tmp_path):
    db_path = str(tmp_path / "db" / "memory.db")
    with patch("sci_fi_dashboard.db.DB_PATH", db_path):
        ...
```

---

## Path Setup in Tests

Every test file that imports from `workspace/` adds the parent to `sys.path`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```
Or using `pathlib`:
```python
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```
This allows tests to run from any working directory.

---

## Async Test Patterns

### Basic async test (no decorator needed with `asyncio_mode=auto`)
```python
async def test_single_message_batched(self, flood_gate):
    flushed = []
    async def callback(chat_id, message, metadata):
        flushed.append(message)
    flood_gate.set_callback(callback)
    await flood_gate.incoming("chat_001", "Hello", {"sender": "user1"})
    await asyncio.sleep(1.5)
    assert len(flushed) == 1
```

### `@pytest.mark.asyncio` (still used in older files)
```python
@pytest.mark.asyncio
async def test_debounce_extends_window(self, flood_gate):
    ...
```

### Inline async callbacks
Tests define `async def callback(...)` inline within the test body when testing
callback-based components (FloodGate, event bus subscribers, etc.).

---

## RED Phase Guard Pattern

For tests written before implementation exists (TDD), a conditional import guard
disables the test file until the implementation lands:

```python
try:
    from sci_fi_dashboard.llm_router import SynapseLLMRouter, _inject_provider_keys, build_router
    ROUTER_AVAILABLE = True
except ImportError:
    ROUTER_AVAILABLE = False

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not ROUTER_AVAILABLE,
        reason="SynapseLLMRouter not yet implemented — RED phase (Plan 02 will create it)",
    ),
]
```
Used in `test_llm_router.py`. All tests in the file are skipped until the module exists.

---

## Local Fixture Pattern (per-class / per-file)

Tests often define their own fixtures inside the test class or file — not just in `conftest.py`:
```python
class TestDualCognitionEngine:
    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock()
        mem.query.return_value = {"results": [...], "graph_context": "..."}
        return mem

    @pytest.fixture
    def engine(self, mock_memory, mock_graph):
        return DualCognitionEngine(memory_engine=mock_memory, graph=mock_graph)
```

Helper factory functions are defined at module level (not as fixtures) when parametrization
or reuse across tests in the same file is needed:
```python
def _make_llm_fn(*responses):
    """Create an AsyncMock that returns successive responses on each call."""
    ...
```

---

## Test Isolation

- Each test uses fresh instances — no shared state between tests
- SQLite DBs always use `tmp_path` or `temp_dir` — never the real `~/.synapse/` paths
- `autouse` fixtures (`github_copilot_fake_auth`) ensure env vars are reset after every test
- `shutil.rmtree(tmp, ignore_errors=True)` in fixture teardown prevents leftover state

---

## Coverage Setup

Coverage is optional (not enforced in CI by default):
```ini
# addopts = --cov=sci_fi_dashboard --cov-report=html
```
To enable: install `pytest-cov` and uncomment the `addopts` line in `pytest.ini`, or pass
`--cov` on the command line:
```bash
pytest tests/ --cov=sci_fi_dashboard --cov-report=term-missing
```

---

## Test Categories by File (Reference)

| File | Marker(s) | What it covers |
|------|-----------|----------------|
| `test_smoke.py` | `smoke` | Core component instantiation, basic I/O |
| `test_flood.py` | (async) | FloodGate debounce, batching, callbacks |
| `test_dedup.py` | (unit) | MessageDeduplicator TTL and dedup logic |
| `test_queue.py` | (unit/async) | TaskQueue enqueue/dequeue/complete/fail |
| `test_config.py` | (unit) | SynapseConfig.load(), env override, write_config |
| `test_db.py` | (unit) | DatabaseManager._ensure_db, WAL, schema |
| `test_sqlite_graph.py` | (unit) | SQLiteGraph nodes/edges/queries |
| `test_dual_cognition.py` | (unit/async) | DualCognitionEngine fast/standard/deep paths |
| `test_memory_engine.py` | (unit) | MemoryEngine init, temporal score, query pipeline |
| `test_llm_router.py` | (unit/async) | SynapseLLMRouter routing, provider prefixes |
| `test_channel_security.py` | (unit) | DmPolicy, PairingStore, resolve_dm_access |
| `test_integration.py` | `integration` | DB + queue cross-module flows |
| `test_e2e.py` | `e2e` | Full inbound message flow simulation |
| `test_acceptance.py` | `acceptance` | Business requirements verification |
| `test_performance.py` | `performance` | Queue throughput, concurrent ops |
| `test_mcp_tools_server.py` | (async) | MCP tool listing, web_search, file ops |
| `test_channels.py` | (unit/async) | Channel adapter base behaviour |
| `test_sbs.py` | (unit) | Soul-Brain Sync pipeline |

---

## Key File Paths (for reference)

| Purpose | Path |
|---------|------|
| pytest config | `workspace/tests/pytest.ini` |
| Shared fixtures | `workspace/tests/conftest.py` |
| Smoke tests | `workspace/tests/test_smoke.py` |
| Unit — flood gate | `workspace/tests/test_flood.py` |
| Unit — config | `workspace/tests/test_config.py` |
| Unit — dual cognition | `workspace/tests/test_dual_cognition.py` |
| Unit — memory engine | `workspace/tests/test_memory_engine.py` |
| Integration | `workspace/tests/test_integration.py` |
| E2E | `workspace/tests/test_e2e.py` |
| Performance | `workspace/tests/test_performance.py` |
