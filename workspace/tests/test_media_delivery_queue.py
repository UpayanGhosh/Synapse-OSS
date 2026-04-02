"""
test_media_delivery_queue.py — Tests for media/delivery_queue.py

Covers:
  - QueuedDelivery dataclass
  - DeliveryQueue: enqueue, mark_done, mark_failed, list_pending
  - Retry tracking (max 3 attempts -> permanently failed)
  - File persistence and atomic writes
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.delivery_queue import DeliveryQueue, QueuedDelivery


class TestQueuedDelivery:
    def test_construction(self):
        d = QueuedDelivery(channel_id="whatsapp", to="user1", payloads=[{"text": "hello"}])
        assert d.channel_id == "whatsapp"
        assert d.to == "user1"
        assert len(d.payloads) == 1
        assert d.attempts == 0
        assert d.failed is False
        assert d.last_error == ""
        assert d.id  # auto-generated

    def test_auto_id_generation(self):
        d1 = QueuedDelivery(channel_id="tg", to="u1", payloads=[])
        d2 = QueuedDelivery(channel_id="tg", to="u1", payloads=[])
        assert d1.id != d2.id


class TestDeliveryQueue:
    @pytest.fixture
    def queue(self, tmp_path):
        return DeliveryQueue(queue_root=tmp_path / "delivery-queue")

    def test_enqueue_creates_file(self, queue, tmp_path):
        d = QueuedDelivery(channel_id="wa", to="user1", payloads=[{"text": "hi"}])
        queue.enqueue(d)
        path = queue._path(d.id)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["channel_id"] == "wa"

    def test_enqueue_returns_id(self, queue):
        d = QueuedDelivery(channel_id="wa", to="user1", payloads=[])
        result_id = queue.enqueue(d)
        assert result_id == d.id

    def test_mark_done_deletes_file(self, queue):
        d = QueuedDelivery(channel_id="wa", to="user1", payloads=[])
        queue.enqueue(d)
        queue.mark_done(d.id)
        assert not queue._path(d.id).exists()

    def test_mark_done_nonexistent_noop(self, queue):
        queue.mark_done("nonexistent-id")  # should not raise

    def test_mark_failed_increments_attempts(self, queue):
        d = QueuedDelivery(channel_id="wa", to="user1", payloads=[])
        queue.enqueue(d)
        queue.mark_failed(d.id, "network error")

        loaded = queue._load(queue._path(d.id))
        assert loaded.attempts == 1
        assert loaded.last_error == "network error"
        assert loaded.failed is False

    def test_mark_failed_permanently_after_3_attempts(self, queue):
        d = QueuedDelivery(channel_id="wa", to="user1", payloads=[])
        queue.enqueue(d)

        queue.mark_failed(d.id, "err 1")
        queue.mark_failed(d.id, "err 2")
        queue.mark_failed(d.id, "err 3")

        # File should be moved to failed/ dir
        pending_path = queue._path(d.id, failed=False)
        failed_path = queue._path(d.id, failed=True)
        assert not pending_path.exists()
        assert failed_path.exists()

        loaded = queue._load(failed_path)
        assert loaded.failed is True
        assert loaded.attempts == 3

    def test_mark_failed_nonexistent_noop(self, queue):
        queue.mark_failed("no-such-id", "err")  # should not raise

    def test_list_pending_returns_pending_only(self, queue):
        d1 = QueuedDelivery(channel_id="wa", to="u1", payloads=[])
        d2 = QueuedDelivery(channel_id="wa", to="u2", payloads=[])
        queue.enqueue(d1)
        queue.enqueue(d2)

        pending = queue.list_pending()
        ids = {d.id for d in pending}
        assert d1.id in ids
        assert d2.id in ids

    def test_list_pending_sorted_by_created_at(self, queue):
        import time

        d1 = QueuedDelivery(channel_id="wa", to="u1", payloads=[], created_at=100.0)
        d2 = QueuedDelivery(channel_id="wa", to="u2", payloads=[], created_at=50.0)
        queue.enqueue(d1)
        queue.enqueue(d2)

        pending = queue.list_pending()
        assert pending[0].created_at <= pending[1].created_at

    def test_list_pending_empty(self, queue):
        assert queue.list_pending() == []

    def test_failed_dir_created(self, queue):
        assert queue._failed_dir.exists()

    def test_corrupt_file_skipped(self, queue):
        # Write a corrupt JSON file
        bad_path = queue._root / "bad.json"
        bad_path.write_text("not valid json", encoding="utf-8")
        pending = queue.list_pending()
        # Should not crash, corrupt file should be skipped
        assert isinstance(pending, list)
