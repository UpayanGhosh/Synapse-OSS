"""
Pytest Configuration and Fixtures
=================================
Shared fixtures and configuration for all tests.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest.mock

import asyncio
import pytest

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


@pytest.fixture(autouse=True)
def github_copilot_fake_auth(tmp_path):
    """Autouse fixture: create a fake GitHub Copilot token so litellm.Router can be
    initialized with 'github_copilot/' model entries during unit tests without
    triggering the real OAuth device-code flow.

    litellm reads the token from GITHUB_COPILOT_TOKEN_DIR/api-key.json.
    We write a fake entry with a far-future expiry and redirect the env var to tmp_path.
    Cleaned up automatically by pytest tmp_path fixture.
    """
    token_dir = tmp_path / "github_copilot"
    token_dir.mkdir(parents=True, exist_ok=True)
    api_key_file = token_dir / "api-key.json"
    api_key_file.write_text(
        json.dumps(
            {
                "token": "ghs_fake_token_for_unit_tests",
                "expires_at": time.time() + 3600,  # 1 hour from now
                "endpoints": {
                    "api": "https://api.githubcopilot.com",
                    "proxy": "https://copilot-proxy.githubusercontent.com",
                    "origin-tracker": "https://origin-tracker.githubusercontent.com",
                    "telemetry": "https://telemetry.individual.githubcopilot.com",
                },
            }
        )
    )
    old_token_dir = os.environ.get("GITHUB_COPILOT_TOKEN_DIR")
    os.environ["GITHUB_COPILOT_TOKEN_DIR"] = str(token_dir)
    yield
    if old_token_dir is None:
        os.environ.pop("GITHUB_COPILOT_TOKEN_DIR", None)
    else:
        os.environ["GITHUB_COPILOT_TOKEN_DIR"] = old_token_dir


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


@pytest.fixture
def mock_acompletion():
    """Patch litellm.acompletion with an AsyncMock that returns a valid response.

    Used by test_llm_router.py to test LLM routing logic without real API calls.
    All tests that request this fixture get a pre-configured AsyncMock that simulates
    a successful litellm completion response.
    """
    mock_response = unittest.mock.MagicMock()
    mock_response.choices = [unittest.mock.MagicMock()]
    mock_response.choices[0].message.content = "Hello from mock LLM"
    mock_response.choices[0].message.role = "assistant"
    mock_response.choices[0].finish_reason = "stop"

    with unittest.mock.patch("litellm.acompletion", new_callable=unittest.mock.AsyncMock) as mock:
        mock.return_value = mock_response
        yield mock


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
