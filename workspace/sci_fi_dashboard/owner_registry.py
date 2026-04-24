"""Owner identity registry across channels.

First-contact auto-pairing: the first peer to DM the bot on any channel is
registered as owner for that channel. Subsequent senders on the same channel
are treated as non-owners. Persisted at ~/.synapse/state/owners.json.

Threat model: only the bot owner knows/owns the channel bot tokens, so first
contact is assumed to be the owner. This trades absolute security for
zero-config setup. If a rogue first contact happens, delete owners.json to
reset.

Usage:
    from sci_fi_dashboard.owner_registry import register_first_contact, is_owner
    register_first_contact(channel="telegram", peer_id="1988095919")
    if is_owner("1988095919"): ...
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_PATH = Path.home() / ".synapse" / "state" / "owners.json"
_LOCK = threading.Lock()


def _default() -> dict:
    return {"the_creator": {}, "the_partner": {}}


def _load() -> dict:
    if not _PATH.exists():
        return _default()
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("owners.json unreadable (%s) — resetting", e)
        return _default()
    data.setdefault("the_creator", {})
    data.setdefault("the_partner", {})
    return data


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def register_first_contact(
    channel: str,
    peer_id: str,
    persona: str = "the_creator",
) -> bool:
    """Register peer_id as owner of persona on channel if slot is empty.

    Returns True on newly registered; False if slot already held by a
    different peer.
    """
    if not channel or not peer_id:
        return False
    with _LOCK:
        data = _load()
        persona_map = data.setdefault(persona, {})
        existing = persona_map.get(channel)
        if existing == peer_id:
            return False
        if existing is not None:
            return False
        persona_map[channel] = peer_id
        _save(data)
        logger.warning(
            "owner_first_contact_registered channel=%s peer_id=%s persona=%s",
            channel,
            peer_id,
            persona,
        )
        return True


def is_owner(peer_id: str | None) -> bool:
    """True if peer_id is registered as owner on any channel, any persona."""
    if not peer_id:
        return False
    data = _load()
    for persona_map in data.values():
        if peer_id in persona_map.values():
            return True
    return False


def get_owner(persona: str, channel: str) -> str | None:
    return _load().get(persona, {}).get(channel)


def all_owners() -> dict:
    """Return a copy of the full registry for inspection."""
    return _load()


def unregister(channel: str, persona: str = "the_creator") -> bool:
    """Remove a channel-owner mapping. Returns True if removed."""
    with _LOCK:
        data = _load()
        persona_map = data.get(persona, {})
        if channel not in persona_map:
            return False
        persona_map.pop(channel, None)
        _save(data)
        logger.info("owner_unregistered channel=%s persona=%s", channel, persona)
        return True
