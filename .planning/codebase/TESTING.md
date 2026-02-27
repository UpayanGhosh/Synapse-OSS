# Testing Patterns

**Analysis Date:** 2026-02-27

## Test Framework

**Runner:**
- `pytest` (with asyncio plugin support)
- Configuration: `workspace/tests/pytest.ini`

**Assertion Library:**
- Built-in `assert` statements (Python native)
- No separate assertion library; pytest assertions sufficient

**Run Commands:**
```bash
# Run all tests from workspace/
cd workspace
pytest tests/ -v

# Run by category
pytest tests/ -m unit
pytest tests/ -m integration
pytest tests/ -m smoke
pytest tests/ -m "not performance"     # Skip slow tests

# Run a single test file
pytest tests/test_queue.py -v

# Run a single test
pytest tests/test_queue.py::TestTaskQueue::test_enqueue_adds_task -v

# Include slow tests
pytest tests/ --run-slow -v
```

**Configuration (pytest.ini):**
- Test discovery: files matching `test_*.py`, classes matching `Test*`, functions matching `test_*`
- Output: verbose mode with short tracebacks
- Asyncio mode: `auto` (all async tests work without explicit `@pytest.mark.asyncio`)
- Markers: unit, integration, functional, e2e, acceptance, performance, smoke, slow
- Test paths: `tests/` directory at workspace root

## Test File Organization

**Location:**
- All tests in: `workspace/tests/`
- Co-located strategy (separate directory, not alongside source code)

**Naming:**
- Files: `test_<component>.py` (e.g., `test_queue.py`, `test_flood.py`, `test_integration.py`)
- Classes: `Test<ComponentName>` or descriptive like `TestMessageProcessingFunctionality`
- Functions: `test_<behavior_description>` (e.g., `test_enqueue_adds_task`)

**Structure:**
```
workspace/tests/
├── conftest.py                  # Shared fixtures and configuration
├── test_queue.py                # Unit tests for TaskQueue
├── test_flood.py                # Unit tests for FloodGate
├── test_dedup.py                # Unit tests for MessageDeduplicator
├── test_sqlite_graph.py          # Unit tests for SQLiteGraph
├── test_conflict_resolver.py     # Unit tests for ConflictManager
├── test_integration.py           # Integration tests (module interactions)
├── test_functional.py            # Functional tests (business logic)
├── test_e2e.py                   # End-to-end tests (full user flows)
├── test_acceptance.py            # Acceptance tests (requirements verification)
├── test_smoke.py                 # Smoke tests (basic functionality)
└── test_performance.py           # Performance tests (load/stress)
```

## Test Structure

**Suite Organization:**
Typical test class structure from `workspace/tests/test_queue.py`:
```python
class TestTaskQueue:
    """Test cases for async task queue operations."""

    @pytest.fixture
    def queue(self):
        """Create a fresh TaskQueue."""
        return TaskQueue(max_size=10, max_history=5)

    @pytest.mark.asyncio
    async def test_enqueue_adds_task(self, queue):
        """Enqueuing a task should add it to active tasks."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)

        assert queue.pending_count == 1
        assert "task_001" in queue._active_tasks
```

**Patterns:**
- **Setup via fixtures:** `@pytest.fixture` decorators provide test data and objects (database connections, message samples, queue instances)
- **Teardown via fixture cleanup:** `yield` pattern with cleanup code after
- **Markers for test categories:** `@pytest.mark.asyncio`, `@pytest.mark.integration`, `@pytest.mark.performance`
- **Docstrings explaining intent:** Every test has a descriptive docstring explaining what it verifies

**Example fixture from `workspace/tests/conftest.py` (lines 18-32):**
```python
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)

@pytest.fixture
def temp_db(temp_dir):
    """Create a temporary database path."""
    return os.path.join(temp_dir, "test.db")
```

## Mocking

**Framework:** `unittest.mock` (Python standard library)

**Patterns:**
Mocking used in async tests (`workspace/tests/test_functional.py` lines 52-73):
```python
@pytest.mark.asyncio
async def test_rapid_messages_batched(self):
    """Rapid messages from same user should be batched."""
    flood = FloodGate(batch_window_seconds=2.0)

    messages_received = []

    async def callback(chat_id, message, metadata):
        messages_received.append(message)

    flood.set_callback(callback)

    # Simulate rapid messages
    await flood.incoming("chat_001", "First", {"sender": "user1"})
    await flood.incoming("chat_001", "Second", {"sender": "user1"})
    await flood.incoming("chat_001", "Third", {"sender": "user1"})

    # Wait for batch window
    await asyncio.sleep(2.5)

    # Should have batched into fewer messages
```

**Mocking approach:**
- Callback functions (not mock objects) for async operations
- `AsyncMock` from unittest.mock imported but pattern shows direct async function definition preferred
- No widespread mocking library; tests generally use real objects (temporary databases, real queues)

**What to Mock:**
- External API calls (when absolutely needed, but tests prefer integration with real local services)
- Long-running operations (but tests use `asyncio.sleep()` to simulate timing)
- File system operations (via `temp_dir` fixture)

**What NOT to Mock:**
- Task queue operations (tested with real `TaskQueue` instances)
- Database operations (tested with real `SQLiteGraph` on temp database)
- Message deduplication (tested with real `MessageDeduplicator` state)
- Graph operations (tested with real SQLite backing)

