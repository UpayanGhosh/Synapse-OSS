"""
config/migration.py — Legacy config migration helpers.

Each migration function is idempotent — running it on already-migrated data
is a no-op.  Migrations are applied in order during config load.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _migrate_routing_to_channels(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy ``routing`` top-level key into ``channels``.

    Old format::

        {"routing": {"whatsapp": {"enabled": true}, "telegram": {"enabled": false}}}

    New format::

        {"channels": {"whatsapp": {"enabled": true}, "telegram": {"enabled": false}}}

    If ``channels`` already exists, routing entries are merged (channels wins
    on conflict).
    """
    routing = raw.get("routing")
    if not isinstance(routing, dict):
        return raw

    result = dict(raw)
    existing_channels = result.get("channels", {})
    if not isinstance(existing_channels, dict):
        existing_channels = {}

    # Merge routing into channels — existing channels entries take precedence
    merged: dict[str, Any] = {}
    merged.update(routing)
    merged.update(existing_channels)

    result["channels"] = merged
    result.pop("routing", None)
    return result


def _migrate_dm_policy_to_session(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy ``dm_policy`` / ``dmPolicy`` top-level key into ``session.dmScope``.

    Old format::

        {"dm_policy": "per-peer"}
        # or
        {"dmPolicy": "per-peer"}

    New format::

        {"session": {"dmScope": "per-peer"}}
    """
    # Check both naming conventions
    dm_val = raw.get("dm_policy") or raw.get("dmPolicy")
    if dm_val is None:
        return raw

    result = dict(raw)
    session = dict(result.get("session", {})) if isinstance(result.get("session"), dict) else {}

    # Only set if not already present in session
    if "dmScope" not in session:
        session["dmScope"] = dm_val

    result["session"] = session
    result.pop("dm_policy", None)
    result.pop("dmPolicy", None)
    return result


def _migrate_bare_model_to_agent_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize bare model strings in ``model_mappings`` to full AgentModelConfig dicts.

    Old format::

        {"model_mappings": {"casual": "gemini/gemini-2.0-flash"}}

    New format::

        {"model_mappings": {"casual": {"model": "gemini/gemini-2.0-flash"}}}

    This mirrors the ``@model_validator`` in ``SynapseConfigSchema`` but
    operates on raw dicts before Pydantic validation, ensuring both legacy
    JSON files and the Pydantic path produce the same normalized structure.
    """
    mappings = raw.get("model_mappings")
    if not isinstance(mappings, dict):
        return raw

    result = dict(raw)
    normalized: dict[str, Any] = {}
    for role, value in mappings.items():
        if isinstance(value, str):
            normalized[role] = {"model": value}
        else:
            normalized[role] = value
    result["model_mappings"] = normalized
    return result


# Ordered list of (name, migration_fn) — applied sequentially.
MIGRATIONS: list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = [
    ("routing_to_channels", _migrate_routing_to_channels),
    ("dm_policy_alias", _migrate_dm_policy_to_session),
    ("bare_model_string", _migrate_bare_model_to_agent_config),
]


def migrate_legacy_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply all legacy migrations in order.

    Each migration is idempotent — safe to run on already-migrated configs.

    Parameters
    ----------
    raw : dict
        The raw config dict loaded from JSON (before Pydantic validation).

    Returns
    -------
    dict
        The migrated config dict.
    """
    result = raw
    for name, fn in MIGRATIONS:
        try:
            result = fn(result)
        except Exception:
            logger.exception("Migration '%s' failed — skipping", name)
    return result
