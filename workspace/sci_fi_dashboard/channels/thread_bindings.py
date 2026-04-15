"""Thread binding manager — tracks active thread conversations."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class ThreadBinding:
    thread_id: str
    channel_id: str
    chat_id: str
    session_key: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class ThreadBindingManager:
    """File-persisted thread binding store with idle/max-age expiry."""

    def __init__(
        self,
        store_path: Path,
        idle_timeout: float = 3600.0,  # 1 hour idle expiry
        max_age: float = 86400.0,  # 24 hour max age
        max_bindings: int = 1000,
    ):
        self._store_path = Path(store_path)
        self._idle_timeout = idle_timeout
        self._max_age = max_age
        self._max_bindings = max_bindings

    @staticmethod
    def _key(channel_id: str, thread_id: str) -> str:
        return f"{channel_id}:{thread_id}"

    def bind(
        self,
        thread_id: str,
        channel_id: str,
        chat_id: str,
        session_key: str,
    ) -> ThreadBinding:
        """Create or update a thread binding."""
        data = self._load()
        key = self._key(channel_id, thread_id)
        now = time.time()

        existing = data.get(key)
        if existing:
            binding = ThreadBinding(**existing)
            binding.last_activity = now
            binding.chat_id = chat_id
            binding.session_key = session_key
        else:
            binding = ThreadBinding(
                thread_id=thread_id,
                channel_id=channel_id,
                chat_id=chat_id,
                session_key=session_key,
                created_at=now,
                last_activity=now,
            )

        # Enforce max_bindings — evict oldest by last_activity if at capacity
        if key not in data and len(data) >= self._max_bindings:
            oldest_key = min(data, key=lambda k: data[k].get("last_activity", 0))
            del data[oldest_key]
            log.debug("Evicted oldest binding %s to stay under max_bindings", oldest_key)

        data[key] = asdict(binding)
        self._save(data)
        return binding

    def lookup(self, thread_id: str, channel_id: str) -> ThreadBinding | None:
        """Find binding, updating last_activity. Returns None if expired."""
        data = self._load()
        key = self._key(channel_id, thread_id)
        entry = data.get(key)
        if entry is None:
            return None

        now = time.time()
        created_at = entry.get("created_at", 0)
        last_activity = entry.get("last_activity", 0)

        # Check expiry: idle timeout or max age
        if (now - last_activity) > self._idle_timeout:
            del data[key]
            self._save(data)
            log.debug("Binding %s expired (idle timeout)", key)
            return None
        if (now - created_at) > self._max_age:
            del data[key]
            self._save(data)
            log.debug("Binding %s expired (max age)", key)
            return None

        # Touch last_activity
        entry["last_activity"] = now
        data[key] = entry
        self._save(data)
        return ThreadBinding(**entry)

    def unbind(self, thread_id: str, channel_id: str) -> bool:
        """Remove a binding. Returns True if it existed."""
        data = self._load()
        key = self._key(channel_id, thread_id)
        if key not in data:
            return False
        del data[key]
        self._save(data)
        return True

    def sweep(self) -> int:
        """Remove expired bindings. Returns count removed."""
        data = self._load()
        now = time.time()
        to_remove: list[str] = []

        for key, entry in data.items():
            created_at = entry.get("created_at", 0)
            last_activity = entry.get("last_activity", 0)
            if (now - last_activity) > self._idle_timeout or (now - created_at) > self._max_age:
                to_remove.append(key)

        for key in to_remove:
            del data[key]

        if to_remove:
            self._save(data)
            log.info("Swept %d expired thread bindings", len(to_remove))

        return len(to_remove)

    def _load(self) -> dict:
        """Load from JSON file."""
        if not self._store_path.exists():
            return {}
        try:
            text = self._store_path.read_text(encoding="utf-8")
            return json.loads(text) if text.strip() else {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load thread bindings from %s: %s", self._store_path, exc)
            return {}

    def _save(self, data: dict) -> None:
        """Atomic save to JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp file in same directory, then atomic replace
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._store_path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, str(self._store_path))
        except OSError:
            # Clean up temp file on failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    async def sweep_loop(self, interval: float = 300.0) -> None:
        """Background coroutine that sweeps expired bindings periodically."""
        while True:
            await asyncio.sleep(interval)
            try:
                self.sweep()
            except Exception:
                log.exception("Error during thread binding sweep")
