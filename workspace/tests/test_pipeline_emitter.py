"""OBS-01: pipeline_emitter.start_run() must honor ContextVar (fix for singleton race)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip(
    "sci_fi_dashboard.observability.context",
    reason="Plan 13-02 creates this",
)
from sci_fi_dashboard.observability.context import mint_run_id  # noqa: E402


@pytest.mark.asyncio
async def test_concurrent_runs_isolated():
    """OBS-01: Two concurrent persona_chat() calls must NOT share pipeline_emitter._current_run_id."""
    from sci_fi_dashboard.pipeline_emitter import PipelineEventEmitter

    emitter = PipelineEventEmitter()
    rids: list[str] = []

    async def one_run(tag: str):
        mint_run_id()
        # Plan 13-04 updates start_run() to read ContextVar FIRST
        rid = emitter.start_run(text=f"msg-{tag}", target="the_creator")
        await asyncio.sleep(0.01)
        rids.append(rid)

    await asyncio.gather(one_run("a"), one_run("b"), one_run("c"))
    # After fix: three distinct run_ids (one per ContextVar context)
    assert len(set(rids)) == 3, f"race condition still present -- shared run_ids: {rids}"
