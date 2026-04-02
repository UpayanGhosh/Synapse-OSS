"""
User-facing tool features -- tool footer, built-in utility tools, HTTP endpoints.
Phase 5 of the Tool Execution milestone.

Usage:
    from sci_fi_dashboard.tool_features import (
        format_tool_footer,
        register_user_tools,
        create_tool_endpoints,
    )

This module is STANDALONE -- zero imports from other Synapse modules.
All data exchange uses plain dicts for portability across phases.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Tool Usage Footer
# ---------------------------------------------------------------------------


def format_tool_footer(
    tools_used: list[str],
    total_tool_time: float,
    round_count: int,
) -> str:
    """Format a compact tool usage footer for WhatsApp responses.

    Returns empty string if no tools were used.
    ASCII-safe for Windows cp1252 encoding -- no emoji.
    """
    if not tools_used:
        return ""

    unique_tools = list(dict.fromkeys(tools_used))  # preserve order, deduplicate
    parts = [
        f"Tools: {', '.join(unique_tools)}",
        f"Tool time: {total_tool_time:.1f}s",
        f"Rounds: {round_count}",
    ]
    return "\n---\n" + " | ".join(parts)


# ---------------------------------------------------------------------------
# 2. Model Override Store
# ---------------------------------------------------------------------------

# In-memory per-session model overrides (chat_id -> role)
_model_overrides: dict[str, str] = {}


def get_model_override(chat_id: str) -> str | None:
    """Get active model override for a chat session."""
    return _model_overrides.get(chat_id)


def set_model_override(chat_id: str, role: str) -> None:
    """Set model override for a chat session."""
    _model_overrides[chat_id] = role


def clear_model_override(chat_id: str) -> None:
    """Clear model override for a chat session."""
    _model_overrides.pop(chat_id, None)


# ---------------------------------------------------------------------------
# 3. Tool Factory Definitions for User Tools
# ---------------------------------------------------------------------------


@dataclass
class UserToolDef:
    """Portable tool definition -- converted to SynapseTool by the integration layer."""

    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], Awaitable[dict]]  # returns {"content": str, "is_error": bool}
    owner_only: bool = False


def get_switch_model_tool(available_roles: list[str]) -> UserToolDef:
    """switch_model -- owner-only tool to change the active LLM model role."""

    async def handle(args: dict) -> dict:
        role = args.get("model_role", "")
        if role not in available_roles:
            return {
                "content": (
                    f"Unknown role '{role}'. "
                    f"Available: {', '.join(available_roles)}"
                ),
                "is_error": True,
            }
        chat_id = args.get("_chat_id", "default")
        set_model_override(chat_id, role)
        return {
            "content": (
                f"Switched to '{role}'. This override lasts until "
                "the session restarts."
            ),
            "is_error": False,
        }

    return UserToolDef(
        name="switch_model",
        description=(
            f"Switch the AI model. Available roles: {', '.join(available_roles)}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_role": {
                    "type": "string",
                    "description": "The role to switch to",
                    "enum": available_roles,
                }
            },
            "required": ["model_role"],
        },
        handler=handle,
        owner_only=True,
    )


def get_import_memory_tool() -> UserToolDef:
    """import_memory -- owner-only tool to store facts in long-term memory."""

    async def handle(args: dict) -> dict:
        content = args.get("content", "").strip()
        if not content:
            return {"content": "No content provided to store.", "is_error": True}
        category = args.get("category", "general")
        # Returns instruction for the integration layer to call memory_engine.ingest()
        return {
            "content": f"Stored in memory (category: {category}): {content[:100]}...",
            "is_error": False,
            "_action": "ingest_memory",
            "_payload": {"content": content, "category": category},
        }

    return UserToolDef(
        name="import_memory",
        description="Store a fact or piece of information in long-term memory.",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact to store",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Category (personal, fact, preference, general)"
                    ),
                    "default": "general",
                },
            },
            "required": ["content"],
        },
        handler=handle,
        owner_only=True,
    )


def get_list_tools_tool(available_tools: list[dict]) -> UserToolDef:
    """list_tools -- list all available tools for the current session."""

    async def handle(args: dict) -> dict:
        return {
            "content": json.dumps(available_tools, indent=2),
            "is_error": False,
        }

    return UserToolDef(
        name="list_tools",
        description="List all available tools and their capabilities.",
        parameters={"type": "object", "properties": {}},
        handler=handle,
    )


# ---------------------------------------------------------------------------
# 4. Command Shortcut Parser
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    """Result of parsing a user message for command shortcuts."""

    is_command: bool = False
    response: str | None = None  # direct response, skip LLM
    action: str | None = None  # "switch_model", "list_tools", "forget_model"


def parse_command_shortcut(
    message: str,
    chat_id: str,
    available_roles: list[str],
) -> CommandResult:
    """Parse user message for /command shortcuts. Returns CommandResult."""
    text = message.strip()

    if text.startswith("/model "):
        role = text[7:].strip()
        if role in available_roles:
            set_model_override(chat_id, role)
            return CommandResult(
                is_command=True,
                response=f"Model switched to '{role}'.",
                action="switch_model",
            )
        else:
            return CommandResult(
                is_command=True,
                response=(
                    f"Unknown role '{role}'. "
                    f"Available: {', '.join(available_roles)}"
                ),
            )

    if text == "/tools":
        return CommandResult(is_command=True, action="list_tools")

    if text == "/forget":
        clear_model_override(chat_id)
        return CommandResult(
            is_command=True,
            response="Model override cleared. Using automatic routing.",
        )

    return CommandResult(is_command=False)


# ---------------------------------------------------------------------------
# 5. HTTP Tool Invocation Helpers
# ---------------------------------------------------------------------------


@dataclass
class ToolInvokeRequest:
    """Incoming request to invoke a tool via HTTP."""

    tool: str
    args: dict = field(default_factory=dict)
    session_key: str = "default"
    dry_run: bool = False


@dataclass
class ToolInvokeResponse:
    """Response from a tool invocation."""

    ok: bool
    tool: str
    result: dict | None = None
    duration_ms: float = 0.0
    dry_run: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON response."""
        d: dict[str, Any] = {"ok": self.ok, "tool": self.tool}
        if self.result is not None:
            d["result"] = self.result
        if self.duration_ms > 0:
            d["duration_ms"] = round(self.duration_ms, 1)
        if self.dry_run:
            d["dry_run"] = True
            d["would_execute"] = self.tool
        if self.error:
            d["error"] = self.error
        return d


