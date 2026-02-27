"""
Pytest Configuration and Fixtures
=================================
Shared fixtures and configuration for all tests.
"""

import pytest
import asyncio
import sys
import os
import tempfile
import shutil

# Add workspace to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


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


@pytest.fixture
def temp_conflicts_file(temp_dir):
    """Create a temporary conflicts file path."""
    return os.path.join(temp_dir, "conflicts.json")


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


# Configure pytest
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "functional: Functional tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "acceptance: Acceptance tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "smoke: Smoke tests")


# Custom pytest options
def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption("--run-slow", action="store_true", default=False, help="Run slow tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection."""
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