**Example integration test (`workspace/tests/test_integration.py` lines 59-76):**
```python
@pytest.mark.asyncio
async def test_dedup_and_queue_integration(self, temp_dir):
    """Test deduplicator working with task queue."""
    dedup = MessageDeduplicator(window_seconds=60)
    queue = TaskQueue(max_size=10)

    # Process first message
    msg_id = "wa_12345"
    assert dedup.is_duplicate(msg_id) is False

    # Create and enqueue task
    task = MessageTask(task_id=msg_id, chat_id="chat_001", user_message="Hello")
    await queue.enqueue(task)

    # Same message should be deduped
    assert dedup.is_duplicate(msg_id) is True

    # Queue should have one task
    assert queue.pending_count == 1
```

## Fixtures and Factories

**Test Data:**
Standard fixtures in `workspace/tests/conftest.py` (lines 46-69):
```python
@pytest.fixture
def sample_message():
    """Sample WhatsApp message for testing."""
    return {
        "message_id": "wa_test_001",
        "from": "+1234567890",
        "chat_id": "chat_001",
        "body": "Hello Synapse",
        "timestamp": 1234567890,
    }

@pytest.fixture
def sample_task():
    """Sample MessageTask for testing."""
    from sci_fi_dashboard.gateway.queue import MessageTask

    return MessageTask(
        task_id="test_001",
        chat_id="chat_001",
        user_message="Test message",
        message_id="wa_001",
        sender_name="Test User",
    )
```

**Location:**
- `workspace/tests/conftest.py` — Shared fixtures across all tests
- Test class-level fixtures: `@pytest.fixture` methods within test classes for localized test data

**Pattern for database fixtures:**
```python
@pytest.fixture
def graph(self, temp_dir):
    """Create a graph instance with temp database."""
    db_path = os.path.join(temp_dir, "test.db")
    return SQLiteGraph(db_path=db_path)
```

## Coverage

**Requirements:** Not enforced; optional via `pytest-cov` if installed

**View Coverage (if installed):**
```bash
pytest tests/ --cov=sci_fi_dashboard --cov-report=html
```

Configuration comment in `pytest.ini` (line 31):
```ini
# Coverage (if pytest-cov installed)
# addopts = --cov=sci_fi_dashboard --cov-report=html
```

Coverage is not mandatory; code is tested primarily through explicit test cases without automated coverage gates.

## Test Types

**Unit Tests:**
- Scope: Individual functions and methods in isolation
- Approach: Test single component behavior with real object instantiation
- Example: `test_enqueue_adds_task` in `test_queue.py` tests `TaskQueue.enqueue()` alone
- Files: `test_queue.py`, `test_flood.py`, `test_dedup.py`, `test_sqlite_graph.py`

**Integration Tests:**
- Scope: Multiple components working together (queue + dedup, graph + task flow)
- Approach: Create real instances of multiple classes and verify interactions
- Example: `test_dedup_and_queue_integration` verifies deduplicator and queue work together
- Files: `test_integration.py`

**Functional Tests:**
- Scope: Business logic and requirements (not how, but what)
- Approach: Test user-facing behavior end-to-end without mocks
- Example: `test_no_duplicate_responses_sent` verifies system logic
- Files: `test_functional.py`

**E2E Tests:**
- Scope: Complete user workflows (webhook → process → respond)
- Approach: Simulate real WhatsApp message flow through entire pipeline
- Prerequisites: Full system running, API keys available
- Files: `test_e2e.py`

**Acceptance Tests:**
- Scope: Business requirements verification (REQUIREMENT comments in code)
- Approach: Verify non-functional requirements (latency <350ms, memory <1MB, etc.)
- Example: `test_memory_retrieval_fast` verifies <350ms requirement
- Files: `test_acceptance.py`

**Smoke Tests:**
- Scope: Basic system functionality (startup, health checks)
- Approach: Quick tests to verify system boots and core features work
- Files: `test_smoke.py`

**Performance Tests:**
- Scope: Load, stress, and optimization
- Approach: Measure timing, throughput, memory under load
- Marker: `@pytest.mark.performance` (skipped by default with `--run-slow`)
- Files: `test_performance.py`

## Common Patterns

**Async Testing:**
All async operations use `async def` with automatic asyncio mode:
```python
@pytest.mark.asyncio
async def test_enqueue_adds_task(self, queue):
    """Enqueuing a task should add it to active tasks."""
    task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

    await queue.enqueue(task)

    assert queue.pending_count == 1
```

No explicit `@pytest.mark.asyncio` required on every test — `asyncio_mode = auto` in `pytest.ini` handles this.

**Error Testing:**
Testing error conditions and exception handling:
```python
def test_task_id_required(self):
    """Task should require task_id, chat_id, and user_message."""
    with pytest.raises(TypeError):
        MessageTask(chat_id="chat_001", user_message="Hello")

    with pytest.raises(TypeError):
        MessageTask(task_id="task_001", user_message="Hello")
```

**Timing/Async Wait Testing:**
Using `asyncio.sleep()` to simulate and test timing behavior:
```python
@pytest.mark.asyncio
async def test_debounce_extends_window(self, flood_gate):
    """Additional messages should extend the batch window."""
    await flood_gate.incoming("chat_001", "First", {"sender": "user1"})
    await asyncio.sleep(0.8)
    await flood_gate.incoming("chat_001", "Second", {"sender": "user1"})
    await asyncio.sleep(0.8)
    assert len(flushed_messages) == 0  # Not flushed yet (window extended)
    await asyncio.sleep(1.0)
    assert len(flushed_messages) == 1  # Now flushed
```

**Temporary File Testing:**
Using fixtures for isolated file operations:
```python
def test_graph_to_queue_integration(self, graph, temp_dir):
    """Test that knowledge graph can inform queue processing."""
    graph.add_node("User1", "person")
    graph.add_edge("User1", "Synapse", "interacts_with")
    task = MessageTask(...)
    assert task.user_message is not None
```

---

*Testing analysis: 2026-02-27*
