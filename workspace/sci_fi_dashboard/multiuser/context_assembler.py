"""context_assembler.py — Full context assembly for a session.

Orchestrates:
    1. Session store lookup (creates entry if absent).
    2. Transcript load with optional history limit.
    3. Workspace bootstrap file load.
    4. System prompt assembly.
    5. Context-window headroom guard + warning.

Constants
---------
CONTEXT_WINDOW_HARD_MIN_TOKENS : int
    Minimum required headroom (tokens) after assembled content.  Raises
    ``ContextWindowTooSmallError`` when remaining headroom falls below this.
CONTEXT_WINDOW_WARN_TOKENS : int
    Warning threshold — logs a ``WARNING`` when remaining headroom is below
    this value but above ``CONTEXT_WINDOW_HARD_MIN_TOKENS``.

Guard semantics::

    estimated_content_tokens = estimate_tokens(messages) + len(system_prompt) // 4
    remaining = context_window_tokens - estimated_content_tokens
    if remaining < CONTEXT_WINDOW_HARD_MIN_TOKENS:
        raise ContextWindowTooSmallError(...)
    if remaining < CONTEXT_WINDOW_WARN_TOKENS:
        logger.warning(...)
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from sci_fi_dashboard.multiuser.compaction import estimate_tokens
from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
from sci_fi_dashboard.multiuser.memory_manager import load_bootstrap_files
from sci_fi_dashboard.multiuser.session_key import parse_session_key
from sci_fi_dashboard.multiuser.session_store import SessionStore
from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

CONTEXT_WINDOW_HARD_MIN_TOKENS: int = 16_000
CONTEXT_WINDOW_WARN_TOKENS: int = 32_000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContextWindowTooSmallError(Exception):
    """Raised when the assembled content leaves insufficient headroom in the context window."""


# ---------------------------------------------------------------------------
# System-prompt builder (lives here, not in persona.py)
# ---------------------------------------------------------------------------


def build_system_prompt(
    bootstrap_files: list[dict],
    agent_id: str,
    session_key: str,
    extra_context: dict | None = None,
) -> str:
    """Assemble a system prompt from pre-loaded bootstrap files.

    Structure::

        You are <agent_id>.  Session: <session_key>.

        # Project Context

        ## <filename>

        <content>

        ...

        ## Authorized Senders
        <sender1>
        <sender2>

    Args:
        bootstrap_files: Output of ``load_bootstrap_files()`` —
                         ``[{"name": str, "path": str, "content": str}]``.
        agent_id:        Logical agent identifier used in the identity line.
        session_key:     Active session key string (included for traceability).
        extra_context:   Optional dict.  If it contains ``"allow_from"``
                         (a list of strings), an ``## Authorized Senders``
                         section is appended.

    Returns:
        Fully assembled system prompt string.
    """
    lines: list[str] = []

    # Identity line.
    lines.append(f"You are {agent_id}.  Session: {session_key}.")
    lines.append("")

    # Project context section.
    if bootstrap_files:
        lines.append("# Project Context")
        lines.append("")
        for bf in bootstrap_files:
            name = bf.get("name", "unknown")
            content = bf.get("content", "").strip()
            lines.append(f"## {name}")
            lines.append("")
            if content:
                lines.append(content)
                lines.append("")

    # Authorized senders block (optional).
    if extra_context:
        allow_from: list[str] = extra_context.get("allow_from", [])
        if allow_from:
            lines.append("## Authorized Senders")
            lines.append("")
            for sender in allow_from:
                lines.append(str(sender))
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------


async def assemble_context(
    session_key: str,
    agent_id: str,
    data_root: Path,
    config: Any,
    context_window_tokens: int,
    conversation_cache: ConversationCache | None = None,
) -> dict:
    """Assemble the full context for a session.

    Args:
        session_key:           Active session key string.
        agent_id:              Logical agent identifier.
        data_root:             Synapse data root (``~/.synapse`` or overridden via env).
        config:                ``SynapseConfig`` instance (or any object with a
                               ``channels`` dict attribute).
        context_window_tokens: Total context window size for the active model.
                               The caller resolves this from their model registry.
        conversation_cache:    Optional ``ConversationCache`` instance.  When
                               provided, cache hits skip the disk read; misses
                               populate the cache for subsequent calls.

    Returns:
        ``{"system_prompt": str, "messages": list[dict]}``

    Raises:
        ContextWindowTooSmallError: When remaining context headroom falls below
            ``CONTEXT_WINDOW_HARD_MIN_TOKENS`` (16 000 tokens).
    """
    # 1. Session store — get or create the entry.
    store = SessionStore(agent_id, data_root=data_root)
    entry = await store.get(session_key)
    if entry is None:
        entry = await store.update(session_key, {})

    # 2. Derive transcript path from the session entry.
    t_path = transcript_path(entry, data_root, agent_id)

    # 3. Resolve history_limit from config.
    #    Channel is the third colon-segment of the session key: agent:<id>:<channel>:...
    history_limit: int | None = None
    parsed = parse_session_key(session_key)
    if parsed:
        channel_segment = parsed.rest.split(":")[0] if parsed.rest else None
        if channel_segment:
            channels_cfg = getattr(config, "channels", {}) or {}
            ch_cfg = channels_cfg.get(channel_segment, {})
            raw_limit = ch_cfg.get("dmHistoryLimit")
            if raw_limit is not None:
                with contextlib.suppress(TypeError, ValueError):
                    history_limit = int(raw_limit)

    # 4. Load messages — try conversation cache first.
    messages: list[dict] | None = None
    if conversation_cache is not None:
        messages = conversation_cache.get(session_key)

    if messages is None:
        # Cache miss — load from disk.
        messages = await load_messages(t_path, limit=history_limit)
        if conversation_cache is not None:
            conversation_cache.put(session_key, messages)
    else:
        # Cache hit — still apply history limit if configured.
        if history_limit is not None:
            from sci_fi_dashboard.multiuser.transcript import limit_history_turns

            messages = limit_history_turns(messages, history_limit)

    # 5. Workspace directory.
    workspace_dir = data_root / "workspace"

    # 6. Load bootstrap files (minimal set for sub-agent/cron keys).
    bootstrap_files = await load_bootstrap_files(workspace_dir, session_key=session_key)

    # 7. Build allow_from list from config.
    allow_from: list[str] = []
    if parsed:
        channel_segment = parsed.rest.split(":")[0] if parsed.rest else None
        if channel_segment:
            channels_cfg = getattr(config, "channels", {}) or {}
            ch_cfg = channels_cfg.get(channel_segment, {})
            allow_from = ch_cfg.get("allowFrom", [])

    # 8. Assemble system prompt.
    system_prompt = build_system_prompt(
        bootstrap_files=bootstrap_files,
        agent_id=agent_id,
        session_key=session_key,
        extra_context={"allow_from": allow_from} if allow_from else None,
    )

    # 9. Context-window headroom guard.
    estimated_content_tokens = estimate_tokens(messages) + len(system_prompt) // 4
    remaining = context_window_tokens - estimated_content_tokens

    if remaining < CONTEXT_WINDOW_HARD_MIN_TOKENS:
        raise ContextWindowTooSmallError(
            f"Insufficient context headroom: {remaining} tokens remaining "
            f"(need at least {CONTEXT_WINDOW_HARD_MIN_TOKENS}).  "
            f"Estimated content: {estimated_content_tokens} tokens, "
            f"context window: {context_window_tokens} tokens."
        )

    if remaining < CONTEXT_WINDOW_WARN_TOKENS:
        logger.warning(
            "assemble_context: low context headroom — %d tokens remaining "
            "(threshold: %d) for session_key=%s",
            remaining,
            CONTEXT_WINDOW_WARN_TOKENS,
            session_key,
        )

    return {"system_prompt": system_prompt, "messages": messages}
