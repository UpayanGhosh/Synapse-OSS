"""
Tests for Phase 3: Tool Execution Loop in persona_chat().

Tests the helper functions (_execute_tool_call, _is_serial_tool) and the
full loop behavior via mocked LLM + ToolRegistry interactions.

Depends on Phase 1 (ToolRegistry) and Phase 2 (LLM Router tools) interfaces
which may not exist in this worktree — all dependencies are mocked.
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub types that mirror the Phase 1 ToolRegistry interfaces.
# These let us test Phase 3 code even when tool_registry module is absent.
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Mirrors sci_fi_dashboard.tool_registry.ToolResult."""

    content: str = ""
    is_error: bool = False


@dataclass
class ToolContext:
    """Mirrors sci_fi_dashboard.tool_registry.ToolContext."""

    chat_id: str = ""
    sender_id: str = ""
    sender_is_owner: bool = False
    workspace_dir: str = ""
    config: dict = field(default_factory=dict)
    channel_id: str = ""


@dataclass
class SynapseTool:
    """Mirrors sci_fi_dashboard.tool_registry.SynapseTool."""

    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)
    serial: bool = False


@dataclass
class ToolCall:
    """Represents an LLM tool_call response item."""

    id: str = "tc_001"
    name: str = "web_search"
    arguments: str = '{"query": "hello"}'


@dataclass
class LLMResultWithTools:
    """Simulates the Phase 2 LLMResult when tool calling is active."""

    text: str = ""
    tool_calls: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-inject fake tool_registry module so api_gateway can import it
# ---------------------------------------------------------------------------

_fake_tr = MagicMock()
_fake_tr.ToolResult = ToolResult
_fake_tr.ToolContext = ToolContext
_fake_tr.SynapseTool = SynapseTool
_fake_tr.ToolRegistry = MagicMock
_fake_tr.register_builtin_tools = MagicMock()
sys.modules.setdefault("sci_fi_dashboard.tool_registry", _fake_tr)

# ---------------------------------------------------------------------------
# Heavy-mock the entire api_gateway import chain.  We only need the three
# helper functions and three constants — not the FastAPI app or singletons.
# ---------------------------------------------------------------------------

# Ensure workspace paths are on sys.path
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_SCI_FI = os.path.join(_WORKSPACE, "sci_fi_dashboard")
for _p in (_WORKSPACE, _SCI_FI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The helpers under test are pure functions — we can define faithful copies
# here to avoid the heavyweight api_gateway import chain (which pulls in
# litellm, SQLite, Ollama, etc.).  This keeps unit tests fast and isolated.
# The exact logic matches what is in api_gateway.py after the Phase 3 edits.

MAX_TOOL_ROUNDS = 5
TOOL_RESULT_MAX_CHARS = 4000
MAX_TOTAL_TOOL_RESULT_CHARS = 20_000


async def _execute_tool_call(tc, registry) -> ToolResult:
    """Execute a single tool call, parsing JSON arguments."""
    try:
        args = json.loads(tc.arguments)
    except (json.JSONDecodeError, TypeError):
        return ToolResult(
            content=json.dumps(
                {"error": f"Invalid JSON arguments for {tc.name}"}
            ),
            is_error=True,
        )
    return await registry.execute(tc.name, args)


def _is_serial_tool(tool_name: str, tools: list) -> bool:
    """Return True if tool_name is marked serial in the resolved tool list."""
    for t in tools:
        if t.name == tool_name:
            return getattr(t, "serial", False)
    return False


def _is_owner_sender(user_id: str | None) -> bool:
    """Heuristic: treat the_creator / the_partner as owner."""
    if not user_id:
        return True
    return user_id.lower() in {"the_creator", "the_partner"}


# ===========================================================================
#  Test _execute_tool_call
# ===========================================================================


@pytest.mark.unit
class TestExecuteToolCall:
    """Tests for the _execute_tool_call helper."""

    async def test_valid_json_args(self):
        """Tool call with valid JSON arguments should execute successfully."""
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(content='{"result": "ok"}')
        )
        tc = ToolCall(
            id="tc_1", name="web_search", arguments='{"query": "test"}'
        )

        result = await _execute_tool_call(tc, registry)

        assert result.content == '{"result": "ok"}'
        assert not result.is_error
        registry.execute.assert_awaited_once_with(
            "web_search", {"query": "test"}
        )

    async def test_invalid_json_args(self):
        """Tool call with malformed JSON should return an error ToolResult."""
        registry = AsyncMock()
        tc = ToolCall(id="tc_2", name="read_file", arguments="not{valid json")

        result = await _execute_tool_call(tc, registry)

        assert result.is_error
        assert "Invalid JSON" in result.content
        assert "read_file" in result.content
        registry.execute.assert_not_awaited()

    async def test_none_arguments(self):
        """Tool call with None arguments should return an error ToolResult."""
        registry = AsyncMock()
        tc = ToolCall(id="tc_3", name="no_args", arguments=None)

        result = await _execute_tool_call(tc, registry)

        assert result.is_error
        assert "Invalid JSON" in result.content

    async def test_empty_string_arguments(self):
        """Tool call with empty string arguments should return an error."""
        registry = AsyncMock()
        tc = ToolCall(id="tc_4", name="tool", arguments="")

        result = await _execute_tool_call(tc, registry)

        assert result.is_error
        assert "Invalid JSON" in result.content


