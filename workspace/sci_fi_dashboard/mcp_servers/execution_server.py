"""
MCP Server: Synapse Execution — run shell commands and manage background processes.
Run standalone: python -m sci_fi_dashboard.mcp_servers.execution_server

Security hardening (2026-04-02):
 - Token-based auth via SYNAPSE_EXEC_TOKEN env var
 - Command allowlist restricts executable binaries
 - Subprocess env scrubbed of secrets (API keys, tokens, passwords)
 - Process isolation via start_new_session / CREATE_NEW_PROCESS_GROUP
 - Timeout enforcement kills processes after deadline
 - TTL cleanup kills OS processes before discarding sessions
 - Poll race condition fixed with asyncio.Lock
 - Workdir validated against workspace root
 - Session count capped to prevent OOM
"""

import asyncio
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .base import _WORKSPACE, logger, setup_logging

server = Server("synapse-execution")

_OUTPUT_CAP = 200 * 1024  # 200 KB
_PENDING_CAP = 30 * 1024  # 30 KB per pending buffer
_TAIL_SIZE = 2000  # last 2000 chars
_SESSION_TTL = 30 * 60  # 30 minutes
_DEFAULT_YIELD_MS = 10_000  # 10s foreground yield
_MAX_SESSIONS = 200  # cap to prevent OOM
_IS_WIN = sys.platform == "win32"

# ── Workspace root for workdir validation ──────────────────────────
_WORKSPACE_ROOT = Path(_WORKSPACE).resolve()

# ── Auth ───────────────────────────────────────────────────────────
_EXEC_TOKEN: str | None = os.environ.get("SYNAPSE_EXEC_TOKEN")

# ── Command allowlist ──────────────────────────────────────────────
# Only these base commands (first token of the shell command) are allowed.
# Extend as needed. Set to None to disable allowlist (NOT recommended for prod).
_ALLOWED_COMMANDS: set[str] | None = {
    # Version control
    "git",
    # Language runtimes
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    # Build / lint
    "pip",
    "pip3",
    "ruff",
    "black",
    "pytest",
    "mypy",
    # File inspection (read-only)
    "ls",
    "dir",
    "cat",
    "head",
    "tail",
    "find",
    "grep",
    "rg",
    "wc",
    # Utilities
    "echo",
    "pwd",
    "which",
    "where",
    "env",
    "date",
    "whoami",
    # Project scripts
    "uvicorn",
}

# ── Secret-key patterns to scrub from child env ───────────────────
_SECRET_PATTERNS: re.Pattern = re.compile(
    r"(API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY)",
    re.IGNORECASE,
)


def _scrubbed_env() -> dict[str, str]:
    """Return a copy of os.environ with secret-bearing keys removed."""
    return {k: v for k, v in os.environ.items() if not _SECRET_PATTERNS.search(k)}


def _validate_auth(args: dict) -> str | None:
    """Return an error string if auth fails, else None."""
    if not _EXEC_TOKEN:
        # No token configured — server operator must set SYNAPSE_EXEC_TOKEN.
        # Reject all requests when unconfigured to avoid running wide-open.
        return "SYNAPSE_EXEC_TOKEN not configured — execution server disabled"
    provided = args.get("auth_token") or ""
    if not provided or provided != _EXEC_TOKEN:
        return "auth_token missing or invalid"
    return None


def _validate_command(command: str) -> str | None:
    """Return an error string if the command is not in the allowlist, else None."""
    if _ALLOWED_COMMANDS is None:
        return None
    # Extract the base command (first token). Handle pipes/chains by checking
    # only the first command — downstream commands inherit the same restrictions
    # via the scrubbed env and process isolation.
    try:
        first_token = command.strip().split()[0].lower() if _IS_WIN else shlex.split(command)[0]
        # Strip path prefix (e.g. /usr/bin/python -> python)
        base = os.path.basename(first_token)
        # Strip .exe suffix on Windows
        if _IS_WIN and base.endswith(".exe"):
            base = base[:-4]
    except (ValueError, IndexError):
        return f"Cannot parse command: {command!r}"

    if base not in _ALLOWED_COMMANDS:
        return f"Command {base!r} not in allowlist"
    return None


def _validate_workdir(workdir: str | None) -> str | None:
    """Return an error string if workdir escapes the workspace root, else None."""
    if workdir is None:
        return None
    try:
        resolved = Path(workdir).resolve()
    except (OSError, ValueError) as e:
        return f"Invalid workdir: {e}"
    if not (resolved == _WORKSPACE_ROOT or _WORKSPACE_ROOT in resolved.parents):
        return f"workdir {str(resolved)!r} is outside workspace root " f"{str(_WORKSPACE_ROOT)!r}"
    return None


