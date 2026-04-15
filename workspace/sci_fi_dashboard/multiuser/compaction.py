"""compaction.py — Context-window-triggered transcript compaction engine.

When the token estimate of the current transcript exceeds 80 % of the model's
context window, ``compact_session`` summarises the first half, keeps the second
half verbatim, and rewrites the JSONL file atomically.

The entire operation is wrapped in a 300-second (5-minute) aggregate asyncio
timeout.  Each individual LLM call is wrapped in a 120-second per-call timeout.
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sci_fi_dashboard.multiuser.memory_manager import append_daily_note
from sci_fi_dashboard.multiuser.session_store import SessionStore
from sci_fi_dashboard.multiuser.transcript import load_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

_PER_CALL_TIMEOUT_S: float = 120.0  # 2 minutes per LLM call
_AGGREGATE_TIMEOUT_S: float = 300.0  # 5 minutes total budget

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SUMMARIZE_INSTRUCTIONS = (
    "You are a transcript summarizer. Produce a concise, factual summary of the "
    "conversation excerpt below. Preserve key decisions, facts, user preferences, "
    "and any context needed to continue the conversation accurately. "
    "Preserve all names, identifiers, usernames, and important proper nouns exactly. "
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

    .. deprecated:: Phase 3
        Prefer ``transcript.repair_orphaned_tool_pairs()`` which returns a
        ``RepairReport``.  This function is kept for backward compatibility.
    """
    from sci_fi_dashboard.multiuser.transcript import repair_orphaned_tool_pairs

    repaired, _report = repair_orphaned_tool_pairs(messages)
    return repaired


# ---------------------------------------------------------------------------
# Adaptive chunking helpers
# ---------------------------------------------------------------------------

_ADAPTIVE_BASE: float = 0.4
_ADAPTIVE_MIN: float = 0.15
_SAFETY_MARGIN: float = 1.2


def compute_adaptive_chunk_ratio(messages: list[dict], context_window: int) -> float:
    """Compute a dynamic split ratio for compaction chunking.

    Returns a ratio in ``[_ADAPTIVE_MIN, _ADAPTIVE_BASE]`` that shrinks as the
    average message size grows relative to the context window.  Larger messages
    push the ratio lower so the "summarize" chunk is smaller, leaving more
    room for the verbatim tail.

    Args:
        messages:       The full message list.
        context_window: Total context window in tokens.

    Returns:
        A float ratio between ``_ADAPTIVE_MIN`` and ``_ADAPTIVE_BASE``.
    """
    if not messages or context_window <= 0:
        return _ADAPTIVE_BASE

    total_tokens = estimate_tokens(messages)
    avg_tokens_per_msg = total_tokens / len(messages) if messages else 0

    # Ratio of the average message size to the context window.
    size_ratio = avg_tokens_per_msg / context_window if context_window > 0 else 0

    # Scale down from BASE toward MIN as size_ratio grows.
    # At size_ratio=0 → BASE; at size_ratio >= (BASE-MIN)/BASE → MIN.
    adjusted = _ADAPTIVE_BASE - (_ADAPTIVE_BASE - _ADAPTIVE_MIN) * min(
        size_ratio * _SAFETY_MARGIN * len(messages), 1.0
    )
    return max(_ADAPTIVE_MIN, min(_ADAPTIVE_BASE, adjusted))


