"""
SynapseLLMRouter — unified litellm.Router dispatch layer.

Replaces call_gemini_direct() and _call_antigravity().
All LLM calls go through router.acompletion() using provider-prefixed model strings
from synapse.json model_mappings. No hardcoded model strings in this file.

InferenceLoop wraps _do_call() with retry logic driven by classify_llm_error():
context overflow → compact → retry, rate limited → exponential backoff,
auth failed → rotate auth profile, server error → retry once,
model not found → try fallback model.
"""

import ast
import asyncio
import copy
import difflib
import inspect
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

# Ensure workspace root on path for SynapseConfig import
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import litellm as _litellm_module  # noqa: E402
from litellm import (  # noqa: E402
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Router,
    ServiceUnavailableError,
    Timeout,
)
from synapse_config import SynapseConfig  # noqa: E402

from sci_fi_dashboard.claude_cli_provider import (  # noqa: E402
    ClaudeCliClient,
    ClaudeCliResponse,
    is_claude_cli_model,
)
from sci_fi_dashboard.openai_codex_provider import (  # noqa: E402
    OpenAICodexResponse,
    is_openai_codex_model,
)

try:
    from litellm.exceptions import BudgetExceededError
except ImportError:
    # litellm versions before the exception was added — define a placeholder
    # that will never match a real exception, so the except clause is inert.
    class BudgetExceededError(Exception):  # type: ignore[no-redef]
        pass


# gpt-5-mini and other restricted models reject custom temperature/top_p —
# drop unsupported params silently instead of raising UnsupportedParamsError.
_litellm_module.drop_params = True

logger = logging.getLogger(__name__)

# OBS-01: structured child logger — inherits runId from ContextVar via
# RunIdFilter attached by apply_logging_config() in Plan 13-05.
try:
    from sci_fi_dashboard.observability import get_child_logger as _get_child_logger

    _log = _get_child_logger("llm.router")
except ImportError:
    # Circular-import fallback for early-boot edge cases (the
    # observability package is pure stdlib so this branch should
    # never actually trigger in production).
    _log = logger  # type: ignore[assignment]

# Once-per-process set: tracks which role fallbacks have already been logged
# so we emit exactly one INFO line per fallback path per process lifetime.
_ROLE_FALLBACK_LOGGED: set[str] = set()