@dataclass
class ProcessSession:
    id: str
    command: str
    pid: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    cwd: str | None = None
    scope_key: str | None = None

    # Output buffers
    aggregated: str = ""
    tail: str = ""
    pending_stdout: list[str] = field(default_factory=list)
    pending_stderr: list[str] = field(default_factory=list)
    truncated: bool = False

    # State
    exit_code: int | None = None
    exited: bool = False
    backgrounded: bool = False

    # Internal
    _task: asyncio.Task | None = field(default=None, repr=False)
    _timeout_task: asyncio.Task | None = field(default=None, repr=False)
    _new_output: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _proc: "asyncio.subprocess.Process | None" = field(default=None, repr=False)


_sessions: dict[str, ProcessSession] = {}


def _ok(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}))]


async def _collect_output(
    session: ProcessSession,
    proc: "asyncio.subprocess.Process",
) -> None:
    """Stream stdout + stderr into session buffers."""

    aggregated_chunks: list[str] = []
    aggregated_len = 0

    async def _drain(stream, target: str):
        nonlocal aggregated_len
        pending = session.pending_stdout if target == "stdout" else session.pending_stderr
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")

            # Append to pending (capped)
            pending_size = sum(len(c) for c in pending)
            if pending_size < _PENDING_CAP:
                pending.append(text)

            # Append to aggregated (capped) — list+join avoids O(n^2) concat.
            # Max ~25 chunks at 8KB each before _OUTPUT_CAP (200KB), so the
            # periodic join below is bounded to ~5MB total work — negligible.
            if aggregated_len < _OUTPUT_CAP:
                aggregated_chunks.append(text)
                aggregated_len += len(text)
                if aggregated_len > _OUTPUT_CAP:
                    session.truncated = True
                # Rebuild session.aggregated so poll/log see incremental data
                joined = "".join(aggregated_chunks)
                if len(joined) > _OUTPUT_CAP:
                    joined = joined[:_OUTPUT_CAP]
                session.aggregated = joined

            # Update tail (rolling window)
            session.tail = (session.tail + text)[-_TAIL_SIZE:]

            # Signal new output available (for poll)
            session._new_output.set()

    tasks = []
    if proc.stdout:
        tasks.append(asyncio.create_task(_drain(proc.stdout, "stdout")))
    if proc.stderr:
        tasks.append(asyncio.create_task(_drain(proc.stderr, "stderr")))
    if tasks:
        await asyncio.gather(*tasks)

    await proc.wait()
    session.exit_code = proc.returncode
    session.exited = True
    session._new_output.set()  # wake any waiting poll


async def _kill_session(sess: ProcessSession) -> None:
    """Kill the OS process for a session and cancel its async tasks."""
    # Kill the OS process first — prevents zombie accumulation
    if not sess.exited and sess.pid:
        from sci_fi_dashboard.process.kill_tree import kill_process_tree

        try:
            await kill_process_tree(sess.pid, grace_ms=2000)
        except Exception as e:
            logger.warning("Failed to kill PID %s during cleanup: %s", sess.pid, e)
    sess.exited = True
    if sess.exit_code is None:
        sess.exit_code = -9
    # Cancel the output collector task
    if sess._task and not sess._task.done():
        sess._task.cancel()
    # Cancel the timeout enforcer task
    if sess._timeout_task and not sess._timeout_task.done():
        sess._timeout_task.cancel()


