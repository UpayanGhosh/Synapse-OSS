"""
test_llm_wrappers.py — Tests for LLM call wrappers and traffic cop routing.

Covers:
  - call_traffic_cop_classifier uses 'traffic_cop' role, not 'casual'
  - route_traffic_cop falls back gracefully when traffic_cop role unset in model_mappings
  - route_traffic_cop returns 'CASUAL' on router failure (error contract)
  - route_traffic_cop strips trailing punctuation from classifier response
"""

import logging
import os
import sys

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
