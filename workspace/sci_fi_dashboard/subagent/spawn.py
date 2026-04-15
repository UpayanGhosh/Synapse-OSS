"""Spawn orchestration — detects spawn intent and delegates to SubAgentRunner.

Extracted from the pipeline to keep persona_chat's SRP intact and make
spawn logic independently testable without importing the full chat pipeline.
"""

import logging
import uuid

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.subagent.intent import detect_spawn_intent
from sci_fi_dashboard.subagent.models import SubAgent

logger = logging.getLogger(__name__)


async def maybe_spawn_agent(
    user_msg: str,
    chat_id: str,
    channel_id: str,
    session_key: str,
) -> "str | None":
    """Detect spawn intent and fire-and-forget a sub-agent if matched.

    Returns the acknowledgment reply string if a sub-agent was spawned,
    or None if the message is not a spawn intent (caller should continue
    with the normal pipeline).

    Parameters come from process_message_pipeline() which has the real
    chat_id, channel_id, and session_key — NOT from ChatRequest which
    only has message, history, user_id, session_type.

    Parameters
    ----------
    user_msg:
        Raw user message text (used for intent detection and as task description).
    chat_id:
        Peer/conversation identifier (e.g. WhatsApp phone number or group JID).
        Passed to SubAgent so results are delivered back to the correct recipient.
    channel_id:
        Channel adapter name (e.g. "whatsapp", "telegram").
        Used by SubAgentRunner to look up the channel for result delivery.
    session_key:
        Built by build_session_key() in process_message_pipeline().
        Used to snapshot the last N conversation turns from the cache.

    Returns
    -------
    str | None
        Acknowledgment string if a sub-agent was spawned.
        None if this is not a spawn intent — caller continues normal pipeline.
    """
    if deps.agent_runner is None:
        # Subagent system not initialized — fall through to normal pipeline.
        return None

    is_spawn, task_desc = detect_spawn_intent(user_msg)
    if not is_spawn:
        return None

    # ------------------------------------------------------------------
    # Build context snapshot: last 10 messages from conversation cache
    # ------------------------------------------------------------------
    context_snap: list[dict] = []
    if deps.conversation_cache is not None and session_key:
        cached = deps.conversation_cache.get(session_key)
        if cached:
            context_snap = list(cached[-10:])

    # ------------------------------------------------------------------
    # Build memory snapshot: query memory engine for the task description.
    # CRITICAL: memory_engine.query() returns a dict with
    #   {"results": [...], "tier": ..., "entities": ..., "graph_context": ...}
    # NOT a list.  We must unwrap via .get("results", []).
    # ------------------------------------------------------------------
    memory_snap: list[dict] = []
    if deps.memory_engine is not None:
        try:
            mem_results = deps.memory_engine.query(task_desc, limit=5)
            memory_snap = mem_results.get("results", []) if isinstance(mem_results, dict) else []
        except Exception:  # noqa: BLE001
            # Memory query failure is not fatal — agent still spawns without
            # pre-seeded memories.
            logger.debug("maybe_spawn_agent: memory query failed (non-fatal)", exc_info=True)

    # ------------------------------------------------------------------
    # Construct SubAgent and spawn
    # ------------------------------------------------------------------
    agent = SubAgent(
        agent_id=str(uuid.uuid4()),
        description=task_desc,
        channel_id=channel_id or "whatsapp",
        chat_id=chat_id,
        parent_session_key=session_key,
        context_snapshot=context_snap,
        memory_snapshot=memory_snap,
    )
    await deps.agent_runner.spawn_agent(agent)
    logger.info("Spawned sub-agent %s for task: %s", agent.agent_id, task_desc)

    return (
        "On it! I've started working on that in the background. "
        f"I'll send you the results when I'm done.\n\n[Task: {task_desc}]"
    )
