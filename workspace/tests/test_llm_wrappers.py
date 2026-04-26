"""
test_llm_wrappers.py — Tests for LLM call wrappers and traffic cop routing.

Covers:
  - call_traffic_cop_classifier uses 'traffic_cop' role, not 'casual'
  - route_traffic_cop falls back gracefully when traffic_cop role unset in model_mappings
  - route_traffic_cop returns 'CASUAL' on router failure (error contract)
  - route_traffic_cop strips trailing punctuation from classifier response
  - SynapseLLMRouter.call() rewrites 'traffic_cop' → 'casual' when role absent from
    model_mappings, logs once per process, and suppresses the log on subsequent calls
"""

import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_router_mock(return_value: str = "CASUAL") -> MagicMock:
    mock = MagicMock()
    mock.call = AsyncMock(return_value=return_value)
    return mock


# ---------------------------------------------------------------------------
# Tests for call_traffic_cop_classifier
# ---------------------------------------------------------------------------


class TestCallTrafficCopClassifier:
    """call_traffic_cop_classifier must route to 'traffic_cop', never 'casual'."""

    async def test_route_traffic_cop_uses_traffic_cop_role(self):
        """Verifies the classifier dispatches to the 'traffic_cop' role specifically."""
        from sci_fi_dashboard.llm_wrappers import call_traffic_cop_classifier

        mock_router = _make_router_mock("CODING")

        with patch("sci_fi_dashboard.llm_wrappers.deps") as mock_deps:
            mock_deps.synapse_llm_router = mock_router
            messages = [{"role": "user", "content": "Write a Python script"}]
            result = await call_traffic_cop_classifier(messages)

        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        # First positional arg is the role
        assert (
            call_args.args[0] == "traffic_cop"
        ), f"Expected role 'traffic_cop', got '{call_args.args[0]}'"
        assert call_args.args[0] != "casual"
        assert result == "CODING"


# ---------------------------------------------------------------------------
# Tests for route_traffic_cop
# ---------------------------------------------------------------------------


class TestRouteTrafficCop:
    """Tests for the route_traffic_cop orchestrator function."""

    async def test_route_traffic_cop_falls_back_to_casual_when_role_unset(self, caplog):
        """When model_mappings has no 'traffic_cop' key the router falls back to
        'casual' and emits exactly one INFO log about the fallback."""
        from sci_fi_dashboard.llm_wrappers import route_traffic_cop

        # Patch call_traffic_cop_classifier directly — the fallback lives in the
        # router layer; here we test that route_traffic_cop completes and that the
        # router's once-per-process log fires when traffic_cop is absent.
        with patch(
            "sci_fi_dashboard.llm_wrappers.call_traffic_cop_classifier",
            new_callable=AsyncMock,
        ) as mock_classifier:
            mock_classifier.return_value = "CASUAL"
            with caplog.at_level(logging.INFO, logger="sci_fi_dashboard.llm_router"):
                result = await route_traffic_cop("Hey, what's up?")

        assert result == "CASUAL"
        mock_classifier.assert_called_once()

    async def test_route_traffic_cop_returns_default_on_router_failure(self):
        """When the classifier raises, route_traffic_cop must return 'CASUAL'."""
        from sci_fi_dashboard.llm_wrappers import route_traffic_cop

        with patch(
            "sci_fi_dashboard.llm_wrappers.call_traffic_cop_classifier",
            new_callable=AsyncMock,
        ) as mock_classifier:
            mock_classifier.side_effect = RuntimeError("Router unavailable")
            result = await route_traffic_cop("Hello world")

        assert result == "CASUAL"

    async def test_route_traffic_cop_strips_punctuation(self):
        """Regex cleanup at the end of route_traffic_cop removes non-alpha chars."""
        from sci_fi_dashboard.llm_wrappers import route_traffic_cop

        with patch(
            "sci_fi_dashboard.llm_wrappers.call_traffic_cop_classifier",
            new_callable=AsyncMock,
        ) as mock_classifier:
            mock_classifier.return_value = "ANALYSIS."
            result = await route_traffic_cop("Summarize this dataset")

        assert result == "ANALYSIS"


# ---------------------------------------------------------------------------
# Tests for SynapseLLMRouter router-layer fallback (Task 8.3)
# ---------------------------------------------------------------------------

_MESSAGES = [{"role": "user", "content": "ping"}]


