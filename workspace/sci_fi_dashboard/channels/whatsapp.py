"""
WhatsAppChannel — Python supervisor + HTTP client for the Baileys Node.js bridge.

Lifecycle:
  start()  → validates Node.js 18+, spawns bridge subprocess, restarts on crash
             with exponential backoff (max MAX_RESTARTS=5). Designed to run as an
             asyncio.create_task() from ChannelRegistry.start_all().
  stop()   → SIGTERM → SIGKILL after 5 s; sets status to "stopped".

HTTP protocol:
  Uses httpx.AsyncClient to POST to bridge endpoints (/send, /typing, /seen, /react,
  /logout, /relink, /groups/*)  and GET from /health and /qr.  Bridge port defaults to 5010.

Windows note:
  WindowsProactorEventLoopPolicy is set at module import time so it is active
  before uvicorn (which imports api_gateway.py at module level) starts its loop.

Polling resilience (Phase 5):
  - wait_for_qr_login(): CLI-friendly QR polling with terminal rendering.
  - update_connection_state(): handles code 515 (restart-after-pairing).
  - health_check(): clears auth cache on 401 errors from bridge.
  - Network error classification via network_errors for smarter send retries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from sci_fi_dashboard.gateway.echo_tracker import OutboundTracker
from sci_fi_dashboard.observability import get_child_logger

from .base import BaseChannel, ChannelMessage
from .network_errors import is_safe_to_retry_send
from .security import ChannelSecurityConfig, PairingStore, resolve_dm_access
from .supervisor import ReconnectPolicy, WhatsAppSupervisor

# ---------------------------------------------------------------------------
# Windows event-loop policy — must be set before any asyncio usage
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)
_log = get_child_logger("channel.whatsapp")

# Path: workspace/sci_fi_dashboard/channels/whatsapp.py → repo_root/baileys-bridge
_BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "baileys-bridge"
_AUTH_STATE_DIR = _BRIDGE_DIR / "auth_state"


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel adapter via self-managed Baileys Node.js microservice.

    Spawns the bridge as a subprocess and supervises it. On unexpected exit the
    supervisor restarts with exponential backoff, up to MAX_RESTARTS attempts.
    All outbound messaging and health queries are done via httpx against the
    bridge's HTTP API.
    """

    def __init__(
        self,
        bridge_port: int = 5010,
        python_webhook_url: str = "",
        security_config: ChannelSecurityConfig | None = None,
        pairing_store: PairingStore | None = None,
        reconnect_policy: ReconnectPolicy | None = None,
    ) -> None:
        self._port = bridge_port
        self._webhook_url = python_webhook_url or "http://127.0.0.1:8000/channels/whatsapp/webhook"
        self._proc: asyncio.subprocess.Process | None = None
        self._bridge_pid: int | None = None
        self._status: str = "stopped"
        self.security_config = security_config
        self._pairing_store = pairing_store

        # Connection state tracking — updated by connection-state webhook
        self._connection_state: str = "unknown"
        self._connected_since: str | None = None
        self._auth_timestamp: str | None = None
        self._restart_count: int = 0
        self._last_disconnect_reason: str | None = None

        # Retry queue reference (injected by api_gateway after construction)
        self._retry_queue = None

        # SUPV-01..04: supervisor with configurable reconnect policy
        self._reconnect_policy = reconnect_policy or ReconnectPolicy()
        self._supervisor = WhatsAppSupervisor(
            restart_callback=self._restart_bridge,
            policy=self._reconnect_policy,
        )

        # ACL-01: self-echo tracker — ring buffer of last 20 outbound fingerprints
        self._echo_tracker = OutboundTracker(window_size=20, ttl_s=60.0)

        # Phase 16 BRIDGE-02/03: bridge health polling + restart race guard
        self._restart_in_progress: asyncio.Event = asyncio.Event()
        self._bridge_health_poller: Any = (
            None
        )  # type: "BridgeHealthPoller | None" — set by lifespan wiring (Plan 04)

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
    async def _validate_nodejs() -> None:
        node_path = shutil.which("node")
        if not node_path:
            raise RuntimeError(
                "Node.js is not installed or not on PATH.\n"
                "The Baileys WhatsApp bridge requires Node.js 18+.\n"
                "Install from: https://nodejs.org/en/download/\n"
                "Then restart Synapse."
            )
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_str = result.stdout.strip().lstrip("v")
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
        await self._validate_nodejs()
        await self._supervisor.start()  # SUPV-01: start inbound-silence watchdog

        attempts = 0
        policy = self._reconnect_policy

        while attempts < policy.max_attempts:
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    "node",
                    str(_BRIDGE_DIR / "index.js"),
                    env={
                        **os.environ,
                        "BRIDGE_PORT": str(self._port),
                        "PYTHON_WEBHOOK_URL": self._webhook_url,
                        "PYTHON_STATE_WEBHOOK_URL": self._webhook_url.replace(
                            "/webhook", "/connection-state"
                        ),
                    },
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(_BRIDGE_DIR),
                )
                self._bridge_pid = self._proc.pid
                self._status = "running"
                logger.info("[WA] Bridge started — PID %d port %d", self._bridge_pid, self._port)

                asyncio.create_task(self._drain_stderr(self._proc.stderr))

                await self._proc.wait()
                rc = self._proc.returncode
                self._status = "crashed"

                # SUPV-04: halt reconnect if non-retryable state reached
                if self._supervisor.stop_reconnect:
                    logger.warning(
                        "[WA] Reconnect halted (health_state=%s)",
                        self._supervisor.health_state,
                    )
                    self._status = "stopped"
                    await self._supervisor.stop()
                    return

                # SUPV-02: configurable backoff via policy
                backoff_s = policy.compute_backoff_s(attempts)
                logger.warning(
                    "[WA] Bridge exited (code %d), restarting in %.2fs (attempt %d/%d)",
                    rc,
                    backoff_s,
                    attempts + 1,
                    policy.max_attempts,
                )

                attempts += 1
                await asyncio.sleep(backoff_s)

                # Re-check stop_reconnect after sleep
                if self._supervisor.stop_reconnect:
                    logger.warning("[WA] Reconnect halted during backoff — stopping loop")
                    self._status = "stopped"
                    await self._supervisor.stop()
                    return

            except asyncio.CancelledError:
                await self.stop()
                raise

        self._status = "failed"
        logger.error("[WA] Bridge failed %d times — giving up", policy.max_attempts)
        await self._supervisor.stop()

    async def stop(self) -> None:
        await self._supervisor.stop()  # SUPV-01: stop watchdog before bridge kill
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except TimeoutError:
                self._proc.kill()
        self._status = "stopped"
        logger.info("[WA] Bridge stopped")

    async def _restart_bridge(self) -> None:
        """Stop and restart the bridge subprocess.

        Triggered by:
          - code 515 (restart-after-pairing) when Baileys needs a fresh connection
            with the newly saved auth state (Phase 14 flow)
          - Phase 16 BridgeHealthPoller after N consecutive /health failures

        Phase 16 BRIDGE-03/G2: `_restart_in_progress` Event prevents concurrent
        restarts. If watchdog + poller both fire simultaneously, the second call
        no-ops and the first completes.
        """
        if self._restart_in_progress.is_set():
            logger.warning("[WA] Bridge restart already in progress — skipping duplicate")
            return
        self._restart_in_progress.set()
        try:
            logger.info("[WA] Restarting bridge (Phase 16 gated restart)")
            await self.stop()
            # start() is normally run as a task — spawn it as a background task
            asyncio.create_task(self.start())
        finally:
            # Clear the flag AFTER scheduling start(). The poller's grace window
            # (Phase 16 G4) handles the "wait for bridge to come up" period —
            # we don't block _restart_bridge on readiness.
            self._restart_in_progress.clear()

    # ------------------------------------------------------------------
    # Connection state tracking (called by connection-state webhook)
    # ------------------------------------------------------------------

    async def update_connection_state(self, payload: dict) -> None:
        """Update internal state from bridge connection-state webhook payload.

        Handles code 515 (restart-after-pairing): when Baileys signals that the
        session was freshly paired and needs a restart, we wait briefly for the
        auth_state to be written to disk, then restart the bridge.
        """
        self._connection_state = payload.get("connectionState", "unknown")
        self._connected_since = payload.get("connectedSince")
        self._auth_timestamp = payload.get("authTimestamp")
        self._restart_count = payload.get("restartCount", 0)
        self._last_disconnect_reason = payload.get("lastDisconnectReason")

        # SUPV-03/04: drive state machine from bridge signals
        if self._connection_state == "connected":
            self._supervisor.note_connected()
        elif self._connection_state in ("logged_out", "reconnecting"):
            self._supervisor.note_disconnect(self._last_disconnect_reason)

        # Code 515: restart-after-pairing
        disconnect_reason = payload.get("lastDisconnectReason")
        if disconnect_reason == 515 or disconnect_reason == "515":
            logger.info("[WA] Code 515 detected — scheduling bridge restart after auth_state write")
            await asyncio.sleep(2)  # wait for auth_state write
            await self._restart_bridge()
            return

        # If bridge reconnected and we have a retry queue, flush pending retries
        if self._connection_state == "connected" and self._retry_queue is not None:
            asyncio.create_task(self._retry_queue.flush())

    # ------------------------------------------------------------------
    # Health and status
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """Return bridge health, clearing auth cache on 401 errors."""
        running = self._proc is not None and self._proc.returncode is None
        bridge_health: dict = {"status": "down", "connection_state": "unknown"}
        if running:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"http://127.0.0.1:{self._port}/health")
                    if r.status_code == 401:
                        logger.warning("[WA] Health check returned 401 — clearing stale auth cache")
                        self._clear_auth_cache()
                        bridge_health = {
                            "status": "degraded",
                            "error": "auth_expired",
                            "hint": "Run /relink or scan QR again",
                        }
                    else:
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

    def _clear_auth_cache(self) -> None:
        """Remove stale auth_state directory so the next restart triggers a fresh QR."""
        if _AUTH_STATE_DIR.exists():
            try:
                import shutil as _shutil

                _shutil.rmtree(_AUTH_STATE_DIR, ignore_errors=True)
                logger.info("[WA] Cleared auth_state at %s", _AUTH_STATE_DIR)
            except OSError as exc:
                logger.warning("[WA] Failed to clear auth_state: %s", exc)

    _HEALTH_STATE_MAP: dict[str, str] = {
        "connected": "connected",
        "logged_out": "logged-out",
        "reconnecting": "reconnecting",
        "conflict": "conflict",
    }

    async def get_status(self) -> dict:
        """Enhanced health check with auth age, uptime, and connection metrics."""
        base = await self.health_check()
        base["connected_since"] = self._connected_since
        base["auth_timestamp"] = self._auth_timestamp
        base["restart_count"] = self._restart_count
        base["last_disconnect_reason"] = self._last_disconnect_reason
        base["connection_state"] = self._connection_state
        base["isLoggedOut"] = self._connection_state == "logged_out"
        # SUPV-03: authoritative healthState from supervisor
        if self._status in ("stopped", "failed"):
            base["healthState"] = "stopped"
        else:
            base["healthState"] = self._supervisor.health_state
        base["stop_reconnect"] = self._supervisor.stop_reconnect
        # Phase 16 BRIDGE-02: expose most recent /health poll result
        if self._bridge_health_poller is not None:
            base["bridge_health"] = self._bridge_health_poller.last_health
        else:
            base["bridge_health"] = {}
        # Phase 16 BRIDGE-04: expose dedup telemetry (hit/miss counts + hit rate)
        try:
            from sci_fi_dashboard import _deps as _deps_mod

            _dedup = getattr(_deps_mod, "dedup", None)
            if _dedup is not None:
                base["dedup"] = {
                    "hits": int(getattr(_dedup, "hits", 0)),
                    "misses": int(getattr(_dedup, "misses", 0)),
                    "hit_rate": float(_dedup.hit_rate()) if hasattr(_dedup, "hit_rate") else 0.0,
                }
            else:
                base["dedup"] = {"hits": 0, "misses": 0, "hit_rate": 0.0}
        except Exception:
            base["dedup"] = {"hits": 0, "misses": 0, "hit_rate": 0.0}
        return base

    async def get_qr(self) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"http://127.0.0.1:{self._port}/qr")
                if r.status_code == 200:
                    return r.json().get("qr")
        except httpx.RequestError:
            pass
        return None

    # ------------------------------------------------------------------
    # QR Login CLI (Phase 5)
    # ------------------------------------------------------------------

    async def wait_for_qr_login(self, timeout: int = 120) -> bool:
        """Poll the bridge ``/qr`` endpoint until connected or timeout.

        Prints QR data to the terminal so the user can scan with their phone.
        Returns ``True`` if the bridge transitions to ``connected`` state
        within *timeout* seconds, ``False`` otherwise.

        Args:
            timeout: Maximum seconds to wait for a successful scan.

        Returns:
            True if connected, False if timed out.
        """
        logger.info("[WA] Waiting for QR login (timeout=%ds)", timeout)
        poll_interval = 3.0
        elapsed = 0.0
        last_qr: str | None = None

        while elapsed < timeout:
            # Check if already connected
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(f"http://127.0.0.1:{self._port}/health")
                    if r.status_code == 200:
                        health = r.json()
                        if (
                            health.get("connection_state") == "connected"
                            or health.get("status") == "connected"
                        ):
                            logger.info("[WA] QR login successful — bridge connected")
                            return True
            except httpx.RequestError:
                pass

            # Fetch and display QR
            qr_data = await self.get_qr()
            if qr_data and qr_data != last_qr:
                last_qr = qr_data
                print(f"\n[WA] Scan this QR code with WhatsApp:\n{qr_data}\n")
                logger.info("[WA] New QR code displayed — waiting for scan...")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning("[WA] QR login timed out after %ds", timeout)
        return False

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def logout(self) -> bool:
        """POST /logout — deregister linked device and wipe session."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"http://127.0.0.1:{self._port}/logout")
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] logout() failed: %s", exc)
            return False

    async def relink(self) -> bool:
        """POST /relink — force fresh QR cycle without full logout."""
        self._supervisor.reset_stop_reconnect()  # SUPV-04: clear halt flag
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"http://127.0.0.1:{self._port}/relink")
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] relink() failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, text: str) -> bool:
        """Send a text message, with network error classification for retry logic."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/send",
                    json={"jid": chat_id, "text": text},
                )
                success = r.status_code == 200
                if success:
                    # ACL-01: record only on confirmed success (failed sends must not pollute tracker)
                    self._echo_tracker.record(chat_id, text)
                return success
        except httpx.RequestError as exc:
            if is_safe_to_retry_send(exc):
                logger.warning("[WA] send() pre-connect failure (retryable): %s", exc)
            else:
                logger.error("[WA] send() failed: %s", exc)
            return False

    async def send_media(
        self,
        chat_id: str,
        media_url: str,
        media_type: str = "image",
        caption: str = "",
    ) -> bool:
        """Send media (image/video/audio/document) via bridge POST /send."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/send",
                    json={
                        "jid": chat_id,
                        "mediaUrl": media_url,
                        "mediaType": media_type,
                        "caption": caption,
                    },
                )
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] send_media() failed: %s", exc)
            return False

    async def send_voice_note(self, chat_id: str, audio_url: str) -> bool:
        """Send OGG Opus audio as a WhatsApp PTT voice note via bridge /send-voice."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/send-voice",
                    json={"jid": chat_id, "audioUrl": audio_url},
                )
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] send_voice_note() failed: %s", exc)
            return False

    async def send_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        """Send emoji reaction to a message via bridge POST /react."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/react",
                    json={"jid": chat_id, "messageId": message_id, "reaction": emoji},
                )
                return r.status_code == 200
        except httpx.RequestError as exc:
            logger.error("[WA] send_reaction() failed: %s", exc)
            return False

    async def send_typing(self, chat_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"http://127.0.0.1:{self._port}/typing",
                    json={"jid": chat_id},
                )
        except httpx.RequestError:
            pass

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"http://127.0.0.1:{self._port}/seen",
                    json={"jid": chat_id, "messageId": message_id, "fromMe": False},
                )
        except httpx.RequestError:
            pass

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    async def create_group(self, subject: str, participants: list[str]) -> dict:
        """Create a WhatsApp group. Returns bridge response dict."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"http://127.0.0.1:{self._port}/groups/create",
                json={"subject": subject, "participants": participants},
            )
            r.raise_for_status()
            return r.json()

    async def invite_to_group(self, group_jid: str, participants: list[str]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/groups/invite",
                    json={"jid": group_jid, "participants": participants},
                )
                return r.status_code == 200
        except httpx.RequestError:
            return False

    async def leave_group(self, group_jid: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/groups/leave",
                    json={"jid": group_jid},
                )
                return r.status_code == 200
        except httpx.RequestError:
            return False

    async def update_group_subject(self, group_jid: str, subject: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"http://127.0.0.1:{self._port}/groups/update",
                    json={"jid": group_jid, "subject": subject},
                )
                return r.status_code == 200
        except httpx.RequestError:
            return False

    async def get_group_metadata(self, group_jid: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"http://127.0.0.1:{self._port}/groups/{group_jid}")
                if r.status_code == 200:
                    return r.json()
        except httpx.RequestError:
            pass
        return None

    # ------------------------------------------------------------------
    # Inbound normalisation
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage | None:
        """
        Normalise a raw Baileys webhook payload to ChannelMessage.

        Handles message types: text, media (image/video/audio/document/sticker),
        reactions, typing indicators, message status updates.

        Returns None for non-message events (status/typing) or blocked DMs.
        """
        payload_type = raw_payload.get("type", "message")

        # Non-message events — handled by dedicated routes, not the message pipeline
        if payload_type in ("message_status", "typing_indicator", "reaction"):
            return None

        ts_raw = raw_payload.get("timestamp")
        timestamp = datetime.fromtimestamp(ts_raw) if ts_raw else datetime.now()

        # Build raw dict with media metadata for MsgContext population
        raw_extra: dict = dict(raw_payload.get("raw", {}))
        if raw_payload.get("mediaType"):
            raw_extra["media_type"] = raw_payload["mediaType"]
            raw_extra["media_url"] = raw_payload.get("mediaUrl", "")
            raw_extra["media_mime_type"] = raw_payload.get("mediaMimeType", "")

        cm = ChannelMessage(
            channel_id=raw_payload.get("channel_id", "whatsapp"),
            user_id=raw_payload.get("user_id", raw_payload.get("chat_id", "")),
            chat_id=raw_payload.get("chat_id", ""),
            text=raw_payload.get("text", "") or raw_payload.get("mediaCaption", ""),
            timestamp=timestamp,
            is_group=raw_payload.get("is_group", False),
            message_id=raw_payload.get("message_id", ""),
            sender_name=raw_payload.get("sender_name", ""),
            raw=raw_extra,
        )

        # DM security check — only for direct messages, skip groups
        if self.security_config and self._pairing_store and not cm.is_group:
            access = resolve_dm_access(cm.user_id, self.security_config, self._pairing_store)
            if access != "allow":
                _log.info(
                    "dm_blocked",
                    extra={"user_id": cm.user_id, "access": access},
                )
                return None

        # --- Audio / voice message transcription ---
        await self._maybe_transcribe_audio(cm, raw_payload)

        return cm

    # ------------------------------------------------------------------
    # Audio transcription
    # ------------------------------------------------------------------

    async def _maybe_transcribe_audio(self, cm: ChannelMessage, raw_payload: dict) -> None:
        """Transcribe audio/voice messages via Groq Whisper and update *cm* in-place.

        If the incoming message is an audio type with a ``mediaUrl``, the audio
        is downloaded to a temporary file, transcribed, and the resulting text
        replaces the ChannelMessage ``text`` field (prefixed with
        ``[Voice message]``).  On failure, a polite fallback is set instead.

        This is a no-op for non-audio messages.
        """
        media_type = (raw_payload.get("mediaType") or "").lower()
        mime_type = (raw_payload.get("mediaMimeType") or "").lower()
        media_url = raw_payload.get("mediaUrl") or ""

        is_audio = media_type == "audio" or mime_type.startswith("audio/")
        if not is_audio or not media_url:
            return

        # Lazy import to avoid circular dependency at module level
        from sci_fi_dashboard.media.audio_transcriber import transcribe_audio

        # Determine file extension from MIME type for server-side detection
        ext = ".ogg"
        if "mp3" in mime_type or "mpeg" in mime_type:
            ext = ".mp3"
        elif "mp4" in mime_type or "m4a" in mime_type:
            ext = ".m4a"
        elif "wav" in mime_type:
            ext = ".wav"
        elif "webm" in mime_type:
            ext = ".webm"

        tmp_path: Path | None = None
        try:
            # Download audio from bridge
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(media_url)
                if resp.status_code != 200:
                    logger.warning(
                        "[WA] Audio download failed (HTTP %d) from %s",
                        resp.status_code,
                        media_url,
                    )
                    cm.text = "I couldn't process that voice message, sorry."
                    return

            # Write to temp file
            tmp_fd, tmp_str = tempfile.mkstemp(suffix=ext, prefix="synapse_voice_")
            tmp_path = Path(tmp_str)
            try:
                os.write(tmp_fd, resp.content)
            finally:
                os.close(tmp_fd)

            # Transcribe
            transcript = await transcribe_audio(tmp_path)

            if transcript:
                cm.text = f"[Voice message] {transcript}"
                cm.transcript = transcript
                logger.info(
                    "[WA] Voice transcription OK for msg %s (%d chars)",
                    cm.message_id,
                    len(transcript),
                )
            else:
                cm.text = "I couldn't process that voice message, sorry."
                logger.warning(
                    "[WA] Voice transcription returned empty for msg %s",
                    cm.message_id,
                )

        except Exception as exc:
            logger.error("[WA] Audio transcription failed for msg %s: %s", cm.message_id, exc)
            cm.text = "I couldn't process that voice message, sorry."
        finally:
            # Clean up temp file
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)

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
                _log.debug(
                    "bridge_stderr",
                    extra={"text": line.decode(errors="replace").rstrip()},
                )
        except asyncio.CancelledError:
            pass
