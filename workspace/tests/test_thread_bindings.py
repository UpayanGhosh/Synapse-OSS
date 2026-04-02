"""Tests for channels/thread_bindings.py — ThreadBinding, ThreadBindingManager.

Covers:
- bind() creates and updates bindings
- lookup() returns binding and updates last_activity
- lookup() returns None for expired (idle / max-age) bindings
- unbind() removes bindings
- sweep() removes expired bindings
- max_bindings eviction
- Persistence across load/save
- Corrupt file handling
"""

import json
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.thread_bindings import ThreadBinding, ThreadBindingManager


class TestThreadBindingDataclass:
    """Tests for ThreadBinding dataclass."""

    def test_construction(self):
        b = ThreadBinding(
            thread_id="t1", channel_id="slack", chat_id="c1", session_key="s1"
        )
        assert b.thread_id == "t1"
        assert b.channel_id == "slack"
        assert b.chat_id == "c1"
        assert b.session_key == "s1"
        assert b.created_at > 0
        assert b.last_activity > 0


class TestThreadBindingManager:
    """Tests for ThreadBindingManager."""

    def test_bind_and_lookup(self, tmp_path):
        """bind() creates a binding; lookup() retrieves it."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        mgr.bind("thread1", "slack", "chat1", "session1")
        result = mgr.lookup("thread1", "slack")
        assert result is not None
        assert result.thread_id == "thread1"
        assert result.chat_id == "chat1"
        assert result.session_key == "session1"

    def test_lookup_nonexistent(self, tmp_path):
        """lookup() returns None for nonexistent binding."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        assert mgr.lookup("nothread", "nochannel") is None

    def test_bind_updates_existing(self, tmp_path):
        """bind() updates chat_id and session_key for existing binding."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        mgr.bind("t1", "slack", "chat_old", "session_old")
        mgr.bind("t1", "slack", "chat_new", "session_new")
        result = mgr.lookup("t1", "slack")
        assert result.chat_id == "chat_new"
        assert result.session_key == "session_new"

    def test_unbind(self, tmp_path):
        """unbind() removes binding and returns True."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        mgr.bind("t1", "slack", "c1", "s1")
        assert mgr.unbind("t1", "slack") is True
        assert mgr.lookup("t1", "slack") is None

    def test_unbind_nonexistent(self, tmp_path):
        """unbind() returns False for nonexistent binding."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        assert mgr.unbind("ghost", "slack") is False

    def test_idle_timeout_expiry(self, tmp_path):
        """lookup() returns None when idle timeout exceeds threshold."""
        mgr = ThreadBindingManager(
            store_path=tmp_path / "bindings.json", idle_timeout=1.0
        )
        mgr.bind("t1", "slack", "c1", "s1")

        # Manually set last_activity to the past
        data = mgr._load()
        key = "slack:t1"
        data[key]["last_activity"] = time.time() - 2.0
        mgr._save(data)

        assert mgr.lookup("t1", "slack") is None

    def test_max_age_expiry(self, tmp_path):
        """lookup() returns None when max age exceeds threshold."""
        mgr = ThreadBindingManager(
            store_path=tmp_path / "bindings.json", max_age=1.0
        )
        mgr.bind("t1", "slack", "c1", "s1")

        # Manually set created_at to the past
        data = mgr._load()
        key = "slack:t1"
        data[key]["created_at"] = time.time() - 2.0
        mgr._save(data)

        assert mgr.lookup("t1", "slack") is None

    def test_sweep_removes_expired(self, tmp_path):
        """sweep() removes expired bindings and returns count."""
        mgr = ThreadBindingManager(
            store_path=tmp_path / "bindings.json", idle_timeout=1.0
        )
        mgr.bind("t1", "slack", "c1", "s1")
        mgr.bind("t2", "slack", "c2", "s2")

        # Expire t1 only
        data = mgr._load()
        data["slack:t1"]["last_activity"] = time.time() - 2.0
        mgr._save(data)

        removed = mgr.sweep()
        assert removed == 1
        assert mgr.lookup("t2", "slack") is not None

    def test_sweep_no_expired(self, tmp_path):
        """sweep() returns 0 when nothing is expired."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        mgr.bind("t1", "slack", "c1", "s1")
        assert mgr.sweep() == 0

    def test_max_bindings_eviction(self, tmp_path):
        """When at max_bindings, oldest is evicted on new bind()."""
        mgr = ThreadBindingManager(
            store_path=tmp_path / "bindings.json", max_bindings=3
        )
        for i in range(3):
            mgr.bind(f"t{i}", "slack", f"c{i}", f"s{i}")
            time.sleep(0.01)  # ensure different last_activity

        # Adding a 4th should evict the oldest (t0)
        mgr.bind("t_new", "slack", "c_new", "s_new")
        data = mgr._load()
        assert len(data) == 3
        assert mgr.lookup("t_new", "slack") is not None

    def test_persistence_across_instances(self, tmp_path):
        """Bindings persist across different manager instances."""
        path = tmp_path / "bindings.json"
        mgr1 = ThreadBindingManager(store_path=path)
        mgr1.bind("t1", "discord", "c1", "s1")

        mgr2 = ThreadBindingManager(store_path=path)
        result = mgr2.lookup("t1", "discord")
        assert result is not None
        assert result.session_key == "s1"

    def test_corrupt_file_handled(self, tmp_path):
        """Corrupt JSON file is handled gracefully."""
        path = tmp_path / "bindings.json"
        path.write_text("NOT VALID JSON {{{")

        mgr = ThreadBindingManager(store_path=path)
        # Should not raise — returns empty dict
        assert mgr.lookup("t1", "slack") is None

    def test_missing_file_handled(self, tmp_path):
        """Missing file is handled gracefully."""
        path = tmp_path / "nonexistent.json"
        mgr = ThreadBindingManager(store_path=path)
        assert mgr.lookup("t1", "slack") is None

    def test_different_channels_same_thread_id(self, tmp_path):
        """Same thread_id on different channels are separate bindings."""
        mgr = ThreadBindingManager(store_path=tmp_path / "bindings.json")
        mgr.bind("t1", "slack", "slack_chat", "slack_session")
        mgr.bind("t1", "discord", "discord_chat", "discord_session")

        slack_result = mgr.lookup("t1", "slack")
        discord_result = mgr.lookup("t1", "discord")
        assert slack_result.chat_id == "slack_chat"
        assert discord_result.chat_id == "discord_chat"