@dataclass
class LLMResult:
    """Structured result from an LLM call, carrying text + usage metadata."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None = None


# --- Tool-call dataclasses ---


@dataclass
class ToolCall:
    """Normalized tool call — provider-agnostic."""

    id: str
    name: str
    arguments: str  # raw JSON string


@dataclass
class LLMToolResult:
    """Result from an LLM call that may include tool invocations."""

    text: str
    tool_calls: list[ToolCall]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None = None


# --- Tool schema normalization ---


def normalize_tool_schemas(tools: list[dict], provider: str) -> list[dict]:
    """Apply provider-specific schema fixes that litellm doesn't handle.

    Each provider has quirks in what JSON Schema keywords it accepts:
    - Gemini rejects ``$schema``, ``$id``, ``examples``, ``default``, ``$defs``
    - xAI / Grok rejects numeric range keywords (``minLength``, ``maximum``, etc.)
    - OpenAI strict mode requires ``additionalProperties: false`` on object schemas

    Args:
        tools: OpenAI-format tool definitions (``{"type": "function", ...}``).
        provider: Provider prefix string (e.g. ``"gemini"``, ``"xai"``).

    Returns:
        Deep-copied list with provider-specific keys removed/added.
    """
    if not tools:
        return tools
    normalized = []
    for tool in tools:
        t = copy.deepcopy(tool)
        schema = t.get("function", {}).get("parameters", {})
        if "gemini" in provider:
            _strip_keys_recursive(schema, {"$schema", "$id", "examples", "default", "$defs"})
        if "xai" in provider or "grok" in provider:
            _strip_keys_recursive(
                schema,
                {"minLength", "maxLength", "minimum", "maximum", "multipleOf"},
            )
        if "openai" in provider and (
            schema.get("type") == "object" and "additionalProperties" not in schema
        ):
            schema["additionalProperties"] = False
        normalized.append(t)
    return normalized


def _strip_keys_recursive(obj: dict, keys: set) -> None:
    """Remove *keys* from *obj* and all nested dicts/lists, in place."""
    if not isinstance(obj, dict):
        return
    for key in keys:
        obj.pop(key, None)
    for value in obj.values():
        if isinstance(value, dict):
            _strip_keys_recursive(value, keys)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_keys_recursive(item, keys)


# --- Tool call response normalization ---


def normalize_tool_calls(
    raw_tool_calls: list | None,
    tools: list[dict] | None = None,
    text: str | None = None,
) -> list[ToolCall]:
    """Parse litellm tool-call objects into provider-agnostic :class:`ToolCall` list.

    Handles missing IDs, whitespace in function names, malformed JSON in
    arguments, fuzzy tool names, schema-driven argument key coercion, and
    markdown/text tool-call fallbacks for smaller local models.
    """
    calls, _attempted, events = _normalize_tool_calls_with_report(
        raw_tool_calls,
        tools=tools,
        text=text,
    )
    _log_tool_recovery_events(events)
    return calls


def _normalize_tool_calls_with_report(
    raw_tool_calls: list | None,
    tools: list[dict] | None = None,
    text: str | None = None,
) -> tuple[list[ToolCall], bool, list[dict[str, str]]]:
    """Normalize tool calls and report whether malformed tool use was attempted."""

    tool_index = _build_tool_index(tools)
    if not raw_tool_calls:
        raw_tool_calls = []
    calls: list[ToolCall] = []
    attempted = bool(raw_tool_calls)
    events: list[dict[str, str]] = []
    for tc in raw_tool_calls:
        call_id, raw_name, raw_args = _raw_tool_call_parts(tc)
        name = (raw_name or "").strip()
        if not name:
            continue
        if tool_index:
            coerced_name = _coerce_tool_name(name, tool_index, events)
            if coerced_name not in tool_index:
                events.append(
                    {
                        "kind": "unknown_tool_name",
                        "tool_name": name,
                    }
                )
                continue
            name = coerced_name
        args = _coerce_tool_arguments(raw_args, name, tool_index.get(name), events)
        calls.append(
            ToolCall(
                id=call_id or f"call_{uuid4().hex[:8]}",
                name=name,
                arguments=args,
            )
        )

    if not calls and text and tool_index:
        text_calls, text_attempted, text_events = _extract_text_tool_calls(text, tool_index)
        calls.extend(text_calls)
        attempted = attempted or text_attempted
        events.extend(text_events)
    return calls, attempted, events


def _attempt_json_repair(raw: str) -> str:
    """Best-effort fix for truncated JSON from streaming tool calls.

    Strips markdown fences, removes trailing commas, closes missing braces /
    brackets / string quotes, and accepts Python-style dicts as a json5-ish
    fallback. Returns ``"{}"`` when repair fails.
    """
    if not isinstance(raw, str):
        return "{}"
    original = raw.rstrip()
    try:
        json.loads(original)
        return original
    except json.JSONDecodeError:
        pass

    try:
        repaired = _loads_tolerant_json(original)
    except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
        return "{}"
    if isinstance(repaired, dict | list):
        return json.dumps(repaired)
    return "{}"


_FENCED_BLOCK_RE = re.compile(
    r"```(?:json|tool|tools|function|javascript)?\s*(.*?)```", re.I | re.S
)
_FUNCTION_CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\((.*?)\)", re.S)
_ARG_KW_RE = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|-?\d+(?:\.\d+)?|true|false|null)",
    re.I,
)

_TOOL_TOKEN_ALIASES = {
    "run": "exec",
    "execute": "exec",
    "executed": "exec",
    "shell": "bash",
    "terminal": "bash",
}

_ARGUMENT_KEY_ALIASES: dict[str, set[str]] = {
    "command": {"cmd", "shell", "bash", "bash_command", "shell_command", "terminal_command"},
    "path": {"file", "file_path", "filepath", "filename", "target_path"},
    "old_string": {"old", "old_text", "oldtext", "find", "search", "target"},
    "new_string": {"new", "new_text", "newtext", "replace", "replacement"},
    "pattern": {"regex", "query", "search_query"},
    "url": {"link", "uri"},
    "content": {"text", "body"},
    "timeout": {"timeout_s", "seconds", "secs"},
}


def _raw_tool_call_parts(tc: Any) -> tuple[str | None, str | None, Any]:
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        if not isinstance(fn, dict):
            fn = {
                "name": getattr(fn, "name", None),
                "arguments": getattr(fn, "arguments", None),
            }
        return (
            tc.get("id"),
            fn.get("name") or tc.get("name"),
            fn.get("arguments") if "arguments" in fn else tc.get("arguments"),
        )

    fn = getattr(tc, "function", None)
    return (
        getattr(tc, "id", None),
        getattr(fn, "name", None),
        getattr(fn, "arguments", None),
    )


def _build_tool_index(tools: list[dict] | None) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        index[name] = {
            "name": name,
            "parameters": function.get("parameters") or {},
        }
    return index


def _coerce_tool_name(
    name: str,
    tool_index: dict[str, dict],
    events: list[dict[str, str]],
) -> str:
    if not tool_index or name in tool_index:
        return name

    names = list(tool_index)
    normalized = _normalize_identifier(name)
    normalized_map = {_normalize_identifier(candidate): candidate for candidate in names}
    if normalized in normalized_map:
        target = normalized_map[normalized]
        _record_recovery(events, "tool_name_coerced", name, target)
        return target

    token_match = _best_token_tool_match(name, names)
    if token_match:
        _record_recovery(events, "tool_name_coerced", name, token_match)
        return token_match

    close = difflib.get_close_matches(name, names, n=1, cutoff=0.72)
    if close:
        _record_recovery(events, "tool_name_coerced", name, close[0])
        return close[0]

    normalized_close = difflib.get_close_matches(normalized, list(normalized_map), n=1, cutoff=0.72)
    if normalized_close:
        target = normalized_map[normalized_close[0]]
        _record_recovery(events, "tool_name_coerced", name, target)
        return target
    return name


def _best_token_tool_match(name: str, candidates: list[str]) -> str | None:
    query_tokens = _tool_name_tokens(name)
    if not query_tokens:
        return None
    best_name = None
    best_score = 0.0
    for candidate in candidates:
        candidate_tokens = _tool_name_tokens(candidate)
        if not candidate_tokens:
            continue
        score = len(query_tokens & candidate_tokens) / max(len(query_tokens), len(candidate_tokens))
        if score > best_score:
            best_name = candidate
            best_score = score
    return best_name if best_score >= 0.66 else None


def _tool_name_tokens(name: str) -> set[str]:
    parts = re.findall(r"[a-z0-9]+", name.lower())
    return {_TOOL_TOKEN_ALIASES.get(part, part) for part in parts if part}


def _coerce_tool_arguments(
    raw_args: Any,
    tool_name: str,
    tool_meta: dict | None,
    events: list[dict[str, str]],
) -> str:
    schema = (tool_meta or {}).get("parameters") or {}
    parsed = _parse_argument_value(raw_args)
    if not isinstance(parsed, dict):
        mapped = _map_scalar_argument(parsed, schema)
        if mapped is None:
            parsed = {}
        else:
            parsed = mapped
            events.append({"kind": "scalar_argument_mapped", "tool_name": tool_name})

    coerced = _coerce_argument_keys(parsed, schema, tool_name, events)
    return json.dumps(coerced)


def _parse_argument_value(raw_args: Any) -> Any:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict | list):
        return raw_args
    if not isinstance(raw_args, str):
        return raw_args

    stripped = raw_args.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        return _loads_tolerant_json(stripped)
    except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
        return stripped


def _loads_tolerant_json(raw: str) -> Any:
    stripped = _strip_json_markdown_fence(raw).strip()
    candidates = [
        stripped,
        re.sub(r",\s*([}\]])", r"\1", stripped),
    ]
    candidates.append(_close_json_delimiters(candidates[-1]))

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(candidate)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, dict | list | str | int | float | bool) or parsed is None:
            return parsed
    raise json.JSONDecodeError("unable to repair JSON", stripped, 0)


def _strip_json_markdown_fence(raw: str) -> str:
    match = _FENCED_BLOCK_RE.fullmatch(raw.strip())
    return match.group(1).strip() if match else raw


def _close_json_delimiters(raw: str) -> str:
    text = raw.strip()
    if not text:
        return text

    if text[0] == "{" and not text.rstrip().endswith(("}", "]")):
        text += "}"
    elif text[0] == "[" and not text.rstrip().endswith(("}", "]")):
        text += "]"

    text = _close_unclosed_string_before_suffix(text)
    curly = text.count("{") - text.count("}")
    square = text.count("[") - text.count("]")
    if curly > 0:
        text += "}" * curly
    if square > 0:
        text += "]" * square
    return _close_unclosed_string_before_suffix(text)


def _close_unclosed_string_before_suffix(raw: str) -> str:
    text = raw.rstrip()
    suffix = ""
    while text.endswith(("}", "]")):
        suffix = text[-1] + suffix
        text = text[:-1].rstrip()
    if _inside_double_quoted_string(text):
        text += '"'
    return text + suffix


def _inside_double_quoted_string(text: str) -> bool:
    in_quote = False
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
    return in_quote


def _coerce_argument_keys(
    parsed: dict,
    schema: dict,
    tool_name: str,
    events: list[dict[str, str]],
) -> dict:
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict) or not properties:
        return parsed

    coerced: dict = {}
    unknown: dict = {}
    for key, value in parsed.items():
        key_str = str(key)
        if key_str in properties:
            coerced[key_str] = value
            continue
        target = _match_argument_key(key_str, properties)
        if target:
            coerced[target] = value
            events.append(
                {
                    "kind": "argument_key_coerced",
                    "tool_name": tool_name,
                    "from": key_str,
                    "to": target,
                }
            )
        else:
            unknown[key_str] = value

    required = _schema_required(schema)
    missing = [key for key in required if key not in coerced]
    if len(missing) == 1 and len(unknown) == 1:
        old_key, value = next(iter(unknown.items()))
        coerced[missing[0]] = value
        events.append(
            {
                "kind": "argument_key_coerced",
                "tool_name": tool_name,
                "from": old_key,
                "to": missing[0],
            }
        )
        unknown.clear()

    coerced.update(unknown)
    return coerced


def _match_argument_key(key: str, properties: dict) -> str | None:
    if key in properties:
        return key
    normalized = _normalize_identifier(key)
    normalized_map = {_normalize_identifier(prop): prop for prop in properties}
    if normalized in normalized_map:
        return normalized_map[normalized]
    for prop in properties:
        aliases = {_normalize_identifier(alias) for alias in _ARGUMENT_KEY_ALIASES.get(prop, set())}
        if normalized in aliases:
            return prop
    close = difflib.get_close_matches(normalized, list(normalized_map), n=1, cutoff=0.78)
    return normalized_map[close[0]] if close else None


def _map_scalar_argument(value: Any, schema: dict) -> dict | None:
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict) or not properties:
        return None

    required = _schema_required(schema)
    if len(required) == 1:
        prop = required[0]
    elif len(properties) == 1:
        prop = next(iter(properties))
    else:
        return None
    return {prop: _coerce_scalar_to_schema(value, properties.get(prop, {}))}


def _coerce_scalar_to_schema(value: Any, prop_schema: dict) -> Any:
    kind = prop_schema.get("type") if isinstance(prop_schema, dict) else None
    if kind == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)
    return str(value)


def _schema_required(schema: dict) -> list[str]:
    required = schema.get("required") if isinstance(schema, dict) else []
    return [str(item) for item in required] if isinstance(required, list) else []


def _extract_text_tool_calls(
    text: str,
    tool_index: dict[str, dict],
) -> tuple[list[ToolCall], bool, list[dict[str, str]]]:
    events: list[dict[str, str]] = []
    attempted = _looks_like_malformed_tool_attempt(text, tool_index)
    segments = [match.group(1).strip() for match in _FENCED_BLOCK_RE.finditer(text)]
    segments.append(text)

    for segment in segments:
        for candidate in _json_candidates_from_text(segment):
            try:
                payload = _loads_tolerant_json(candidate)
            except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                continue
            calls = _tool_calls_from_payload(payload, tool_index, events)
            if calls:
                events.append({"kind": "text_tool_call_parsed"})
                return calls, True, events

    function_calls = _function_like_tool_calls(text, tool_index, events)
    if function_calls:
        events.append({"kind": "text_tool_call_parsed"})
        return function_calls, True, events
    return [], attempted, events


def _json_candidates_from_text(text: str) -> list[str]:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped.startswith(("{", "[")):
        candidates.append(stripped)

    stack: list[str] = []
    start: int | None = None
    in_quote = False
    escaped = False
    pairs = {"{": "}", "[": "]"}
    for idx, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if char in pairs:
            if not stack:
                start = idx
            stack.append(pairs[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            if not stack and start is not None:
                candidates.append(text[start : idx + 1])
                start = None
    return candidates


def _tool_calls_from_payload(
    payload: Any,
    tool_index: dict[str, dict],
    events: list[dict[str, str]],
) -> list[ToolCall]:
    if isinstance(payload, list):
        calls: list[ToolCall] = []
        for item in payload:
            calls.extend(_tool_calls_from_payload(item, tool_index, events))
        return calls
    if not isinstance(payload, dict):
        return []

    if isinstance(payload.get("tool_calls"), list):
        return _tool_calls_from_payload(payload["tool_calls"], tool_index, events)

    function = payload.get("function")
    if isinstance(function, dict) and function.get("name"):
        call = _build_recovered_tool_call(
            str(function.get("name")),
            function.get("arguments", payload.get("arguments", {})),
            tool_index,
            events,
        )
        return [call] if call else []

    for name_key in ("tool", "tool_name", "name"):
        if payload.get(name_key):
            args = (
                payload.get("arguments")
                if "arguments" in payload
                else payload.get("args", payload.get("parameters", payload.get("input", {})))
            )
            call = _build_recovered_tool_call(str(payload[name_key]), args, tool_index, events)
            return [call] if call else []

    calls: list[ToolCall] = []
    for key, value in payload.items():
        name = _coerce_tool_name(str(key), tool_index, events)
        if name in tool_index:
            call = _build_recovered_tool_call(name, value, tool_index, events)
            if call:
                calls.append(call)
    return calls


def _function_like_tool_calls(
    text: str,
    tool_index: dict[str, dict],
    events: list[dict[str, str]],
) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _FUNCTION_CALL_RE.finditer(text):
        name = _coerce_tool_name(match.group(1), tool_index, events)
        if name not in tool_index:
            continue
        args = _parse_function_like_args(match.group(2), name, tool_index[name], events)
        call = _build_recovered_tool_call(name, args, tool_index, events)
        if call:
            calls.append(call)
    return calls


def _parse_function_like_args(
    raw: str,
    tool_name: str,
    tool_meta: dict,
    events: list[dict[str, str]],
) -> Any:
    body = raw.strip()
    if not body:
        return {}
    if body.startswith(("{", "[")):
        return _parse_argument_value(body)
    try:
        literal = ast.literal_eval(body)
        return literal
    except (ValueError, SyntaxError):
        pass

    kwargs = {}
    for key, value in _ARG_KW_RE.findall(body):
        kwargs[key] = _parse_argument_value(value)
    if kwargs:
        events.append({"kind": "function_kwargs_parsed", "tool_name": tool_name})
        return kwargs
    return body


def _build_recovered_tool_call(
    name: str,
    args: Any,
    tool_index: dict[str, dict],
    events: list[dict[str, str]],
) -> ToolCall | None:
    coerced_name = _coerce_tool_name(name, tool_index, events)
    if coerced_name not in tool_index:
        return None
    return ToolCall(
        id=f"call_{uuid4().hex[:8]}",
        name=coerced_name,
        arguments=_coerce_tool_arguments(args, coerced_name, tool_index[coerced_name], events),
    )


def _looks_like_malformed_tool_attempt(text: str, tool_index: dict[str, dict]) -> bool:
    if not text or not tool_index:
        return False
    lowered = text.lower()
    toolish = (
        "```" in text or "{" in text or "(" in text or "tool" in lowered or "arguments" in lowered
    )
    if not toolish:
        return False
    for name in tool_index:
        if name.lower() in lowered:
            return True
        if _tool_name_tokens(name) & set(re.findall(r"[a-z0-9]+", lowered)):
            return True
    return False


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _record_recovery(
    events: list[dict[str, str]],
    kind: str,
    old: str,
    new: str,
) -> None:
    if old != new:
        events.append({"kind": kind, "from": old, "to": new})


def _log_tool_recovery_events(events: list[dict[str, str]]) -> None:
    for event in events:
        kind = event.get("kind", "unknown")
        logger.info("tool_call_resilience_%s", kind, extra={"tool_recovery": event})


def _build_tool_retry_instruction(tools: list[dict]) -> str:
    lines = [
        "Your previous response attempted a tool call but the format was malformed.",
        "Do not describe or simulate tool results. Use the native tool_call format.",
        "Available tool schemas:",
    ]
    for tool in tools:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = function.get("name")
        params = function.get("parameters", {})
        props = params.get("properties", {}) if isinstance(params, dict) else {}
        required = set(params.get("required", [])) if isinstance(params, dict) else set()
        arg_bits = []
        for prop, prop_schema in props.items():
            type_name = prop_schema.get("type", "any") if isinstance(prop_schema, dict) else "any"
            suffix = " required" if prop in required else " optional"
            arg_bits.append(f"{prop}: {type_name}{suffix}")
        if name:
            lines.append(f"- {name}({', '.join(arg_bits)})")
    return "\n".join(lines)


# --- Provider key injection ---

# Maps synapse.json provider name → litellm-expected env var name.
# Bedrock handled separately (uses AWS_* env vars, not a single api_key).
# Vertex AI handled separately (uses GCP project_id + location + SA JSON path,
# not a single api_key).
_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "togetherai": "TOGETHERAI_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "zai": "ZAI_API_KEY",  # Zhipu Z.AI — prefix is zai/, NOT zhipu/
    "volcengine": "VOLCENGINE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_BEDROCK_MAP: dict[str, str] = {
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "aws_region_name": "AWS_REGION_NAME",
}

_VERTEX_MAP: dict[str, str] = {
    "project_id": "VERTEXAI_PROJECT",
    "location": "VERTEXAI_LOCATION",
    "credentials_path": "GOOGLE_APPLICATION_CREDENTIALS",
}


def _inject_provider_keys(providers: dict) -> None:
    """
    Inject provider API keys from synapse.json into os.environ for litellm.
    litellm reads credentials from os.environ at call time (per-call lookup).
    Must be called before the first acompletion() call.
    """
    for provider_name, env_var in _KEY_MAP.items():
        prov_cfg = providers.get(provider_name, {})
        if isinstance(prov_cfg, dict):
            api_key = prov_cfg.get("api_key")
        elif isinstance(prov_cfg, str):
            api_key = prov_cfg
        else:
            api_key = None
        if api_key and env_var not in os.environ:
            # Only inject if not already set (env var takes precedence)
            os.environ[env_var] = api_key

    # Bedrock: multiple AWS credentials, no single api_key field
    bedrock_cfg = providers.get("bedrock", {})
    if isinstance(bedrock_cfg, dict):
        for aws_key, env_key in _BEDROCK_MAP.items():
            val = bedrock_cfg.get(aws_key)
            if val and env_key not in os.environ:
                os.environ[env_key] = val

    # Vertex AI: GCP project_id + location + service-account-JSON path
    # (no single api_key — auth is via GOOGLE_APPLICATION_CREDENTIALS / ADC).
    vertex_cfg = providers.get("vertex_ai", {})
    if isinstance(vertex_cfg, dict):
        for vertex_key, env_key in _VERTEX_MAP.items():
            val = vertex_cfg.get(vertex_key)
            if val and env_key not in os.environ:
                os.environ[env_key] = val


# Ollama chat prefix sentinel — centralised so no bare provider strings appear at call sites
_OLLAMA_CHAT_PREFIX = "ollama_chat/"  # allowed: constant-definition

# Ollama runtime defaults. num_ctx is critical: Ollama defaults to 2048 tokens
# regardless of the model's native window, which silently truncates large system
# prompts (Synapse's identity prompt is ~7k tokens) and drops the trailing user
# message. Override per-role via model_mappings.<role>.ollama_options.num_ctx.
_OLLAMA_DEFAULT_OPTS = {
    # 8192 is a safe default for 6-8 GB VRAM hardware. Note: Synapse's full
    # identity prompt is ~19k tokens — at 8k context the trailing user message
    # gets truncated. Two paths:
    #   1) Bump num_ctx via model_mappings.<role>.ollama_options.num_ctx
    #      (32768 fits comfortably on 8 GB VRAM with 7B-class models)
    #   2) Wait for W2 minimal-mode prompt builder (see MODEL-AGNOSTIC-ROADMAP.md)
    # The startup-time prompt-size warning logs when a call's prompt exceeds
    # the configured num_ctx — surfaces the issue without OOM-ing low-VRAM users.
    "num_ctx": 8192,
    "temperature": 0.7,
    "repeat_penalty": 1.15,
}


def _build_ollama_options(cfg: dict) -> dict:
    """Merge per-role ollama_options on top of defaults so num_ctx is always set."""
    return {**_OLLAMA_DEFAULT_OPTS, **(cfg.get("ollama_options") or {})}


# --- Router builder ---


def _get_copilot_token() -> str:
    """Get a valid GitHub Copilot API token, refreshing automatically if expired."""
    from litellm.llms.github_copilot.authenticator import Authenticator  # noqa: PLC0415

    try:
        return Authenticator().get_api_key()
    except Exception as exc:
        logger.warning("GitHub Copilot token refresh failed: %s", exc)
        return "missing"


def _copilot_litellm_params(model_suffix: str) -> dict:
    """Build litellm_params for a github_copilot/ model via the openai/ shim.

    litellm's Router doesn't apply Copilot auth headers automatically, so we
    rewrite github_copilot/gpt-4o → openai/gpt-4o with the Copilot API base
    and required headers injected directly.
    """
    from litellm.llms.github_copilot.common_utils import (  # noqa: PLC0415
        GITHUB_COPILOT_API_BASE,
        get_copilot_default_headers,
    )

    api_key = _get_copilot_token()

    return {
        "model": f"openai/{model_suffix}",
        "api_key": api_key,
        "api_base": GITHUB_COPILOT_API_BASE,
        "extra_headers": get_copilot_default_headers(api_key),
        "timeout": 60,
        "stream": False,
    }


_GITHUB_COPILOT_PREFIX = "github_copilot/"
_GOOGLE_ANTIGRAVITY_PREFIX = "google_antigravity/"
_CLAUDE_CLI_PROVIDER_KEYS = ("claude_cli", "claude-cli", "claude_max")


def _is_direct_provider_model(model: str | None) -> bool:
    """Models Synapse dispatches itself instead of registering with litellm."""
    model = model or ""
    return (
        model.startswith(_GOOGLE_ANTIGRAVITY_PREFIX)
        or is_claude_cli_model(model)
        or is_openai_codex_model(model)
    )


def build_router(model_mappings: dict, providers: dict) -> Router:
    """
    Build a litellm.Router from synapse.json model_mappings.

    model_mappings structure:
      {"casual": {"model": "gemini/gemini-2.0-flash", "fallback": "groq/llama-3.3-70b-versatile"}, ...}

    Ollama models MUST use ollama_chat/ prefix (not ollama/).
    api_base for Ollama is read from providers.ollama.api_base (default: http://localhost:11434).
    """
    ollama_api_base = (providers.get("ollama") or {}).get("api_base", "http://localhost:11434")
    qianfan_api_base = (providers.get("qianfan") or {}).get(
        "api_base", "https://qianfan.baidubce.com/v2"
    )
    vllm_api_base = (providers.get("vllm") or {}).get("api_base", "http://localhost:8000")

    model_list: list[dict] = []
    fallbacks: list[dict] = []

    for role, cfg in model_mappings.items():
        primary_model: str = cfg["model"]

        # Google Antigravity is dispatched directly by SynapseLLMRouter, not by
        # litellm.Router — skip registering it here. The router handles primary
        # antigravity via _invoke_antigravity(). If a fallback is also
        # antigravity it's likewise handled outside; if the fallback is a
        # litellm-supported provider, register it as <role>_fallback so the
        # standard fallback machinery still works.
        if _is_direct_provider_model(primary_model):
            fallback_model = cfg.get("fallback")
            if fallback_model and not _is_direct_provider_model(fallback_model):
                fallback_role = f"{role}_fallback"
                if fallback_model.startswith(_GITHUB_COPILOT_PREFIX):
                    fallback_params = _copilot_litellm_params(
                        fallback_model[len(_GITHUB_COPILOT_PREFIX) :]
                    )
                else:
                    fallback_params = {"model": fallback_model, "timeout": 60, "stream": False}
                    if fallback_model.startswith(_OLLAMA_CHAT_PREFIX):
                        fallback_params["api_base"] = ollama_api_base
                        fallback_params["extra_body"] = {"options": _build_ollama_options(cfg)}
                model_list.append({"model_name": fallback_role, "litellm_params": fallback_params})
                fallbacks.append({role: [fallback_role]})
            continue

        if primary_model.startswith(_GITHUB_COPILOT_PREFIX):
            litellm_params = _copilot_litellm_params(primary_model[len(_GITHUB_COPILOT_PREFIX) :])
        elif primary_model.startswith(_OLLAMA_CHAT_PREFIX):
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = ollama_api_base
            litellm_params["extra_body"] = {"options": _build_ollama_options(cfg)}
        elif primary_model.startswith("ollama/"):
            raise ValueError(
                f"Role '{role}' uses ollama/ prefix — must be {_OLLAMA_CHAT_PREFIX} for chat calls. "
                f"Got: {primary_model}"
            )
        elif primary_model.startswith("hosted_vllm/"):
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = vllm_api_base
        elif primary_model.startswith("openai/") and providers.get("qianfan") and role == "qianfan":
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = qianfan_api_base
        else:
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}

        model_list.append({"model_name": role, "litellm_params": litellm_params})

        # Fallback model (optional)
        fallback_model = cfg.get("fallback")
        if fallback_model:
            if _is_direct_provider_model(fallback_model):
                logger.warning(
                    "Direct-provider fallback for role '%s' is not registered with litellm: %s",
                    role,
                    fallback_model,
                )
                continue
            fallback_role = f"{role}_fallback"
            if fallback_model.startswith(_GITHUB_COPILOT_PREFIX):
                fallback_params = _copilot_litellm_params(
                    fallback_model[len(_GITHUB_COPILOT_PREFIX) :]
                )
            else:
                fallback_params = {"model": fallback_model, "timeout": 60, "stream": False}
                if fallback_model.startswith(_OLLAMA_CHAT_PREFIX):
                    fallback_params["api_base"] = ollama_api_base
                    fallback_params["extra_body"] = {"options": _build_ollama_options(cfg)}
            model_list.append({"model_name": fallback_role, "litellm_params": fallback_params})
            fallbacks.append({role: [fallback_role]})

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=0,
        retry_after=0,
    )


# --- Session tracking ---


def _write_session(role: str, model: str, usage) -> None:
    """
    Write one row to the sessions table in memory.db.
    Non-fatal: caller must wrap in try/except.

    Args:
        role:  The router role name (e.g., 'casual', 'vault').
        model: The actual model string returned by the provider.
        usage: litellm.Usage object or None.
    """
    from sci_fi_dashboard.db import DB_PATH  # noqa: PLC0415

    input_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens: int = getattr(usage, "completion_tokens", 0) or 0
    total_tokens: int = getattr(usage, "total_tokens", 0) or 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, role, model, input_tokens, output_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), role, model, input_tokens, output_tokens, total_tokens),
        )
        conn.commit()


def get_provider_spend(provider: str, duration: str = "monthly") -> dict:
    """
    Return cumulative token counts for a provider within a time window.

    Args:
        provider: Provider name (e.g., "openai", "deepseek").
        duration: "daily", "weekly", or "monthly".

    Returns:
        {"total_tokens": int, "call_count": int}
    """
    from sci_fi_dashboard.db import DB_PATH  # noqa: PLC0415

    duration_map = {
        "daily": "-1 day",
        "weekly": "-7 days",
        "monthly": "-30 days",
    }
    interval = duration_map.get(duration, "-30 days")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(total_tokens), 0) as total_tokens,
                       COUNT(*) as call_count
                FROM sessions
                WHERE model LIKE ? || '%'
                  AND created_at > datetime('now', ?)
                """,
                (f"{provider}/", interval),
            ).fetchone()
            return {"total_tokens": row[0], "call_count": row[1]}
    except Exception as exc:
        logger.debug("get_provider_spend failed (non-fatal): %s", exc)
        return {"total_tokens": 0, "call_count": 0}


