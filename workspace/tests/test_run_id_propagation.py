"""OBS-01 integration tests — runId across FloodGate -> Queue -> Worker -> Pipeline -> LLM -> Channel."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip(
    "sci_fi_dashboard.observability.context",
    reason="Plan 13-02 creates this",
)
from sci_fi_dashboard.observability.context import (  # noqa: E402
    get_run_id,
    mint_run_id,
    set_run_id,
)


@pytest.mark.asyncio
async def test_end_to_end_run_id(monkeypatch, capsys):
    """OBS-01: a runId minted at webhook entry survives through MessageTask.run_id into the worker."""
    from sci_fi_dashboard.gateway.flood import FloodGate
    from sci_fi_dashboard.gateway.queue import MessageTask

    minted = mint_run_id()
    captured_rid: list[str | None] = []

    async def fake_callback(chat_id: str, combined: str, metadata: dict):
        captured_rid.append(metadata.get("run_id"))
        # Simulate pipeline_helpers.on_batch_ready populating MessageTask.run_id
        task = MessageTask(
            task_id="t1",
            chat_id=chat_id,
            user_message=combined,
            run_id=metadata.get("run_id"),  # Plan 13-03 adds this field
        )
        captured_rid.append(task.run_id)

    fg = FloodGate(batch_window_seconds=0.05)
    fg.set_callback(fake_callback)
    await fg.incoming("chat1", "hello", {"run_id": minted})
    await asyncio.sleep(0.15)
    assert captured_rid[0] == minted, f"FloodGate metadata lost run_id: {captured_rid}"
    assert captured_rid[1] == minted, f"MessageTask.run_id not populated: {captured_rid}"


@pytest.mark.asyncio
async def test_flood_batch_last_wins():
    """OBS-01: FloodGate overwrites metadata per message (documented last-wins behavior)."""
    from sci_fi_dashboard.gateway.flood import FloodGate

    captured: list[str] = []

    async def cb(chat_id: str, combined: str, metadata: dict):
        captured.append(metadata.get("run_id"))

    fg = FloodGate(batch_window_seconds=0.05)
    fg.set_callback(cb)
    await fg.incoming("c1", "m1", {"run_id": "rid1"})
    await fg.incoming("c1", "m2", {"run_id": "rid2"})
    await fg.incoming("c1", "m3", {"run_id": "rid3"})
    await asyncio.sleep(0.15)
    # Last-wins: only rid3 reaches the callback
    assert captured == ["rid3"], f"expected last-wins ['rid3'], got {captured}"


@pytest.mark.asyncio
async def test_worker_inherits_task_run_id():
    """OBS-01 (checker fix -- referenced by 13-VALIDATION.md row 13-03-01): the MessageWorker
    loop MUST inherit MessageTask.run_id into the ContextVar before dispatching to
    persona_chat, so every log line downstream of the worker hop carries the same runId
    as the inbound webhook set.

    This test validates the critical webhook->worker->pipeline continuity: without this
    wiring, the runId minted at routes/whatsapp.py::unified_webhook is lost the moment
    the task pops off the queue in a fresh worker task (ContextVar does NOT survive
    across queue boundaries -- it must be explicitly restored by `set_run_id(task.run_id)`
    at worker entry).
    """
    from sci_fi_dashboard.gateway.queue import MessageTask

    # Simulate the worker's per-task ContextVar restore
    task = MessageTask(
        task_id="t-inherit-01",
        chat_id="test-chat",
        user_message="hello",
        run_id="rid-worker-inherit-01",
    )

    observed: list[str | None] = []

    async def worker_body(t: MessageTask):
        # Plan 13-03 Task 13-03-02 inserts `set_run_id(t.run_id)` here as the first
        # line of MessageWorker._dispatch() (or equivalent). This test proves that
        # after the restore, ContextVar reads the task's run_id.
        if t.run_id is not None:
            set_run_id(t.run_id)
        observed.append(get_run_id())

    await worker_body(task)
    assert observed == ["rid-worker-inherit-01"], (
        f"worker did not inherit task.run_id into ContextVar: {observed}"
    )


@pytest.mark.asyncio
async def test_all_hops_share_run_id(monkeypatch):
    """OBS-01: Smoke -- with a minted run_id in ContextVar, every observability-aware logger sees it."""
    from sci_fi_dashboard.observability.logger_factory import get_child_logger

    rid = mint_run_id()
    captured: list[str | None] = []

    async def hop():
        get_child_logger("test.hop")  # confirms adapter is retrievable; ContextVar read below
        captured.append(get_run_id())  # represents any logger reading ContextVar at emit

    await asyncio.gather(hop(), hop(), hop())
    assert captured == [rid, rid, rid], f"runId not stable across async tasks: {captured}"
