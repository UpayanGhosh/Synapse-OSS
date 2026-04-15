"""
Cross-platform graceful→forced process tree kill utilities.
"""

import asyncio
import logging
import os
import signal
import sys

logger = logging.getLogger("synapse.process")

_IS_WIN = sys.platform == "win32"
_DEFAULT_GRACE_MS = 3000
_MAX_GRACE_MS = 60_000


def _win_get_creation_time(pid: int) -> int | None:
    """Return the process creation time as a 64-bit FILETIME integer, or None.

    Uses kernel32 OpenProcess + GetProcessTimes via ctypes.  Returns None if
    the process cannot be opened (dead, access denied, etc.).
    """
    import ctypes
    import ctypes.wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # noqa: N806

    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid,
    )
    if not handle:
        return None

    try:
        creation = ctypes.wintypes.FILETIME()
        exit_t = ctypes.wintypes.FILETIME()
        kernel = ctypes.wintypes.FILETIME()
        user = ctypes.wintypes.FILETIME()

        ok = ctypes.windll.kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_t),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None

        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def get_creation_time(pid: int) -> int | None:
    """Return a process creation timestamp for PID-reuse detection.

    On Windows: returns a 64-bit FILETIME integer (via kernel32).
    On Unix: returns the integer start time from /proc/<pid>/stat (Linux)
    or None on other Unix variants where this is unavailable.

    Used to disambiguate reused PIDs — store the creation time when spawning,
    compare before signalling.
    """
    if _IS_WIN:
        return _win_get_creation_time(pid)
    else:
        # Linux: parse field 22 (starttime) from /proc/<pid>/stat
        try:
            with open(f"/proc/{pid}/stat") as f:
                # Fields after the comm field (which may contain spaces/parens)
                data = f.read()
                # Find the closing paren of the comm field
                idx = data.rfind(")")
                fields = data[idx + 2 :].split()
                # starttime is field 20 (0-indexed) after the comm section
                return int(fields[19])
        except (OSError, IndexError, ValueError):
            return None


def is_pid_alive(pid: int, creation_time: int | None = None) -> bool:
    """
    Check if a PID is alive.

    Unix: sends signal 0 (no-op signal — checks permission/existence only).
    Windows: calls OpenProcess via ctypes; returns False if the process handle
    cannot be opened or the process has exited.

    When *creation_time* is provided, additionally verifies that the process
    creation time matches the expected value.  This guards against PID reuse
    on Windows (and Linux) where the OS may recycle PIDs after a process exits.

    Returns False on ProcessLookupError or PermissionError (treat as dead for
    our purposes — we can't signal it anyway).
    """
    if _IS_WIN:
        import ctypes

        SYNCHRONIZE = 0x00100000  # noqa: N806
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        # WAIT_TIMEOUT (258) means still running; WAIT_OBJECT_0 (0) means exited
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)
        alive = result == 258  # WAIT_TIMEOUT → still alive

        if alive and creation_time is not None:
            current_ct = _win_get_creation_time(pid)
            if current_ct is not None and current_ct != creation_time:
                logger.debug(
                    "PID %d alive but creation time mismatch "
                    "(expected %d, got %d) — treating as dead (PID reuse)",
                    pid,
                    creation_time,
                    current_ct,
                )
                return False

        return alive
    else:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False

        if creation_time is not None:
            current_ct = get_creation_time(pid)
            if current_ct is not None and current_ct != creation_time:
                logger.debug(
                    "PID %d alive but creation time mismatch "
                    "(expected %d, got %d) — treating as dead (PID reuse)",
                    pid,
                    creation_time,
                    current_ct,
                )
                return False

        return True


async def _taskkill(pid: int, force: bool = False) -> bool:
    """Windows: run taskkill /T /PID <pid>, optionally with /F. Returns success."""
    cmd = ["taskkill", "/T", "/PID", str(pid)]
    if force:
        cmd.insert(1, "/F")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            proc.kill()
            return False
        return proc.returncode == 0
    except Exception as e:
        logger.warning("taskkill failed for PID %d: %s", pid, e)
        return False


async def kill_process_tree(
    pid: int,
    grace_ms: int = _DEFAULT_GRACE_MS,
) -> bool:
    """
    Kill a process and its children. Returns True if the process is dead after
    this call.

    Unix:
      1. os.killpg(pgid, SIGTERM) — send SIGTERM to process group
      2. Wait grace_ms
      3. If still alive: os.killpg(pgid, SIGKILL)
      4. If group kill fails (no group or permission): os.kill(pid, SIGKILL) directly

    Windows:
      1. taskkill /T /PID <pid>  — graceful, recursive children
      2. Wait grace_ms
      3. If still alive: taskkill /F /T /PID <pid>  — force kill + recursive

    Catches ProcessLookupError (already dead) → returns True.
    Catches PermissionError → logs warning, returns False.
    grace_ms is clamped to [0, 60000].
    """
    grace_ms = max(0, min(grace_ms, _MAX_GRACE_MS))

    if not is_pid_alive(pid):
        return True

    if _IS_WIN:
        # Step 1: graceful taskkill with child tree
        await _taskkill(pid, force=False)
        if grace_ms > 0:
            await asyncio.sleep(grace_ms / 1000)
        if not is_pid_alive(pid):
            return True
        # Step 3: force kill
        await _taskkill(pid, force=True)
        return not is_pid_alive(pid)
    else:
        # Unix: use process group for child propagation
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError):
            return True  # already gone

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError as e:
            logger.warning("SIGTERM to pgid %d denied: %s", pgid, e)
            # Fall through to direct kill attempt

        if grace_ms > 0:
            await asyncio.sleep(grace_ms / 1000)

        if not is_pid_alive(pid):
            return True

        # Step 3: SIGKILL the group
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Last resort: direct PID kill
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as e:
                logger.warning("SIGKILL to PID %d denied: %s", pid, e)
                return False

        return not is_pid_alive(pid)
