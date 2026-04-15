"""session_key.py — Pure session-key builder and parser.

All functions are stateless.  No I/O, no Synapse singletons.

Key shapes
----------
Non-direct (group / channel):
    agent:<agentId>:<channel>:<peerKind>:<peerId>
    agent:<agentId>:<channel>:<peerKind>:<peerId>:thread:<threadId>

Direct DM — four dmScope variants:
    main                      → agent:<agentId>:<mainKey>
    per-peer                  → agent:<agentId>:<channel>:dm:<peerId>
    per-channel-peer          → agent:<agentId>:<channel>:dm:<peerId>
                                  (same as per-peer; channel already in key)
    per-account-channel-peer  → agent:<agentId>:<channel>:dm:<accountId>:<peerId>
"""

from __future__ import annotations

import re
from typing import NamedTuple

from sci_fi_dashboard.multiuser.identity_linker import resolve_linked_peer_id

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_VALID_CHARS = re.compile(r"[^a-z0-9._\-]")


class ParsedSessionKey(NamedTuple):
    """Structured result returned by :func:`parse_session_key`."""

    agent_id: str
    rest: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def normalise_agent_id(agent_id: str) -> str:
    """Lower-case and sanitize an agent ID using the same rules as peer IDs."""
    return _sanitize(agent_id.lower())


def _sanitize(value: str) -> str:
    """Replace chars outside ``[a-z0-9._-]``, strip edge dashes, fallback to 'unknown'."""
    cleaned = _VALID_CHARS.sub("-", value.lower())
    cleaned = cleaned.strip("-")
    return cleaned or "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_session_key(
    agent_id: str,
    channel: str,
    peer_id: str,
    peer_kind: str,
    account_id: str,
    dm_scope: str,
    main_key: str,
    identity_links: dict,
    thread_id: str | None = None,
) -> str:
    """Build a canonical session-key string from the given inputs.

    All string inputs are normalised to lowercase before use.

    Args:
        agent_id:       Logical agent identifier.
        channel:        Channel name (``"whatsapp"``, ``"telegram"``, …).
        peer_id:        Raw peer / chat identifier (phone number, group ID, …).
        peer_kind:      ``"direct"``, ``"group"``, or ``"channel"``.
        account_id:     Platform account identifier (used in per-account scope).
        dm_scope:       One of ``"main"``, ``"per-peer"``, ``"per-channel-peer"``,
                        ``"per-account-channel-peer"``.
        main_key:       Fallback key used when ``dm_scope == "main"``; typically
                        ``"<channel>:dm"`` or a config-supplied constant.
        identity_links: ``session.identityLinks`` dict from config.
        thread_id:      Optional message-thread identifier.  Appended as
                        ``:thread:<id>`` suffix for non-direct keys only.

    Returns:
        Fully-formed session key string, e.g.
        ``"agent:jarvis:whatsapp:dm:alice"``.
    """
    norm_agent = normalise_agent_id(agent_id)
    norm_channel = channel.lower().strip()
    norm_peer_kind = peer_kind.lower().strip()
    norm_account = _sanitize(account_id.lower()) if account_id else "unknown"
    norm_main_key = main_key.lower().strip() if main_key else "main"
    norm_thread = thread_id.lower().strip() if thread_id else None

    # Sanitize peer_id *before* identity-link lookup so the lookup uses the
    # same normalised value that would end up in the key.
    sanitized_peer = _sanitize(peer_id.lower()) if peer_id else "unknown"

    # Identity-link substitution applies to direct DMs only when dm_scope != "main".
    if norm_peer_kind == "direct" and dm_scope != "main":
        linked = resolve_linked_peer_id(sanitized_peer, norm_channel, identity_links, dm_scope)
        if linked:
            sanitized_peer = linked.lower().strip()

    # Build the key.
    if norm_peer_kind == "direct":
        key = _build_dm_key(
            norm_agent, norm_channel, sanitized_peer, norm_account, dm_scope, norm_main_key
        )
    else:
        # Group / channel keys.
        key = f"agent:{norm_agent}:{norm_channel}:{norm_peer_kind}:{sanitized_peer}"
        if norm_thread:
            key = f"{key}:thread:{norm_thread}"

    return key


def _build_dm_key(
    agent_id: str,
    channel: str,
    peer_id: str,
    account_id: str,
    dm_scope: str,
    main_key: str,
) -> str:
    """Return the DM portion of the session key for the given *dm_scope*."""
    if dm_scope == "main":
        # All DMs share one session — use the pre-supplied main_key verbatim.
        return f"agent:{agent_id}:{main_key}"

    if dm_scope == "per-peer":
        return f"agent:{agent_id}:{channel}:dm:{peer_id}"

    if dm_scope == "per-channel-peer":
        # Channel already embedded — identical shape to per-peer in practice.
        return f"agent:{agent_id}:{channel}:dm:{peer_id}"

    if dm_scope == "per-account-channel-peer":
        return f"agent:{agent_id}:{channel}:dm:{account_id}:{peer_id}"

    # Unknown scope → fall back to per-peer shape.
    return f"agent:{agent_id}:{channel}:dm:{peer_id}"


def parse_session_key(key: str) -> ParsedSessionKey | None:
    """Parse *key* and return a :class:`ParsedSessionKey`, or ``None`` on invalid input.

    A valid key must:
    - Start with the literal segment ``"agent"``.
    - Contain at least three colon-delimited parts (``"agent:<id>:<rest>"``).

    Args:
        key: Session key string to parse.

    Returns:
        :class:`ParsedSessionKey` on success, ``None`` on invalid input.
    """
    if not key:
        return None
    parts = key.split(":")
    if len(parts) < 3 or parts[0] != "agent":
        return None
    agent_id = parts[1]
    rest = ":".join(parts[2:])
    return ParsedSessionKey(agent_id=agent_id, rest=rest)


def is_subagent_key(key: str) -> bool:
    """Return ``True`` if *key* represents a sub-agent session."""
    return ":subagent:" in key


def is_cron_key(key: str) -> bool:
    """Return ``True`` if *key* represents a cron / scheduled session."""
    parsed = parse_session_key(key)
    if not parsed:
        return False
    return parsed.rest.startswith("cron:")


def get_subagent_depth(key: str) -> int:
    """Return how many ``:subagent:`` segments appear in *key* (nesting depth).

    Returns 0 for non-subagent keys.
    """
    return key.count(":subagent:")
