"""session_store.py — Atomic JSON session store with LRU cache and cross-process locking.

Locking layers (innermost → outermost):
    asyncio.Lock   (in-process serialisation per store path)
    SynapseFileLock (cross-process serialisation with stale-lock reclaim)
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
import atexit
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
# Optional psutil for PID-recycling detection
# ---------------------------------------------------------------------------

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False

# ---------------------------------------------------------------------------
# Module-level concurrency state
# ---------------------------------------------------------------------------

_STORE_LOCKS: dict[str, asyncio.Lock] = {}
_STORE_PENDING: dict[str, int] = {}

# LRU cache: key → (SessionEntry, expiry_epoch_seconds)
_CACHE: OrderedDict[str, tuple[SessionEntry, float]] = OrderedDict()
_CACHE_MAX_SIZE: int = 200

# Track all SynapseFileLock instances for atexit cleanup.
_ACTIVE_LOCKS: list[SynapseFileLock] = []

# ---------------------------------------------------------------------------
# SynapseFileLock — stale-lock reclaim + watchdog
# ---------------------------------------------------------------------------


@dataclass
class LockMetadata:
    """Metadata written alongside the lock file for stale-lock detection."""

    pid: int
    created_at: float  # time.monotonic() at acquisition
    starttime: float  # process start time for PID-recycling detection


class SynapseFileLock:
    """Cross-process file lock with stale-lock reclaim.

    Wraps ``filelock.FileLock`` and adds:
    - PID-alive check via ``os.kill(pid, 0)``
    - PID-recycling check via ``psutil.Process(pid).create_time()`` (optional)
    - Age check: locks held longer than ``MAX_LOCK_AGE_S`` are reclaimed
    - Metadata sidecar file (``.lock.meta``) for diagnostics
    - atexit handler to release lock + delete metadata on interpreter exit
    """

    MAX_LOCK_AGE_S: float = 1800  # 30 minutes
    WATCHDOG_INTERVAL_S: float = 60
    _WATCHDOG_FORCE_RELEASE_S: float = 300  # 5 minutes for watchdog

    def __init__(self, lock_path: Path, timeout: float = 30.0) -> None:
        self._lock_path = Path(lock_path)
        self._meta_path = Path(f"{lock_path}.meta")
        self._timeout = timeout
        self._fl = filelock.FileLock(str(lock_path), timeout=timeout)
        self._acquired = False
        _ACTIVE_LOCKS.append(self)

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> SynapseFileLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """Acquire the file lock, reclaiming stale locks on contention."""
        try:
            self._fl.acquire(timeout=0)
        except filelock.Timeout:
            # Contention — check if the current holder is dead or stale.
            if self._is_stale():
                logger.info(
                    "SynapseFileLock: reclaiming stale lock at %s", self._lock_path
                )
                self._force_release()
                self._fl.acquire(timeout=self._timeout)
            else:
                # Not stale — wait with the configured timeout.
                self._fl.acquire(timeout=self._timeout)

        self._acquired = True
        self._write_metadata()

    def release(self) -> None:
        """Release the lock and clean up metadata."""
        if self._acquired:
            self._acquired = False
            with contextlib.suppress(OSError):
                if self._meta_path.exists():
                    self._meta_path.unlink()
            self._fl.release()

    # ------------------------------------------------------------------
    # Stale detection
    # ------------------------------------------------------------------

    def _is_stale(self) -> bool:
        """Return ``True`` if the lock holder is dead, recycled, or too old."""
        meta = self._read_metadata()
        if meta is None:
            # No metadata — treat age-based: if lock file is old, consider stale.
            try:
                stat = self._lock_path.stat()
                age = time.time() - stat.st_mtime
                return age > self.MAX_LOCK_AGE_S
            except OSError:
                return False

        # 1. PID alive check.
        if not _is_pid_alive(meta.pid):
            return True

        # 2. PID recycling check (psutil only).
        if _HAS_PSUTIL:
            try:
                proc = psutil.Process(meta.pid)
                if abs(proc.create_time() - meta.starttime) > 2.0:
                    # PID was recycled — different process now owns this PID.
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return True

        # 3. Age check.
        # created_at is monotonic, so compare against file mtime for cross-process.
        try:
            stat = self._lock_path.stat()
            age = time.time() - stat.st_mtime
            return age > self.MAX_LOCK_AGE_S
        except OSError:
            return False

    def _force_release(self) -> None:
        """Forcibly remove the lock file and metadata."""
        with contextlib.suppress(OSError):
            if self._meta_path.exists():
                self._meta_path.unlink()
        with contextlib.suppress(OSError):
            if self._lock_path.exists():
                self._lock_path.unlink()
        # Re-create the underlying FileLock object so it can acquire fresh.
        self._fl = filelock.FileLock(str(self._lock_path), timeout=self._timeout)

    # ------------------------------------------------------------------
    # Metadata I/O
    # ------------------------------------------------------------------

    def _write_metadata(self) -> None:
        """Write lock metadata to the sidecar file."""
        pid = os.getpid()
        starttime = _get_process_starttime(pid)
        meta = {
            "pid": pid,
            "created_at": time.monotonic(),
            "starttime": starttime,
        }
        try:
            with open(self._meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
        except OSError:
            logger.debug("SynapseFileLock: failed to write metadata at %s", self._meta_path)

    def _read_metadata(self) -> LockMetadata | None:
        """Read lock metadata from the sidecar file, or ``None`` if unavailable."""
        try:
            with open(self._meta_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return LockMetadata(
                pid=int(data["pid"]),
                created_at=float(data["created_at"]),
                starttime=float(data["starttime"]),
            )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None


def _is_pid_alive(pid: int) -> bool:
    """Check whether process *pid* is still running.

    Uses ``os.kill(pid, 0)`` which works on both Unix and Windows.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_process_starttime(pid: int) -> float:
    """Return the start time of process *pid*.

    Uses psutil if available; otherwise returns ``time.time()`` as a
    best-effort fallback.
    """
    if _HAS_PSUTIL:
        try:
            return psutil.Process(pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return time.time()


def clean_stale_lock_files(sessions_dir: Path) -> int:
    """Scan *sessions_dir* for stale ``.lock`` files and remove them.

    Intended for startup cleanup.  Returns the number of stale locks removed.
    """
    removed = 0
    if not sessions_dir.exists():
        return removed
    for lock_file in sessions_dir.glob("*.lock"):
        meta_file = Path(f"{lock_file}.meta")
        meta = None
        try:
            if meta_file.exists():
                with open(meta_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                meta = LockMetadata(
                    pid=int(data["pid"]),
                    created_at=float(data["created_at"]),
                    starttime=float(data["starttime"]),
                )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            pass

        is_stale = False
        if meta is not None:
            if not _is_pid_alive(meta.pid):
                is_stale = True
            elif _HAS_PSUTIL:
                try:
                    proc = psutil.Process(meta.pid)
                    if abs(proc.create_time() - meta.starttime) > 2.0:
                        is_stale = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    is_stale = True
        else:
            # No metadata — check age via mtime.
            try:
                age = time.time() - lock_file.stat().st_mtime
                if age > SynapseFileLock.MAX_LOCK_AGE_S:
                    is_stale = True
            except OSError:
                continue

        if is_stale:
            with contextlib.suppress(OSError):
                lock_file.unlink()
            with contextlib.suppress(OSError):
                meta_file.unlink()
            removed += 1
            logger.info("clean_stale_lock_files: removed stale lock %s", lock_file)

    return removed


async def _watchdog_loop(sessions_dir: Path) -> None:
    """Background watchdog that force-releases locks held > 300s.

    Runs every ``SynapseFileLock.WATCHDOG_INTERVAL_S`` seconds.  Designed
    to be launched as an ``asyncio.Task`` at startup.
    """
    while True:
        await asyncio.sleep(SynapseFileLock.WATCHDOG_INTERVAL_S)
        try:
            if not sessions_dir.exists():
                continue
            for lock_file in sessions_dir.glob("*.lock"):
                meta_file = Path(f"{lock_file}.meta")
                try:
                    if not meta_file.exists():
                        continue
                    with open(meta_file, encoding="utf-8") as fh:
                        data = json.load(fh)
                    # Use file mtime for age since monotonic is per-process.
                    age = time.time() - lock_file.stat().st_mtime
                    if age > SynapseFileLock._WATCHDOG_FORCE_RELEASE_S:
                        logger.warning(
                            "watchdog: force-releasing lock held for %.0fs: %s",
                            age,
                            lock_file,
                        )
                        with contextlib.suppress(OSError):
                            lock_file.unlink()
                        with contextlib.suppress(OSError):
                            meta_file.unlink()
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            logger.debug("watchdog: scan error", exc_info=True)


def _atexit_release_all() -> None:
    """Release all SynapseFileLock instances on interpreter exit."""
    for lock in _ACTIVE_LOCKS:
        try:
            lock.release()
        except Exception:
            pass
    _ACTIVE_LOCKS.clear()


atexit.register(_atexit_release_all)


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
        fl = SynapseFileLock(Path(str(self._path) + ".lock"), timeout=30)
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

    async def delete(self, session_key: str) -> None:
        """Remove session_key from the store, evicting cache and on-disk entry.

        Use before update() when you need to rotate the session_id (e.g. /new command,
        POST /reset). _merge_entry() keeps session_id stable once set, so delete() is
        the only way to force a fresh UUID on the next update() call.
        """
        norm_key = session_key.lower()
        lock_key = self._lock_key

        if lock_key not in _STORE_LOCKS:
            _STORE_LOCKS[lock_key] = asyncio.Lock()
        lock = _STORE_LOCKS[lock_key]

        async with lock:
            await asyncio.to_thread(self._delete_sync, norm_key)

        _cache_invalidate(norm_key)

    def _delete_sync(self, norm_key: str) -> None:
        """Synchronous portion of delete — runs inside asyncio.to_thread."""
        fl = SynapseFileLock(Path(str(self._path) + ".lock"), timeout=30)
        with fl:
            store = _load_store_sync(self._path)
            store.pop(norm_key, None)  # no-op if key doesn't exist
            _save_store_sync(self._path, store)
