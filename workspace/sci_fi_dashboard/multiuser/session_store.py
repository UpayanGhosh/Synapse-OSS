"""session_store.py — Atomic JSON session store with LRU cache and cross-process locking.

Locking layers (innermost → outermost):
    asyncio.Lock   (in-process serialisation per store path)
    filelock.FileLock (cross-process serialisation)
    tempfile.mkstemp + os.replace  (atomic write)

Module-level state
------------------
_STORE_LOCKS   : dict[str, asyncio.Lock]   — lazily created, cleaned up at pending=0
_STORE_PENDING : dict[str, int]            — pending op count per key
_CACHE         : OrderedDict               — max 200 entries, LRU eviction

Mirrors the pending-count cleanup pattern from
``gateway/session_actor.py:47-51``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import filelock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level concurrency state
# ---------------------------------------------------------------------------

_STORE_LOCKS: dict[str, asyncio.Lock] = {}
_STORE_PENDING: dict[str, int] = {}

# LRU cache: key → (SessionEntry, expiry_epoch_seconds)
_CACHE: OrderedDict[str, tuple[SessionEntry, float]] = OrderedDict()
_CACHE_MAX_SIZE: int = 200

# ---------------------------------------------------------------------------
# TTL resolution (env var is in milliseconds, default 45 000 ms = 45 s)
# ---------------------------------------------------------------------------


def _cache_ttl_seconds() -> float:
    return int(os.environ.get("SYNAPSE_SESSION_CACHE_TTL_MS", 45_000)) / 1000.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SessionEntry:
    """Mutable record stored per session key inside ``sessions.json``."""

    session_id: str
    updated_at: float
    session_file: str | None = None
    compaction_count: int = 0
    memory_flush_at: float | None = None
    memory_flush_compaction_count: int | None = None


def _entry_from_dict(d: dict) -> SessionEntry:
    return SessionEntry(
        session_id=d["session_id"],
        updated_at=d.get("updated_at", 0.0),
        session_file=d.get("session_file"),
        compaction_count=d.get("compaction_count", 0),
        memory_flush_at=d.get("memory_flush_at"),
        memory_flush_compaction_count=d.get("memory_flush_compaction_count"),
    )


# ---------------------------------------------------------------------------
# Cache helpers (must be called with GIL held — single-threaded asyncio)
# ---------------------------------------------------------------------------


def _cache_get(key: str) -> SessionEntry | None:
    """Return a cached entry if still within TTL, else ``None``."""
    item = _CACHE.get(key)
    if item is None:
        return None
    entry, expiry = item
    if time.monotonic() > expiry:
        _CACHE.pop(key, None)
        return None
    # Move to end (most-recently-used).
    _CACHE.move_to_end(key)
    return entry


def _cache_put(key: str, entry: SessionEntry) -> None:
    """Store *entry* in the LRU cache, evicting the oldest if at capacity."""
    expiry = time.monotonic() + _cache_ttl_seconds()
    _CACHE[key] = (entry, expiry)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX_SIZE:
        _CACHE.popitem(last=False)  # remove oldest (front)


def _cache_invalidate(key: str) -> None:
    _CACHE.pop(key, None)


# ---------------------------------------------------------------------------
# Disk helpers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _load_store_sync(path: Path) -> dict[str, dict]:
    """Read and deserialise the JSON store from *path*.  Returns ``{}`` if absent."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            logger.warning("SessionStore: corrupt JSON at %s — starting fresh", path)
            return {}


