"""
synapse_config.py — Single source of truth for all paths and credentials in Synapse-OSS.

All Python files use ~/.synapse/ via SynapseConfig — zero legacy path references remain.
This module establishes the path contract that every downstream component depends on.

Usage:
    from synapse_config import SynapseConfig, write_config

    config = SynapseConfig.load()
    print(config.data_root)   # e.g. /home/user/.synapse
    print(config.db_dir)      # e.g. /home/user/.synapse/workspace/db
"""

import contextlib
import json
import os
import stat
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Module-level default only — never evaluated at import time except as a constant.
_DEFAULT_SYNAPSE_HOME = Path.home() / ".synapse"


@dataclass(frozen=True)
class SynapseConfig:
    """Immutable configuration snapshot for a single Synapse-OSS process.

    All derived paths (db_dir, sbs_dir, log_dir) are computed from data_root and
    cannot be overridden via synapse.json — only data_root drives the path tree.

    providers and channels come from synapse.json (Layer 2) and can be empty dicts
    (Layer 3 default) when the file is absent.

    gateway holds WebSocket control-plane config (port, host, token).
    """

    data_root: Path
    db_dir: Path
    sbs_dir: Path
    log_dir: Path
    providers: dict = field(default_factory=dict)
    channels: dict = field(default_factory=dict)
    model_mappings: dict = field(default_factory=dict)
    gateway: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    mcp: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "SynapseConfig":
        """Build a SynapseConfig using three-layer precedence:

        Layer 1 (highest priority): SYNAPSE_HOME env var → data_root
        Layer 2: synapse.json in data_root → providers, channels, model_mappings
        Layer 3 (defaults): empty dicts for providers/channels/model_mappings

        Returns a frozen dataclass.  Calling load() twice with different env vars
        returns different configs — this method is NOT cached.
        """
        # Layer 1: resolve data_root
        data_root = resolve_data_root()

        # Derived paths (always computed from data_root, not from file)
        db_dir = data_root / "workspace" / "db"
        sbs_dir = data_root / "workspace" / "sci_fi_dashboard" / "synapse_data"
        log_dir = data_root / "logs"

        # Layer 2 / Layer 3: read synapse.json if present; else defaults
        providers: dict[str, Any] = {}
        channels: dict[str, Any] = {}
        model_mappings: dict[str, Any] = {}
        gateway: dict[str, Any] = {}
        session: dict[str, Any] = {}
        mcp: dict[str, Any] = {}

        config_file = data_root / "synapse.json"
        if config_file.exists():
            _verify_permissions(config_file)
            with open(config_file, encoding="utf-8-sig") as fh:
                raw = json.load(fh)
            providers = raw.get("providers", {})
            channels = raw.get("channels", {})
            model_mappings = raw.get("model_mappings", {})
            gateway = raw.get("gateway", {})
            session = raw.get("session", {})
            mcp = raw.get("mcp", {})

        return cls(
            data_root=data_root,
            db_dir=db_dir,
            sbs_dir=sbs_dir,
            log_dir=log_dir,
            providers=providers,
            channels=channels,
            model_mappings=model_mappings,
            gateway=gateway,
            session=session,
            mcp=mcp,
        )


def resolve_data_root() -> Path:
    """Return the data root path, honoring SYNAPSE_HOME env var.

    If SYNAPSE_HOME is set:
      - Expand user (~) and resolve symlinks.
      - Attempt to create the directory (parents=True).
      - Raise RuntimeError if the directory cannot be created (PermissionError).

    If SYNAPSE_HOME is not set (or blank):
      - Return Path.home() / ".synapse"

    The returned path is NOT guaranteed to exist — callers that need the directory
    to exist must create it themselves.
    """
    raw = os.environ.get("SYNAPSE_HOME", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise RuntimeError(
                f"SYNAPSE_HOME={raw} cannot be created: {e}\n"
                "Fix the path or unset SYNAPSE_HOME to use the default (~/.synapse/)"
            ) from e
        return p
    return Path.home() / ".synapse"


def _verify_permissions(path: Path) -> None:
    """Warn if the given path is readable by group or other.

    This is a best-effort advisory — not a security enforcement.  On Windows,
    stat mode bits don't map to Unix semantics so we skip the check entirely.
    """
    if sys.platform == "win32":
        return
    mode = path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        warnings.warn(
            f"{path} is readable by group/other (mode {oct(mode)}). " f"Run: chmod 600 {path}",
            stacklevel=3,
        )


def write_config(data_root: Path, config: dict) -> None:
    """Atomically write config dict to <data_root>/synapse.json with mode 600.

    Steps:
      1. Ensure data_root exists.
      2. Serialise config to a temp file (*.json.tmp) opened with O_CREAT mode 0o600.
      3. os.replace() the temp file over the target — atomic on POSIX.
      4. Re-enforce mode 600 after replace to guard against umask drift.

    On any write error the temp file is cleaned up before re-raising.
    """
    config_file = data_root / "synapse.json"
    data_root.mkdir(parents=True, exist_ok=True)

    tmp = config_file.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp))
        raise

    os.replace(str(tmp), str(config_file))
    os.chmod(str(config_file), 0o600)  # re-enforce after replace (umask drift)


def gateway_token(config: SynapseConfig) -> str | None:
    """Return the WebSocket gateway auth token from config, or None if unset."""
    val = config.gateway.get("token", "")
    return val if val else None


def dm_scope(config: SynapseConfig) -> str:
    """Return the active DM scope from ``config.session``.

    One of ``"main"``, ``"per-peer"``, ``"per-channel-peer"``,
    ``"per-account-channel-peer"``.  Defaults to ``"main"`` (zero-config safe).
    """
    return config.session.get("dmScope", "main")


def identity_links(config: SynapseConfig) -> dict:
    """Return the identity-links map from ``config.session``.

    Shape: ``dict[canonical_name, list[str]]`` where each value is a list of
    platform IDs that resolve to the canonical name.  Returns ``{}`` if absent.
    """
    return config.session.get("identityLinks", {})
