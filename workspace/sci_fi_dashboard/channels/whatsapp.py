"""
WhatsAppChannel — Python supervisor + HTTP client for the Baileys Node.js bridge.

Lifecycle:
  start()  → validates Node.js 18+, spawns bridge subprocess, restarts on crash
             with exponential backoff (max MAX_RESTARTS=5). Designed to run as an
             asyncio.create_task() from ChannelRegistry.start_all().
  stop()   → SIGTERM → SIGKILL after 5 s; sets status to "stopped".

HTTP protocol:
  Uses httpx.AsyncClient to POST to bridge endpoints (/send, /typing, /seen)
  and GET from /health and /qr.  Bridge port defaults to 5010.

Windows note:
  WindowsProactorEventLoopPolicy is set at module import time so it is active
  before uvicorn (which imports api_gateway.py at module level) starts its loop.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

from .base import BaseChannel, ChannelMessage
from .security import ChannelSecurityConfig, PairingStore, resolve_dm_access

# ---------------------------------------------------------------------------
# Windows event-loop policy — must be set before any asyncio usage
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)

# Path: workspace/sci_fi_dashboard/channels/whatsapp.py → repo_root/baileys-bridge
# __file__ = .../workspace/sci_fi_dashboard/channels/whatsapp.py
# parent.parent.parent = .../workspace (3 levels)
# parent.parent.parent.parent = repo root (4 levels)
_BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "baileys-bridge"


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel adapter via self-managed Baileys Node.js microservice.

    Spawns the bridge as a subprocess and supervises it. On unexpected exit the
    supervisor restarts with exponential backoff, up to MAX_RESTARTS attempts.
    All outbound messaging and health queries are done via httpx against the
    bridge's HTTP API.
    """

    MAX_RESTARTS: int = 5
    INITIAL_BACKOFF: float = 0.0  # first restart immediate; subsequent: 1 s → 2 s → 4 s → … → 60 s

    def __init__(
        self,
        bridge_port: int = 5010,
        python_webhook_url: str = "",
        security_config: ChannelSecurityConfig | None = None,
        pairing_store: PairingStore | None = None,
    ) -> None:
        self._port = bridge_port
        self._webhook_url = python_webhook_url or "http://127.0.0.1:8000/channels/whatsapp/webhook"
        self._proc: asyncio.subprocess.Process | None = None
        self._bridge_pid: int | None = None
        self._status: str = "stopped"
        self.security_config = security_config
        self._pairing_store = pairing_store

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return "whatsapp"

    # ------------------------------------------------------------------
    # Node.js validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_nodejs() -> None:
        """
        Raise RuntimeError with a clear, actionable message if Node.js 18+ is absent.

        Checks PATH via shutil.which first (fast), then runs `node --version` to confirm
        the version major is >= 18.
        """
        node_path = shutil.which("node")
        if not node_path:
            raise RuntimeError(
                "Node.js is not installed or not on PATH.\n"
                "The Baileys WhatsApp bridge requires Node.js 18+.\n"
                "Install from: https://nodejs.org/en/download/\n"
                "Then restart Synapse."
            )
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
        version_str = result.stdout.strip().lstrip("v")  # e.g. "22.14.0"
        try:
            major = int(version_str.split(".")[0])
        except (ValueError, IndexError) as exc:
            raise RuntimeError(f"Could not parse Node.js version: {version_str!r}") from exc
        if major < 18:
            raise RuntimeError(
                f"Node.js {version_str} found but Node.js 18+ is required.\n"
                f"Upgrade from: https://nodejs.org/en/download/"
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Supervisor loop: validate Node.js, start bridge subprocess, restart on crash.

        Spawns `node baileys-bridge/index.js` with BRIDGE_PORT and PYTHON_WEBHOOK_URL
        env vars. Restarts up to MAX_RESTARTS times with exponential backoff (doubles
        each attempt, caps at 60 s). Runs until cancelled or exhausted.

        Called by ChannelRegistry.start_all() as asyncio.create_task(channel.start()).
        CancelledError propagates after graceful stop().
        """
        self._validate_nodejs()

        attempts = 0
        backoff = self.INITIAL_BACKOFF

        while attempts < self.MAX_RESTARTS:
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    "node",
                    str(_BRIDGE_DIR / "index.js"),
                    env={
                        **os.environ,
                        "BRIDGE_PORT": str(self._port),
                        "PYTHON_WEBHOOK_URL": self._webhook_url,
                    },
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(_BRIDGE_DIR),
                )
                self._bridge_pid = self._proc.pid
                self._status = "running"
                logger.info("[WA] Bridge started — PID %d port %d", self._bridge_pid, self._port)

                # Drain stderr asynchronously to prevent pipe buffer deadlock
                asyncio.create_task(self._drain_stderr(self._proc.stderr))

                await self._proc.wait()  # blocks until bridge exits
                rc = self._proc.returncode
                self._status = "crashed"
                logger.warning(
                    "[WA] Bridge exited (code %d), restarting in %.1fs (attempt %d/%d)",
                    rc,
                    backoff,
                    attempts + 1,
                    self.MAX_RESTARTS,
                )

                attempts += 1
                await asyncio.sleep(backoff)
                # After the first (immediate) restart, use exponential backoff
                backoff = min(max(backoff * 2, 1.0), 60.0)

            except asyncio.CancelledError:
                await self.stop()
                raise

        self._status = "failed"
        logger.error("[WA] Bridge failed %d times — giving up", self.MAX_RESTARTS)

    async def stop(self) -> None:
        """
        Gracefully terminate the bridge subprocess.

        Sends SIGTERM and waits up to 5 s, then SIGKILL if it has not exited.
        """
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except TimeoutError:
                self._proc.kill()
        self._status = "stopped"
        logger.info("[WA] Bridge stopped")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """
        Return a status dict describing the channel and bridge health.

        Polls bridge GET /health when the subprocess appears to be running.
        Returns:
            {
                "status":        "ok" | "down",
                "channel":       "whatsapp",
                "bridge_pid":    int | None,
                "bridge_status": str,
                "bridge":        dict,  # raw response from bridge GET /health
            }
        """
        running = self._proc is not None and self._proc.returncode is None
        bridge_health: dict = {"status": "down", "connection_state": "unknown"}
        if running:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"http://127.0.0.1:{self._port}/health")
                    bridge_health = r.json()
            except httpx.RequestError:
                bridge_health = {"status": "degraded", "error": "bridge_unreachable"}
        return {
            "status": "ok" if running else "down",
            "channel": "whatsapp",
            "bridge_pid": self._bridge_pid,
            "bridge_status": self._status,
            "bridge": bridge_health,
        }

    async def get_qr(self) -> str | None:
        """
        Fetch the QR string from bridge GET /qr for WhatsApp pairing.

        Returns None if already authenticated or bridge unreachable.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"http://127.0.0.1:{self._port}/qr")
                if r.status_code == 200:
                    return r.json().get("qr")
        except httpx.RequestError:
            pass
        return None

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, text: str) -> bool:
        """
        Send outbound message via bridge POST /send.

        Args:
            chat_id: WhatsApp JID (e.g. "1234567890@s.whatsapp.net").
            text:    Message body.

        Returns:
            True on HTTP 200, False on any error.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/send",
                    json={"jid": chat_id, "text": text},
                )
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] send() failed: %s", exc)
            return False

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator via bridge POST /typing."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"http://127.0.0.1:{self._port}/typing",
                    json={"jid": chat_id},
                )
        except httpx.RequestError:
            pass

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """Mark message as read via bridge POST /seen."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"http://127.0.0.1:{self._port}/seen",
                    json={"jid": chat_id, "messageId": message_id, "fromMe": False},
                )
        except httpx.RequestError:
            pass

    # ------------------------------------------------------------------
    # Inbound normalisation
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage | None:
        """
        Normalise a raw Baileys webhook payload to ChannelMessage.

        Bridge sends:
            {channel_id, user_id, chat_id, text, message_id,
             is_group, timestamp (Unix seconds), sender_name, raw}

        Returns None if the message is blocked by the DM security policy.
        """
        ts_raw = raw_payload.get("timestamp")
        timestamp = datetime.fromtimestamp(ts_raw) if ts_raw else datetime.now()
        cm = ChannelMessage(
            channel_id=raw_payload.get("channel_id", "whatsapp"),
            user_id=raw_payload.get("user_id", raw_payload.get("chat_id", "")),
            chat_id=raw_payload.get("chat_id", ""),
            text=raw_payload.get("text", ""),
            timestamp=timestamp,
            is_group=raw_payload.get("is_group", False),
            message_id=raw_payload.get("message_id", ""),
            sender_name=raw_payload.get("sender_name", ""),
            raw=raw_payload.get("raw", {}),
        )

        # DM security check — only for direct messages, skip groups
        if self.security_config and self._pairing_store and not cm.is_group:
            access = resolve_dm_access(cm.user_id, self.security_config, self._pairing_store)
            if access != "allow":
                logger.info("[WA] DM from %s blocked (%s)", cm.user_id, access)
                return None

        return cm

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _drain_stderr(stderr) -> None:
        """Drain subprocess stderr to prevent pipe buffer deadlock."""
        if stderr is None:
            return
        try:
            async for line in stderr:
                logger.debug("[WA-BRIDGE] %s", line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            pass
