"""
Cron Scheduler — isolated agent session.

Creates a temporary session key, executes the LLM payload via the provided
``execute_fn``, and returns the raw output text.  The session is discarded
after the call, ensuring no state leaks into the main conversation.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Coroutine, Optional

from .types import CronPayload

logger = logging.getLogger(__name__)


async def run_isolated_agent(
    payload: CronPayload,
    session_key: str,
    execute_fn: Optional[Callable[..., Coroutine[Any, Any, str]]] = None,
) -> str:
    """Create a temp session, run the LLM with the payload, return output text.

    Parameters
    ----------
    payload:
        The cron payload containing the message, model overrides, etc.
    session_key:
        A unique key for this ephemeral session (typically ``cron-<job_id>-<uuid>``).
    execute_fn:
        An async callable ``(message, session_key, **kwargs) -> str`` that
        performs the actual LLM invocation.  If None, returns a placeholder.
    """
    if execute_fn is None:
        logger.warning("No execute_fn provided — returning empty output")
        return ""

    kwargs: dict[str, Any] = {}
    if payload.model_override:
        kwargs["model_override"] = payload.model_override
    if payload.fallbacks:
        kwargs["fallbacks"] = payload.fallbacks
    if payload.thinking:
        kwargs["thinking"] = payload.thinking
    if payload.tools_allow:
        kwargs["tools_allow"] = payload.tools_allow
    if payload.light_context:
        kwargs["light_context"] = payload.light_context
    kwargs["timeout_seconds"] = payload.timeout_seconds

    try:
        output = await execute_fn(
            payload.message or "",
            session_key,
            **kwargs,
        )
        return output or ""
    except Exception:
        logger.exception("Isolated agent execution failed (session=%s)", session_key)
        raise