# --- Environment variable resolution ---

_ENV_VAR_RE = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")


def resolve_env_var(value: str) -> str:
    """Resolve ${ENV_VAR} syntax to the actual environment variable value.

    If value matches the pattern ${SOME_VAR}, look up SOME_VAR in os.environ.
    If the env var is not set, return the original string unchanged.

    Args:
        value: A string that may contain ${ENV_VAR} syntax.

    Returns:
        The resolved value, or the original string if no match or env var not set.
    """
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


# --- LLM Error Classification ---


class AuthProfileFailureReason(StrEnum):
    """Classifies LLM API failures for key-rotation decision-making.

    Retryable failures (RATE_LIMIT, OVERLOADED, TIMEOUT) trigger rotation
    to the next API key. Non-retryable failures (AUTH_PERMANENT, FORMAT,
    BILLING, MODEL_NOT_FOUND) are raised immediately.
    """

    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    FORMAT = "format"
    OVERLOADED = "overloaded"
    RATE_LIMIT = "rate_limit"
    BILLING = "billing"
    TIMEOUT = "timeout"
    MODEL_NOT_FOUND = "model_not_found"
    UNKNOWN = "unknown"


# Retryable failure reasons — rotation to the next key is worthwhile
_RETRYABLE_REASONS = frozenset(
    {
        AuthProfileFailureReason.RATE_LIMIT,
        AuthProfileFailureReason.OVERLOADED,
        AuthProfileFailureReason.TIMEOUT,
    }
)


