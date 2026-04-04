"""
pipeline_emitter.py — Real-time pipeline event bus for the dashboard.

Singleton PipelineEventEmitter that:
- Accepts emit() calls from anywhere in the pipeline (fire-and-forget, sync-safe)
- Distributes SSE-formatted messages to all active browser subscribers
- Handles slow/disconnected subscribers gracefully (QueueFull → drop + remove)
- Thread-safe: emit() uses call_soon_threadsafe when called from a thread
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any


class PipelineEventEmitter:
    """Singleton event bus. Call get_emitter() to access."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[str]] = []
        self._current_run_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[str]:
        """Register a new SSE subscriber. Returns a queue of SSE-formatted strings."""
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """
        Emit a pipeline event. Safe to call from sync or async code, main
        thread or worker thread.

        Formats the event as an SSE message string:
            event: <event_type>\\ndata: <json>\\n\\n
        """
        payload = {
            "event": event_type,
            "ts": round(time.time() * 1000),   # ms timestamp
            "run_id": self._current_run_id,
            **(data or {}),
        }
        msg = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        self._broadcast(msg)

    def _broadcast(self, msg: str) -> None:
        dead: list[asyncio.Queue[str]] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # ------------------------------------------------------------------
    # Run lifecycle helpers (called by chat_pipeline.py)
    # ------------------------------------------------------------------

    def start_run(self, run_id: str | None = None, **kwargs: Any) -> str:
        """Mark start of a new pipeline run. Returns the run_id."""
        rid = run_id or uuid.uuid4().hex[:12]
        self._current_run_id = rid
        self.emit("pipeline.start", {"run_id": rid, **kwargs})
        return rid

    def end_run(self, **kwargs: Any) -> None:
        """Mark end of current pipeline run."""
        self.emit("pipeline.done", {"run_id": self._current_run_id, **kwargs})
        self._current_run_id = None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_emitter: PipelineEventEmitter | None = None


def get_emitter() -> PipelineEventEmitter:
    """Return the module-level singleton emitter (creates on first call)."""
    global _emitter
    if _emitter is None:
        _emitter = PipelineEventEmitter()
    return _emitter
