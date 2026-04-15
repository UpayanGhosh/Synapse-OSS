"""Canonical channel identifiers and ordering."""

from __future__ import annotations

from typing import Literal

# Canonical ordering — determines display/iteration order
CHANNEL_ORDER: tuple[str, ...] = (
    "whatsapp",
    "telegram",
    "discord",
    "slack",
    "cli",
    "websocket",
    "voice",
)

ChannelId = Literal["whatsapp", "telegram", "discord", "slack", "cli", "websocket", "voice"]

# Alias -> canonical ID mapping
CHANNEL_ALIASES: dict[str, str] = {
    "wa": "whatsapp",
    "tg": "telegram",
    "dc": "discord",
    "ws": "websocket",
    "web": "websocket",
}


def resolve_channel_id(raw: str) -> str:
    """Resolve an alias or raw channel ID to its canonical form.

    Returns the input unchanged if not a known alias or ID.
    """
    lower = raw.lower().strip()
    return CHANNEL_ALIASES.get(lower, lower)


def is_valid_channel_id(raw: str) -> bool:
    """Check if a string is a known channel ID or alias."""
    resolved = resolve_channel_id(raw)
    return resolved in CHANNEL_ORDER