async def _ttl_cleanup() -> None:
    """Remove sessions older than SESSION_TTL — kills OS processes first."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        stale = [sid for sid, s in _sessions.items() if now - s.started_at > _SESSION_TTL]
        for sid in stale:
            sess = _sessions.pop(sid, None)
            if sess:
                await _kill_session(sess)
        if stale:
            logger.info("TTL cleanup removed %d sessions", len(stale))


async def _enforce_timeout(session: ProcessSession, timeout_secs: float) -> None:
    """Kill the process after timeout_secs. Scheduled as an asyncio task."""
    try:
        await asyncio.sleep(timeout_secs)
    except asyncio.CancelledError:
        return  # process exited normally before timeout
    if not session.exited and session.pid:
        logger.warning(
            "Session %s (PID %s) exceeded %ds timeout — killing",
            session.id,
            session.pid,
            timeout_secs,
        )
        await _kill_session(session)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="exec",
            description=(
                "Execute a shell command (requires auth_token). "
                "If background=false (default), waits up to yield_ms then yields to background. "
                "If background=true, spawns immediately and returns sessionId. "
                "Use scope_key to group processes for batch cancellation. "
                "Command must be in the server allowlist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "auth_token": {
                        "type": "string",
                        "description": "SYNAPSE_EXEC_TOKEN value for authentication",
                    },
                    "command": {"type": "string", "description": "Shell command to run"},
                    "workdir": {
                        "type": "string",
                        "description": (
                            "Working directory (defaults to workspace root). "
                            "Must be inside the workspace boundary."
                        ),
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Seconds before killing the process (default 30)",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Spawn in background and return sessionId immediately (default false)",
                    },
                    "yield_ms": {
                        "type": "number",
                        "description": "Background after N milliseconds in foreground mode (default 10000)",
                    },
                    "scope_key": {
                        "type": "string",
                        "description": "Group processes for batch cancellation via kill-scope",
                    },
                },
                "required": ["auth_token", "command"],
            },
        ),
        Tool(
            name="process",
            description=(
                "Manage background processes (requires auth_token). "
                "action: list | poll | log | kill | write | kill-scope. "
                "sessionId required for all actions except list and kill-scope."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "auth_token": {
                        "type": "string",
                        "description": "SYNAPSE_EXEC_TOKEN value for authentication",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["list", "poll", "log", "kill", "write", "kill-scope"],
                    },
                    "sessionId": {"type": "string"},
                    "timeout": {
                        "type": "number",
                        "description": "Seconds to wait for new output in poll (default 10, max 60)",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of tail lines to return for log (default 50)",
                    },
                    "data": {
                        "type": "string",
                        "description": "Data to write to stdin (for write action)",
                    },
                    "eof": {
                        "type": "boolean",
                        "description": "Close stdin after writing (for write action)",
                    },
                    "scope_key": {
                        "type": "string",
                        "description": "Scope to cancel (for kill-scope action)",
                    },
                },
                "required": ["auth_token", "action"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "exec":
        return await _handle_exec(arguments)
    elif name == "process":
        return await _handle_process(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_exec(args: dict) -> list[TextContent]:
    # ── Auth gate ─────────────────────────────────────────────────
    auth_err = _validate_auth(args)
    if auth_err:
        return _err(auth_err)

    command = args["command"]
    workdir = args.get("workdir") or None
    timeout = float(args.get("timeout", 30))
    background = bool(args.get("background", False))
    yield_ms = float(args.get("yield_ms", _DEFAULT_YIELD_MS))
    scope_key = args.get("scope_key") or None

    # ── Command allowlist ─────────────────────────────────────────
    cmd_err = _validate_command(command)
    if cmd_err:
        return _err(cmd_err)

    # ── Workdir boundary check ────────────────────────────────────
    wd_err = _validate_workdir(workdir)
    if wd_err:
        return _err(wd_err)

    # ── Session cap ───────────────────────────────────────────────
    if len(_sessions) >= _MAX_SESSIONS:
        return _err(f"Session limit reached ({_MAX_SESSIONS}). Kill existing sessions first.")

    session = ProcessSession(
        id=uuid.uuid4().hex[:12],
        command=command,
        cwd=workdir,
        scope_key=scope_key,
    )
    _sessions[session.id] = session

    # ── Process isolation + scrubbed env ──────────────────────────
    spawn_kwargs: dict = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "stdin": asyncio.subprocess.PIPE,
        "cwd": workdir,
        "env": _scrubbed_env(),
    }
    if _IS_WIN:
        spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        spawn_kwargs["start_new_session"] = True

    try:
        cmd_args = command.strip().split() if _IS_WIN else shlex.split(command)
        proc = await asyncio.create_subprocess_exec(*cmd_args, **spawn_kwargs)
    except Exception as e:
        _sessions.pop(session.id, None)
        return _err(str(e))

    session.pid = proc.pid
    session._proc = proc

    collect_task = asyncio.create_task(_collect_output(session, proc))
    session._task = collect_task

    # ── Timeout enforcement ───────────────────────────────────────
    if timeout > 0:
        session._timeout_task = asyncio.create_task(_enforce_timeout(session, timeout))

    if background:
        session.backgrounded = True
        return _ok({"status": "running", "sessionId": session.id, "pid": proc.pid})

    # Foreground: wait up to yield_ms, then yield to background
    try:
        await asyncio.wait_for(proc.wait(), timeout=yield_ms / 1000)
    except TimeoutError:
        session.backgrounded = True
        return _ok(
            {
                "status": "running",
                "sessionId": session.id,
                "pid": proc.pid,
                "tail": session.tail,
                "backgrounded": True,
            }
        )

    # Process completed within yield window — _collect_output already set
    # session.exited and session.exit_code, so no need to overwrite here.
    await collect_task
    # Cancel timeout enforcer — process already done
    if session._timeout_task and not session._timeout_task.done():
        session._timeout_task.cancel()

    return _ok(
        {
            "status": "completed" if proc.returncode == 0 else "failed",
            "exitCode": proc.returncode,
            "output": session.aggregated,
            "truncated": session.truncated,
        }
    )


async def _handle_process(args: dict) -> list[TextContent]:
    # ── Auth gate ─────────────────────────────────────────────────
    auth_err = _validate_auth(args)
    if auth_err:
        return _err(auth_err)

    action = args.get("action", "")

    if action == "list":
        result = [
            {
                "sessionId": s.id,
                "command": s.command,
                "pid": s.pid,
                "status": "exited" if s.exited else "running",
                "exitCode": s.exit_code,
                "backgrounded": s.backgrounded,
                "scopeKey": s.scope_key,
                "startedAgo": round(time.monotonic() - s.started_at, 1),
            }
            for s in _sessions.values()
        ]
        return _ok(result)

    if action == "kill-scope":
        scope = args.get("scope_key")
        if not scope:
            return _err("scope_key required")
        from sci_fi_dashboard.process.kill_tree import kill_process_tree

        killed = []
        for sid, s in list(_sessions.items()):
            if s.scope_key == scope and not s.exited:
                if s.pid:
                    await kill_process_tree(s.pid)
                s.exited = True
                s.exit_code = -9
                killed.append(sid)
        return _ok({"killed_sessions": killed})

    session_id = args.get("sessionId")
    if not session_id:
        return _err("sessionId required")

    session = _sessions.get(session_id)
    if not session:
        return _err(f"session {session_id!r} not found")

    if action == "poll":
        # Lock prevents race between _drain() setting the event and our
        # clear-then-check sequence losing output notifications.
        async with session._poll_lock:
            if session.pending_stdout or session.pending_stderr:
                pass  # return immediately — data already waiting
            elif not session.exited:
                session._new_output.clear()
                timeout = min(float(args.get("timeout", 10)), 60)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(session._new_output.wait(), timeout=timeout)

            stdout = "".join(session.pending_stdout)
            stderr = "".join(session.pending_stderr)
            session.pending_stdout.clear()
            session.pending_stderr.clear()

        return _ok(
            {
                "sessionId": session_id,
                "exited": session.exited,
                "exitCode": session.exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": session.truncated,
            }
        )

    elif action == "log":
        lines = int(args.get("lines", 50))
        tail_lines = session.aggregated.splitlines()[-lines:]
        tail = "\n".join(tail_lines)
        if len(tail) > _TAIL_SIZE:
            tail = tail[-_TAIL_SIZE:]
        return _ok(
            {
                "output": tail,
                "status": "exited" if session.exited else "running",
                "exitCode": session.exit_code,
            }
        )

    elif action == "kill":
        if session.exited:
            return _ok({"status": "already_exited", "exitCode": session.exit_code})
        from sci_fi_dashboard.process.kill_tree import kill_process_tree

        dead = False
        if session.pid:
            dead = await kill_process_tree(session.pid, grace_ms=3000)
        if session._task and not session._task.done():
            session._task.cancel()
        session.exited = True
        session.exit_code = -9
        return _ok({"killed": dead, "pid": session.pid, "sessionId": session_id})

    elif action == "write":
        data = args.get("data", "")
        eof = bool(args.get("eof", False))
        if not session._proc or session._proc.stdin is None:
            return _err("Session has no stdin")
        try:
            session._proc.stdin.write(data.encode())
            await session._proc.stdin.drain()
            if eof:
                session._proc.stdin.close()
        except Exception as e:
            return _err(f"Write failed: {e}")
        return _ok({"written": len(data), "eof": eof})

    return _err(f"unknown action: {action!r}")


_cleanup_task: asyncio.Task | None = None


async def main():
    global _cleanup_task
    setup_logging()
    logger.info("Starting Synapse Execution MCP Server")
    _cleanup_task = asyncio.create_task(_ttl_cleanup())
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        if _cleanup_task and not _cleanup_task.done():
            _cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _cleanup_task


if __name__ == "__main__":
    asyncio.run(main())
