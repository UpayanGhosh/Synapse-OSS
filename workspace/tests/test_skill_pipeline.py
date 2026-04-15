"""Tests for skill pipeline integration: SkillRunner and persona_chat routing.

Tests are organized in two groups:
1. SkillRunner tests — unit tests for the execution engine (test_runner_*)
2. Pipeline integration tests — confirm routing intercept in persona_chat (test_pipeline_*)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sci_fi_dashboard.skills.schema import SkillManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "test-skill",
    description: str = "A test skill",
    version: str = "1.0.0",
    model_hint: str = "",
    instructions: str = "You are a test skill assistant.",
    triggers: list[str] | None = None,
) -> SkillManifest:
    return SkillManifest(
        name=name,
        description=description,
        version=version,
        model_hint=model_hint,
        instructions=instructions,
        triggers=triggers or [],
        path=Path("."),
    )


def _make_llm_router(return_value: str = "Hello from skill!") -> AsyncMock:
    mock = AsyncMock()
    mock.call = AsyncMock(return_value=return_value)
    return mock


def _make_dual_cognition_mock():
    """Create a dual_cognition mock with all string-returning methods properly stubbed."""
    dc = MagicMock()
    # trajectory.get_summary() must return a string, not a MagicMock
    dc.trajectory.get_summary.return_value = ""
    dc.build_cognitive_context.return_value = ""
    return dc


# ---------------------------------------------------------------------------
# SkillRunner Tests (unit tests)
# ---------------------------------------------------------------------------


class TestSkillRunner:
    """Unit tests for SkillRunner.execute() behaviour."""

    @pytest.mark.asyncio
    async def test_runner_calls_llm_with_skill_instructions(self):
        """SkillRunner.execute calls the LLM with skill instructions as system prompt."""
        from sci_fi_dashboard.skills.runner import SkillResult, SkillRunner

        manifest = _make_manifest(instructions="You are a code review skill.")
        llm = _make_llm_router("Code looks good!")

        result = await SkillRunner.execute(
            manifest=manifest,
            user_message="Review my code",
            history=[],
            llm_router=llm,
        )

        assert isinstance(result, SkillResult)
        assert result.text == "Code looks good!"
        assert result.skill_name == "test-skill"
        assert result.error is False

        # Verify system prompt contains skill instructions
        call_args = llm.call.call_args
        messages = call_args[0][1]  # positional: role, messages
        system_messages = [m for m in messages if m["role"] == "system"]
        assert len(system_messages) >= 1
        assert "You are a code review skill." in system_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_runner_uses_model_hint_as_role(self):
        """SkillRunner.execute uses manifest.model_hint as LLM role if set."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = _make_manifest(model_hint="code")
        llm = _make_llm_router("response")

        await SkillRunner.execute(
            manifest=manifest,
            user_message="some message",
            history=[],
            llm_router=llm,
        )

        call_args = llm.call.call_args
        role = call_args[0][0]  # first positional arg is role
        assert role == "code"

    @pytest.mark.asyncio
    async def test_runner_falls_back_to_casual_when_no_model_hint(self):
        """SkillRunner.execute uses 'casual' role when manifest.model_hint is empty."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = _make_manifest(model_hint="")
        llm = _make_llm_router("response")

        await SkillRunner.execute(
            manifest=manifest,
            user_message="hello",
            history=[],
            llm_router=llm,
        )

        call_args = llm.call.call_args
        role = call_args[0][0]
        assert role == "casual"

    @pytest.mark.asyncio
    async def test_runner_catches_exception_returns_error_result(self):
        """SkillRunner.execute wraps LLM exceptions — returns error SkillResult, never raises."""
        from sci_fi_dashboard.skills.runner import SkillResult, SkillRunner

        manifest = _make_manifest(name="failing-skill")
        llm = AsyncMock()
        llm.call = AsyncMock(side_effect=RuntimeError("connection failed"))

        result = await SkillRunner.execute(
            manifest=manifest,
            user_message="test message",
            history=[],
            llm_router=llm,
        )

        assert isinstance(result, SkillResult)
        assert result.error is True
        assert "failing-skill" in result.text
        assert "RuntimeError" in result.text or "connection failed" in result.text
        assert result.skill_name == "failing-skill"

    @pytest.mark.asyncio
    async def test_runner_never_raises(self):
        """SkillRunner.execute never raises — any exception is caught and returned as error."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = _make_manifest(name="exploding-skill")
        llm = AsyncMock()
        llm.call = AsyncMock(side_effect=Exception("catastrophic failure"))

        # This must not raise
        try:
            result = await SkillRunner.execute(
                manifest=manifest,
                user_message="test",
                history=[],
                llm_router=llm,
            )
        except Exception as exc:
            pytest.fail(f"SkillRunner.execute raised an exception: {exc}")

        assert result.error is True

    @pytest.mark.asyncio
    async def test_runner_includes_conversation_history_in_messages(self):
        """SkillRunner.execute includes conversation history in the messages list."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = _make_manifest()
        llm = _make_llm_router("response with context")
        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]

        await SkillRunner.execute(
            manifest=manifest,
            user_message="follow-up question",
            history=history,
            llm_router=llm,
        )

        call_args = llm.call.call_args
        messages = call_args[0][1]
        assert any("previous question" in m.get("content", "") for m in messages)
        assert any("follow-up question" in m.get("content", "") for m in messages)

    @pytest.mark.asyncio
    async def test_runner_execution_ms_recorded(self):
        """SkillRunner.execute records execution_ms on the result."""
        from sci_fi_dashboard.skills.runner import SkillResult, SkillRunner

        manifest = _make_manifest()
        llm = _make_llm_router("fast response")

        result = await SkillRunner.execute(
            manifest=manifest,
            user_message="quick test",
            history=[],
            llm_router=llm,
        )

        assert isinstance(result, SkillResult)
        assert result.execution_ms >= 0.0

    @pytest.mark.asyncio
    async def test_runner_uses_description_fallback_when_no_instructions(self):
        """When manifest.instructions is empty, system prompt uses name + description."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = _make_manifest(
            name="helper-skill",
            description="Helps with tasks.",
            instructions="",
        )
        llm = _make_llm_router("response")

        await SkillRunner.execute(
            manifest=manifest,
            user_message="help me",
            history=[],
            llm_router=llm,
        )

        call_args = llm.call.call_args
        messages = call_args[0][1]
        system_messages = [m for m in messages if m["role"] == "system"]
        combined = " ".join(m["content"] for m in system_messages)
        assert "helper-skill" in combined or "Helps with tasks." in combined