async def handle_tool_invoke(
    request: ToolInvokeRequest,
    execute_fn: Callable[[str, dict], Awaitable[dict]],
    available_tools: list[str],
    hook_before: Callable | None = None,
    hook_after: Callable | None = None,
) -> ToolInvokeResponse:
    """Handle a direct tool invocation request.

    Args:
        request: The invocation request.
        execute_fn: async (name, args) -> {"content": str, "is_error": bool}
        available_tools: List of tool names available to this caller.
        hook_before: Optional pre-execution hook. Signature:
            async (tool_name, args, ctx) -> (action, modified_args).
            action="block" rejects the call.
        hook_after: Optional post-execution hook. Signature:
            async (tool_name, args, result, duration_ms) -> None.
    """
    if request.tool not in available_tools:
        return ToolInvokeResponse(
            ok=False,
            tool=request.tool,
            error=f"Tool '{request.tool}' not found or not allowed",
        )

    if request.dry_run:
        return ToolInvokeResponse(
            ok=True,
            tool=request.tool,
            dry_run=True,
        )

    effective_args = request.args
    if hook_before:
        action, modified = await hook_before(request.tool, effective_args, {})
        if action == "block":
            return ToolInvokeResponse(
                ok=False,
                tool=request.tool,
                error="Blocked by hook",
            )
        if modified is not None:
            effective_args = modified

    t0 = time.time()
    result = await execute_fn(request.tool, effective_args)
    duration_ms = (time.time() - t0) * 1000

    if hook_after:
        await hook_after(request.tool, effective_args, result, duration_ms)

    return ToolInvokeResponse(
        ok=True,
        tool=request.tool,
        result={
            "content": result.get("content", ""),
            "is_error": result.get("is_error", False),
        },
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# 6. Tool Catalog Builder
# ---------------------------------------------------------------------------


@dataclass
class ToolCatalogEntry:
    """A single entry in the tool catalog."""

    name: str
    description: str
    parameters: dict


def build_tool_catalog(tools: list[dict]) -> list[dict]:
    """Build catalog response from an OpenAI-format tool schema list.

    Each input dict is expected to have the shape::

        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    Returns a flat list of dicts with name/description/parameters.
    """
    return [
        {
            "name": t.get("function", {}).get("name", ""),
            "description": t.get("function", {}).get("description", ""),
            "parameters": t.get("function", {}).get("parameters", {}),
        }
        for t in tools
    ]