async def summarize_with_fallback(
    messages: list[dict], llm_client: Any, context_window: int
) -> str:
    """Summarize messages, retrying with oversized messages filtered on failure.

    On ``BadRequestError`` (or any error with "context" / "too long" in the
    message), filters out messages whose token estimate exceeds 50% of the
    context window and retries once.

    Args:
        messages:       Messages to summarize.
        llm_client:     LLM client with ``acompletion(messages=[...])`` method.
        context_window: Context window size in tokens.

    Returns:
        Summary string.
    """
    prompt = [
        {"role": "system", "content": _SUMMARIZE_INSTRUCTIONS},
        *messages,
    ]
    try:
        resp = await asyncio.wait_for(
            llm_client.acompletion(messages=prompt),
            timeout=_PER_CALL_TIMEOUT_S,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        exc_str = str(exc).lower()
        is_context_error = any(
            kw in exc_str for kw in ("context", "too long", "too large", "max.*token")
        )
        if not is_context_error:
            raise

        # Filter out oversized messages (> 50% of context window).
        threshold = context_window * 0.5
        filtered = [m for m in messages if estimate_tokens([m]) <= threshold]
        if not filtered:
            # All messages are oversized — truncate the largest one.
            filtered = [
                {
                    **messages[0],
                    "content": (messages[0].get("content", "") or "")[: context_window * 2],
                }
            ]
        logger.info(
            "summarize_with_fallback: retrying after filtering %d oversized messages",
            len(messages) - len(filtered),
        )
        retry_prompt = [
            {"role": "system", "content": _SUMMARIZE_INSTRUCTIONS},
            *filtered,
        ]
        resp = await asyncio.wait_for(
            llm_client.acompletion(messages=retry_prompt),
            timeout=_PER_CALL_TIMEOUT_S,
        )
        return resp.choices[0].message.content


def prune_history_for_context_share(
    messages: list[dict], max_tokens: int, max_share: float = 0.5
) -> list[dict]:
    """Drop oldest messages until the remaining list fits within budget.

    The budget is ``max_tokens * max_share``.  Messages are dropped from the
    front (oldest first).

    Args:
        messages:   Full message list.
        max_tokens: Total context window in tokens.
        max_share:  Maximum fraction of the context window that history may
                    occupy.  Default 0.5.

    Returns:
        A tail slice of *messages* that fits within budget.
    """
    budget = int(max_tokens * max_share)
    while messages and estimate_tokens(messages) > budget:
        messages = messages[1:]
    return messages


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
            timeout=_AGGREGATE_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning(
            "compact_session: timed out after %.0fs for key=%s",
            _AGGREGATE_TIMEOUT_S,
            session_key,
        )
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
    """Inner implementation — wrapped by the aggregate timeout in ``compact_session``."""
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
            flush_resp = await asyncio.wait_for(
                llm_client.acompletion(messages=flush_prompt),
                timeout=_PER_CALL_TIMEOUT_S,
            )
            daily_note = flush_resp.choices[0].message.content
            await append_daily_note(workspace_dir, daily_note)
        except Exception:
            logger.warning(
                "compact_session: memory flush failed for key=%s", session_key, exc_info=True
            )

    # Strip tool-result details before summarisation LLM calls.
    stripped = strip_tool_result_details(messages)

    # Compute adaptive chunk ratio based on message sizes.
    chunk_ratio = compute_adaptive_chunk_ratio(stripped, context_window_tokens)

    # Split: first `chunk_ratio` fraction for summarisation, rest verbatim.
    total_tokens = estimate_tokens(stripped)
    target_summarize_tokens = int(total_tokens * chunk_ratio)

    # Walk messages to find the split point.
    accumulated = 0
    split_idx = 0
    for i, msg in enumerate(stripped):
        accumulated += len(msg.get("content", "") or "") // 4
        if accumulated >= target_summarize_tokens:
            split_idx = i + 1
            break
    else:
        split_idx = len(stripped) // 2  # fallback to midpoint

    half_a = stripped[:split_idx]
    half_b = stripped[split_idx:]

    # Summarise each half using fallback-capable summarizer.
    summary_a = await summarize_with_fallback(half_a, llm_client, context_window_tokens)
    summary_b = await summarize_with_fallback(half_b, llm_client, context_window_tokens)

    # Merge the two summaries with per-call timeout.
    merge_resp = await asyncio.wait_for(
        llm_client.acompletion(
            messages=[
                {"role": "system", "content": _MERGE_SUMMARIES_INSTRUCTIONS},
                {"role": "user", "content": f"Part 1:\n{summary_a}\n\nPart 2:\n{summary_b}"},
            ]
        ),
        timeout=_PER_CALL_TIMEOUT_S,
    )
    final_summary = merge_resp.choices[0].message.content

    # Identify the tail of the *original* (not stripped) messages using the same
    # ratio-based split point.
    original_split = max(1, int(len(messages) * chunk_ratio))
    tail_messages = messages[original_split:]
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


# ---------------------------------------------------------------------------
# Factory for Phase 1 compact_fn interface
# ---------------------------------------------------------------------------


def make_compact_fn(
    transcript_path: Path,
    context_window_tokens: int,
    llm_client: Any,
    agent_id: str,
    session_key: str,
    store_path: Path,
) -> Callable:
    """Factory returning an async callable matching Phase 1's ``compact_fn`` interface.

    The returned callable:
    - Re-reads the transcript from disk (picks up any appended messages).
    - Runs ``compact_session`` with the bound parameters.
    - Returns the compaction result dict.

    Usage::

        compact_fn = make_compact_fn(t_path, ctx_window, llm, agent, key, store)
        result = await compact_fn()
    """

    async def _compact() -> dict:
        return await compact_session(
            transcript_path=transcript_path,
            context_window_tokens=context_window_tokens,
            llm_client=llm_client,
            agent_id=agent_id,
            session_key=session_key,
            store_path=store_path,
        )

    return _compact