def classify_llm_error(error: Exception) -> AuthProfileFailureReason:
    """Map a litellm exception to an AuthProfileFailureReason.

    Args:
        error: The exception raised by litellm.

    Returns:
        The classified failure reason.
    """
    if isinstance(error, RateLimitError):
        return AuthProfileFailureReason.RATE_LIMIT
    if isinstance(error, AuthenticationError):
        return AuthProfileFailureReason.AUTH
    if isinstance(error, BadRequestError):
        return AuthProfileFailureReason.FORMAT
    if isinstance(error, Timeout):
        return AuthProfileFailureReason.TIMEOUT
    if isinstance(error, ServiceUnavailableError):
        return AuthProfileFailureReason.OVERLOADED
    if isinstance(error, APIConnectionError):
        return AuthProfileFailureReason.TIMEOUT
    return AuthProfileFailureReason.UNKNOWN


# --- API Key Rotation ---


async def execute_with_api_key_rotation(
    provider: str,
    api_keys: list[str],
    execute_fn,  # Callable[[str], Awaitable[T]]
    should_retry_fn=None,  # Callable[[Exception, int], bool] | None
):
    """Try each API key in order; on retryable failure, advance to the next key.

    Deduplicates keys (preserving order), strips empty/None entries. For each key,
    calls execute_fn(key). On failure, classifies the error: if retryable
    (RATE_LIMIT, OVERLOADED, TIMEOUT) and more keys are available, moves to the
    next key. Otherwise re-raises.

    Args:
        provider: Provider name (for logging and error messages).
        api_keys: List of API keys to try in order.
        execute_fn: Async callable that takes an API key string and returns a result.
        should_retry_fn: Optional override for retry logic. Takes (exception, key_index)
            and returns True if the next key should be tried. Defaults to checking
            whether the classified error is in _RETRYABLE_REASONS.

    Returns:
        The result from the first successful execute_fn call.

    Raises:
        ValueError: If no valid API keys are provided after deduplication.
        Exception: The last exception encountered if all keys are exhausted.
    """
    # Dedupe keys, remove empty/None, preserve order
    seen: set[str] = set()
    unique_keys: list[str] = []
    for k in api_keys:
        if k and isinstance(k, str) and k.strip() and k not in seen:
            seen.add(k)
            unique_keys.append(k)

    if not unique_keys:
        raise ValueError(f"No API keys configured for {provider}")

    last_error: Exception | None = None

    for idx, key in enumerate(unique_keys):
        try:
            return await execute_fn(key)
        except Exception as exc:
            last_error = exc
            reason = classify_llm_error(exc)
            is_last_key = idx >= len(unique_keys) - 1

            # Check if we should retry with the next key
            if should_retry_fn is not None:
                should_retry = should_retry_fn(exc, idx)
            else:
                should_retry = reason in _RETRYABLE_REASONS

            if should_retry and not is_last_key:
                logger.warning(
                    "Key %d/%d for %s failed (%s: %s) — rotating to next key",
                    idx + 1,
                    len(unique_keys),
                    provider,
                    reason.value,
                    exc,
                )
                continue

            # Non-retryable or last key — raise immediately
            logger.error(
                "Key %d/%d for %s failed (%s: %s) — no more keys to try",
                idx + 1,
                len(unique_keys),
                provider,
                reason.value,
                exc,
            )
            raise

    # Should not reach here, but satisfy type checker
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No API keys available for {provider}")  # pragma: no cover


