"""
Pytest Configuration and Fixtures
=================================
Shared fixtures and configuration for all tests.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest.mock

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
    config.addinivalue_line("markers", "live_provider: Opt-in live LLM provider smoke tests")


# Custom pytest options
def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption("--run-slow", action="store_true", default=False, help="Run slow tests")
    parser.addoption(
        "--run-live-providers",
        action="store_true",
        default=False,
        help="Run live provider smoke tests when matching credentials/services are present",
    )
    parser.addoption(
        "--live-provider",
        action="append",
        default=[],
        help="Limit live provider tests to one provider key; can be passed multiple times",
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection."""
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    if not config.getoption("--run-live-providers"):
        skip_live = pytest.mark.skip(reason="need --run-live-providers option to run")
        for item in items:
            if "live_provider" in item.keywords:
                item.add_marker(skip_live)


# ---------------------------------------------------------------------------
# Phase 13 observability: clear run_id ContextVar between tests
# ---------------------------------------------------------------------------
import contextlib  # noqa: E402


@pytest.fixture(autouse=True)
def clear_run_id_between_tests():
    """OBS-01: Prevent run_id ContextVar leakage across tests.

    Plan 13-02 creates sci_fi_dashboard.observability.context; until then this
    fixture is a no-op (silently suppresses ImportError).
    """
    yield
    with contextlib.suppress(ImportError):
        from sci_fi_dashboard.observability.context import _run_id_ctx

        # Reset to module default (None) -- no Token needed for post-test cleanup
        _run_id_ctx.set(None)


# ---------------------------------------------------------------------------
# Phase 13 observability smoke helpers
# ---------------------------------------------------------------------------

import json as _obs_json  # noqa: E402  # avoid shadowing other json imports in this file
import logging as _obs_logging  # noqa: E402


@pytest.fixture
def fake_whatsapp_payload():
    """Factory producing a synthetic inbound WhatsApp payload matching the
    schema unified_webhook expects. The JID contains a 10-digit run which,
    after Phase 13 redaction, must NEVER appear raw in any log line.
    """

    def _build(
        text: str = "smoke test message",
        chat_id: str = "5551234567890@s.whatsapp.net",
        sender_name: str = "Smoke Tester",
    ) -> dict:
        return {
            "type": "message",
            "chat_id": chat_id,
            "text": text,
            "message_id": "SMOKE_MSG_ID_001",
            "sender_name": sender_name,
            "channel_id": "whatsapp",
        }

    return _build


@pytest.fixture
def json_log_capture():
    """Capture every emitted LogRecord after passing through the Synapse
    observability stack (JsonFormatter + RunIdFilter). Yields a list of
    (parsed_dict, raw_line) tuples. Handler is torn down at fixture exit.
    """
    from sci_fi_dashboard.observability.filters import RunIdFilter
    from sci_fi_dashboard.observability.formatter import JsonFormatter

    captured: list[tuple[dict, str]] = []

    class _CaptureHandler(_obs_logging.Handler):
        def emit(self, record: _obs_logging.LogRecord) -> None:
            try:
                line = self.format(record)
                parsed = _obs_json.loads(line)
                captured.append((parsed, line))
            except Exception as e:  # pragma: no cover
                captured.append(({"_capture_error": str(e)}, ""))

    handler = _CaptureHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RunIdFilter())

    root = _obs_logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(_obs_logging.DEBUG)

    try:
        yield captured
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)


# ---------------------------------------------------------------------------
# Phase 14 shared fixtures
# ---------------------------------------------------------------------------

try:
    from sci_fi_dashboard.observability.context import _run_id_ctx as _p14_run_id_ctx
except ImportError:
    _p14_run_id_ctx = None


@pytest.fixture(autouse=True)
def reset_run_id():
    """Clear the observability run_id ContextVar between every test.

    Prevents cross-test leakage when Phase 13 emitted a run_id in one test
    and a later test asserts on a clean starting state.
    """
    token = None
    if _p14_run_id_ctx is not None:
        token = _p14_run_id_ctx.set(None)
    yield
    if _p14_run_id_ctx is not None and token is not None:
        _p14_run_id_ctx.reset(token)


@pytest.fixture
def fake_monotonic():
    """Return a mutable single-element list acting as a patchable monotonic clock.

    Usage::

        def test_something(fake_monotonic):
            from unittest.mock import patch
            with patch("module.path.time.monotonic", lambda: fake_monotonic[0]):
                fake_monotonic[0] = 1000.0
                ...
    """
    return [0.0]


# --- Phase 16 fixtures — heartbeat + bridge health poller ---
# ---------------------------------------------------------------------------
# Phase 16 fixtures — heartbeat + bridge health poller
# ---------------------------------------------------------------------------

import types

import pytest


@pytest.fixture
def fake_channel_with_recorded_sends():
    """Return a SimpleNamespace(send=async_fn) that records every call.

    Usage:
        ch = fake_channel_with_recorded_sends()
        await ch.send("1234@s.whatsapp.net", "hi")
        assert ch.calls == [("1234@s.whatsapp.net", "hi")]
    """
    calls: list[tuple[str, str]] = []

    async def _send(chat_id: str, text: str) -> dict:
        calls.append((chat_id, text))
        return {"ok": True, "messageId": f"M{len(calls)}"}

    ch = types.SimpleNamespace(send=_send)
    ch.calls = calls
    return ch


@pytest.fixture
def fake_channel_registry_factory(fake_channel_with_recorded_sends):
    """Return a factory that builds a registry exposing the fake channel.

    Usage:
        registry = fake_channel_registry_factory("whatsapp")
        assert registry.get("whatsapp").send is not None
    """

    def _factory(channel_name: str = "whatsapp"):
        ch = fake_channel_with_recorded_sends
        return types.SimpleNamespace(get=lambda cid: ch if cid == channel_name else None)

    return _factory


@pytest.fixture
def reset_emitter_singleton():
    """Reset PipelineEventEmitter singleton state between tests so emit counts don't leak."""
    # Module may not exist yet in Wave 0 — import defensively
    try:
        from sci_fi_dashboard import pipeline_emitter as pe  # noqa: F401

        if hasattr(pe, "_EMITTER_SINGLETON"):
            pe._EMITTER_SINGLETON = None
    except Exception:
        pass
    yield
    try:
        from sci_fi_dashboard import pipeline_emitter as pe

        if hasattr(pe, "_EMITTER_SINGLETON"):
            pe._EMITTER_SINGLETON = None
    except Exception:
        pass