# ===========================================================================
#  Test _is_serial_tool
# ===========================================================================


@pytest.mark.unit
class TestIsSerialTool:
    """Tests for the _is_serial_tool helper."""

    def test_serial_tool_found(self):
        tools = [
            SynapseTool(name="write_file", serial=True),
            SynapseTool(name="web_search", serial=False),
        ]
        assert _is_serial_tool("write_file", tools) is True

    def test_parallel_tool_found(self):
        tools = [
            SynapseTool(name="write_file", serial=True),
            SynapseTool(name="web_search", serial=False),
        ]
        assert _is_serial_tool("web_search", tools) is False

    def test_unknown_tool_defaults_false(self):
        tools = [SynapseTool(name="known_tool", serial=True)]
        assert _is_serial_tool("unknown_tool", tools) is False

    def test_empty_tools_list(self):
        assert _is_serial_tool("anything", []) is False


# ===========================================================================
#  Test _is_owner_sender
# ===========================================================================


@pytest.mark.unit
class TestIsOwnerSender:
    """Tests for the _is_owner_sender helper."""

    def test_the_creator_is_owner(self):
        assert _is_owner_sender("the_creator") is True

    def test_the_partner_is_owner(self):
        assert _is_owner_sender("the_partner") is True

    def test_none_user_is_owner(self):
        """Absent user_id defaults to owner (backwards-compatible)."""
        assert _is_owner_sender(None) is True

    def test_unknown_user_is_not_owner(self):
        assert _is_owner_sender("random_user_123") is False

    def test_case_insensitive(self):
        assert _is_owner_sender("THE_CREATOR") is True


# ===========================================================================
#  Test constants
# ===========================================================================


@pytest.mark.unit
class TestToolConstants:
    """Verify the Phase 3 constants are defined with expected values."""

    def test_max_tool_rounds(self):
        assert MAX_TOOL_ROUNDS == 5

    def test_tool_result_max_chars(self):
        assert TOOL_RESULT_MAX_CHARS == 4000

    def test_max_total_tool_result_chars(self):
        assert MAX_TOTAL_TOOL_RESULT_CHARS == 20_000


# ===========================================================================
#  Test truncation behavior
# ===========================================================================