# --- Helpers ---


def _provider_from_model(model_string: str) -> str | None:
    """Extract the provider prefix from a litellm model string.

    e.g. "gemini/gemini-2.0-flash" -> "gemini",
         "ollama_chat/mistral" -> "ollama"
    Returns None if no prefix found.
    """
    if "/" in model_string:
        prefix = model_string.split("/", 1)[0]
        return "ollama" if prefix == "ollama_chat" else prefix
    return None


# --- SynapseLLMRouter ---


def _build_antigravity_response_shim(antigravity_response):
    """Wrap an :class:`AntigravityResponse` in litellm's response shape.

    Downstream code (``_do_call``, ``call``, ``call_with_metadata``,
    ``call_with_tools``) reads ``response.choices[0].message.content``,
    ``response.usage.prompt_tokens``, etc. Producing the same shape lets the
    Google Antigravity path share the rest of the pipeline.
    """
    from types import SimpleNamespace

    tool_calls = [
        SimpleNamespace(
            id=tc.get("id", ""),
            type="function",
            function=SimpleNamespace(
                name=tc.get("name", ""),
                arguments=tc.get("arguments", "{}"),
            ),
        )
        for tc in antigravity_response.tool_calls
    ]
    message = SimpleNamespace(
        content=antigravity_response.text or "",
        tool_calls=tool_calls or None,
        role="assistant",
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason=antigravity_response.finish_reason or "stop",
        index=0,
    )
    usage = SimpleNamespace(
        prompt_tokens=antigravity_response.prompt_tokens,
        completion_tokens=antigravity_response.completion_tokens,
        total_tokens=antigravity_response.total_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        model=antigravity_response.model,
        usage=usage,
    )


def _build_claude_cli_response_shim(claude_response: ClaudeCliResponse):
    """Wrap Claude Code CLI output in litellm's response shape."""
    from types import SimpleNamespace

    message = SimpleNamespace(
        content=claude_response.text or "",
        tool_calls=None,
        role="assistant",
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason=claude_response.finish_reason or "stop",
        index=0,
    )
    usage = SimpleNamespace(
        prompt_tokens=claude_response.prompt_tokens,
        completion_tokens=claude_response.completion_tokens,
        total_tokens=claude_response.total_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        model=claude_response.model,
        usage=usage,
    )


def _build_openai_codex_response_shim(codex_response: OpenAICodexResponse):
    """Wrap OpenAI Codex output in litellm's response shape."""
    from types import SimpleNamespace

    tool_calls = [
        SimpleNamespace(
            id=tc.get("id", ""),
            type="function",
            function=SimpleNamespace(
                name=tc.get("name", ""),
                arguments=tc.get("arguments", "{}"),
            ),
        )
        for tc in codex_response.tool_calls
    ]
    message = SimpleNamespace(
        content=codex_response.text or "",
        tool_calls=tool_calls or None,
        role="assistant",
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason=codex_response.finish_reason or "stop",
        index=0,
    )
    usage = SimpleNamespace(
        prompt_tokens=codex_response.prompt_tokens,
        completion_tokens=codex_response.completion_tokens,
        total_tokens=codex_response.total_tokens,
    )
    raw_model = str(codex_response.model or "").strip()
    if raw_model.startswith(("openai_codex/", "openai-codex/", "codex/")):
        canonical_model = raw_model
    else:
        canonical_model = f"openai_codex/{raw_model or 'unknown'}"

    return SimpleNamespace(
        choices=[choice],
        model=canonical_model,
        usage=usage,
    )


