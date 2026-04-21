"""OBS-01: Async-safe correlation ID propagation via contextvars.

The runId convention is 12 hex characters -- matches pipeline_emitter.start_run()
(uuid.uuid4().hex[:12]) so a single identifier flows through both the JSON log
stream and the dashboard SSE stream.

Python 3.11+ propagates context across asyncio.create_task() automatically.
Callers must use contextvars.copy_context() manually when dispatching to
ThreadPoolExecutor via loop.run_in_executor.
"""

from __future__ import annotations

import contextvars
import uuid

_run_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "synapse_run_id", default=None
)


def mint_run_id() -> str:
    """Generate a fresh 12-hex-char runId and store it in the ContextVar."""
    rid = uuid.uuid4().hex[:12]
    _run_id_ctx.set(rid)
    return rid


def set_run_id(run_id: str) -> contextvars.Token:
    """Explicitly set the runId (e.g. when restoring after a queue handoff).

    Returns a Token the caller should pass to _run_id_ctx.reset() in a
    finally block to avoid bleeding context into subsequent requests.
    """
    return _run_id_ctx.set(run_id)


def get_run_id() -> str | None:
    """Return the current runId or None if nothing set in this context."""
    return _run_id_ctx.get()
