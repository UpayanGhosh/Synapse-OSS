"""Read/write the ``integrations`` section of ``synapse.json``.

Also keeps the legacy ``mcp.builtin_servers.<name>`` keys populated so
existing MCP servers (Calendar, Gmail) keep loading their tokens without
being aware of the hub.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from synapse_config import write_config

from .errors import IntegrationError
from .registry import IntegrationDefinition


def load_raw_config(data_root: Path) -> dict[str, Any]:
    path = data_root / "synapse.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"Could not read synapse.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntegrationError("synapse.json must be a JSON object")
    return payload


def integrations_section(config: dict[str, Any]) -> dict[str, Any]:
    section = config.setdefault("integrations", {})
    if not isinstance(section, dict):
        raise IntegrationError("synapse.json integrations section must be a JSON object")
    return section


def integration_entry(
    config: dict[str, Any],
    integration: IntegrationDefinition,
) -> dict[str, Any]:
    section = integrations_section(config)
    entry = section.setdefault(integration.name, {})
    if not isinstance(entry, dict):
        raise IntegrationError(
            f"synapse.json integrations.{integration.name} must be a JSON object"
        )
    return entry


def mark_connected(
    *,
    data_root: Path,
    integration: IntegrationDefinition,
    token_path: Path,
    account_email: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist the connection state to synapse.json (hub + legacy keys)."""
    config = load_raw_config(data_root)

    entry = integration_entry(config, integration)
    entry.update(
        {
            "enabled": True,
            "token_path": str(token_path),
            "auth_type": integration.auth_type,
            "scopes": list(integration.scopes),
            "account_email": account_email,
            "connected_at": datetime.now(UTC).isoformat(),
        }
    )
    if extra:
        entry.update(extra)

    _populate_legacy_keys(config, integration, token_path)

    write_config(data_root, config)


def mark_disconnected(
    *,
    data_root: Path,
    integration: IntegrationDefinition,
) -> None:
    """Disable the integration in synapse.json without losing prior metadata."""
    config = load_raw_config(data_root)
    entry = integration_entry(config, integration)
    entry["enabled"] = False
    entry["disconnected_at"] = datetime.now(UTC).isoformat()
    _disable_legacy_keys(config, integration)
    write_config(data_root, config)


def get_entry(
    *,
    data_root: Path,
    integration: IntegrationDefinition,
) -> dict[str, Any]:
    config = load_raw_config(data_root)
    entry = (config.get("integrations") or {}).get(integration.name)
    return entry if isinstance(entry, dict) else {}


# ---------------------------------------------------------------------------
# Legacy synapse.json paths (backwards compat for existing MCP servers)
# ---------------------------------------------------------------------------


def _populate_legacy_keys(
    config: dict[str, Any],
    integration: IntegrationDefinition,
    token_path: Path,
) -> None:
    """Mirror token_path into legacy mcp.builtin_servers.<name>.token_path keys."""
    for dotted in integration.legacy_synapse_json_keys:
        _set_dotted(config, dotted, _legacy_value(dotted, token_path))


def _disable_legacy_keys(
    config: dict[str, Any],
    integration: IntegrationDefinition,
) -> None:
    for dotted in integration.legacy_synapse_json_keys:
        if dotted.endswith(".enabled"):
            _set_dotted(config, dotted, False)


def _legacy_value(dotted_key: str, token_path: Path) -> Any:
    if dotted_key.endswith(".enabled"):
        return True
    if dotted_key.endswith(".token_path"):
        return str(token_path)
    if dotted_key.endswith(".credentials_path"):
        return ""
    return ""


def _set_dotted(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cursor: Any = config
    for part in parts[:-1]:
        next_node = cursor.get(part)
        if not isinstance(next_node, dict):
            next_node = {}
            cursor[part] = next_node
        cursor = next_node
    cursor[parts[-1]] = value
