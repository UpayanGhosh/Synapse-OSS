"""CLI helpers for the Integrations Hub.

Thin wrappers around ``sci_fi_dashboard.integrations.manager`` that format
results for Typer/Rich output. The module itself prints nothing — the
Typer command handlers in ``synapse_cli.py`` decide how to render each
``ConnectionResult``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sci_fi_dashboard.integrations import (
    ConnectionResult,
    IntegrationError,
    connect as _connect,
    disconnect as _disconnect,
    list_integrations as _list,
    list_definitions,
    status as _status,
    verify as _verify,
)


def connect_integration(
    name: str,
    *,
    override_client_path: str | Path | None = None,
    open_browser: bool = True,
    data_root: Path | None = None,
) -> ConnectionResult:
    return _connect(
        name,
        override_client_path=override_client_path,
        open_browser=open_browser,
        data_root=data_root,
    )


def verify_integration(
    name: str,
    *,
    data_root: Path | None = None,
) -> ConnectionResult:
    return _verify(name, data_root=data_root)


def integration_status(
    name: str,
    *,
    data_root: Path | None = None,
) -> ConnectionResult:
    return _status(name, data_root=data_root)


def disconnect_integration(
    name: str,
    *,
    data_root: Path | None = None,
) -> bool:
    return _disconnect(name, data_root=data_root)


def list_all(
    *,
    data_root: Path | None = None,
    include_unavailable: bool = True,
) -> list[ConnectionResult]:
    return _list(data_root=data_root, include_unavailable=include_unavailable)


def integration_summary(name: str) -> dict[str, Any]:
    """Return registry metadata for help text rendering."""
    for definition in list_definitions(include_unavailable=True):
        if definition.name == name:
            return {
                "name": definition.name,
                "display_name": definition.display_name,
                "auth_type": definition.auth_type,
                "scopes": list(definition.scopes),
                "available": definition.available,
                "description": definition.description,
                "setup_notes": definition.setup_notes,
            }
    raise IntegrationError(f"Unknown integration '{name}'.")


__all__ = [
    "connect_integration",
    "disconnect_integration",
    "integration_status",
    "integration_summary",
    "list_all",
    "verify_integration",
]