def _supported_call_kwargs(fn: Callable[..., Any]) -> tuple[set[str], bool]:
    """Return (named kwargs, accepts **kwargs) for *fn*."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return set(), True
    named = {
        name
        for name, param in sig.parameters.items()
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    accepts_var_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
    )
    return named, accepts_var_kwargs


class SynapseLLMRouter:
    """
    Unified litellm.Router wrapper. One instance per FastAPI lifespan.
    Thread-safe: litellm.Router is async-safe for concurrent calls.

    Usage:
        router = SynapseLLMRouter()
        text = await router.call("casual", messages)
        text = await router.call("vault", messages)
    """

    def __init__(self, config: SynapseConfig | None = None) -> None:
        self._config = config or SynapseConfig.load()
        _inject_provider_keys(self._config.providers)
        self._router = build_router(self._config.model_mappings, self._config.providers)
        self._uses_copilot = any(
            v.get("model", "").startswith(_GITHUB_COPILOT_PREFIX)
            for v in self._config.model_mappings.values()
        )
        # Roles whose primary model goes through the Google Antigravity client
        # rather than litellm.Router.
        self._antigravity_roles: set[str] = {
            role
            for role, cfg in self._config.model_mappings.items()
            if cfg.get("model", "").startswith(_GOOGLE_ANTIGRAVITY_PREFIX)
        }
        self._claude_cli_roles: set[str] = {
            role
            for role, cfg in self._config.model_mappings.items()
            if is_claude_cli_model(cfg.get("model", ""))
        }
        self._openai_codex_roles: set[str] = {
            role
            for role, cfg in self._config.model_mappings.items()
            if is_openai_codex_model(cfg.get("model", ""))
        }
        # C-09: Lock to prevent concurrent Copilot token refresh races
        self._copilot_refresh_lock = asyncio.Lock()
        logger.info(
            "SynapseLLMRouter initialized with %d roles (antigravity: %d, claude_cli: %d, openai_codex: %d)",
            len(self._config.model_mappings),
            len(self._antigravity_roles),
            len(self._claude_cli_roles),
            len(self._openai_codex_roles),
        )

    async def _invoke_antigravity(
        self,
        *,
        role: str,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        max_tokens: int,
    ):
        """Dispatch a chat completion through the Google Antigravity client.

        Returns a litellm-shaped response shim so the rest of the pipeline can
        reuse the same field accesses (``choices[0].message.content`` etc).
        """
        from sci_fi_dashboard.antigravity_provider import (  # noqa: PLC0415
            get_default_client,
        )

        model_str = self._model_string_for_role(role) or ""
        client = await get_default_client()
        ag_response = await client.chat_completion(
            messages=messages,
            model=model_str,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            _write_session(
                role=role,
                model=ag_response.model,
                usage=type(
                    "U",
                    (),
                    {
                        "prompt_tokens": ag_response.prompt_tokens,
                        "completion_tokens": ag_response.completion_tokens,
                        "total_tokens": ag_response.total_tokens,
                    },
                )(),
            )
        except Exception as session_exc:  # noqa: BLE001
            logger.debug("Session write failed (non-fatal): %s", session_exc)
        return _build_antigravity_response_shim(ag_response)

    def _claude_cli_provider_cfg(self) -> dict:
        """Return provider config for Claude CLI, accepting legacy keys."""
        for key in _CLAUDE_CLI_PROVIDER_KEYS:
            cfg = self._config.providers.get(key)
            if isinstance(cfg, dict):
                return cfg
        return {}

    async def _invoke_claude_cli(
        self,
        *,
        role: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ):
        """Dispatch a chat completion through Claude Code CLI subscription auth."""
        cfg = self._claude_cli_provider_cfg()
        model_str = self._model_string_for_role(role) or "claude_cli/sonnet"
        client = ClaudeCliClient(
            command=str(cfg.get("binary_path") or cfg.get("command") or "claude"),
            timeout=float(cfg.get("timeout") or cfg.get("timeout_sec") or 180.0),
            cwd=cfg.get("cwd"),
            extra_args=list(cfg.get("extra_args") or []),
            setting_sources=str(cfg.get("setting_sources") or "user"),
            disable_tools=bool(cfg.get("disable_tools", True)),
            disable_slash_commands=bool(cfg.get("disable_slash_commands", True)),
        )
        cli_response = await client.chat_completion(
            messages=messages,
            model=model_str,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            _write_session(
                role=role,
                model=cli_response.model,
                usage=type(
                    "U",
                    (),
                    {
                        "prompt_tokens": cli_response.prompt_tokens,
                        "completion_tokens": cli_response.completion_tokens,
                        "total_tokens": cli_response.total_tokens,
                    },
                )(),
            )
        except Exception as session_exc:  # noqa: BLE001
            logger.debug("Session write failed (non-fatal): %s", session_exc)
        return _build_claude_cli_response_shim(cli_response)

    async def _invoke_openai_codex(
        self,
        *,
        role: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        **kwargs: Any,
    ):
        """Dispatch a chat completion through the OpenAI Codex client."""
        from sci_fi_dashboard.openai_codex_provider import (  # noqa: PLC0415
            get_default_client,
        )

        model_str = self._model_string_for_role(role) or "openai_codex/gpt-5-codex"
        client = await get_default_client()
        named_kwargs, accepts_var_kwargs = _supported_call_kwargs(client.chat_completion)

        def _can_forward(name: str) -> bool:
            return accepts_var_kwargs or name in named_kwargs

        request_kwargs: dict[str, Any] = {
            "messages": messages,
            "model": model_str,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools is not None:
            request_kwargs["tools"] = tools

        tool_choice = kwargs.pop("tool_choice", None)
        if tool_choice is not None:
            if tool_choice != "auto":
                raise BadRequestError(
                    message=(
                        "OpenAI Codex path only supports tool_choice='auto'. "
                        f"Got: {tool_choice!r}"
                    ),
                    llm_provider="openai_codex",
                    model=model_str,
                )
            if _can_forward("tool_choice"):
                request_kwargs["tool_choice"] = tool_choice

        unsupported_kwargs = [
            key for key, value in kwargs.items() if value is not None and not _can_forward(key)
        ]
        if unsupported_kwargs:
            raise BadRequestError(
                message=(
                    "Unsupported OpenAI Codex kwargs: "
                    + ", ".join(sorted(set(unsupported_kwargs)))
                ),
                llm_provider="openai_codex",
                model=model_str,
            )

        for key, value in kwargs.items():
            if value is not None and _can_forward(key):
                request_kwargs[key] = value

        codex_response = await client.chat_completion(**request_kwargs)
        try:
            _write_session(
                role=role,
                model=codex_response.model,
                usage=type(
                    "U",
                    (),
                    {
                        "prompt_tokens": codex_response.prompt_tokens,
                        "completion_tokens": codex_response.completion_tokens,
                        "total_tokens": codex_response.total_tokens,
                    },
                )(),
            )
        except Exception as session_exc:  # noqa: BLE001
            logger.debug("Session write failed (non-fatal): %s", session_exc)
        return _build_openai_codex_response_shim(codex_response)

    def _rebuild_router(self) -> None:
        """Rebuild the litellm Router (e.g. after a Copilot token refresh)."""
        self._router = build_router(self._config.model_mappings, self._config.providers)
        logger.info("Router rebuilt with fresh credentials")

    def _model_string_for_role(self, role: str) -> str | None:
        """Return the provider-prefixed model string for a role, or None."""
        cfg = self._config.model_mappings.get(role)
        return cfg.get("model") if cfg else None

    def _apply_profile_credentials(self, profile, role: str) -> None:
        """Inject credentials from an AuthProfile into os.environ.

        litellm reads API keys from os.environ at call time, so overwriting
        the env var before the acompletion() call rotates the active key.
        """
        model_str = self._model_string_for_role(role)
        if not model_str:
            return
        provider = _provider_from_model(model_str)
        if not provider:
            return
        api_key = profile.credentials.get("api_key") or profile.credentials.get("access_token")
        if not api_key:
            return
        env_var = _KEY_MAP.get(provider)
        if env_var:
            os.environ[env_var] = api_key
            logger.debug("Applied credentials from profile %s to %s", profile.id, env_var)

    async def _do_call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ):
        """
        Internal: route to the litellm model for the given role and return the raw
        litellm response object. Handles error classification and session tracking.
        Extra **kwargs (e.g. response_format) are forwarded to litellm acompletion.
        """
        # --- Pre-call budget enforcement (PROV-02) ---
        role_cfg = self._config.model_mappings.get(role, {})
        model_str = role_cfg.get("model", "")
        provider_prefix = model_str.split("/")[0] if "/" in model_str else ""
        if provider_prefix:
            provider_cfg = self._config.providers.get(provider_prefix, {})
            if isinstance(provider_cfg, dict):
                budget_usd = provider_cfg.get("budget_usd")
                budget_duration = provider_cfg.get("budget_duration", "monthly")
                if budget_usd is not None:
                    spend = get_provider_spend(provider_prefix, budget_duration)
                    # Approximate cost: use token count as proxy.
                    # 1M tokens ~ $1 is a rough average across providers.
                    # This is a safety net, not a billing system.
                    approx_spend = spend["total_tokens"] / 1_000_000
                    if approx_spend >= budget_usd:
                        raise BudgetExceededError(
                            approx_spend,
                            budget_usd,
                            f"Provider '{provider_prefix}' budget exceeded: "
                            f"~${approx_spend:.2f} spent vs ${budget_usd:.2f} cap "
                            f"({budget_duration})",
                        )
        try:
            _prompt_chars = sum(len(m.get("content") or "") for m in messages)
            _est_tokens = _prompt_chars // 4
            logger.info(
                "llm.call role=%s msgs=%d total_chars=%d est_tokens=%d",
                role,
                len(messages),
                _prompt_chars,
                _est_tokens,
            )
            # OSS guardrail: warn if local engine prompt exceeds the configured
            # num_ctx. Ollama silently truncates oversized prompts, dropping the
            # trailing user message — bot replies with generic boilerplate.
            _model_str = self._model_string_for_role(role) or ""
            if _model_str.startswith(_OLLAMA_CHAT_PREFIX):
                _cfg = self._config.model_mappings.get(role) or {}
                _opts = _build_ollama_options(_cfg)
                _num_ctx = int(_opts.get("num_ctx") or 0)
                if _num_ctx and _est_tokens > _num_ctx:
                    logger.warning(
                        "ollama prompt likely overflows context: role=%s est_tokens=%d num_ctx=%d. "
                        "Either bump model_mappings.%s.ollama_options.num_ctx (cost: VRAM) "
                        "or wait for W2 minimal-mode prompt builder.",
                        role,
                        _est_tokens,
                        _num_ctx,
                        role,
                    )
            if role in getattr(self, "_antigravity_roles", set()):
                return await self._invoke_antigravity(
                    role=role,
                    messages=messages,
                    tools=kwargs.get("tools"),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            if role in getattr(self, "_claude_cli_roles", set()):
                try:
                    return await self._invoke_claude_cli(
                        role=role,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as cli_exc:
                    fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
                    if fallback_cfg and not _is_direct_provider_model(fallback_cfg):
                        fallback_role = f"{role}_fallback"
                        logger.warning(
                            "Claude CLI failed for role '%s' (%s); falling back to '%s'",
                            role,
                            cli_exc,
                            fallback_role,
                        )
                        return await self._router.acompletion(
                            model=fallback_role,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            **kwargs,
                        )
                    raise
            if role in getattr(self, "_openai_codex_roles", set()):
                try:
                    return await self._invoke_openai_codex(
                        role=role,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    )
                except Exception as codex_exc:
                    fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
                    if fallback_cfg and not _is_direct_provider_model(fallback_cfg):
                        fallback_role = f"{role}_fallback"
                        logger.warning(
                            "OpenAI Codex failed for role '%s' (%s); falling back to '%s'",
                            role,
                            codex_exc,
                            fallback_role,
                        )
                        return await self._router.acompletion(
                            model=fallback_role,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            **kwargs,
                        )
                    raise
            response = await self._router.acompletion(
                model=role,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            finish_reason = choice.finish_reason
            if finish_reason not in ("stop", "end_turn", "length", None):
                logger.warning("Unexpected finish_reason '%s' for role '%s'", finish_reason, role)
            # SESS-01: Write token usage to sessions table (non-fatal side effect)
            try:
                _write_session(
                    role=role,
                    model=response.model or role,
                    usage=getattr(response, "usage", None),
                )
            except Exception as session_exc:
                logger.debug("Session write failed (non-fatal): %s", session_exc)
            return response
        except AuthenticationError as exc:
            # Copilot returns 401 "token expired" when the tid= bearer token
            # lapses (30-min TTL). Refresh and retry once — same logic as the
            # 403 path in the except Exception handler below.
            if self._uses_copilot and (
                "token expired" in str(exc).lower() or "unauthorized" in str(exc).lower()
            ):
                if self._copilot_refresh_lock.locked():
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning("Copilot token expired (401) — refreshing and retrying")
                        _get_copilot_token()
                        self._rebuild_router()
                return await self._router.acompletion(
                    model=role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            logger.error("Auth failed for role '%s': %s", role, exc)
            raise
        except RateLimitError as exc:
            logger.warning("Rate limit hit for role '%s': %s", role, exc)
            raise
        except Timeout as exc:
            logger.error("Timeout for role '%s': %s", role, exc)
            raise
        except (APIConnectionError, ServiceUnavailableError) as exc:
            logger.error("Provider unavailable for role '%s': %s", role, exc)
            raise
        except BadRequestError as exc:
            logger.error("Bad request for role '%s': %s", role, exc)
            raise
        except BudgetExceededError as exc:
            logger.warning("Budget exceeded for role '%s': %s — attempting fallback", role, exc)
            fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
            if fallback_cfg:
                fallback_role = f"{role}_fallback"
                logger.info("Falling back to '%s' after budget exceeded", fallback_role)
                return await self._router.acompletion(
                    model=fallback_role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            logger.error("Budget exceeded for role '%s' with no fallback configured", role)
            raise
        except Exception as exc:
            # Copilot tokens are short-lived — on "forbidden" errors, refresh
            # the token and retry once before giving up.
            # C-09: Use lock to prevent concurrent double-refresh races.
            if self._uses_copilot and "forbidden" in str(exc).lower():
                if self._copilot_refresh_lock.locked():
                    # Another coroutine is already refreshing — wait for it
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning("Copilot token rejected — refreshing and retrying")
                        _get_copilot_token()  # triggers Authenticator refresh
                        self._rebuild_router()
                return await self._router.acompletion(
                    model=role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            raise

    async def call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        """
        Route to the litellm model for the given role (e.g., 'casual', 'vault').
        Falls back to fallback model on AuthenticationError or RateLimitError.
        Returns extracted text string; raises on unrecoverable errors.

        stream=False enforced — Phase 2 does not stream (see 02-RESEARCH.md Pitfall 4).
        """
        # traffic_cop role: fall back to 'casual' when not configured in model_mappings.
        # Logs once per process lifetime to avoid log spam.
        if role == "traffic_cop" and role not in self._config.model_mappings:
            if "traffic_cop" not in _ROLE_FALLBACK_LOGGED:
                _ROLE_FALLBACK_LOGGED.add("traffic_cop")
                logger.info(
                    "traffic_cop role not found in model_mappings — falling back to 'casual'. "
                    "Add a 'traffic_cop' entry to synapse.json model_mappings for a dedicated "
                    "classifier model (see synapse.json.example)."
                )
            role = "casual"
        if role in getattr(self, "_claude_cli_roles", set()):
            result = await self.call_with_metadata(
                role, messages, temperature, max_tokens, **kwargs
            )
            return result.text
        response = await self._do_call(role, messages, temperature, max_tokens, **kwargs)
        return response.choices[0].message.content or ""

    async def call_with_metadata(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> LLMResult:
        """
        Same as call() but returns an LLMResult with text + usage metadata.
        Extra **kwargs (e.g. response_format) are forwarded to the underlying call.
        """
        _start_time = time.time()
        response = await self._do_call(role, messages, temperature, max_tokens, **kwargs)
        usage = getattr(response, "usage", None)
        result = LLMResult(
            text=response.choices[0].message.content or "",
            model=response.model or "unknown",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            finish_reason=response.choices[0].finish_reason,
        )
        _log.info(
            "llm_call_done",
            extra={
                "role": role,
                "model": result.model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "latency_ms": round((time.time() - _start_time) * 1000),
            },
        )
        return result

    async def call_model(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        api_base: str | None = None,
    ) -> str:
        """
        Direct call with explicit litellm model string (bypasses Router role lookup).
        Used by tools server, validation pings in onboarding wizard, and Ollama local calls.
        """
        import litellm  # noqa: PLC0415

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": 60.0,
            "stream": False,
        }
        if api_base:
            kwargs["api_base"] = api_base

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        return choice.message.content or ""

    # --- Tool execution support (Phase 2) ---

    def _resolve_provider(self, role: str) -> str:
        """Extract the provider prefix from the model string mapped to *role*.

        Returns the portion before the first ``/`` (e.g. ``"gemini"`` for
        ``"gemini/gemini-2.0-flash"``), or ``"unknown"`` if no slash is present.
        """
        mapping = self._config.model_mappings.get(role, {})
        model_str = mapping.get("model", "")
        return model_str.split("/")[0] if "/" in model_str else "unknown"

    async def call_with_tools(
        self,
        role: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        tool_choice: str = "auto",
    ) -> LLMToolResult:
        """Route an LLM call that includes tool definitions.

        Normalizes tool schemas for the target provider, forwards the call
        through ``litellm.Router.acompletion``, and parses any tool-call
        objects in the response into provider-agnostic :class:`ToolCall`
        instances.

        Args:
            role: Router role name (must exist in ``model_mappings``).
            messages: Chat-format message list.
            tools: OpenAI-format tool definitions.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
            tool_choice: ``"auto"`` | ``"none"`` | ``"required"`` | specific
                tool name dict.

        Returns:
            :class:`LLMToolResult` with text, parsed tool calls, and usage.
        """
        provider = self._resolve_provider(role)
        normalized_tools = normalize_tool_schemas(tools, provider)

        # Claude Code CLI headless mode does not expose native tool calls; use
        # it as a text fallback for tool-bearing chat paths.
        if role in getattr(self, "_claude_cli_roles", set()):
            try:
                response = await self._invoke_claude_cli(
                    role=role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                message = response.choices[0].message
                usage = getattr(response, "usage", None)
                return LLMToolResult(
                    text=message.content or "",
                    tool_calls=[],
                    model=response.model or role,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    finish_reason=response.choices[0].finish_reason,
                )
            except Exception as cli_exc:
                import traceback

                logger.warning(
                    "claude CLI failed in call_with_tools (%s)\n%s", cli_exc, traceback.format_exc()
                )
                raise

        if role in getattr(self, "_openai_codex_roles", set()):
            response = await self._invoke_openai_codex(
                role=role,
                messages=messages,
                tools=normalized_tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            message = response.choices[0].message
            usage = (
                getattr(response, "usage", None)
                or type(
                    "U",
                    (),
                    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )()
            )
            tool_calls, _malformed, recovery_events = _normalize_tool_calls_with_report(
                message.tool_calls,
                tools=normalized_tools,
                text=message.content,
            )
            for tool_call in tool_calls:
                try:
                    tool_call.arguments = json.dumps(
                        json.loads(tool_call.arguments),
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    pass
            _log_tool_recovery_events(recovery_events)
            return LLMToolResult(
                text=message.content or "",
                tool_calls=tool_calls,
                model=response.model or role,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                finish_reason=response.choices[0].finish_reason,
            )

        # Google Antigravity is dispatched directly — feed normalized tools
        # straight into the antigravity client and reuse the litellm-shaped
        # shim so the rest of this method's tool-call extraction works.
        if role in getattr(self, "_antigravity_roles", set()):
            response = await self._invoke_antigravity(
                role=role,
                messages=messages,
                tools=normalized_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            message = response.choices[0].message
            usage = (
                getattr(response, "usage", None)
                or type(
                    "U",
                    (),
                    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )()
            )
            tool_calls, _malformed, recovery_events = _normalize_tool_calls_with_report(
                message.tool_calls,
                tools=normalized_tools,
                text=message.content,
            )
            _log_tool_recovery_events(recovery_events)
            return LLMToolResult(
                text=message.content or "",
                tool_calls=tool_calls,
                model=response.model or role,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                finish_reason=response.choices[0].finish_reason,
            )

        kwargs: dict = {
            "model": role,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": normalized_tools,
            "tool_choice": tool_choice,
        }

        try:
            response = await self._router.acompletion(**kwargs)
        except AuthenticationError as exc:
            if self._uses_copilot and (
                "token expired" in str(exc).lower() or "unauthorized" in str(exc).lower()
            ):
                if self._copilot_refresh_lock.locked():
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning(
                            "Copilot token expired (401, tools) — refreshing and retrying"
                        )
                        _get_copilot_token()
                        self._rebuild_router()
                response = await self._router.acompletion(**kwargs)
                # fall through to normal response handling below
            else:
                logger.error("Auth failed for role '%s' (tools): %s", role, exc)
                raise
        except RateLimitError as exc:
            logger.warning("Rate limit for role '%s' (tools): %s", role, exc)
            raise
        except Timeout as exc:
            logger.error("Timeout for role '%s' (tools): %s", role, exc)
            raise
        except (APIConnectionError, ServiceUnavailableError) as exc:
            logger.error("Provider unavailable for role '%s' (tools): %s", role, exc)
            raise
        except BadRequestError as exc:
            logger.error("Bad request for role '%s' (tools): %s", role, exc)
            raise
        except BudgetExceededError as exc:
            logger.warning(
                "Budget exceeded for role '%s' (tools): %s — attempting fallback", role, exc
            )
            fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
            if fallback_cfg:
                fallback_role = f"{role}_fallback"
                logger.info("Falling back to '%s' after budget exceeded (tools)", fallback_role)
                kwargs["model"] = fallback_role
                response = await self._router.acompletion(**kwargs)
            else:
                raise
        except Exception as exc:
            # M-03: Copilot 403 refresh — same logic as _do_call()
            if self._uses_copilot and "forbidden" in str(exc).lower():
                if self._copilot_refresh_lock.locked():
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning("Copilot token rejected (tools) — refreshing")
                        _get_copilot_token()
                        self._rebuild_router()
                response = await self._router.acompletion(**kwargs)
            else:
                raise

        message = response.choices[0].message
        usage = (
            getattr(response, "usage", None)
            or type(
                "U",
                (),
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )()
        )
        tool_calls, malformed_attempt, recovery_events = _normalize_tool_calls_with_report(
            message.tool_calls,
            tools=normalized_tools,
            text=message.content,
        )
        _log_tool_recovery_events(recovery_events)

        if not tool_calls and malformed_attempt:
            logger.info("tool_call_retry_after_malformed_response role=%s", role)
            retry_messages = [
                *messages,
                {"role": "assistant", "content": message.content or ""},
                {"role": "system", "content": _build_tool_retry_instruction(normalized_tools)},
            ]
            retry_kwargs = {**kwargs, "messages": retry_messages}
            try:
                retry_response = await self._router.acompletion(**retry_kwargs)
            except Exception as retry_exc:
                logger.warning("tool-call retry failed for role '%s': %s", role, retry_exc)
            else:
                response = retry_response
                message = response.choices[0].message
                usage = (
                    getattr(response, "usage", None)
                    or type(
                        "U",
                        (),
                        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    )()
                )
                tool_calls, _retry_attempted, retry_events = _normalize_tool_calls_with_report(
                    message.tool_calls,
                    tools=normalized_tools,
                    text=message.content,
                )
                _log_tool_recovery_events(retry_events)

        # SESS-01: Write token usage (non-fatal)
        try:
            _write_session(
                role=role,
                model=response.model or role,
                usage=usage,
            )
        except Exception as session_exc:
            logger.debug("Session write failed (non-fatal): %s", session_exc)

        return LLMToolResult(
            text=message.content or "",
            tool_calls=tool_calls,
            model=response.model or "unknown",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            finish_reason=response.choices[0].finish_reason,
        )


# --- Inference Loop ---


class InferenceLoop:
    """Multi-attempt inference loop wrapping SynapseLLMRouter._do_call().

    Drives retry decisions based on classify_llm_error():
    - CONTEXT_OVERFLOW (FORMAT with context cues): compact_fn → retry
    - RATE_LIMIT: exponential backoff (2s, 4s, 8s + jitter) → retry
    - AUTH / AUTH_PERMANENT: rotate auth profile via AuthProfileStore → retry
    - OVERLOADED / TIMEOUT: retry once with backoff
    - MODEL_NOT_FOUND: try fallback model, no retry
    - FORMAT / BILLING / UNKNOWN: raise immediately

    Args:
        router: The SynapseLLMRouter instance to use for calls.
        max_attempts: Maximum number of retry attempts (default 3).
        compact_fn: Optional async callable to compact messages on context overflow.
            Signature: async (messages: list[dict]) -> list[dict].
            If None, context overflow retries are skipped.
        tool_loop_cb: Optional callback invoked after each attempt (for observability).
            Signature: (attempt: int, error: Exception | None) -> None.
        auth_store: Optional AuthProfileStore for auth profile rotation.
    """

    def __init__(
        self,
        router: SynapseLLMRouter,
        max_attempts: int = 3,
        compact_fn: Callable | None = None,
        tool_loop_cb: Callable | None = None,
        auth_store: Any | None = None,  # AuthProfileStore — lazy import to avoid circular
    ) -> None:
        self._router = router
        self._max_attempts = max(1, max_attempts)
        self._compact_fn = compact_fn
        self._tool_loop_cb = tool_loop_cb
        self._auth_store = auth_store

    @staticmethod
    def _is_context_overflow(error: Exception) -> bool:
        """Detect context overflow from error message heuristics.

        litellm maps context overflow to BadRequestError (FORMAT), so we
        inspect the message for common overflow indicators.
        """
        msg = str(error).lower()
        indicators = [
            "context_length_exceeded",
            "context length",
            "maximum context",
            "too many tokens",
            "token limit",
            "max_tokens",
            "content too large",
            "request too large",
        ]
        return any(ind in msg for ind in indicators)

    @staticmethod
    def _is_model_not_found(error: Exception) -> bool:
        """Detect model-not-found errors from message heuristics."""
        msg = str(error).lower()
        indicators = [
            "model_not_found",
            "model not found",
            "does not exist",
            "no such model",
            "invalid model",
            "unknown model",
        ]
        return any(ind in msg for ind in indicators)

    async def run(
        self,
        role: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResult:
        """Execute an LLM call with automatic retries and error-driven recovery.

        Args:
            role: The router role (e.g., "casual", "code", "vault").
            messages: The chat messages to send.
            **kwargs: Additional kwargs passed to _do_call (temperature, max_tokens).

        Returns:
            LLMResult with text and usage metadata.

        Raises:
            The last exception encountered if all attempts are exhausted.
        """
        last_error: Exception | None = None
        current_messages = list(messages)  # shallow copy — compact_fn may mutate
        server_error_retried = False

        # Select and apply the initial auth profile BEFORE the first call.
        # active_profile tracks which profile's credentials are in os.environ
        # so we report success/failure against the correct profile.
        active_profile = None
        if self._auth_store is not None:
            active_profile = self._auth_store.select_best(role)
            if active_profile is not None:
                self._router._apply_profile_credentials(active_profile, role)

        for attempt in range(self._max_attempts):
            try:
                response = await self._router._do_call(role, current_messages, **kwargs)
                # Build LLMResult from raw response
                usage = getattr(response, "usage", None)
                result = LLMResult(
                    text=response.choices[0].message.content or "",
                    model=response.model or "unknown",
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    finish_reason=response.choices[0].finish_reason,
                )

                # Report success for the profile that actually handled the call
                if self._auth_store is not None and active_profile is not None:
                    self._auth_store.report_success(active_profile.id, model=role)

                if self._tool_loop_cb is not None:
                    self._tool_loop_cb(attempt, None)

                return result

            except Exception as exc:
                last_error = exc
                reason = classify_llm_error(exc)

                if self._tool_loop_cb is not None:
                    self._tool_loop_cb(attempt, exc)

                logger.warning(
                    "InferenceLoop attempt %d/%d for role=%s failed: %s (%s)",
                    attempt + 1,
                    self._max_attempts,
                    role,
                    reason.value,
                    exc,
                )

                # --- Context overflow (FORMAT with context cues) ---
                if reason == AuthProfileFailureReason.FORMAT and self._is_context_overflow(exc):
                    if self._compact_fn is not None:
                        logger.info("Context overflow — compacting messages")
                        current_messages = await self._compact_fn(current_messages)
                        continue
                    else:
                        logger.error("Context overflow but no compact_fn — raising")
                        raise

                # --- Model not found ---
                if reason == AuthProfileFailureReason.FORMAT and self._is_model_not_found(exc):
                    # Try fallback role if it exists, but don't retry
                    fallback_role = f"{role}_fallback"
                    try:
                        response = await self._router._do_call(
                            fallback_role, current_messages, **kwargs
                        )
                        usage = getattr(response, "usage", None)
                        return LLMResult(
                            text=response.choices[0].message.content or "",
                            model=response.model or "unknown",
                            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                            total_tokens=getattr(usage, "total_tokens", 0) or 0,
                            finish_reason=response.choices[0].finish_reason,
                        )
                    except Exception:
                        raise exc from None  # raise original model_not_found

                # --- Rate limited ---
                if reason == AuthProfileFailureReason.RATE_LIMIT:
                    if attempt < self._max_attempts - 1:
                        base_delay = 2 ** (attempt + 1)  # 2, 4, 8
                        jitter = random.uniform(0, base_delay * 0.5)
                        delay = base_delay + jitter
                        logger.info("Rate limited — backing off %.1fs before retry", delay)
                        if self._auth_store is not None and active_profile is not None:
                            self._auth_store.report_failure(
                                active_profile.id,
                                AuthProfileFailureReason.RATE_LIMIT,
                                model=role,
                            )
                        await asyncio.sleep(delay)
                        continue
                    raise

                # --- Auth failed ---
                if reason == AuthProfileFailureReason.AUTH:
                    if self._auth_store is not None and active_profile is not None:
                        self._auth_store.report_failure(
                            active_profile.id,
                            AuthProfileFailureReason.AUTH,
                            model=role,
                        )
                        next_profile = self._auth_store.select_best(role)
                        if next_profile is not None:
                            active_profile = next_profile
                            self._router._apply_profile_credentials(active_profile, role)
                            logger.info(
                                "Auth failed — rotated to profile %s",
                                active_profile.id,
                            )
                            continue
                    raise

                # --- Server error / overloaded / timeout ---
                if reason in (
                    AuthProfileFailureReason.OVERLOADED,
                    AuthProfileFailureReason.TIMEOUT,
                ):
                    if not server_error_retried and attempt < self._max_attempts - 1:
                        server_error_retried = True
                        delay = 2.0 + random.uniform(0, 1.0)
                        logger.info(
                            "Server error — backing off %.1fs before single retry",
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

                # --- Non-retryable (FORMAT without context cues, BILLING, UNKNOWN) ---
                raise

        # All attempts exhausted
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"InferenceLoop exhausted {self._max_attempts} attempts for role={role}")
