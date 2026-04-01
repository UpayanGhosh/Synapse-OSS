"""
media/delivery_queue.py — Persistent retry queue for outbound channel delivery.

Storage layout::

    ~/.synapse/state/delivery-queue/
        <id>.json          ← pending deliveries
        failed/
            <id>.json      ← permanently failed (≥ 3 attempts)

No background retry loop is included here — that is Phase 5.
This module is storage-only.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE_ROOT = Path.home() / ".synapse" / "state" / "delivery-queue"
_MAX_ATTEMPTS = 3


@dataclass
class QueuedDelivery:
    """A single outbound delivery job."""

    channel_id: str
    to: str
    payloads: list[dict]                             # ReplyPayload dicts
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    last_error: str = ""
    failed: bool = False


class DeliveryQueue:
    """Persistent file-backed queue for outbound delivery with retry tracking."""

    def __init__(self, queue_root: Path | None = None) -> None:
        self._root = queue_root or _DEFAULT_QUEUE_ROOT
        self._failed_dir = self._root / "failed"
        self._root.mkdir(parents=True, exist_ok=True)
        self._failed_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path(self, delivery_id: str, *, failed: bool = False) -> Path:
        base = self._failed_dir if failed else self._root
        return base / f"{delivery_id}.json"

    def _write(self, delivery: QueuedDelivery, *, failed: bool = False) -> None:
        """Atomic write (tmp + replace) to prevent corrupt state on crash."""
        path = self._path(delivery.id, failed=failed)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(delivery), indent=2), encoding="utf-8")
        tmp.replace(path)

    def _load(self, path: Path) -> QueuedDelivery | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return QueuedDelivery(**data)
        except Exception as exc:
            logger.warning("DeliveryQueue: failed to parse %s: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, delivery: QueuedDelivery) -> str:
        """Persist *delivery* to the queue directory.

        Returns
        -------
        str
            The delivery ID.
        """
        self._write(delivery)
        logger.debug("DeliveryQueue.enqueue: id=%s to=%s", delivery.id, delivery.to)
        return delivery.id

    def mark_failed(self, delivery_id: str, error: str) -> None:
        """Record a failed delivery attempt.

        If ``attempts >= MAX_ATTEMPTS`` (3), the file is moved to ``failed/``
        and ``failed=True`` is set.  Otherwise the attempt counter is
        incremented and the file is re-persisted for later retry.
        """
        path = self._path(delivery_id, failed=False)
        if not path.exists():
            logger.warning("DeliveryQueue.mark_failed: %s not found", delivery_id)
            return

        delivery = self._load(path)
        if delivery is None:
            return

        delivery.attempts += 1
        delivery.last_error = error

        if delivery.attempts >= _MAX_ATTEMPTS:
            delivery.failed = True
            path.unlink(missing_ok=True)
            self._write(delivery, failed=True)
            logger.warning(
                "DeliveryQueue: %s permanently failed after %d attempts: %s",
                delivery_id, delivery.attempts, error,
            )
        else:
            self._write(delivery, failed=False)
            logger.debug(
                "DeliveryQueue: %s attempt %d/%d failed: %s",
                delivery_id, delivery.attempts, _MAX_ATTEMPTS, error,
            )

    def mark_done(self, delivery_id: str) -> None:
        """Delete the delivery file (success path)."""
        path = self._path(delivery_id, failed=False)
        try:
            path.unlink(missing_ok=True)
            logger.debug("DeliveryQueue.mark_done: %s deleted", delivery_id)
        except OSError as exc:
            logger.warning("DeliveryQueue.mark_done: cannot delete %s: %s", delivery_id, exc)

    def list_pending(self) -> list[QueuedDelivery]:
        """Return all pending (non-failed) deliveries sorted by ``created_at``."""
        result: list[QueuedDelivery] = []
        for p in self._root.glob("*.json"):
            delivery = self._load(p)
            if delivery is not None:
                result.append(delivery)
        result.sort(key=lambda d: d.created_at)
        return result