def _save_store_sync(path: Path, data: dict[str, dict]) -> None:
    """Atomic write: tempfile in same dir + os.replace.

    Replicates ``PairingStore._save()`` (security.py:181-206).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, separators=(",", ": "))
        os.replace(tmp_path, str(path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _merge_entry(existing: dict | None, patch: dict) -> dict:
    """Shallow-merge *patch* onto *existing*.

    - ``session_id`` is stable: taken from *existing* if present, else generated once.
    - ``updated_at`` is ``max(existing.updated_at, patch.updated_at, now)``.
    """
    now = time.time()
    base: dict = dict(existing) if existing else {}

    # Stable UUID — only generated for brand-new entries.
    if "session_id" not in base or not base["session_id"]:
        base["session_id"] = str(uuid.uuid4())

    # Shallow spread patch (overrides all keys except session_id stability above).
    base.update(patch)

    # Ensure session_id is not accidentally overwritten by a patch that carries one.
    # The rule: once set, session_id never changes.
    if existing and existing.get("session_id"):
        base["session_id"] = existing["session_id"]

    # updated_at = max(existing, patch, now)
    existing_ts = float((existing or {}).get("updated_at", 0))
    patch_ts = float(patch.get("updated_at", 0))
    base["updated_at"] = max(existing_ts, patch_ts, now)

    return base


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class SessionStore:
    """Per-agent atomic JSON store for session metadata.

    ``sessions.json`` lives at::

        <data_root>/state/agents/<agent_id>/sessions/sessions.json

    No I/O is performed in ``__init__`` — mirrors ``PairingStore`` (security.py:92-94).
    """

    def __init__(self, agent_id: str, data_root: Path | None = None) -> None:
        root = data_root or (Path.home() / ".synapse")
        self._path: Path = root / "state" / "agents" / agent_id / "sessions" / "sessions.json"
        self._lock_key: str = str(self._path)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def update(self, session_key: str, patch: dict) -> SessionEntry:
        """Atomically read-modify-write the entry for *session_key*.

        Locking order:
        1. ``asyncio.Lock`` (in-process, non-blocking to other coroutines).
        2. ``filelock.FileLock(timeout=30)`` (cross-process, inside to_thread).
        3. ``os.replace()`` (atomic rename).

        Pending-count cleanup mirrors ``session_actor.py:47-51``.
        """
        norm_key = session_key.lower()
        lock_key = self._lock_key

        # Lazily create asyncio lock for this store path.
        if lock_key not in _STORE_LOCKS:
            _STORE_LOCKS[lock_key] = asyncio.Lock()
        lock = _STORE_LOCKS[lock_key]
        _STORE_PENDING[lock_key] = _STORE_PENDING.get(lock_key, 0) + 1

        try:
            async with lock:
                entry = await asyncio.to_thread(
                    self._update_sync, norm_key, patch
                )
            _cache_invalidate(norm_key)
            _cache_put(norm_key, entry)
            return entry
        finally:
            _STORE_PENDING[lock_key] -= 1
            if _STORE_PENDING.get(lock_key, 0) <= 0:
                _STORE_PENDING.pop(lock_key, None)
                _STORE_LOCKS.pop(lock_key, None)

    def _update_sync(self, norm_key: str, patch: dict) -> SessionEntry:
        """Synchronous portion of update — runs inside asyncio.to_thread."""
        fl = filelock.FileLock(str(self._path) + ".lock", timeout=30)
        with fl:
            store = _load_store_sync(self._path)
            existing = store.get(norm_key)
            merged = _merge_entry(existing, patch)
            store[norm_key] = merged
            _save_store_sync(self._path, store)
        return _entry_from_dict(merged)

    async def get(self, session_key: str) -> SessionEntry | None:
        """Return the cached entry for *session_key*, refreshing from disk if stale.

        TTL is controlled by ``SYNAPSE_SESSION_CACHE_TTL_MS`` (milliseconds, default 45 000).
        """
        norm_key = session_key.lower()

        cached = _cache_get(norm_key)
        if cached is not None:
            return cached

        # Cache miss — read from disk.
        store = await asyncio.to_thread(_load_store_sync, self._path)
        raw = store.get(norm_key)
        if raw is None:
            return None
        entry = _entry_from_dict(raw)
        _cache_put(norm_key, entry)
        return entry

    async def load(self, store_path: Path | None = None) -> dict[str, SessionEntry]:
        """Load the full store from disk (bypasses per-key TTL cache).

        Used by callers that need the entire sessions map at once.
        """
        path = store_path or self._path
        raw_store = await asyncio.to_thread(_load_store_sync, path)
        return {k: _entry_from_dict(v) for k, v in raw_store.items()}
