"""
DM pairing, allowlist, and access-control primitives for channel adapters.

Provides:
  - DmPolicy enum (PAIRING, ALLOWLIST, OPEN, DISABLED)
  - ChannelSecurityConfig dataclass (per-channel policy + allow-from lists)
  - PairingStore — JSONL-backed approved-senders store with lazy async loading
  - resolve_dm_access() — pure function that returns "allow" / "deny" / "pending_approval"

Usage:
    from sci_fi_dashboard.channels.security import (
        DmPolicy, ChannelSecurityConfig, PairingStore, resolve_dm_access,
    )

    store = PairingStore("whatsapp", data_root=cfg.data_root)
    await store.load()  # explicit async I/O — never in __init__

    config = ChannelSecurityConfig(dm_policy=DmPolicy.ALLOWLIST, allow_from=["+1234"])
    result = resolve_dm_access(sender_id, config, store)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy enum
# ---------------------------------------------------------------------------


class DmPolicy(StrEnum):
    """Access-control policy for direct messages on a channel."""

    PAIRING = "pairing"
    ALLOWLIST = "allowlist"
    OPEN = "open"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Per-channel security configuration
# ---------------------------------------------------------------------------


@dataclass
class ChannelSecurityConfig:
    """Immutable-ish security knobs for a single channel adapter.

    Built in ``api_gateway.py`` from ``SynapseConfig.channels[channel_id]``
    and injected into the channel constructor.  Channels never read
    ``SynapseConfig`` themselves.
    """

    dm_policy: DmPolicy = DmPolicy.OPEN
    allow_from: list[str] = field(default_factory=list)
    group_policy: str = "open"
    group_allow_from: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# JSONL-backed pairing store
# ---------------------------------------------------------------------------


class PairingStore:
    """JSONL-backed approved-senders store per channel.

    **Lazy loading (Review Change #4):**  The constructor only stores the
    file path.  No file I/O happens until the explicit ``async load()``
    method is called (typically from ``lifespan()`` in ``api_gateway.py``).

    Each JSONL line is ``{"action": "approve"|"revoke", "sender_id": "..."}``.
    Corrupt lines are skipped with a warning (non-blocking recommendation E).

    File layout::

        ~/.synapse/state/pairing/<channel_id>.jsonl
    """

    def __init__(self, channel_id: str, data_root: Path | None = None) -> None:
        root = data_root or (Path.home() / ".synapse")
        self._path: Path = root / "state" / "pairing" / f"{channel_id}.jsonl"
        self._approved: set[str] = set()
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Async loading (called from lifespan, NOT from __init__)
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load approved senders from the JSONL file.

        Uses ``asyncio.to_thread`` for non-blocking file I/O.
        Skips corrupt lines with a warning instead of crashing.
        """
        self._approved = await asyncio.to_thread(self._load_sync)
        self._loaded = True

    def _load_sync(self) -> set[str]:
        """Synchronous file read, called via ``asyncio.to_thread``."""
        approved: set[str] = set()
        if not self._path.exists():
            return approved
        with open(self._path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "PairingStore: skipping corrupt line %d in %s",
                        lineno,
                        self._path,
                    )
                    continue
                sid = entry.get("sender_id")
                if not sid:
                    logger.warning(
                        "PairingStore: missing sender_id on line %d in %s",
                        lineno,
                        self._path,
                    )
                    continue
                action = entry.get("action")
                if action == "approve":
                    approved.add(sid)
                elif action == "revoke":
                    approved.discard(sid)
        return approved

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_approved(self, sender_id: str) -> bool:
        """Return True if *sender_id* is in the approved set."""
        return sender_id in self._approved

    def load_all(self) -> list[str]:
        """Return a snapshot of all currently approved sender IDs."""
        return sorted(self._approved)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def approve(self, sender_id: str) -> None:
        """Add *sender_id* to the approved set and persist via JSONL append."""
        self._approved.add(sender_id)
        self._append_line({"action": "approve", "sender_id": sender_id})

    def revoke(self, sender_id: str) -> None:
        """Remove *sender_id* from the approved set and rewrite the file atomically."""
        self._approved.discard(sender_id)
        self._save()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _append_line(self, entry: dict) -> None:
        """Append a single JSONL line (used by approve — append-friendly)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def _save(self) -> None:
        """Atomic rewrite: write to temp file then ``os.replace``.

        Used by ``revoke`` which needs to remove entries (not append-friendly).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for sid in sorted(self._approved):
                    f.write(
                        json.dumps(
                            {"action": "approve", "sender_id": sid},
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
            os.replace(tmp_path, str(self._path))
        except Exception:
            # Clean up temp file on failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise


# ---------------------------------------------------------------------------
# Access resolution
# ---------------------------------------------------------------------------


def resolve_dm_access(
    sender_id: str,
    security_config: ChannelSecurityConfig,
    pairing_store: PairingStore | None = None,
) -> Literal["allow", "deny", "pending_approval"]:
    """Decide whether a DM from *sender_id* should be allowed.

    Returns:
        ``"allow"``            — message passes through.
        ``"deny"``             — message is silently dropped.
        ``"pending_approval"`` — sender not yet approved (PAIRING mode).
    """
    policy = security_config.dm_policy

    if policy == DmPolicy.OPEN:
        return "allow"

    if policy == DmPolicy.DISABLED:
        return "deny"

    if policy == DmPolicy.ALLOWLIST:
        return "allow" if sender_id in security_config.allow_from else "deny"

    if policy == DmPolicy.PAIRING:
        # Explicitly allowed senders always pass
        if sender_id in security_config.allow_from:
            return "allow"
        # Check the pairing store
        if pairing_store is not None and pairing_store.is_approved(sender_id):
            return "allow"
        return "pending_approval"

    # Unreachable for valid enum values, but defensive
    return "deny"