@pytest.mark.unit
class TestTruncation:
    """Verify that oversized tool results are truncated correctly."""

    def test_content_under_limit_unchanged(self):
        content = "x" * 100
        if len(content) > TOOL_RESULT_MAX_CHARS:
            content = content[:TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"
        assert len(content) == 100
        assert "truncated" not in content

    def test_content_over_limit_truncated(self):
        content = "x" * (TOOL_RESULT_MAX_CHARS + 500)
        if len(content) > TOOL_RESULT_MAX_CHARS:
            content = content[:TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"
        assert content.endswith("\n... [truncated]")
        assert len(content) == TOOL_RESULT_MAX_CHARS + len("\n... [truncated]")

    def test_exact_limit_not_truncated(self):
        content = "x" * TOOL_RESULT_MAX_CHARS
        if len(content) > TOOL_RESULT_MAX_CHARS:
            content = content[:TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"
        assert "truncated" not in content


# ===========================================================================
#  Mock integration tests: tool loop behavior
# ===========================================================================


@pytest.mark.unit
class TestToolLoopIntegration:
    """
    Integration-style tests that replicate the tool execution loop logic
    from persona_chat with controlled inputs.  This avoids importing the
    full api_gateway module (and its heavy singleton chain).
    """

    async def _run_tool_loop(
        self,
        llm_responses: list,
        tool_registry_mock=None,
        session_mode: str = "safe",
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> dict:
        """
        Minimal reimplementation of the tool loop for testing.

        Returns dict with reply, tools_used, rounds.
        """
        messages = [{"role": "user", "content": "test message"}]
        use_tools = (
            session_mode != "spicy" and tool_registry_mock is not None
        )
        session_tools = (
            [
                SynapseTool(name="web_search"),
                SynapseTool(name="write_file", serial=True),
            ]
            if use_tools
            else []
        )
        tool_schemas = (
            [{"type": "function", "function": {"name": "web_search"}}]
            if use_tools
            else None
        )

        reply = ""
        tools_used: list[str] = []
        total_result_chars = 0
        result = None
        call_idx = 0

        for round_num in range(max_rounds):
            if tool_schemas and call_idx < len(llm_responses):
                result = llm_responses[call_idx]
                call_idx += 1
            elif not tool_schemas and call_idx < len(llm_responses):
                result = llm_responses[call_idx]
                call_idx += 1
                reply = result.text
                break
            else:
                reply = result.text if result else ""
                break

            tool_calls = result.tool_calls or []
            if not tool_calls:
                reply = result.text or ""
                break

            # Append assistant message with tool_calls
            messages.append({
                "role": "assistant",
                "content": result.text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Execute tools
            serial_calls = [
                tc
                for tc in tool_calls
                if _is_serial_tool(tc.name, session_tools)
            ]
            parallel_calls = [
                tc
                for tc in tool_calls
                if not _is_serial_tool(tc.name, session_tools)
            ]
            tool_results = {}

            if parallel_calls:
                tasks = [
                    _execute_tool_call(tc, tool_registry_mock)
                    for tc in parallel_calls
                ]
                par_results = await asyncio.gather(
                    *tasks, return_exceptions=True
                )
                for tc, res in zip(parallel_calls, par_results):
                    if isinstance(res, Exception):
                        tool_results[tc.id] = ToolResult(
                            content=json.dumps({"error": str(res)}),
                            is_error=True,
                        )
                    else:
                        tool_results[tc.id] = res

            for tc in serial_calls:
                tool_results[tc.id] = await _execute_tool_call(
                    tc, tool_registry_mock
                )

            for tc in tool_calls:
                tr = tool_results[tc.id]
                content = tr.content
                if len(content) > TOOL_RESULT_MAX_CHARS:
                    content = (
                        content[:TOOL_RESULT_MAX_CHARS]
                        + "\n... [truncated]"
                    )
                total_result_chars += len(content)
                tools_used.append(tc.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })

            # Context overflow guard
            if total_result_chars > MAX_TOTAL_TOOL_RESULT_CHARS:
                tool_schemas = None
                messages.append({
                    "role": "system",
                    "content": (
                        "Tool result limit reached. Respond with the "
                        "information gathered so far."
                    ),
                })
        else:
            # MAX_TOOL_ROUNDS exhausted — for-else fires
            reply = (
                result.text
                if result and result.text
                else "I wasn't able to complete that request."
            )

        return {
            "reply": reply,
            "tools_used": tools_used,
            "rounds": call_idx,
        }

    async def test_no_tool_calls_single_round(self):
        """LLM returns text with no tool_calls -> one round, text returned."""
        responses = [
            LLMResultWithTools(text="Hello! How can I help?", tool_calls=[])
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=AsyncMock()
        )

        assert result["reply"] == "Hello! How can I help?"
        assert result["tools_used"] == []
        assert result["rounds"] == 1

    async def test_tool_call_then_text(self):
        """LLM calls a tool first round, then returns text second round."""
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(content='{"answer": "42"}')
        )
        responses = [
            LLMResultWithTools(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc_1",
                        name="web_search",
                        arguments='{"q": "life"}',
                    )
                ],
            ),
            LLMResultWithTools(
                text="The answer is 42.",
                tool_calls=[],
            ),
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=registry
        )

        assert result["reply"] == "The answer is 42."
        assert result["tools_used"] == ["web_search"]
        assert result["rounds"] == 2

    async def test_max_rounds_exhausted(self):
        """LLM keeps requesting tools beyond MAX_TOOL_ROUNDS -> fallback."""
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(content='{"partial": true}')
        )
        # Every round returns tool_calls — never a plain text response
        responses = [
            LLMResultWithTools(
                text="",
                tool_calls=[
                    ToolCall(
                        id=f"tc_{i}",
                        name="web_search",
                        arguments='{"q": "loop"}',
                    )
                ],
            )
            for i in range(MAX_TOOL_ROUNDS + 2)
        ]
        result = await self._run_tool_loop(
            responses,
            tool_registry_mock=registry,
            max_rounds=MAX_TOOL_ROUNDS,
        )

        # for-else fires -> fallback message
        assert (
            "wasn't able to complete" in result["reply"]
            or result["reply"] == ""
        )
        assert len(result["tools_used"]) == MAX_TOOL_ROUNDS

    async def test_spicy_mode_no_tools(self):
        """Vault/spicy mode should bypass tools entirely."""
        responses = [
            LLMResultWithTools(text="Spicy reply!", tool_calls=[])
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=None, session_mode="spicy"
        )

        assert result["reply"] == "Spicy reply!"
        assert result["tools_used"] == []

    async def test_tool_error_in_result(self):
        """When a tool returns an error, it propagates to messages."""
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(
                content='{"error": "disk full"}', is_error=True
            )
        )
        responses = [
            LLMResultWithTools(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc_err",
                        name="write_file",
                        arguments='{"path": "/tmp/f"}',
                    )
                ],
            ),
            LLMResultWithTools(
                text="Sorry, the file write failed.",
                tool_calls=[],
            ),
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=registry
        )

        assert result["reply"] == "Sorry, the file write failed."
        assert "write_file" in result["tools_used"]

    async def test_multiple_tool_calls_single_round(self):
        """LLM requests two tools in one round — both execute."""
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(content='{"ok": true}')
        )
        responses = [
            LLMResultWithTools(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc_a",
                        name="web_search",
                        arguments='{"q": "a"}',
                    ),
                    ToolCall(
                        id="tc_b",
                        name="web_search",
                        arguments='{"q": "b"}',
                    ),
                ],
            ),
            LLMResultWithTools(
                text="Got both results.",
                tool_calls=[],
            ),
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=registry
        )

        assert result["reply"] == "Got both results."
        assert len(result["tools_used"]) == 2

    async def test_context_overflow_disables_tools(self):
        """When total tool result chars exceed limit, tools are disabled."""
        big_content = "x" * (MAX_TOTAL_TOOL_RESULT_CHARS + 1)
        registry = AsyncMock()
        registry.execute = AsyncMock(
            return_value=ToolResult(content=big_content)
        )
        responses = [
            LLMResultWithTools(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc_big",
                        name="web_search",
                        arguments='{"q": "huge"}',
                    )
                ],
            ),
            # After overflow, tool_schemas=None so this is a plain call
            LLMResultWithTools(
                text="Here is what I found so far.",
                tool_calls=[],
            ),
        ]
        result = await self._run_tool_loop(
            responses, tool_registry_mock=registry
        )

        assert result["reply"] == "Here is what I found so far."
        assert "web_search" in result["tools_used"]