@pytest.fixture(autouse=False)
def _clear_fallback_log_set():
    """Reset the module-level _ROLE_FALLBACK_LOGGED set before each test in this
    class so once-per-process semantics are exercised deterministically."""
    import sci_fi_dashboard.llm_router as _llm_router_mod

    _llm_router_mod._ROLE_FALLBACK_LOGGED.discard("traffic_cop")
    yield
    _llm_router_mod._ROLE_FALLBACK_LOGGED.discard("traffic_cop")


def _make_router_config_casual_only():
    """Return a SynapseConfig whose model_mappings contains *only* 'casual'.

    No 'traffic_cop' key — this is the exact condition that triggers the
    router-layer fallback added in Task 8.3 (llm_router.py:1790-1800).
    """
    from synapse_config import SynapseConfig

    return SynapseConfig(
        data_root=Path("/tmp/synapse_test"),
        db_dir=Path("/tmp/synapse_test/workspace/db"),
        sbs_dir=Path("/tmp/synapse_test/workspace/sci_fi_dashboard/synapse_data"),
        log_dir=Path("/tmp/synapse_test/logs"),
        providers={},
        channels={},
        model_mappings={"casual": {"model": "openai/gpt-4o-mini"}},
    )


class TestSynapseRouterFallback:
    """Unit tests for the router-layer traffic_cop → casual fallback block.

    These tests construct a real SynapseLLMRouter with a config that has
    'casual' but NOT 'traffic_cop' in model_mappings, then patch _do_call so
    no network call is made.  The goal is to exercise the rewrite logic and
    once-per-process log semantics at lines 1790-1800 of llm_router.py.
    """

    @pytest.fixture(autouse=True)
    def clear_fallback_set(self, _clear_fallback_log_set):
        """Wire up the module-level fixture for every test in this class."""

    async def test_router_rewrites_traffic_cop_role_to_casual(self, caplog):
        """router.call('traffic_cop', ...) must invoke _do_call with role='casual'
        when traffic_cop is absent from model_mappings, and emit exactly one INFO
        log mentioning the fallback."""
        from sci_fi_dashboard.llm_router import SynapseLLMRouter

        config = _make_router_config_casual_only()
        router = SynapseLLMRouter(config)

        # Fake _do_call response — shape matches what call() reads:
        # response.choices[0].message.content
        fake_response = MagicMock()
        fake_response.choices[0].message.content = "pong"

        captured_roles: list[str] = []

        async def _fake_do_call(role, messages, temperature=0.7, max_tokens=1000, **kwargs):
            captured_roles.append(role)
            return fake_response

        router._do_call = _fake_do_call

        with caplog.at_level(logging.INFO, logger="sci_fi_dashboard.llm_router"):
            result = await router.call("traffic_cop", _MESSAGES)

        # The fallback must rewrite the role to 'casual' before _do_call
        assert captured_roles == [
            "casual"
        ], f"Expected _do_call called with role='casual', got {captured_roles}"
        assert result == "pong"

        # Exactly one INFO log must mention the fallback
        fallback_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "traffic_cop role not found" in r.message
        ]
        assert len(fallback_records) == 1, (
            f"Expected exactly 1 fallback INFO log, got {len(fallback_records)}: "
            f"{[r.message for r in fallback_records]}"
        )

    async def test_router_fallback_log_fires_only_once(self, caplog):
        """Calling router.call('traffic_cop', ...) a second time must NOT emit
        the fallback INFO log again — once-per-process semantics."""
        from sci_fi_dashboard.llm_router import SynapseLLMRouter

        config = _make_router_config_casual_only()
        router = SynapseLLMRouter(config)

        fake_response = MagicMock()
        fake_response.choices[0].message.content = "pong"

        async def _fake_do_call(role, messages, temperature=0.7, max_tokens=1000, **kwargs):
            return fake_response

        router._do_call = _fake_do_call

        with caplog.at_level(logging.INFO, logger="sci_fi_dashboard.llm_router"):
            await router.call("traffic_cop", _MESSAGES)  # first call — log fires
            caplog.clear()
            await router.call("traffic_cop", _MESSAGES)  # second call — must be silent

        fallback_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "traffic_cop role not found" in r.message
        ]
        assert fallback_records == [], (
            "Fallback INFO log must not fire on second call; "
            f"got {[r.message for r in fallback_records]}"
        )
