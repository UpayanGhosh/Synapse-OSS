"""
Tool Safety Pipeline -- Policy filtering, hooks, graduated loop detection, audit.
Phase 4 of the Tool Execution milestone.

Usage by the execution loop (Phase 3):
    from sci_fi_dashboard.tool_safety import (
        ToolPolicy, PolicyStep, apply_tool_policy_pipeline,
        ToolHookRunner, ToolLoopDetector, ToolAuditLogger,
        build_policy_steps,
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Tool Policy Pipeline
#    4 layers in priority order: Global -> Channel -> Sender -> Session.
# ---------------------------------------------------------------------------


@dataclass
class ToolPolicy:
    """Allow/deny filter for tool names."""

    allow: list[str] | None = None  # None = allow all
    deny: list[str] | None = None


@dataclass
class PolicyStep:
    """One layer of the policy pipeline."""

    policy: ToolPolicy
    label: str  # for diagnostic logging


def apply_tool_policy_pipeline(
    tool_names: list[dict],  # [{"name": str, "owner_only": bool}, ...]
    steps: list[PolicyStep],
    sender_is_owner: bool,
) -> tuple[list[str], list[dict]]:
    """
    Filter tools through layered policies.

    Args:
        tool_names: List of dicts with "name" and "owner_only" keys.
        steps: Policy steps in priority order.
        sender_is_owner: Whether the sender is the bot owner.

    Returns:
        (surviving_tool_names, removal_log)
    """
    remaining = list(tool_names)
    removed_log: list[dict] = []

    for step in steps:
        keep: list[dict] = []
        for tool_info in remaining:
            name = tool_info["name"]
            is_owner_only = tool_info.get("owner_only", False)

            # Owner-only check
            if is_owner_only and not sender_is_owner:
                removed_log.append({"tool": name, "step": step.label, "reason": "owner_only"})
                logger.info(
                    '[tool-policy] "%s" removed by step "%s" (owner_only)',
                    name,
                    step.label,
                )
                continue

            # Deny list
            if step.policy.deny and name in step.policy.deny:
                removed_log.append({"tool": name, "step": step.label, "reason": "denied"})
                logger.info(
                    '[tool-policy] "%s" removed by step "%s" (denied)',
                    name,
                    step.label,
                )
                continue

            # Allow list
            if step.policy.allow is not None and name not in step.policy.allow:
                removed_log.append({"tool": name, "step": step.label, "reason": "not_in_allowlist"})
                logger.info(
                    '[tool-policy] "%s" removed by step "%s" (not_in_allowlist)',
                    name,
                    step.label,
                )
                continue

            keep.append(tool_info)
        remaining = keep

    surviving_names = [t["name"] for t in remaining]
    logger.info(
        "[tool-policy] %d tools available after policy filtering",
        len(surviving_names),
    )
    return surviving_names, removed_log


# ---------------------------------------------------------------------------
# 2. Before / After Tool Call Hooks
# ---------------------------------------------------------------------------

# Hook type signatures
BeforeToolCallHook = Callable[[str, dict, dict], Awaitable[tuple[str, dict | None]]]
# Receives: (tool_name, args, context_dict)
# Returns:  ("allow", modified_args | None) or ("block", None)

AfterToolCallHook = Callable[[str, dict, dict, float], Awaitable[None]]
# Receives: (tool_name, args, result_dict, duration_ms)


class ToolHookRunner:
    """Manages before/after hooks for tool invocations."""

    def __init__(self) -> None:
        self._before_hooks: list[BeforeToolCallHook] = []
        self._after_hooks: list[AfterToolCallHook] = []

    def register_before(self, hook: BeforeToolCallHook) -> None:
        self._before_hooks.append(hook)

    def register_after(self, hook: AfterToolCallHook) -> None:
        self._after_hooks.append(hook)

    async def run_before(self, tool_name: str, args: dict, context: dict) -> tuple[str, dict]:
        """Run all before-hooks. Any hook can block or modify args."""
        effective_args = dict(args)
        for hook in self._before_hooks:
            try:
                action, modified = await hook(tool_name, effective_args, context)
                if action == "block":
                    logger.warning("[tool-hooks] '%s' blocked by before-hook", tool_name)
                    return ("block", effective_args)
                if modified is not None:
                    effective_args = modified
            except Exception as exc:
                logger.warning("[tool-hooks] Before-hook error for '%s': %s", tool_name, exc)
        return ("allow", effective_args)

    async def run_after(self, tool_name: str, args: dict, result: dict, duration_ms: float) -> None:
        """Run all after-hooks (fire-and-forget, errors logged)."""
        for hook in self._after_hooks:
            try:
                await hook(tool_name, args, result, duration_ms)
            except Exception as exc:
                logger.warning("[tool-hooks] After-hook error: %s", exc)


# ---------------------------------------------------------------------------
# 3. Graduated Loop Detection
#    Escalation: 3 repeats -> warn, 5 -> error inject, 7 -> hard block.
# ---------------------------------------------------------------------------


class ToolLoopDetector:
    """Detects repeated identical tool calls and escalates severity."""

    def __init__(self) -> None:
        self._history: list[tuple[str, str]] = []  # (name, args_hash)

    def record(self, name: str, arguments: dict) -> str:
        """Record a tool call. Returns severity: 'ok', 'warn', 'error', 'block'."""
        args_hash = hashlib.md5(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:12]
        key = (name, args_hash)
        self._history.append(key)

        # Count consecutive identical calls (walking backwards)
        consecutive = 0
        for prev in reversed(self._history):
            if prev == key:
                consecutive += 1
            else:
                break

        if consecutive >= 7:
            logger.error(
                "[tool-loop] BLOCK: '%s' called %dx with identical args",
                name,
                consecutive,
            )
            return "block"
        if consecutive >= 5:
            logger.warning(
                "[tool-loop] ERROR: '%s' called %dx with identical args",
                name,
                consecutive,
            )
            return "error"
        if consecutive >= 3:
            logger.info(
                "[tool-loop] WARN: '%s' called %dx with identical args",
                name,
                consecutive,
            )
            return "warn"
        return "ok"

    def get_warning_message(self, name: str, severity: str) -> str:
        """Return a user-facing message for the given severity level."""
        if severity == "block":
            return (
                f"Tool loop detected: '{name}' called 7+ times with identical "
                "arguments. Stopping to prevent infinite loop. "
                "Try a different approach."
            )
        if severity == "error":
            return (
                f"Warning: '{name}' has been called 5+ times with the same "
                "arguments. You may be stuck in a loop. "
                "Try a different tool or approach."
            )
        return ""

    def reset(self) -> None:
        """Reset history (e.g., new session)."""
        self._history.clear()


# ---------------------------------------------------------------------------
# 4. Audit Logger for Tool Calls
# ---------------------------------------------------------------------------


class ToolAuditLogger:
    """Logs tool calls to a JSONL audit file."""

    def __init__(self, audit_dir: str | None = None) -> None:
        self._audit_dir = audit_dir
        self._log_path: str | None = None
        if audit_dir:
            os.makedirs(audit_dir, exist_ok=True)
            self._log_path = os.path.join(audit_dir, "tool_audit.jsonl")

    def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result_content: str,
        is_error: bool,
        duration_ms: float,
        sender_id: str,
        chat_id: str,
    ) -> None:
        """Append a single audit entry."""
        entry = {
            "event": "TOOL_CALL",
            "tool": tool_name,
            "args_preview": json.dumps(args, default=str)[:200],
            "result_length": len(result_content),
            "is_error": is_error,
            "duration_ms": round(duration_ms, 1),
            "sender": sender_id,
            "chat_id": chat_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        logger.debug("[tool-audit] %s: %.1fms, error=%s", tool_name, duration_ms, is_error)

        if self._log_path:
            try:
                with open(self._log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
            except OSError as exc:
                logger.warning("[tool-audit] Failed to write audit log: %s", exc)


# ---------------------------------------------------------------------------
# 5. Policy Builder Helper
# ---------------------------------------------------------------------------


def build_policy_steps(config: dict, channel_id: str | None = None) -> list[PolicyStep]:
    """Build policy steps from synapse.json config.

    Produces up to 3 steps:
      1. Global   -- from config["tools"]
      2. Channel  -- from config["channels"][channel_id]["tools"]
      3. Sender   -- pass-through (owner_only is handled in apply_tool_policy_pipeline)
    """
    steps: list[PolicyStep] = []

    # Layer 1: Global
    global_tools = config.get("tools", {})
    if global_tools.get("deny") or global_tools.get("allow"):
        steps.append(
            PolicyStep(
                policy=ToolPolicy(
                    deny=global_tools.get("deny"),
                    allow=global_tools.get("allow"),
                ),
                label="global",
            )
        )

    # Layer 2: Channel-specific
    if channel_id:
        channel_config = config.get("channels", {}).get(channel_id, {})
        channel_tools = channel_config.get("tools", {})
        if channel_tools.get("deny") or channel_tools.get("allow"):
            steps.append(
                PolicyStep(
                    policy=ToolPolicy(
                        deny=channel_tools.get("deny"),
                        allow=channel_tools.get("allow"),
                    ),
                    label=f"channel:{channel_id}",
                )
            )

    # Layer 3: Sender (owner_only handled in apply_tool_policy_pipeline)
    steps.append(
        PolicyStep(
            policy=ToolPolicy(),
            label="sender",
        )
    )

    return steps
