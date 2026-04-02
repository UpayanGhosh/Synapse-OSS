"""test_session_lock.py — Tests for SynapseFileLock stale-lock reclaim and watchdog.

Covers:
- Stale lock detection: mock dead PID -> lock reclaimed
- PID recycling: same PID, different start time -> lock reclaimed
- Watchdog: lock held > 300s -> force-released
- Clean startup: stale .lock files cleaned
- Graceful degradation: no psutil -> falls back to basic filelock
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from sci_fi_dashboard.multiuser.session_store import (
        LockMetadata,
        SynapseFileLock,
        _is_pid_alive,
        _watchdog_loop,
        clean_stale_lock_files,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="sci_fi_dashboard/multiuser not yet available",
)


class TestSynapseFileLock:
    """Tests for SynapseFileLock acquire/release lifecycle."""

    @_skip
    def test_basic_acquire_release(self, tmp_path):
        """Lock can be acquired and released cleanly."""
        lock_path = tmp_path / "test.lock"
        fl = SynapseFileLock(lock_path, timeout=5.0)
        fl.acquire()
        assert lock_path.exists()
        meta_path = Path(f"{lock_path}.meta")
        assert meta_path.exists()

        # Verify metadata contains our PID.
        with open(meta_path) as fh:
            meta = json.load(fh)
        assert meta["pid"] == os.getpid()

        fl.release()
        assert not meta_path.exists()

    @_skip
    def test_context_manager(self, tmp_path):
        """Lock works as a context manager."""
        lock_path = tmp_path / "test.lock"
        with SynapseFileLock(lock_path, timeout=5.0):
            assert lock_path.exists()
        # After exit, metadata should be cleaned up.
        meta_path = Path(f"{lock_path}.meta")
        assert not meta_path.exists()

    @_skip
    def test_stale_lock_dead_pid_reclaimed(self, tmp_path):
        """When the lock holder PID is dead, the lock is reclaimed.

        We simulate a stale lock by creating the metadata file with a dead
        PID.  The underlying filelock is NOT held by any process (simulating
        the OS having released it when the holder died).  SynapseFileLock
        should detect the stale metadata and reclaim cleanly.
        """
        lock_path = tmp_path / "test.lock"
        meta_path = Path(f"{lock_path}.meta")

        # Create only the metadata sidecar — the lock file will be created
        # by filelock on acquisition attempt.  The meta indicates the lock
        # was once held by a dead PID.
        lock_path.write_text("")
        dead_pid = 999999  # very unlikely to be alive
        meta = {
            "pid": dead_pid,
            "created_at": time.monotonic() - 10,
            "starttime": time.time() - 100,
        }
        with open(meta_path, "w") as fh:
            json.dump(meta, fh)

        # Verify _is_stale returns True for a dead PID.
        with patch(
            "sci_fi_dashboard.multiuser.session_store._is_pid_alive",
            return_value=False,
        ):
            fl = SynapseFileLock(lock_path, timeout=5.0)
            assert fl._is_stale() is True

            # Should acquire successfully since no actual OS lock is held.
            fl.acquire()
            assert fl._acquired
            fl.release()

    @_skip
    def test_pid_recycling_detected(self, tmp_path):
        """Same PID but different start time -> lock is considered stale."""
        lock_path = tmp_path / "test.lock"
        meta_path = Path(f"{lock_path}.meta")

        # Create metadata with current PID but wrong start time.
        lock_path.write_text("")
        current_pid = os.getpid()
        meta = {
            "pid": current_pid,
            "created_at": time.monotonic() - 10,
            "starttime": 1000.0,  # obviously wrong start time
        }
        with open(meta_path, "w") as fh:
            json.dump(meta, fh)

        # Mock psutil to report a different create_time.
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = time.time()  # current, not 1000.0

        with patch(
            "sci_fi_dashboard.multiuser.session_store._HAS_PSUTIL", True
        ), patch(
            "sci_fi_dashboard.multiuser.session_store.psutil"
        ) as mock_psutil, patch(
            "sci_fi_dashboard.multiuser.session_store._is_pid_alive",
            return_value=True,
        ):
            mock_psutil.Process.return_value = mock_proc
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception

            fl = SynapseFileLock(lock_path, timeout=5.0)
            assert fl._is_stale() is True

            # Acquire succeeds because no OS-level lock is held.
            fl.acquire()
            assert fl._acquired
            fl.release()

    @_skip
    def test_age_based_stale_detection(self, tmp_path):
        """Lock file older than MAX_LOCK_AGE_S is considered stale (no metadata)."""
        lock_path = tmp_path / "test.lock"

        # Create lock file with old mtime, no metadata sidecar.
        lock_path.write_text("")
        old_time = time.time() - SynapseFileLock.MAX_LOCK_AGE_S - 100
        os.utime(str(lock_path), (old_time, old_time))

        fl = SynapseFileLock(lock_path, timeout=5.0)
        assert fl._is_stale() is True

        # Should acquire since no OS-level lock is held.
        fl.acquire()
        assert fl._acquired
        fl.release()


class TestCleanStaleLockFiles:
    """Tests for clean_stale_lock_files() startup scan."""

    @_skip
    def test_removes_stale_locks_with_dead_pid(self, tmp_path):
        """Stale lock files with dead PIDs are cleaned up."""
        lock_file = tmp_path / "session.lock"
        meta_file = Path(f"{lock_file}.meta")
        lock_file.write_text("")
        meta = {
            "pid": 999999,  # dead PID
            "created_at": time.monotonic() - 100,
            "starttime": time.time() - 200,
        }
        with open(meta_file, "w") as fh:
            json.dump(meta, fh)

        with patch(
            "sci_fi_dashboard.multiuser.session_store._is_pid_alive",
            return_value=False,
        ):
            removed = clean_stale_lock_files(tmp_path)

        assert removed == 1
        assert not lock_file.exists()
        assert not meta_file.exists()

    @_skip
    def test_preserves_live_locks(self, tmp_path):
        """Lock files with live PIDs are not removed."""
        lock_file = tmp_path / "session.lock"
        meta_file = Path(f"{lock_file}.meta")
        lock_file.write_text("")
        meta = {
            "pid": os.getpid(),  # our own PID — definitely alive
            "created_at": time.monotonic(),
            "starttime": time.time(),
        }
        with open(meta_file, "w") as fh:
            json.dump(meta, fh)

        # Mock psutil to confirm PID is not recycled.
        mock_proc = MagicMock()
        mock_proc.create_time.return_value = meta["starttime"]

        with patch(
            "sci_fi_dashboard.multiuser.session_store._is_pid_alive",
            return_value=True,
        ), patch(
            "sci_fi_dashboard.multiuser.session_store._HAS_PSUTIL", True
        ), patch(
            "sci_fi_dashboard.multiuser.session_store.psutil"
        ) as mock_psutil:
            mock_psutil.Process.return_value = mock_proc
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception

            removed = clean_stale_lock_files(tmp_path)

        assert removed == 0
        assert lock_file.exists()

    @_skip
    def test_handles_nonexistent_dir(self):
        """clean_stale_lock_files on nonexistent dir returns 0."""
        removed = clean_stale_lock_files(Path("/nonexistent/dir/12345"))
        assert removed == 0

    @_skip
    def test_no_metadata_old_lock_removed(self, tmp_path):
        """Lock file without metadata but with old mtime is removed."""
        lock_file = tmp_path / "session.lock"
        lock_file.write_text("")
        old_time = time.time() - SynapseFileLock.MAX_LOCK_AGE_S - 100
        os.utime(str(lock_file), (old_time, old_time))

        removed = clean_stale_lock_files(tmp_path)
        assert removed == 1
        assert not lock_file.exists()


class TestWatchdog:
    """Tests for the background watchdog loop."""

    @_skip
    @pytest.mark.asyncio
    async def test_watchdog_force_releases_old_locks(self, tmp_path):
        """Locks held > 300s are force-released by the watchdog."""
        lock_file = tmp_path / "session.lock"
        meta_file = Path(f"{lock_file}.meta")
        lock_file.write_text("")
        meta = {
            "pid": os.getpid(),
            "created_at": time.monotonic() - 400,
            "starttime": time.time() - 400,
        }
        with open(meta_file, "w") as fh:
            json.dump(meta, fh)

        # Set the lock file mtime to be old enough.
        old_time = time.time() - 400
        os.utime(str(lock_file), (old_time, old_time))

        # Run one iteration of the watchdog.
        # We'll patch sleep to raise after one iteration.
        call_count = 0

        async def _mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError

        with patch("sci_fi_dashboard.multiuser.session_store.asyncio.sleep", _mock_sleep):
            try:
                await _watchdog_loop(tmp_path)
            except asyncio.CancelledError:
                pass

        assert not lock_file.exists()
        assert not meta_file.exists()


class TestGracefulDegradation:
    """Tests for graceful degradation without psutil."""

    @_skip
    def test_no_psutil_falls_back_to_basic(self, tmp_path):
        """When psutil is unavailable, SynapseFileLock still works."""
        lock_path = tmp_path / "test.lock"

        with patch("sci_fi_dashboard.multiuser.session_store._HAS_PSUTIL", False):
            fl = SynapseFileLock(lock_path, timeout=5.0)
            fl.acquire()
            assert fl._acquired
            fl.release()

    @_skip
    def test_no_psutil_stale_detection_uses_age(self, tmp_path):
        """Without psutil, stale detection relies on age-based check."""
        lock_path = tmp_path / "test.lock"
        meta_path = Path(f"{lock_path}.meta")

        # Create a lock with alive PID but no psutil, and old mtime.
        lock_path.write_text("")
        meta = {
            "pid": os.getpid(),
            "created_at": time.monotonic() - 10,
            "starttime": time.time(),
        }
        with open(meta_path, "w") as fh:
            json.dump(meta, fh)

        # Make lock file old enough to trigger age-based stale detection.
        old_time = time.time() - SynapseFileLock.MAX_LOCK_AGE_S - 100
        os.utime(str(lock_path), (old_time, old_time))

        with patch(
            "sci_fi_dashboard.multiuser.session_store._HAS_PSUTIL", False
        ), patch(
            "sci_fi_dashboard.multiuser.session_store._is_pid_alive",
            return_value=True,
        ):
            fl = SynapseFileLock(lock_path, timeout=5.0)
            # Without psutil, PID alive + old mtime -> stale via age check.
            assert fl._is_stale() is True

            # Should acquire since no OS-level lock is held.
            fl.acquire()
            assert fl._acquired
            fl.release()
