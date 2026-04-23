"""Phase 16 HEART-01..05 — scheduled heartbeat runner for WhatsApp.

Port of OpenClaw's TypeScript heartbeat implementation:
  - extensions/whatsapp/src/auto-reply/heartbeat-runner.ts::runWebHeartbeatOnce
  - extensions/whatsapp/src/heartbeat-recipients.ts::resolveWhatsAppHeartbeatRecipients
  - src/auto-reply/tokens.ts::HEARTBEAT_TOKEN
  - src/auto-reply/heartbeat.ts::stripHeartbeatToken
  - src/infra/heartbeat-visibility.ts::resolveHeartbeatVisibility
  - src/infra/heartbeat-runner.ts::startHeartbeatRunner (scheduling loop)

Scheduling loop mirrors sci_fi_dashboard/channels/polling_watchdog.py (asyncio.create_task
+ asyncio.sleep). No APScheduler dependency.

Reuse from Phase 13 observability:
  - mint_run_id (per-cycle correlation ID)
  - get_child_logger (structured JSON logs)
  - redact_identifier (recipient JID redaction before logging)

HEART-05 never-crash contract: every exception inside _run_cycle is caught and logged
at WARNING level. The loop continues. Only asyncio.CancelledError exits the loop (via stop()).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sci_fi_dashboard.observability import (
    get_child_logger,
    mint_run_id,
    redact_identifier,
)

_log = get_child_logger("gateway.heartbeat")


# ---------------------------------------------------------------------------
# Constants — VERBATIM PORT from OpenClaw src/auto-reply/tokens.ts + heartbeat.ts
# ---------------------------------------------------------------------------

HEARTBEAT_TOKEN: str = "HEARTBEAT_OK"
"""Magic string the LLM replies when there is nothing to report.

Source: D:/Shorty/openclaw/src/auto-reply/tokens.ts:3 — VERIFIED via direct read.
"""

DEFAULT_HEARTBEAT_PROMPT: str = "Health check — any updates?"
"""Fallback prompt when synapse.json does not specify heartbeat.prompt."""

DEFAULT_HEARTBEAT_ACK_MAX_CHARS: int = 300
"""Matches OpenClaw's DEFAULT_HEARTBEAT_ACK_MAX_CHARS constant."""


# ---------------------------------------------------------------------------
# Visibility flags — VERBATIM PORT from src/infra/heartbeat-visibility.ts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeartbeatVisibility:
    """Independent visibility flags per HEART-04.

    show_ok: if True AND LLM reply is empty/HEARTBEAT_OK, send literal HEARTBEAT_OK.
             if False, stay silent on ok-responses.
    show_alerts: if True, forward content replies (non-empty, non-HEARTBEAT_OK) to recipient.
                 if False, drop content replies — telemetry-only mode.
    use_indicator: if True, emit payloads include `indicator_type` for UI badges.
                   if False, emit payloads omit that field.

    Defaults match OpenClaw resolveHeartbeatVisibility (show_ok=False, show_alerts=True,
    use_indicator=True). VERIFIED via direct read of
    D:/Shorty/openclaw/src/infra/heartbeat-visibility.ts.
    """

    show_ok: bool = False
    show_alerts: bool = True
    use_indicator: bool = True


def resolve_heartbeat_visibility(cfg: Any) -> HeartbeatVisibility:
    """Resolve visibility flags from cfg.heartbeat['visibility'] with OpenClaw defaults."""
    heartbeat = getattr(cfg, "heartbeat", None) or {}
    vis = heartbeat.get("visibility", {}) if isinstance(heartbeat, dict) else {}
    return HeartbeatVisibility(
        show_ok=bool(vis.get("showOk", False)),
        show_alerts=bool(vis.get("showAlerts", True)),
        use_indicator=bool(vis.get("useIndicator", True)),
    )


# ---------------------------------------------------------------------------
# Recipient resolution (HEART-01)
# ---------------------------------------------------------------------------


def resolve_recipients(cfg: Any, to_override: str | None = None) -> list[str]:
    """Resolve the list of heartbeat recipient JIDs.

    Priority (OpenClaw-simplified):
      1. to_override (single recipient, for manual/dry-run triggers)
      2. cfg.heartbeat['recipients'] list
      3. [] (empty → no-op cycle)

    Returns list[str] of trimmed JIDs. Empty entries skipped.
    """
    if to_override:
        stripped = to_override.strip()
        return [stripped] if stripped else []

    heartbeat = getattr(cfg, "heartbeat", None) or {}
    recipients = heartbeat.get("recipients", []) if isinstance(heartbeat, dict) else []
    if not isinstance(recipients, list):
        return []
    return [r.strip() for r in recipients if isinstance(r, str) and r.strip()]


# ---------------------------------------------------------------------------
# HEARTBEAT_TOKEN strip (HEART-03) — VERBATIM PORT from src/auto-reply/heartbeat.ts:117-178
# ---------------------------------------------------------------------------


_TAIL_RE = re.compile(re.escape(HEARTBEAT_TOKEN) + r"[^\w]{0,4}$")


