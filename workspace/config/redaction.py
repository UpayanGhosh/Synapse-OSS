"""
config/redaction.py — Redact and restore sensitive fields in config snapshots.

Sensitive fields are replaced with ``{"type": "secret-ref", "ref": "path.to.field"}``
so that config snapshots can be safely logged or displayed.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {"api_key", "token", "secret", "password", "access_token", "refresh_token"}
)


def redact_snapshot(config_dict: dict[str, Any], path: str = "") -> dict[str, Any]:
    """Return a deep copy of *config_dict* with sensitive values replaced.

    Parameters
    ----------
    config_dict : dict
        The configuration dict to redact.
    path : str
        Dot-delimited path prefix (used for recursive descent).

    Returns
    -------
    dict
        A new dict with sensitive values replaced by secret-ref markers.
    """
    result: dict[str, Any] = {}
    for key, value in config_dict.items():
        current_path = f"{path}.{key}" if path else key

        if key in SENSITIVE_FIELDS and value is not None:
            # Replace with a secret-ref marker
            result[key] = {"type": "secret-ref", "ref": current_path}
        elif isinstance(value, dict):
            result[key] = redact_snapshot(value, current_path)
        else:
            result[key] = value
    return result


def restore_snapshot(redacted: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Restore redacted fields by pulling values from *live* config.

    Parameters
    ----------
    redacted : dict
        A previously-redacted config dict.
    live : dict
        The actual (unredacted) config dict to pull real values from.

    Returns
    -------
    dict
        A new dict with secret-ref markers replaced by real values from *live*.
    """
    result: dict[str, Any] = {}
    for key, value in redacted.items():
        if isinstance(value, dict) and value.get("type") == "secret-ref" and "ref" in value:
            # Restore from live config
            result[key] = live.get(key, value)
        elif isinstance(value, dict):
            live_sub = live.get(key) if isinstance(live.get(key), dict) else {}
            result[key] = restore_snapshot(value, live_sub)
        else:
            result[key] = value
    return result