# ---------------------------------------------------------------------------
# Pipeline Integration Tests (test_pipeline_*)
# These verify skill routing intercept in persona_chat after Task 2 integration.
# ---------------------------------------------------------------------------


class TestSkillPipelineIntegration:
    """Integration tests for skill routing in persona_chat."""

    def _make_chat_request(self, message: str = "hello", session_type: str = "safe"):
        """Create a minimal ChatRequest-like object for testing."""
        mock_request = MagicMock()
        mock_request.message = message
        mock_request.session_type = session_type
        mock_request.user_id = "test_user"
        mock_request.history = []
        return mock_request

    def _base_deps(self, mock_deps):
        """Apply common mock_deps attributes needed by persona_chat."""
        mock_deps.memory_engine = MagicMock()
        mock_deps.memory_engine.query = MagicMock(
            return_value={"results": [], "tier": "standard", "graph_context": ""}
        )
        mock_deps.memory_engine.add_memory = MagicMock()
        mock_deps.toxic_scorer = MagicMock()
        mock_deps.toxic_scorer.score = MagicMock(return_value=0.1)
        mock_deps._synapse_cfg = MagicMock()
        mock_deps._synapse_cfg.session = {"dual_cognition_enabled": False}
        mock_deps._synapse_cfg.data_root = Path("/tmp/synapse")
        mock_deps._synapse_cfg.model_mappings = {}
        mock_deps._synapse_cfg.raw = {}
        mock_deps.get_sbs_for_target = MagicMock(
            return_value=MagicMock(
                on_message=MagicMock(return_value={"msg_id": "abc"}),
                get_system_prompt=MagicMock(return_value="system prompt"),
            )
        )
        mock_deps._proactive_engine = None
        # dual_cognition: trajectory.get_summary() must return a string
        mock_deps.dual_cognition = _make_dual_cognition_mock()
        mock_deps.tool_registry = None
        mock_deps._TOOL_REGISTRY_AVAILABLE = False
        mock_deps._TOOL_SAFETY_AVAILABLE = False
        mock_deps._TOOL_FEATURES_AVAILABLE = False
        mock_deps.MAX_TOOL_ROUNDS = 5
        mock_deps.TOOL_RESULT_MAX_CHARS = 10000
        mock_deps.MAX_TOTAL_TOOL_RESULT_CHARS = 50000

    @pytest.mark.asyncio
    async def test_pipeline_skill_match_routes_to_runner(self):
        """When skill_router.match returns a manifest, persona_chat returns skill response."""
        from sci_fi_dashboard.chat_pipeline import persona_chat

        manifest = _make_manifest(name="weather-skill", instructions="You are a weather skill.")

        with patch("sci_fi_dashboard.chat_pipeline.deps") as mock_deps:
            self._base_deps(mock_deps)
            mock_deps._SKILL_SYSTEM_AVAILABLE = True
            mock_deps.skill_router = MagicMock()
            mock_deps.skill_router.match = MagicMock(return_value=manifest)
            mock_deps.synapse_llm_router = AsyncMock()
            mock_deps.synapse_llm_router.call = AsyncMock(return_value="Sunny today!")

            request = self._make_chat_request("What's the weather?")
            result = await persona_chat(request, "the_creator")

        assert result["model"].startswith("skill:")
        assert "weather-skill" in result["model"]
        assert result.get("retrieval_method") == "skill"

    @pytest.mark.asyncio
    async def test_pipeline_no_match_falls_through(self):
        """When skill_router.match returns None, persona_chat continues normally."""
        from sci_fi_dashboard.chat_pipeline import persona_chat

        with patch("sci_fi_dashboard.chat_pipeline.deps") as mock_deps:
            self._base_deps(mock_deps)
            mock_deps._SKILL_SYSTEM_AVAILABLE = True
            mock_deps.skill_router = MagicMock()
            mock_deps.skill_router.match = MagicMock(return_value=None)

            # Normal pipeline LLM result
            mock_deps.synapse_llm_router = AsyncMock()
            mock_result = MagicMock()
            mock_result.text = "Normal response"
            mock_result.model = "gemini/test"
            mock_result.completion_tokens = 10
            mock_result.prompt_tokens = 100
            mock_result.total_tokens = 110
            mock_result.tool_calls = None
            mock_deps.synapse_llm_router.call_with_metadata = AsyncMock(return_value=mock_result)

            request = self._make_chat_request("Hello there!")
            result = await persona_chat(request, "the_creator")

        # Should have gone through normal pipeline — no skill: prefix
        assert "skill:" not in result.get("model", "")

    @pytest.mark.asyncio
    async def test_pipeline_skill_router_none_falls_through(self):
        """When deps.skill_router is None (system disabled), normal pipeline continues."""
        from sci_fi_dashboard.chat_pipeline import persona_chat

        with patch("sci_fi_dashboard.chat_pipeline.deps") as mock_deps:
            self._base_deps(mock_deps)
            mock_deps._SKILL_SYSTEM_AVAILABLE = True
            mock_deps.skill_router = None  # System available but router not initialized

            mock_deps.synapse_llm_router = AsyncMock()
            mock_result = MagicMock()
            mock_result.text = "Normal response"
            mock_result.model = "gemini/test"
            mock_result.completion_tokens = 10
            mock_result.prompt_tokens = 100
            mock_result.total_tokens = 110
            mock_result.tool_calls = None
            mock_deps.synapse_llm_router.call_with_metadata = AsyncMock(return_value=mock_result)

            request = self._make_chat_request("Hi!")
            result = await persona_chat(request, "the_creator")

        assert "skill:" not in result.get("model", "")

    @pytest.mark.asyncio
    async def test_pipeline_spicy_session_skips_skill_routing(self):
        """Skills are never triggered in spicy/vault hemisphere (T-01-14)."""
        from sci_fi_dashboard.chat_pipeline import persona_chat

        manifest = _make_manifest(name="spy-skill")

        with patch("sci_fi_dashboard.chat_pipeline.deps") as mock_deps:
            self._base_deps(mock_deps)
            mock_deps._SKILL_SYSTEM_AVAILABLE = True
            mock_deps.skill_router = MagicMock()
            mock_deps.skill_router.match = MagicMock(return_value=manifest)
            mock_deps._synapse_cfg.model_mappings = {"vault": {"model": "ollama/mistral"}}

            # Vault path
            mock_result = MagicMock()
            mock_result.text = "Vault response"
            mock_result.model = "ollama/mistral"
            mock_result.completion_tokens = 5
            mock_result.prompt_tokens = 50
            mock_result.total_tokens = 55
            mock_deps.synapse_llm_router = AsyncMock()
            mock_deps.synapse_llm_router.call_with_metadata = AsyncMock(return_value=mock_result)

            request = self._make_chat_request("secret message", session_type="spicy")
            result = await persona_chat(request, "the_creator")

        # skill router's match should NOT have been called for spicy session
        mock_deps.skill_router.match.assert_not_called()
        assert "skill:" not in result.get("model", "")