def strip_heartbeat_token(
    raw: str,
    max_ack_chars: int = DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
) -> tuple[str, bool]:
    """Strip HEARTBEAT_OK from the start/end of text.

    Returns (stripped, should_skip):
      - should_skip=True iff the text was entirely the token (possibly with
        whitespace or up to 4 trailing non-word chars).
      - should_skip=False iff there is residual content after stripping.

    Algorithm (verified from OpenClaw heartbeat.ts):
      1. If token not in text → return text[:max_ack_chars], False
      2. Iteratively strip from start if text begins with HEARTBEAT_OK
      3. Iteratively strip from end using regex HEARTBEAT_OK[^\\w]{0,4}$
      4. Collapse whitespace; truncate to max_ack_chars
      5. should_skip = not collapsed.strip()
    """
    if not raw:
        return "", True
    text = raw.strip()
    if not text:
        return "", True
    if HEARTBEAT_TOKEN not in text:
        return text[:max_ack_chars], False

    changed = True
    while changed:
        changed = False
        next_text = text.strip()
        if next_text.startswith(HEARTBEAT_TOKEN):
            text = next_text[len(HEARTBEAT_TOKEN) :].lstrip()
            changed = True
            continue
        m = _TAIL_RE.search(next_text)
        if m:
            text = next_text[: m.start()].rstrip()
            changed = True

    collapsed = re.sub(r"\s+", " ", text).strip()
    # Heartbeat-mode post-strip: short residue consisting entirely of non-word
    # chars (punct like "!", ".", "...", " ;") is treated as a skip — mirrors
    # OpenClaw stripHeartbeatToken mode="heartbeat" branch (lines 171-175).
    if collapsed and re.fullmatch(r"[^\w]{1,4}", collapsed):
        return "", True
    return collapsed[:max_ack_chars], not collapsed


# ---------------------------------------------------------------------------
# HeartbeatRunner — scheduling + per-cycle orchestration (HEART-05 never-crash)
# ---------------------------------------------------------------------------


