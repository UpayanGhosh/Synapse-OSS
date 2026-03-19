"""compaction.py — Context-window-triggered transcript compaction engine.

When the token estimate of the current transcript exceeds 80 % of the model's
context window, ``compact_session`` summarises the first half, keeps the second
half verbatim, and rewrites the JSONL file atomically.

The entire operation is wrapped in a 900-second (15-minute) asyncio timeout.
On timeout the function returns ``{"ok": False, "compacted": False, "reason": "timeout"}``
without re-raising.

LLM client contract
-------------------
``llm_client`` must expose::

    await llm_client.acompletion(messages=[...])

returning an object whose ``.choices[0].message.content`` is a plain string.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from sci_fi_dashboard.multiuser.memory_manager import append_daily_note
from sci_fi_dashboard.multiuser.session_store import SessionStore
from sci_fi_dashboard.multiuser.transcript import load_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SUMMARIZE_INSTRUCTIONS = (
    "You are a transcript summarizer. Produce a concise, factual summary of the "
    "conversation excerpt below. Preserve key decisions, facts, user preferences, "
    "and any context needed to continue the conversation accurately. "
    "Output the summary as plain prose — no bullet points, no headers."
)

_MERGE_SUMMARIES_INSTRUCTIONS = (
    "You are given two partial summaries of a conversation, in chronological order. "
    "Merge them into a single coherent summary that preserves all important context. "
    "Output the merged summary as plain prose — no bullet points, no headers."
)

_MEMORY_FLUSH_INSTRUCTIONS = (
    "You are given a conversation transcript excerpt. "
    "Write a concise daily-note entry (2–5 sentences) capturing the most important "
    "facts, decisions, or user preferences from this session."
)

# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate token count using a chars-÷-4 heuristic.

    Matches the blueprint Section 4.1 ``SAFETY_MARGIN`` approach.
    """
    return sum(len(m.get("content", "") or "") // 4 for m in messages)


def should_compact(
    messages: list[dict],
    context_window_tokens: int,
    threshold_ratio: float = 0.8,
) -> bool:
    """Return ``True`` when the estimated token count exceeds the threshold."""
    return estimate_tokens(messages) > context_window_tokens * threshold_ratio


def strip_tool_result_details(messages: list[dict]) -> list[dict]:
    """Drop all messages where ``role == "tool"`` entirely.

    For ``role == "assistant"`` messages that contain ``tool_calls``, keep only
    the ``"name"`` field in each tool call, discarding arguments and output.
    """
    result: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool":
            continue  # drop tool result messages completely
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Retain a stripped copy of the tool_calls list.
            stripped_calls = [
                {"name": tc.get("name") or tc.get("function", {}).get("name", "")}
                for tc in msg["tool_calls"]
            ]
            msg = {**msg, "tool_calls": stripped_calls}
        result.append(msg)
    return result


def split_by_token_share(messages: list[dict], parts: int) -> list[list[dict]]:
    """Split *messages* into *parts* roughly equal-token groups.

    Works from left to right accumulating token counts.  Does not crash on
    odd counts or when ``len(messages) < parts``.
    """
    if not messages or parts <= 1:
        return [messages] if messages else [[] for _ in range(parts)]

    total_tokens = estimate_tokens(messages)
    target_per_part = total_tokens / parts

    buckets: list[list[dict]] = [[] for _ in range(parts)]
    current_part = 0
    accumulated = 0

    for msg in messages:
        if current_part < parts - 1 and accumulated >= target_per_part * (current_part + 1):
            current_part += 1
        buckets[current_part].append(msg)
        accumulated += len(msg.get("content", "") or "") // 4

    return buckets


def _repair_orphaned_tool_pairs(messages: list[dict]) -> list[dict]:
    """Remove orphaned tool_use / tool_result pairs.

    After a compaction rewrite the second half may begin mid-exchange, leaving
    tool_result messages with no matching tool_use above them, or vice versa.
    This pass strips any such unpaired entries.
    """
    # Collect tool_use IDs that are present.
    tool_use_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tid = tc.get("id") or tc.get("tool_use_id") or tc.get("name")
                if tid:
                    tool_use_ids.add(tid)

    result: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id") or msg.get("tool_use_id")
            if tid and tid not in tool_use_ids:
                logger.debug("compaction: dropping orphaned tool_result id=%s", tid)
                continue
        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# Atomic JSONL rewrite helper (sync, for asyncio.to_thread)
# ---------------------------------------------------------------------------


def _rewrite_jsonl_sync(path: Path, lines: list[dict]) -> None:
    """Atomically rewrite the JSONL at *path* with *lines*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, separators=(",", ":")) + "\n")
        os.replace(tmp_path, str(path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Main compaction entry point
# ---------------------------------------------------------------------------


async def compact_session(
    *,
    transcript_path: Path,
    context_window_tokens: int,
    llm_client: Any,
    agent_id: str,
    session_key: str,
    store_path: Path,
    session_store: SessionStore | None = None,
    data_root: Path | None = None,
) -> dict:
    """Compact *transcript_path* if the token estimate exceeds 80 % of the context window.

    All keyword-only parameters beyond the first three are required at call time.

    Args:
        transcript_path:       Path to the ``.jsonl`` transcript file.
        context_window_tokens: Total context window size for the active model.
        llm_client:            LLM client with ``acompletion(messages=[...])`` method.
        agent_id:              Agent ID (used for daily-note workspace path).
        session_key:           Session key string (used for store update).
        store_path:            Path to the agent's ``sessions.json`` store file.
        session_store:         Optional pre-constructed ``SessionStore``.  If absent,
                               one is created from *store_path*.
        data_root:             Data root used for daily-note writes.  Falls back to
                               ``store_path.parent.parent.parent.parent.parent``
                               (reversing the ``state/agents/<id>/sessions/`` nesting).

    Returns:
        ``{"ok": bool, "compacted": bool, ...}`` — never raises on timeout.
    """
    try:
        return await asyncio.wait_for(
            _compact_inner(
                transcript_path=transcript_path,
                context_window_tokens=context_window_tokens,
                llm_client=llm_client,
                agent_id=agent_id,
                session_key=session_key,
                store_path=store_path,
                session_store=session_store,
                data_root=data_root,
            ),
            timeout=900,
        )
    except TimeoutError:
        logger.warning("compact_session: timed out after 900s for key=%s", session_key)
        return {"ok": False, "compacted": False, "reason": "timeout"}


async def _compact_inner(
    *,
    transcript_path: Path,
    context_window_tokens: int,
    llm_client: Any,
    agent_id: str,
    session_key: str,
    store_path: Path,
    session_store: SessionStore | None,
    data_root: Path | None,
) -> dict:
    """Inner implementation — wrapped by the 900 s timeout in ``compact_session``."""
    messages = await load_messages(transcript_path)

    if not should_compact(messages, context_window_tokens):
        return {"ok": True, "compacted": False, "reason": "below threshold"}

    # Resolve store and data_root.
    if session_store is None:
        # Derive agent_id from store_path: .../state/agents/<agent_id>/sessions/sessions.json
        derived_agent_id = agent_id or store_path.parent.parent.name
        derived_root = data_root or store_path.parent.parent.parent.parent.parent
        session_store = SessionStore(derived_agent_id, data_root=derived_root)

    entry = await session_store.get(session_key)
    if entry is None:
        entry = await session_store.update(session_key, {})

    workspace_dir = (data_root or store_path.parent.parent.parent.parent.parent) / "workspace"

    # Memory-flush guard: one flush per compaction cycle.
    flush_count = entry.memory_flush_compaction_count
    compact_count = entry.compaction_count
    if flush_count == compact_count:
        # Run memory flush: summarize and append as a daily note.
        stripped_for_flush = strip_tool_result_details(messages)
        flush_prompt = [
            {"role": "system", "content": _MEMORY_FLUSH_INSTRUCTIONS},
            *stripped_for_flush,
        ]
        try:
            flush_resp = await llm_client.acompletion(messages=flush_prompt)
            daily_note = flush_resp.choices[0].message.content
            await append_daily_note(workspace_dir, daily_note)
        except Exception:
            logger.warning(
                "compact_session: memory flush failed for key=%s", session_key, exc_info=True
            )

    # Strip tool-result details before summarisation LLM calls.
    stripped = strip_tool_result_details(messages)

    # Split into two equal-token halves.
    halves = split_by_token_share(stripped, 2)
    half_a = halves[0] if len(halves) > 0 else []
    half_b = halves[1] if len(halves) > 1 else []

    # Summarise each half independently.
    async def _summarize(chunk: list[dict]) -> str:
        resp = await llm_client.acompletion(
            messages=[
                {"role": "system", "content": _SUMMARIZE_INSTRUCTIONS},
                *chunk,
            ]
        )
        return resp.choices[0].message.content

    summary_a = await _summarize(half_a)
    summary_b = await _summarize(half_b)

    # Merge the two summaries.
    merge_resp = await llm_client.acompletion(
        messages=[
            {"role": "system", "content": _MERGE_SUMMARIES_INSTRUCTIONS},
            {"role": "user", "content": f"Part 1:\n{summary_a}\n\nPart 2:\n{summary_b}"},
        ]
    )
    final_summary = merge_resp.choices[0].message.content

    # Identify the second half of the *original* (not stripped) messages.
    midpoint = len(messages) // 2
    tail_messages = messages[midpoint:]
    tail_messages = _repair_orphaned_tool_pairs(tail_messages)

    # Build new JSONL: summary system message + tail.
    new_lines: list[dict] = [
        {"role": "system", "content": final_summary, "timestamp": time.time()},
        *tail_messages,
    ]

    await asyncio.to_thread(_rewrite_jsonl_sync, transcript_path, new_lines)

    # Update session store: compaction_count += 1, memory_flush_compaction_count = new count.
    new_compact_count = compact_count + 1
    updated_entry = await session_store.update(
        session_key,
        {
            "compaction_count": new_compact_count,
            "memory_flush_compaction_count": new_compact_count,
        },
    )

    return {
        "ok": True,
        "compacted": True,
        "result": {
            "compaction_count": updated_entry.compaction_count,
            "original_message_count": len(messages),
            "retained_message_count": len(tail_messages),
            "summary_tokens_estimate": len(final_summary) // 4,
        },
    }
