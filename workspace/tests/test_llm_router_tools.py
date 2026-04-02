"""
test_llm_router_tools.py — Phase 2 tool-execution unit tests.

Tests for:
  - normalize_tool_schemas(): provider-specific schema quirk handling
  - normalize_tool_calls(): response parsing + whitespace/ID normalization
  - _attempt_json_repair(): truncated JSON recovery
"""

import json
import sys
import types
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.llm_router import (
    ToolCall,
    _attempt_json_repair,
    normalize_tool_calls,
    normalize_tool_schemas,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "get_weather",
    parameters: dict | None = None,
) -> dict:
    """Build a minimal OpenAI-format tool definition for testing."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Test tool: {name}",
            "parameters": parameters
            or {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                },
                "required": ["location"],
            },
        },
    }


def _make_raw_tool_call(
    name: str = "get_weather",
    arguments: str = '{"location": "London"}',
    call_id: str | None = "call_abc123",
) -> types.SimpleNamespace:
    """Build a mock litellm tool-call object using SimpleNamespace."""
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(
            name=name,
            arguments=arguments,
        ),
    )


# ---------------------------------------------------------------------------
# TestSchemaQuirks — normalize_tool_schemas provider-specific fixes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchemaQuirks:
    def test_gemini_strips_defs_and_default(self):
        """Gemini provider must strip $schema, $id, examples, default, $defs."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "$schema": "http://json-schema.org/draft-07/schema#",
                "$id": "test",
                "$defs": {"Foo": {"type": "string"}},
                "properties": {
                    "city": {
                        "type": "string",
                        "default": "London",
                        "examples": ["Paris", "Tokyo"],
                    },
                },
            }
        )
        result = normalize_tool_schemas([tool], "gemini")
        schema = result[0]["function"]["parameters"]
        assert "$schema" not in schema
        assert "$id" not in schema
        assert "$defs" not in schema
        # Nested keys inside properties should also be stripped
        city_prop = schema["properties"]["city"]
        assert "default" not in city_prop
        assert "examples" not in city_prop

    def test_xai_strips_range_keywords(self):
        """xAI/Grok provider must strip minLength, maxLength, minimum, maximum, multipleOf."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "multipleOf": 5,
                    },
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 50,
                    },
                },
            }
        )
        result = normalize_tool_schemas([tool], "xai")
        props = result[0]["function"]["parameters"]["properties"]
        count_prop = props["count"]
        assert "minimum" not in count_prop
        assert "maximum" not in count_prop
        assert "multipleOf" not in count_prop
        name_prop = props["name"]
        assert "minLength" not in name_prop
        assert "maxLength" not in name_prop

    def test_openai_adds_additional_properties(self):
        """OpenAI provider must add additionalProperties: false when missing."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            }
        )
        result = normalize_tool_schemas([tool], "openai")
        schema = result[0]["function"]["parameters"]
        assert schema["additionalProperties"] is False

    def test_openai_preserves_existing_additional_properties(self):
        """OpenAI must NOT overwrite an existing additionalProperties value."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "additionalProperties": True,
            }
        )
        result = normalize_tool_schemas([tool], "openai")
        schema = result[0]["function"]["parameters"]
        assert schema["additionalProperties"] is True

    def test_unknown_provider_passes_through(self):
        """Unknown providers get no modifications."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "$schema": "http://json-schema.org/draft-07/schema#",
                "default": "hi",
                "minimum": 1,
                "properties": {"x": {"type": "number"}},
            }
        )
        result = normalize_tool_schemas([tool], "anthropic")
        schema = result[0]["function"]["parameters"]
        assert "$schema" in schema
        assert "default" in schema
        assert "minimum" in schema

    def test_empty_tools_returns_empty(self):
        """Empty tool list returns the same empty list, not None."""
        assert normalize_tool_schemas([], "gemini") == []

    def test_does_not_mutate_original(self):
        """normalize_tool_schemas must deep-copy — original dict is untouched."""
        tool = _make_tool(
            parameters={
                "type": "object",
                "$schema": "keep-me",
                "properties": {"x": {"type": "string"}},
            }
        )
        normalize_tool_schemas([tool], "gemini")
        assert tool["function"]["parameters"]["$schema"] == "keep-me"


# ---------------------------------------------------------------------------
# TestToolCallNormalization — normalize_tool_calls
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolCallNormalization:
    def test_trims_whitespace_in_names(self):
        """Leading/trailing whitespace in function names must be stripped."""
        raw = [_make_raw_tool_call(name="  get_weather  ")]
        result = normalize_tool_calls(raw)
        assert len(result) == 1
        assert result[0].name == "get_weather"

    def test_repairs_broken_json_args(self):
        """Truncated JSON arguments should be repaired."""
        raw = [_make_raw_tool_call(arguments='{"location": "London"')]
        result = normalize_tool_calls(raw)
        assert len(result) == 1
        parsed = json.loads(result[0].arguments)
        assert parsed["location"] == "London"

    def test_returns_empty_for_none(self):
        """None input returns an empty list."""
        assert normalize_tool_calls(None) == []

    def test_returns_empty_for_empty_list(self):
        """Empty list input returns an empty list."""
        assert normalize_tool_calls([]) == []

    def test_skips_empty_name(self):
        """Tool calls with blank or empty function names are dropped."""
        raw = [
            _make_raw_tool_call(name=""),
            _make_raw_tool_call(name="   "),
            _make_raw_tool_call(name="valid_tool"),
        ]
        result = normalize_tool_calls(raw)
        assert len(result) == 1
        assert result[0].name == "valid_tool"

    def test_generates_id_when_missing(self):
        """When tc.id is None, a synthetic call_XXXXXXXX id is generated."""
        raw = [_make_raw_tool_call(call_id=None)]
        result = normalize_tool_calls(raw)
        assert len(result) == 1
        assert result[0].id.startswith("call_")
        assert len(result[0].id) == 13  # "call_" + 8 hex chars

    def test_preserves_valid_args(self):
        """Valid JSON arguments are passed through unchanged."""
        args = '{"city": "Tokyo", "units": "metric"}'
        raw = [_make_raw_tool_call(arguments=args)]
        result = normalize_tool_calls(raw)
        assert result[0].arguments == args


# ---------------------------------------------------------------------------
# TestJsonRepair — _attempt_json_repair
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonRepair:
    def test_adds_missing_closing_brace(self):
        """A single missing closing brace is appended."""
        raw = '{"key": "value"'
        repaired = _attempt_json_repair(raw)
        parsed = json.loads(repaired)
        assert parsed == {"key": "value"}

    def test_adds_multiple_missing_braces(self):
        """Multiple missing braces are appended."""
        raw = '{"outer": {"inner": "value"'
        repaired = _attempt_json_repair(raw)
        parsed = json.loads(repaired)
        assert parsed == {"outer": {"inner": "value"}}

    def test_returns_empty_for_garbage(self):
        """Completely invalid input returns '{}'."""
        assert _attempt_json_repair("not json at all [[[") == "{}"

    def test_valid_json_passes_through(self):
        """Already-valid JSON is returned unchanged (after rstrip)."""
        raw = '{"ok": true}'
        assert _attempt_json_repair(raw) == raw

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace before repair does not break the fix."""
        raw = '{"key": "val"   '
        repaired = _attempt_json_repair(raw)
        parsed = json.loads(repaired)
        assert parsed == {"key": "val"}
