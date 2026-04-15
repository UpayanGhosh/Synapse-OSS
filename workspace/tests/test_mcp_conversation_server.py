"""
Tests for sci_fi_dashboard.mcp_servers.conversation_server — profile + system prompt.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _text(results: list) -> str:
    return results[0].text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_both_tools(self):
        from sci_fi_dashboard.mcp_servers.conversation_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"get_profile_summary", "get_system_prompt"}


# ---------------------------------------------------------------------------
# get_profile_summary
# ---------------------------------------------------------------------------


class TestGetProfileSummary:
    @pytest.mark.asyncio
    async def test_returns_profile_json(self):
        import sci_fi_dashboard.mcp_servers.conversation_server as conv_srv

        mock_orch = MagicMock()
        mock_orch.get_profile_summary.return_value = {
            "mood": "chill",
            "vocab_size": 1200,
        }

        with patch.object(conv_srv, "_get_orchestrator", return_value=mock_orch):
            result = await conv_srv.call_tool("get_profile_summary", {})

        data = json.loads(_text(result))
        assert data["mood"] == "chill"
        assert data["vocab_size"] == 1200


# ---------------------------------------------------------------------------
# get_system_prompt
# ---------------------------------------------------------------------------


class TestGetSystemPrompt:
    @pytest.mark.asyncio
    async def test_returns_compiled_prompt(self):
        import sci_fi_dashboard.mcp_servers.conversation_server as conv_srv

        mock_orch = MagicMock()
        mock_orch.get_system_prompt.return_value = "You are Synapse..."

        with patch.object(conv_srv, "_get_orchestrator", return_value=mock_orch):
            result = await conv_srv.call_tool(
                "get_system_prompt", {"base_instructions": "Be helpful"}
            )

        assert "Synapse" in _text(result)
        mock_orch.get_system_prompt.assert_called_once_with("Be helpful")

    @pytest.mark.asyncio
    async def test_default_base_instructions_empty(self):
        import sci_fi_dashboard.mcp_servers.conversation_server as conv_srv

        mock_orch = MagicMock()
        mock_orch.get_system_prompt.return_value = "prompt"

        with patch.object(conv_srv, "_get_orchestrator", return_value=mock_orch):
            await conv_srv.call_tool("get_system_prompt", {})

        mock_orch.get_system_prompt.assert_called_once_with("")


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        import sci_fi_dashboard.mcp_servers.conversation_server as conv_srv

        mock_orch = MagicMock()
        with patch.object(conv_srv, "_get_orchestrator", return_value=mock_orch):
            result = await conv_srv.call_tool("bad_tool", {})

        assert "Unknown tool" in _text(result)


# ---------------------------------------------------------------------------
# Orchestrator singleton
# ---------------------------------------------------------------------------


class TestOrchestratorSingleton:
    def test_caches_instance(self):
        import sci_fi_dashboard.mcp_servers.conversation_server as conv_srv

        mock_cfg = MagicMock()
        mock_cfg.sbs_dir = "/tmp/sbs"
        mock_orch = MagicMock()

        mock_config_mod = MagicMock()
        mock_config_mod.SynapseConfig.load.return_value = mock_cfg
        mock_sbs_mod = MagicMock()
        mock_sbs_mod.SBSOrchestrator.return_value = mock_orch

        with patch.dict(
            "sys.modules",
            {
                "synapse_config": mock_config_mod,
                "sbs.orchestrator": mock_sbs_mod,
            },
        ):
            conv_srv._orchestrator = None
            o1 = conv_srv._get_orchestrator()
            o2 = conv_srv._get_orchestrator()
            assert o1 is o2

        conv_srv._orchestrator = None
