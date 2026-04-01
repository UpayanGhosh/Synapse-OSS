"""
MCP Server: Synapse Execution — run shell commands and manage background processes.
Run standalone: python -m sci_fi_dashboard.mcp_servers.execution_server
"""
import asyncio
import json
import os
import signal
import time
import uuid
from dataclasses import dataclass, field

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .base import setup_logging, logger

server = Server("synapse-execution")

_OUTPUT_CAP = 100 * 1024  # 100 KB
_LOG_TAIL = 2000           # chars
_SESSION_TTL = 30 * 60     # 30 minutes


@dataclass
class ProcessSession:
    id: str
    command: str
    pid: int | None
    started_at: float
    aggregated: str = ""
    exit_code: int | None = None
    exited: bool = False
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)


_sessions: dict[str, ProcessSession] = {}


async def _collect_output(session: ProcessSession, proc: asyncio.subprocess.Process) -> None:
    """Stream stdout+stderr into session.aggregated, then capture exit code."""
    async def _read_stream(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace")
            session.aggregated += text
            if len(session.aggregated) > _OUTPUT_CAP:
                session.aggregated = session.aggregated[-_OUTPUT_CAP:]

    streams = []
    if proc.stdout:
        streams.append(_read_stream(proc.stdout))
    if proc.stderr:
        streams.append(_read_stream(proc.stderr))
    if streams:
        await asyncio.gather(*streams)

    await proc.wait()
    session.exit_code = proc.returncode
    session.exited = True


async def _ttl_cleanup() -> None:
    """Remove sessions older than SESSION_TTL."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        stale = [sid for sid, s in _sessions.items() if now - s.started_at > _SESSION_TTL]
        for sid in stale:
            sess = _sessions.pop(sid, None)
            if sess and sess._task and not sess._task.done():
                sess._task.cancel()
        if stale:
            logger.info("TTL cleanup removed %d sessions", len(stale))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="exec",
            description=(
                "Execute a shell command. "
                "If background=false (default), waits for completion and returns output. "
                "If background=true, spawns the process and returns a sessionId for polling."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "workdir": {
                        "type": "string",
                        "description": "Working directory (defaults to current directory)",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Seconds before killing foreground process (default 30)",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Spawn in background and return sessionId (default false)",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="process",
            description=(
                "Manage background processes. "
                "action: list | poll | log | kill. "
                "sessionId is required for all actions except list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "poll", "log", "kill"],
                    },
                    "sessionId": {"type": "string"},
                    "timeout": {
                        "type": "number",
                        "description": "Seconds to wait for new output in poll (default 10)",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of tail lines to return for log (default 50)",
                    },
                },
                "required": ["action"],
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
    command = args["command"]
    workdir = args.get("workdir") or os.getcwd()
    timeout = float(args.get("timeout", 30))
    background = bool(args.get("background", False))

    # TODO (Phase 4): add approval gating before execution

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"status": "error", "error": str(e)}))]

    if background:
        session_id = str(uuid.uuid4())
        session = ProcessSession(
            id=session_id,
            command=command,
            pid=proc.pid,
            started_at=time.monotonic(),
        )
        task = asyncio.create_task(_collect_output(session, proc))
        session._task = task
        _sessions[session_id] = session
        return [TextContent(
            type="text",
            text=json.dumps({"status": "running", "sessionId": session_id, "pid": proc.pid}),
        )]

    # Foreground: wait with timeout
    session = ProcessSession(
        id="",
        command=command,
        pid=proc.pid,
        started_at=time.monotonic(),
    )
    collect_task = asyncio.create_task(_collect_output(session, proc))
    try:
        await asyncio.wait_for(collect_task, timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return [TextContent(type="text", text=json.dumps({
            "status": "timeout",
            "exitCode": None,
            "output": session.aggregated[-_LOG_TAIL:],
        }))]

    return [TextContent(type="text", text=json.dumps({
        "status": "done",
        "exitCode": session.exit_code,
        "output": session.aggregated[-_LOG_TAIL:],
    }))]


async def _handle_process(args: dict) -> list[TextContent]:
    action = args.get("action", "")

    if action == "list":
        result = [
            {
                "sessionId": s.id,
                "command": s.command,
                "pid": s.pid,
                "status": "exited" if s.exited else "running",
                "exitCode": s.exit_code,
                "startedAgo": round(time.monotonic() - s.started_at, 1),
            }
            for s in _sessions.values()
        ]
        return [TextContent(type="text", text=json.dumps(result))]

    session_id = args.get("sessionId")
    if not session_id:
        return [TextContent(type="text", text=json.dumps({"error": "sessionId required"}))]

    session = _sessions.get(session_id)
    if not session:
        return [TextContent(type="text", text=json.dumps({"error": f"session {session_id!r} not found"}))]

    if action == "poll":
        poll_timeout = float(args.get("timeout", 10))
        prev_len = len(session.aggregated)
        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline and not session.exited:
            if len(session.aggregated) > prev_len:
                break
            await asyncio.sleep(0.2)
        new_output = session.aggregated[prev_len:]
        return [TextContent(type="text", text=json.dumps({
            "newOutput": new_output[-_LOG_TAIL:],
            "status": "exited" if session.exited else "running",
            "exitCode": session.exit_code,
        }))]

    elif action == "log":
        lines = int(args.get("lines", 50))
        tail_lines = session.aggregated.splitlines()[-lines:]
        tail = "\n".join(tail_lines)
        if len(tail) > _LOG_TAIL:
            tail = tail[-_LOG_TAIL:]
        return [TextContent(type="text", text=json.dumps({
            "output": tail,
            "status": "exited" if session.exited else "running",
            "exitCode": session.exit_code,
        }))]

    elif action == "kill":
        if session.exited:
            return [TextContent(type="text", text=json.dumps({"status": "already_exited", "exitCode": session.exit_code}))]
        if session.pid:
            try:
                os.kill(session.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        if session._task and not session._task.done():
            session._task.cancel()
        session.exited = True
        session.exit_code = -9
        return [TextContent(type="text", text=json.dumps({"status": "killed", "sessionId": session_id}))]

    return [TextContent(type="text", text=json.dumps({"error": f"unknown action: {action!r}"}))]


async def main():
    setup_logging()
    logger.info("Starting Synapse Execution MCP Server")
    asyncio.create_task(_ttl_cleanup())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