class _EmitterProto(Protocol):
    """Minimal duck-type for PipelineEventEmitter (Phase 13)."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None: ...


class HeartbeatRunner:
    """Asyncio-based heartbeat scheduler.

    Lifecycle mirrors channels/polling_watchdog.py::PollingWatchdog:
      - start() spawns an asyncio.Task running _loop()
      - stop() cancels the task and awaits clean exit
      - _loop() sleeps interval_s between cycles, catches ALL exceptions (HEART-05)

    Per-cycle orchestration (run_cycle_once):
      1. Mint fresh runId (ContextVar — inherited by channel.send downstream)
      2. Resolve recipients via resolve_recipients(cfg)
      3. For each recipient: await run_heartbeat_once(to) with isolated exception scope
      4. Exceptions inside any single run_heartbeat_once do NOT abort the cycle

    Per-recipient logic (run_heartbeat_once):
      - Guard: if all 3 visibility flags are False, skip with emit
      - Build prompt from cfg.heartbeat.prompt OR DEFAULT_HEARTBEAT_PROMPT
      - Call get_reply_fn(prompt) — async wrapper around persona_chat
      - Strip HEARTBEAT_OK; branch on should_skip + visibility flags
      - Emit events at every decision boundary (heartbeat.send_start, .sent, .ok_token, .skipped, .failed)
    """

    def __init__(
        self,
        channel_registry: Any,
        cfg: Any,
        get_reply_fn: Callable[[str], Awaitable[str]],
        emitter: _EmitterProto | None = None,
        interval_s: float = 1800.0,
        channel_name: str = "whatsapp",
    ) -> None:
        self._channel_registry = channel_registry
        self._cfg = cfg
        self._get_reply_fn = get_reply_fn
        self._emitter = emitter
        self._interval_s = float(interval_s)
        self._channel_name = channel_name

        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._cycle_count: int = 0

    # -------- lifecycle --------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop())
        _log.info(
            "heartbeat_runner_started",
            extra={"interval_s": self._interval_s, "channel": self._channel_name},
        )

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        _log.info("heartbeat_runner_stopped")

    async def _loop(self) -> None:
        """Background scheduler loop. HEART-05: never crashes."""
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(self._interval_s)
                if self._stopped.is_set():
                    break
                try:
                    await self.run_cycle_once()
                except Exception as exc:  # noqa: BLE001 — HEART-05 explicit
                    _log.warning(
                        "heartbeat_cycle_failed",
                        extra={"error": str(exc), "cycle": self._cycle_count},
                    )
        except asyncio.CancelledError:
            pass

    # -------- public orchestration --------

    async def run_cycle_once(self) -> None:
        """Run one full cycle: all recipients, fresh runId."""
        self._cycle_count += 1
        mint_run_id()
        recipients = resolve_recipients(self._cfg)
        ch = self._channel_registry.get(self._channel_name) if self._channel_registry else None
        if ch is None or not recipients:
            _log.debug(
                "heartbeat_cycle_skipped",
                extra={"reason": "no-channel-or-recipients", "recipients": len(recipients)},
            )
            return

        # Guard: if Phase 14 supervisor halted the channel, do not attempt sends (G5 from RESEARCH.md)
        sup = getattr(ch, "_supervisor", None)
        if sup is not None and getattr(sup, "stop_reconnect", False):
            _log.info("heartbeat_cycle_skipped", extra={"reason": "supervisor-halted"})
            return

        for to in recipients:
            try:
                await self.run_heartbeat_once(to)
            except Exception as exc:  # noqa: BLE001 — HEART-05 per-recipient isolation
                _log.warning(
                    "heartbeat_recipient_failed",
                    extra={"to": to, "error": str(exc)},
                )

    async def run_heartbeat_once(self, to: str, dry_run: bool = False) -> None:
        """Run one heartbeat for a single recipient.

        Emits events at every decision boundary. Never raises — all exceptions
        caught and emitted as heartbeat.failed (HEART-05).
        """
        visibility = resolve_heartbeat_visibility(self._cfg)
        to_redacted = redact_identifier(to)
        heartbeat_cfg = getattr(self._cfg, "heartbeat", {}) or {}
        prompt: str = heartbeat_cfg.get("prompt") or DEFAULT_HEARTBEAT_PROMPT
        ack_max = int(heartbeat_cfg.get("ack_max_chars", DEFAULT_HEARTBEAT_ACK_MAX_CHARS))

        # Guard: fully-silent visibility → emit skip and return
        if not (visibility.show_alerts or visibility.show_ok or visibility.use_indicator):
            self._emit(
                "heartbeat.skipped",
                {
                    "to_redacted": to_redacted,
                    "reason": "all-flags-false",
                },
            )
            return

        self._emit(
            "heartbeat.send_start",
            self._with_indicator(
                visibility,
                {
                    "to_redacted": to_redacted,
                    "prompt_preview": prompt[:60],
                },
                "sending",
            ),
        )

        try:
            reply = await self._get_reply_fn(prompt)
        except Exception as exc:  # noqa: BLE001 — HEART-05
            _log.warning(
                "heartbeat_llm_failed",
                extra={"to": to, "error": str(exc)},
            )
            self._emit(
                "heartbeat.failed",
                self._with_indicator(
                    visibility,
                    {
                        "to_redacted": to_redacted,
                        "error": str(exc),
                        "stage": "llm",
                    },
                    "failed",
                ),
            )
            return

        stripped, should_skip = strip_heartbeat_token(reply or "", max_ack_chars=ack_max)
        ch = self._channel_registry.get(self._channel_name)

        if should_skip:
            # HEARTBEAT_OK path
            if visibility.show_ok and not dry_run:
                try:
                    await ch.send(to, HEARTBEAT_TOKEN)
                except Exception as exc:  # noqa: BLE001 — HEART-05
                    _log.warning(
                        "heartbeat_ok_send_failed",
                        extra={"to": to, "error": str(exc)},
                    )
                    self._emit(
                        "heartbeat.failed",
                        self._with_indicator(
                            visibility,
                            {
                                "to_redacted": to_redacted,
                                "error": str(exc),
                                "stage": "send-ok",
                            },
                            "failed",
                        ),
                    )
                    return
                self._emit(
                    "heartbeat.ok_token",
                    self._with_indicator(
                        visibility,
                        {
                            "to_redacted": to_redacted,
                            "silent": False,
                        },
                        "ok-token",
                    ),
                )
            else:
                self._emit(
                    "heartbeat.ok_token",
                    {"to_redacted": to_redacted, "silent": True},
                )
            return

        # Content reply path
        if not visibility.show_alerts or dry_run:
            self._emit(
                "heartbeat.skipped",
                {
                    "to_redacted": to_redacted,
                    "reason": "alerts-disabled" if not visibility.show_alerts else "dry-run",
                },
            )
            return

        try:
            await ch.send(to, stripped)
        except Exception as exc:  # noqa: BLE001 — HEART-05
            _log.warning(
                "heartbeat_send_failed",
                extra={"to": to, "error": str(exc)},
            )
            self._emit(
                "heartbeat.failed",
                self._with_indicator(
                    visibility,
                    {
                        "to_redacted": to_redacted,
                        "error": str(exc),
                        "stage": "send-content",
                    },
                    "failed",
                ),
            )
            return

        self._emit(
            "heartbeat.sent",
            self._with_indicator(
                visibility,
                {
                    "to_redacted": to_redacted,
                    "chars": len(stripped),
                },
                "sent",
            ),
        )

    # -------- internals --------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire emitter event, swallowing emitter exceptions (HEART-05)."""
        if self._emitter is None:
            return
        try:
            self._emitter.emit(event_type, data)
        except Exception as exc:  # noqa: BLE001 — HEART-05 emitter failures never crash runner
            _log.warning(
                "heartbeat_emitter_failed",
                extra={"event": event_type, "error": str(exc)},
            )

    @staticmethod
    def _with_indicator(
        visibility: HeartbeatVisibility,
        data: dict[str, Any],
        indicator_type: str,
    ) -> dict[str, Any]:
        """Conditionally attach indicator_type per HEART-04.

        Returns new dict — never mutates input.
        """
        if visibility.use_indicator:
            return {**data, "indicator_type": indicator_type}
        return dict(data)
