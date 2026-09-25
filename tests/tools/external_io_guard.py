"""Test-only process-wide deny guard for outbound I/O in Synapse simulations."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import httpx


class ExternalIOBlockedError(RuntimeError):
    """Raised whenever simulation code tries network or child-process I/O."""


class ExternalIODenyGuard:
    def __init__(self, artifact_path: str | Path | None = None) -> None:
        self.artifact_path = Path(artifact_path) if artifact_path is not None else None
        self.attempts: list[dict[str, str]] = []
        self._originals: list[tuple[object, str, object]] = []
        self._socketpair_local = threading.local()

    def install(self) -> None:
        self._patch(socket.socket, "connect", "socket.connect")
        self._patch(socket.socket, "connect_ex", "socket.connect_ex")
        self._patch(socket, "create_connection", "socket.create_connection")
        self._patch(socket, "getaddrinfo", "socket.getaddrinfo")
        self._patch_socketpair()
        self._patch(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            "httpx.AsyncHTTPTransport.handle_async_request",
        )
        self._patch(httpx.HTTPTransport, "handle_request", "httpx.HTTPTransport.handle_request")
        self._patch(subprocess, "Popen", "subprocess.Popen")
        self._patch(os, "system", "os.system")
        self._patch(asyncio, "create_subprocess_exec", "asyncio.create_subprocess_exec")
        self._patch(asyncio, "create_subprocess_shell", "asyncio.create_subprocess_shell")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return
        loop_type = type(loop)
        if hasattr(loop_type, "subprocess_exec"):
            self._patch(loop_type, "subprocess_exec", "event_loop.subprocess_exec")
        if hasattr(loop_type, "subprocess_shell"):
            self._patch(loop_type, "subprocess_shell", "event_loop.subprocess_shell")
        if hasattr(os, "startfile"):
            self._patch(os, "startfile", "os.startfile")

    def restore(self) -> None:
        while self._originals:
            obj, name, value = self._originals.pop()
            setattr(obj, name, value)
        self._write_attempts()

    def _patch(self, obj: object, name: str, kind: str) -> None:
        original = getattr(obj, name)
        self._originals.append((obj, name, original))

        def blocked(*args, **_kwargs):
            if (
                kind == "socket.connect"
                and getattr(self._socketpair_local, "active", False)
                and len(args) > 1
                and isinstance(args[1], tuple)
                and args[1]
                and args[1][0] in {"127.0.0.1", "::1"}
            ):
                return original(*args, **_kwargs)
            detail = self._safe_detail(kind, args)
            event = {"kind": kind, "detail": detail}
            self.attempts.append(event)
            self._write_attempts()
            raise ExternalIOBlockedError(
                f"simulation blocked outbound operation: {kind} ({detail})"
            )

        setattr(obj, name, blocked)

    def _patch_socketpair(self) -> None:
        original = socket.socketpair
        self._originals.append((socket, "socketpair", original))

        def guarded_socketpair(*args, **kwargs):
            previous = getattr(self._socketpair_local, "active", False)
            self._socketpair_local.active = True
            try:
                return original(*args, **kwargs)
            finally:
                self._socketpair_local.active = previous

        socket.socketpair = guarded_socketpair

    @staticmethod
    def _safe_detail(kind: str, args: tuple) -> str:
        if kind.startswith("socket."):
            address = args[1] if len(args) > 1 else "unknown"
            if isinstance(address, tuple) and len(address) >= 2:
                return f"{address[0]}:{address[1]}"
            return str(address)[:120]
        if kind == "subprocess.Popen":
            command = args[0] if args else "unknown"
            if isinstance(command, (list, tuple)):
                command = command[0] if command else "unknown"
            return Path(str(command)).name[:120]
        return "blocked"

    def _write_attempts(self) -> None:
        if self.artifact_path is None:
            return
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(
            json.dumps(self.attempts, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
