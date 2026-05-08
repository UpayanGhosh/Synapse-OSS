"""Unified token storage for the Integrations Hub.

All integrations write to ``~/.synapse/integrations/<name>/token.json``.
Legacy locations (e.g. ``~/.synapse/google/calendar_token.json``) are still
read so existing installs keep working — the manager copies the legacy
token to the new location on first connect.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from .errors import IntegrationError
from .registry import IntegrationDefinition


def data_root(custom_root: Path | None = None) -> Path:
    if custom_root is not None:
        return Path(custom_root).expanduser()
    return Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse")).expanduser()


def integration_dir(integration: IntegrationDefinition, custom_root: Path | None = None) -> Path:
    return data_root(custom_root) / "integrations" / integration.token_dirname()


def token_path(integration: IntegrationDefinition, custom_root: Path | None = None) -> Path:
    return integration_dir(integration, custom_root) / "token.json"


def legacy_token_paths(
    integration: IntegrationDefinition,
    custom_root: Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    for raw in integration.legacy_token_paths:
        if "~" in raw or raw.startswith("/") or raw.startswith("\\"):
            paths.append(Path(raw).expanduser())
        else:
            paths.append(data_root(custom_root) / raw)
    return paths


def find_existing_token(
    integration: IntegrationDefinition,
    custom_root: Path | None = None,
) -> Path | None:
    """Return the first existing token file (preferred location first)."""
    candidates: list[Path] = [token_path(integration, custom_root)]
    candidates.extend(legacy_token_paths(integration, custom_root))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def save_token_json(
    integration: IntegrationDefinition,
    payload: str | bytes,
    *,
    custom_root: Path | None = None,
) -> Path:
    """Write a token payload atomically and chmod 600 where supported."""
    path = token_path(integration, custom_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    if isinstance(payload, bytes):
        tmp.write_bytes(payload)
    else:
        tmp.write_text(str(payload), encoding="utf-8")
    os.replace(tmp, path)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return path


def save_credentials(
    integration: IntegrationDefinition,
    credentials: Any,
    *,
    custom_root: Path | None = None,
) -> Path:
    """Persist a google-auth ``Credentials`` instance."""
    if hasattr(credentials, "to_json"):
        return save_token_json(integration, credentials.to_json(), custom_root=custom_root)
    raise IntegrationError(
        f"{integration.name}: credentials object has no to_json() method; "
        "cannot persist token."
    )


def read_token_json(
    integration: IntegrationDefinition,
    *,
    custom_root: Path | None = None,
) -> dict[str, Any] | None:
    """Best-effort read of the persisted token JSON. None when absent or invalid."""
    found = find_existing_token(integration, custom_root)
    if found is None:
        return None
    try:
        return json.loads(found.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def delete_token(
    integration: IntegrationDefinition,
    *,
    custom_root: Path | None = None,
) -> bool:
    """Remove every known token location (new + legacy). Return True if any deleted."""
    removed = False
    for candidate in [token_path(integration, custom_root), *legacy_token_paths(integration, custom_root)]:
        try:
            if candidate.exists():
                candidate.unlink()
                removed = True
        except OSError:
            continue
    return removed
