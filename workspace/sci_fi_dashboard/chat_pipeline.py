"""Core chat pipeline -- persona_chat() and tool execution helpers."""

import asyncio
import contextlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

from fastapi import BackgroundTasks

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.action_receipts import (
    ActionReceipt,
    guard_reply_against_unreceipted_claims,
    render_receipt_contract,
)
from sci_fi_dashboard.dual_cognition import CognitiveMerge
from sci_fi_dashboard.llm_router import LLMResult
from sci_fi_dashboard.observability import get_child_logger
from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter
from sci_fi_dashboard.prompt_tiers import (
    PromptTierPolicy,
    filter_tier_sections,
    get_prompt_tier_policy,
    prompt_tier_for_role,
)
from sci_fi_dashboard.stance import decide_turn_stance
from sci_fi_dashboard.schemas import ChatRequest

logger = logging.getLogger(__name__)
_log = get_child_logger("pipeline.chat")  # OBS-01 structured logger carrying runId

# ---------------------------------------------------------------------------
# Agent Workspace Prefix (RT2)
# ---------------------------------------------------------------------------
# Static markdown discipline + identity layer (Jarvis-style backbone).
# Concatenated into the system prompt at the top -- sits ABOVE the SBS dynamic
# persona layer so SBS adaptation still wins for tone/style while these files
# anchor the bot's identity, rules, and tool discipline.
#
# Resolution order per file:
#   1. ~/.synapse/workspace/<NAME>.md            (user override)
#   2. ~/.synapse/workspace/<NAME>.md.template   (runtime fallback)
#   3. <repo>/agent_workspace/<NAME>.md.template (repo default)
#
# INSTRUCTIONS, CORE, and AGENTS are special: the repo has one canonical shipping copy at
# <repo>/agent_workspace/<NAME>.md. CLI seeding and prompt fallback both read
# that same file so personality rules cannot drift across duplicate templates.

_AGENT_WORKSPACE_FILES: tuple[str, ...] = (
    "INSTRUCTIONS",
    "SOUL",
    "CORE",
    "CODE",
    "IDENTITY",
    "USER",
    "TOOLS",
    "MEMORY",
    "AGENTS",  # AGENTS last -- discipline rules are freshest before dynamic layer
)

_REPO_AGENT_WORKSPACE: Path = Path(__file__).parent / "agent_workspace"
_USER_AGENT_WORKSPACE: Path = Path.home() / ".synapse" / "workspace"

# Module-level cache keyed by file mtimes + prompt tier for cheap invalidation.
_agent_workspace_cache: dict = {"content": "", "content_by_tier": {}, "mtimes": {}}
_agent_workspace_session_cache: dict[tuple[str, str], str] = {}


def _repo_agent_workspace_default(name: str) -> Path:
    """Return the repo-packaged default for an agent workspace file."""
    if name in {"INSTRUCTIONS", "CORE", "AGENTS"}:
        return _REPO_AGENT_WORKSPACE / f"{name}.md"
    return _REPO_AGENT_WORKSPACE / f"{name}.md.template"


def _resolve_agent_workspace_path(name: str) -> Path | None:
    """Resolve a single agent workspace file using the 3-tier override order.

    Returns the first existing path or ``None`` if no copy is reachable.
    """
    candidates = (
        _USER_AGENT_WORKSPACE / f"{name}.md",
        _USER_AGENT_WORKSPACE / f"{name}.md.template",
        _repo_agent_workspace_default(name),
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def clear_agent_workspace_session_prefix(session_key: str | None = None) -> None:
    """Clear frozen identity-prefix cache for one session or all sessions."""
    if session_key is None:
        _agent_workspace_session_cache.clear()
        return
    normalized = str(session_key or "default")
    for key in list(_agent_workspace_session_cache):
        if key[0] == normalized:
            _agent_workspace_session_cache.pop(key, None)


def _load_agent_workspace_prefix_for_session(
    session_key: str | None,
    prompt_tier: str = "frontier",
) -> str:
    """Load the identity prefix once per session and reuse it for later turns."""
    tier = get_prompt_tier_policy(prompt_tier).tier
    key = (str(session_key or "default"), tier)
    cached = _agent_workspace_session_cache.get(key)
    if cached is not None:
        return cached
    content = _load_agent_workspace_prefix(tier)
    _agent_workspace_session_cache[key] = content
    return content


def _load_agent_workspace_prefix(prompt_tier: str = "frontier") -> str:
    """Load and concatenate the 7 agent workspace markdown files into a stable prompt prefix.

    Files loaded in order: SOUL -> CORE -> IDENTITY -> USER -> TOOLS -> MEMORY -> AGENTS.
    AGENTS comes LAST so its discipline rules are the freshest thing the LLM sees
    before the dynamic SBS persona layer.

    The result is cached at module level. The cache invalidates when ANY of the
    7 resolved file mtimes changes -- letting users edit ``~/.synapse/workspace/SOUL.md``
    and see changes on the next message without restart.

    Tier markers (``<tier:frontier>`` / ``<tier:small>`` / ``<tier:all>``)
    are stripped before concatenation so the prompt can target a model class.

    Returns one big string with file boundaries marked by ``# ===== <NAME>.md =====``
    headers. Empty string if none of the files resolve (logged at WARNING level).
    """
    tier = get_prompt_tier_policy(prompt_tier).tier
    resolved: dict[str, Path] = {}
    for name in _AGENT_WORKSPACE_FILES:
        path = _resolve_agent_workspace_path(name)
        if path is not None:
            resolved[name] = path

    if not resolved:
        cached_any = _agent_workspace_cache.get("content") or ""
        if cached_any:
            return cached_any
        _log.warning(
            "agent_workspace_empty",
            extra={
                "user_dir": str(_USER_AGENT_WORKSPACE),
                "repo_dir": str(_REPO_AGENT_WORKSPACE),
            },
        )
        return ""

    # mtime-based cache invalidation -- reload if ANY resolved file changed.
    current_mtimes: dict[Path, float] = {}
    for path in resolved.values():
        try:
            current_mtimes[path] = path.stat().st_mtime
        except OSError:
            current_mtimes[path] = 0.0

    content_by_tier = _agent_workspace_cache.setdefault("content_by_tier", {})
    if _agent_workspace_cache["mtimes"] == current_mtimes and tier in content_by_tier:
        return content_by_tier[tier]

    if _agent_workspace_cache["mtimes"] != current_mtimes:
        content_by_tier.clear()

    sections: list[str] = []
    for name in _AGENT_WORKSPACE_FILES:
        path = resolved.get(name)
        if path is None:
            continue
        try:
            body = filter_tier_sections(path.read_text(encoding="utf-8"), tier).strip()
        except OSError as exc:
            _log.warning(
                "agent_workspace_read_failed",
                extra={"file": str(path), "error": str(exc)},
            )
            continue
        if not body:
            continue
        sections.append(f"# ===== {name}.md =====\n{body}")

    content = "\n\n".join(sections)
    content_by_tier[tier] = content
    if tier == "frontier":
        _agent_workspace_cache["content"] = content
    _agent_workspace_cache["mtimes"] = current_mtimes
    return content


def _build_runtime_info_block() -> str:
    """Build a runtime info block to inject into the system prompt.

    Without this, LLMs hallucinate about their own model identity (e.g. Gemini
    answering "I'm GPT-4o" because that's the most common answer in training
    data). The fix is to put the live routing table in the prompt itself, so
    the bot has factual ground truth.

    Returns a formatted string showing all role->model mappings from
    synapse.json plus OS/time. Best-effort -- returns empty string on read
    failure rather than raising.
    """
    import platform
    from datetime import datetime

    lines: list[str] = ["## Runtime"]

    try:
        from synapse_config import SynapseConfig

        cfg = SynapseConfig.load()
        mappings = getattr(cfg, "model_mappings", None) or {}
    except Exception:
        mappings = {}

    if mappings:
        lines.append(
            "Active model routing -- Traffic Cop selects role per turn based on "
            "message content, then the role's model handles the LLM call. "
            "If asked about your model, answer from this table -- do NOT guess "
            "from training-data priors:"
        )
        for role, m in mappings.items():
            if isinstance(m, dict):
                model = m.get("model", "<unset>")
                fallback = m.get("fallback")
            else:
                model = str(m)
                fallback = None
            line = f"  - {role}: {model}"
            if fallback:
                line += f"  (fallback: {fallback})"
            lines.append(line)
    else:
        lines.append(
            "Model routing unknown (synapse.json unreachable). If asked, say "
            "you don't have visibility into the active model rather than guessing."
        )

    lines.append(f"OS: {platform.system()} {platform.release()}")
    lines.append(f"UTC time: {datetime.now(UTC).isoformat(timespec='minutes')}")

    return "\n".join(lines)


def _format_memory_context_for_tier(
    permanent_facts: list[str],
    mem_response: dict | None,
    policy: PromptTierPolicy,
) -> str:
    """Render retrieved memory under the active prompt-tier budget."""

    if not mem_response:
        return "(Memory retrieval unavailable)"

    raw_results = mem_response.get("results", []) or []
    selected: list[dict] = []
    memory_limit = max(0, int(policy.memory_limit or 0))
    if memory_limit:
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            if policy.memory_min_score is not None:
                try:
                    score = float(result.get("score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                if score < policy.memory_min_score:
                    continue
            selected.append(result)
            if len(selected) >= memory_limit:
                break

    profile_limit = policy.profile_fact_limit
    profile_facts = permanent_facts if profile_limit is None else permanent_facts[:profile_limit]
    profile_block = "\n".join(
        f"* {_truncate_text(fact, policy.profile_fact_chars)}" for fact in profile_facts if fact
    )
    dynamic_facts = "\n".join(
        f"* {_truncate_text(str(item.get('content', '')), policy.profile_fact_chars)}"
        for item in selected
        if item.get("content")
    )

    parts = []
    if profile_block:
        parts.append(f"[PERMANENT USER PROFILE]\n{profile_block}")
    if dynamic_facts:
        parts.append(f"[RECENT CONTEXT FROM MEMORY]\n{dynamic_facts}")
    if policy.include_graph_context and mem_response.get("graph_context"):
        parts.append(str(mem_response.get("graph_context")))
    if mem_response.get("affect_hints"):
        parts.append(str(mem_response.get("affect_hints")))
    return "\n\n".join(parts).strip() or "(No relevant memories retrieved)"


def _message_requests_recent_session_recall(user_msg: str) -> bool:
    """Detect prompts that ask about the immediately previous conversation."""

    msg = (user_msg or "").lower()
    recall_markers = (
        "remember",
        "what was i",
        "what were we",
        "what did we",
        "before this",
        "fresh session",
        "previous session",
        "last session",
        "just discussed",
        "earlier",
    )
    temporal_markers = (
        "fresh session",
        "previous session",
        "last session",
        "before this",
        "just",
        "earlier",
        "ago",
    )
    return any(marker in msg for marker in recall_markers) and any(
        marker in msg for marker in temporal_markers
    )


def _fetch_recent_session_recall_context(
    user_msg: str,
    db_path: str | Path,
    *,
    limit: int = 2,
    max_chars: int = 1800,
) -> str:
    """Fetch the newest archived session docs for temporal recall prompts."""

    if not _message_requests_recent_session_recall(user_msg):
        return ""

    try:
        path = Path(db_path)
        if not path.exists():
            return ""
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, content
                FROM documents
                WHERE filename = 'session'
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    except Exception:
        return ""

    entries: list[str] = []
    remaining = max(200, int(max_chars))
    for doc_id, created_at, content in rows:
        if not content or remaining <= 0:
            continue
        snippet = _format_recent_session_snippet(str(content), remaining)
        entries.append(f"* doc {doc_id} at {created_at}: {snippet}")
        remaining -= len(snippet)

    if not entries:
        return ""
    return (
        "[RECENT ARCHIVED SESSION - highest priority for 'what just happened' recall]\n"
        "Use this before older semantic memories when the user asks about the previous/fresh session.\n"
        + "\n".join(entries)
    )


def _format_recent_session_snippet(content: str, max_chars: int) -> str:
    """Preserve both session setup and latest turns for recency recall."""

    compact = " ".join(str(content or "").split())
    if len(compact) <= max_chars:
        return compact
    budget = max(200, int(max_chars))
    head_chars = min(360, max(80, budget // 3))
    tail_chars = max(80, budget - head_chars - 38)
    return (
        compact[:head_chars].rstrip()
        + " ... [middle truncated; latest turns follow] ... "
        + compact[-tail_chars:].lstrip()
    )


def _build_cognitive_context_for_tier(cognitive_merge, policy: PromptTierPolicy) -> str:
    """Ask the cognition engine for either full narrative or strategy-only context."""

    if cognitive_merge is None:
        return ""
    try:
        context = deps.dual_cognition.build_cognitive_context(
            cognitive_merge, detail=policy.cognitive_detail
        )
    except TypeError:
        # Tests and external integrations may still provide the old one-arg shape.
        context = deps.dual_cognition.build_cognitive_context(cognitive_merge)
    return context if isinstance(context, str) else ""


def _select_recent_history(history: list | None, policy: PromptTierPolicy) -> list:
    """Keep the most recent N turns. A turn is approximated as user+assistant."""

    if not history:
        return []
    max_messages = max(0, policy.history_turns * 2)
    return list(history[-max_messages:]) if max_messages else []


def _format_profile_reminder(permanent_facts: list[str], policy: PromptTierPolicy) -> str:
    """Render a short recency-biased profile reminder before the user turn."""

    if not permanent_facts:
        return ""
    profile_limit = policy.profile_fact_limit
    facts = permanent_facts if profile_limit is None else permanent_facts[:profile_limit]
    lines = [
        f"- {_truncate_text(fact, policy.profile_fact_chars)}"
        for fact in facts
        if str(fact).strip()
    ]
    if not lines:
        return ""
    return "USER PROFILE (always true, use this to personalize your reply):\n" + "\n".join(lines)


def _format_tool_inventory(session_tools: list, policy: PromptTierPolicy) -> str:
    """Render current tools as either names-only or compact one-line entries."""

    if not session_tools:
        return ""
    if policy.native_tool_schemas:
        names = ", ".join(t.name for t in session_tools)
        return f"Available tools this turn: {names}."

    lines = ["Available tools this turn (compact inventory):"]
    for tool in session_tools:
        name = getattr(tool, "name", "unknown_tool")
        description = (
            getattr(tool, "description", "")
            or getattr(tool, "summary", "")
            or "No description provided."
        )
        lines.append(f"- {name}: {_truncate_text(str(description), 160)}")
    return "\n".join(lines)


def _truncate_text(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 15)].rstrip() + " ... [truncated]"


def _truncate_tool_result(text: str, max_chars: int) -> str:
    content = str(text or "").strip()
    if len(content) <= max_chars:
        return content
    return content[: max(0, max_chars - 16)].rstrip() + "\n... [truncated]"


def _estimate_message_tokens(messages: list[dict]) -> int:
    chars = 0
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else ""
        chars += len(content if isinstance(content, str) else str(content))
    return chars // 4


def _dep_int(name: str, default: int) -> int:
    value = getattr(deps, name, default)
    return value if isinstance(value, int) else default


def _dep_float(name: str, default: float) -> float:
    value = getattr(deps, name, default)
    return value if isinstance(value, int | float) else default


def _is_reflective_casual_message(message: str) -> bool:
    msg = " ".join(str(message or "").lower().split())
    reflective_markers = (
        "worried",
        "worry",
        "anxious",
        "scared",
        "sad",
        "hurt",
        "lonely",
        "depressed",
        "stressed",
        "frustrated",
        "confused",
        "upset",
        "tension",
        "i feel",
        "i'm feeling",
        "i am feeling",
        "feel like",
        "doesn't feel",
        "won't make",
        "not human",
        "generic",
        "slop",
        "ki korbo",
        "bujhte parchhi na",
        "valo nei",
        "bhalo nei",
        "kharap",
    )
    return any(marker in msg for marker in reflective_markers)


def _is_relationship_voice_turn(user_msg: str, role: str, session_mode: str) -> bool:
    """Return True when the reply should lean into close-friend voice.

    This is deliberately broader than "emotional support": the Jarvis-style target
    is day-to-day companionship, so work rants, crush updates, family pressure,
    money impulses, health slips, and tiny wins all qualify.
    """
    if session_mode == "spicy" or str(role).lower() != "casual":
        return False
    msg = " ".join(str(user_msg or "").lower().split())
    memory_turn = any(
        marker in msg for marker in ("remember ", "remember:", "save my", "save this")
    )
    if _message_requests_external_action(user_msg) and not memory_turn:
        return False

    markers = (
        "crush",
        "love",
        "date",
        "naina",
        "family",
        "ma ",
        "mother",
        "father",
        "boss",
        "office",
        "raghav",
        "mira",
        "friend",
        "lonely",
        "guilty",
        "irritated",
        "angry",
        "annoyed",
        "pissed",
        "vent",
        "rant",
        "bitch",
        "defensive",
        "dumped",
        "unfair",
        "office politics",
        "toxic",
        "anxious",
        "scared",
        "fear",
        "stressed",
        "pressure",
        "hurt",
        "sad",
        "tired",
        "sleep",
        "breakfast",
        "walk",
        "health",
        "money",
        "budget",
        "bought",
        "buy",
        "save",
        "shopping",
        "travel",
        "goa",
        "alone",
        "quiet",
        "jealous",
        "guilt",
        "small joy",
        "life update",
        "personal update",
        "work stress",
        "anger moment",
        "fear check",
        "i feel",
        "i felt",
        "i want",
        "i think",
    )
    return any(marker in msg for marker in markers)


def _build_relationship_voice_contract(
    user_msg: str,
    role: str,
    session_mode: str,
    prompt_depth: str,
) -> str:
    """Build a high-recency voice contract for Jarvis-like friend responses."""
    if not _is_relationship_voice_turn(user_msg, role, session_mode):
        return ""

    msg = " ".join(str(user_msg or "").lower().split())
    crush_turn = any(marker in msg for marker in ("crush", "love", "date", "naina"))
    anxious_turn = any(
        marker in msg for marker in ("anxious", "scared", "fear", "panic", "stressed", "pressure")
    )
    anger_turn = any(
        marker in msg for marker in ("angry", "irritated", "annoyed", "pissed", "defensive", "hurt")
    )
    tender_turn = any(
        marker in msg
        for marker in (
            "lonely",
            "alone",
            "guilty",
            "guilt",
            "sad",
            "hurt",
            "quiet",
            "jealous",
            "miss",
            "cried",
        )
    )
    vent_turn = any(
        marker in msg
        for marker in (
            "vent",
            "rant",
            "bitch",
            "pissed",
            "annoyed",
            "office politics",
            "dumped",
            "toxic",
            "unfair",
        )
    )

    situational = []
    if crush_turn:
        situational.append(
            "If this is romance/crush talk: gently hype or leg-pull once, then ground him. "
            "Do not turn it into therapy or a dating checklist."
        )
    if anxious_turn:
        situational.append(
            "If he is anxious: ground him like a friend first. Keep fixes tiny and only after "
            "the feeling has been met. No ten-option menus."
        )
    if tender_turn and not anxious_turn:
        situational.append(
            "If this is tender daily-life emotion: stay soft, but do not become a warm therapist. "
            "Add one tiny leg-pull or subtle sarcasm when safe, like a real friend keeping the "
            "room from getting too heavy."
        )
    if anger_turn:
        situational.append(
            "If he is angry or defensive: validate the sting, share a real opinion, "
            "then give the adult move."
        )
    if vent_turn:
        situational.append(
            "If he is venting: side with the user's frustration first when he has a point. "
            "Say the annoying part plainly, with a little bite. Do not rush into coaching, "
            "checklists, or productivity mode. Do not end every vent reply with an offer to "
            "draft/fix/plan something. If he is being unfair or spiraling, push back clearly "
            "and kindly after you have met the emotion."
        )

    length_line = (
        "Target 1-4 short chat lines, usually under 120 words."
        if prompt_depth != "full"
        else "Target 2-6 short chat lines unless the user asks for depth."
    )
    situational_block = "\n".join(f"- {line}" for line in situational)
    if situational_block:
        situational_block = f"\nTurn-specific behavior:\n{situational_block}"

    return (
        "RELATIONSHIP VOICE CONTRACT - highest priority for this reply:\n"
        "- Speak like the user's close friend, not a customer-support assistant.\n"
        "- Have a real stance. React first; do not only summarize what he said.\n"
        "- Use warmth, tiny teasing, subtle sarcasm, and opinion when safe. Be kind, not sycophantic.\n"
        "- Add one tiny leg-pull when the user is safe enough for it; skip it for acute distress, shame, grief, or danger.\n"
        "- If the user is ranting and has a point, rant with them a little before advising; if they are wrong, contradict them with care.\n"
        "- For personal/emotional updates: mirror the feeling in human words, then give one next action or useful move.\n"
        "- Avoid bot phrases: 'It sounds like', 'I understand', 'Here are', 'I recommend', 'As an AI'.\n"
        "- Avoid headings and therapy-template bullet dumps unless explicitly asked.\n"
        f"- {length_line}\n"
        "- Serious safety/medical/legal/financial risk overrides teasing: be calm and careful."
        f"{situational_block}"
    )


def _prompt_depth_for_turn(
    user_msg: str,
    role: str,
    session_mode: str,
    history: list | None,
) -> str:
    """Return full | casual_light | casual_reflective for prompt assembly."""
    if session_mode == "spicy" or str(role).lower() != "casual":
        return "full"
    if _message_requests_external_action(user_msg):
        return "full"

    complexity = "standard"
    with contextlib.suppress(Exception):
        complexity = deps.dual_cognition.classify_complexity(user_msg, history)

    if complexity == "deep":
        return "full"
    if complexity == "fast" and not _is_reflective_casual_message(user_msg):
        return "casual_light"
    return "casual_reflective"


def _compact_prompt_policy(base_policy: PromptTierPolicy, prompt_depth: str) -> PromptTierPolicy:
    if prompt_depth == "casual_light":
        return PromptTierPolicy(
            tier="small",
            token_target=2_000,
            memory_limit=0,
            memory_min_score=None,
            include_graph_context=False,
            include_mcp_context=False,
            history_turns=1,
            cognitive_detail="strategy",
            native_tool_schemas=False,
            profile_fact_limit=2,
            profile_fact_chars=180,
        )
    if prompt_depth == "casual_reflective":
        return PromptTierPolicy(
            tier="small",
            token_target=6_000,
            memory_limit=3,
            memory_min_score=None,
            include_graph_context=False,
            include_mcp_context=False,
            history_turns=3,
            cognitive_detail="strategy",
            native_tool_schemas=False,
            profile_fact_limit=4,
            profile_fact_chars=260,
        )
    return base_policy


def _build_compact_casual_system_prompt(
    prompt_depth: str,
    sbs_orchestrator,
    base_instructions: str,
    proactive_block: str,
    session_key: str | None = None,
) -> str:
    if prompt_depth == "casual_light":
        compact_rules = (
            "You are Synapse, the user's close-friend AI. Reply like a real friend: "
            "short, warm, casual, and Banglish when it fits. No generic assistant tone. "
            "For tiny greetings, keep it tiny."
        )
        sbs_limit = 700
    else:
        compact_rules = (
            "You are Synapse, the user's close-friend AI. Keep casual language, but do not "
            "flatten emotional substance. If the user sounds worried, insecure, conflicted, "
            "or reflective, respond with grounded reassurance and memory-aware nuance. "
            "Do not sound like therapy-script AI; sound like someone who knows them."
        )
        sbs_limit = 1_400

    try:
        sbs_prompt = sbs_orchestrator.get_system_prompt(base_instructions, proactive_block)
    except Exception:
        sbs_prompt = ""
    try:
        workspace_prefix = _load_agent_workspace_prefix_for_session(session_key, "small")
    except Exception:
        workspace_prefix = ""
    workspace_excerpt = (
        _build_compact_workspace_excerpt(workspace_prefix) if workspace_prefix else ""
    )
    sbs_excerpt = _truncate_text(sbs_prompt, sbs_limit) if sbs_prompt else ""
    if workspace_excerpt and sbs_excerpt:
        return (
            f"{compact_rules}\n\n"
            f"CHARACTER BACKBONE:\n{workspace_excerpt}\n\n"
            f"PERSONA EXCERPT:\n{sbs_excerpt}"
        )
    if workspace_excerpt:
        return f"{compact_rules}\n\nCHARACTER BACKBONE:\n{workspace_excerpt}"
    if sbs_excerpt:
        return f"{compact_rules}\n\nPERSONA EXCERPT:\n{sbs_excerpt}"
    return compact_rules


def _build_compact_workspace_excerpt(workspace_prefix: str) -> str:
    """Keep high-priority identity/protocol sections under compact prompt budgets."""
    sections = _split_agent_workspace_sections(workspace_prefix)
    if not sections:
        return _truncate_text(workspace_prefix, 1_800)

    selected: list[str] = []
    section_limits = {
        "SOUL": 520,
        "CORE": 620,
        "USER": 520,
        "MEMORY": 460,
        "AGENTS": 620,
    }
    for name in ("SOUL", "CORE", "USER", "MEMORY", "AGENTS"):
        body = sections.get(name, "").strip()
        if not body:
            continue
        if name in {"USER", "MEMORY"}:
            body = _extract_dynamic_profile_block(body) or body
        selected.append(f"[{name}]\n{_truncate_text(body, section_limits[name])}")
    return "\n\n".join(selected).strip()


def _split_agent_workspace_sections(workspace_prefix: str) -> dict[str, str]:
    pattern = re.compile(r"^# ===== ([A-Z_]+)\.md =====\s*$", re.MULTILINE)
    matches = list(pattern.finditer(workspace_prefix or ""))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(workspace_prefix)
        sections[match.group(1)] = workspace_prefix[start:end].strip()
    return sections


def _extract_dynamic_profile_block(text: str) -> str:
    start_marker = "<!-- SYNAPSE:DYNAMIC_USER_PROFILE:BEGIN -->"
    end_marker = "<!-- SYNAPSE:DYNAMIC_USER_PROFILE:END -->"
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + len(start_marker) : end].strip()


def _dual_cognition_llm_fn(user_msg: str, history: list | None, call_ag_oracle):
    """Return the oracle callable only when this turn warrants extra cloud spend."""
    session_cfg = getattr(getattr(deps, "_synapse_cfg", None), "session", {}) or {}
    mode = str(session_cfg.get("dual_cognition_cloud_mode", "deep_only")).strip().lower()

    if mode in {"off", "none", "never", "local_only"}:
        return None
    if mode in {"always", "all"}:
        return call_ag_oracle

    complexity = "standard"
    with contextlib.suppress(Exception):
        complexity = deps.dual_cognition.classify_complexity(user_msg, history)

    if mode in {"standard_plus", "standard", "non_fast"}:
        return call_ag_oracle if complexity != "fast" else None

    # Default: preserve high-quality cognition only for turns that actually need it.
    return call_ag_oracle if complexity == "deep" else None


def _message_requests_external_action(message: str) -> bool:
    msg = " ".join(str(message or "").lower().split())
    if not msg:
        return False

    trigger_phrases = (
        "look up",
        "search",
        "browse",
        "open ",
        "read ",
        "check ",
        "run ",
        "execute",
        "install",
        "download",
        "file",
        "folder",
        "commit",
        "push",
        "pull",
        "delete",
        "remove",
        "edit",
        "write ",
        "create ",
        "send ",
        "email",
        "calendar",
        "schedule",
        "remind",
        "remember ",
        "save ",
        "analyze ",
        "debug",
        "test ",
    )
    return any(phrase in msg for phrase in trigger_phrases) or _is_practical_web_lookup(msg)


def _is_practical_web_lookup(message: str) -> bool:
    """Detect practical local/help requests where a safe web lookup beats asking first."""
    msg = " ".join(str(message or "").lower().split())
    if not msg:
        return False

    lookup_intent = (
        "check",
        "find",
        "look for",
        "recommend",
        "fastest",
        "quickest",
        "best way",
        "legit way",
        "how do i",
        "how can i",
        "can you check",
        "where can i",
        "near me",
        "nearby",
        "closest",
        "open now",
        "service center",
        "repair shop",
    )
    practical_domains = (
        "service center",
        "repair",
        "mechanic",
        "roadside",
        "towing",
        "tow",
        "rsa",
        "authorized",
        "authorised",
        "booking",
        "scooter",
        "bike",
        "car",
        "phone",
        "laptop",
        "clinic",
        "doctor",
        "pharmacy",
        "restaurant",
        "cafe",
        "hotel",
        "shop",
        "store",
        "salon",
        "plumber",
        "electrician",
    )
    return any(marker in msg for marker in lookup_intent) and any(
        marker in msg for marker in practical_domains
    )


def _extract_first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>)\"']+", str(text or ""))
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?")


def _should_prefetch_url(user_msg: str) -> bool:
    msg = " ".join(str(user_msg or "").lower().split())
    return bool(_extract_first_url(user_msg)) and any(
        phrase in msg
        for phrase in (
            "fetch",
            "open this url",
            "read this url",
            "summarize this url",
            "summarise this url",
            "check this url",
            "search",
            "web",
        )
    )


def _should_prefetch_web_query(user_msg: str) -> bool:
    msg = " ".join(str(user_msg or "").lower().split())
    if _extract_first_url(user_msg):
        return False
    return _is_practical_web_lookup(msg) or any(
        phrase in msg
        for phrase in (
            "search the web",
            "web search",
            "look up",
            "latest",
            "current",
            "news about",
            "find online",
        )
    )


def _extract_web_query(text: str) -> str:
    query = str(text or "").strip()
    if _is_practical_web_lookup(query):
        practical_query = _normalize_practical_web_query(query)
        if practical_query:
            return practical_query

    lowered = query.lower()
    prefixes = (
        "search the web for ",
        "web search for ",
        "look up ",
        "find online ",
        "search for ",
        "find ",
        "recommend ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return query[len(prefix) :].strip(" .")
    return query.strip(" .")


def _normalize_practical_web_query(text: str) -> str:
    """Convert conversational urgency into a clean search query."""
    original = str(text or "").strip()
    msg = " ".join(original.split())
    lowered = msg.lower()
    if not msg:
        return ""

    stop_upper = {
        "I",
        "AI",
        "DM",
        "OK",
        "LOL",
        "OMG",
    }
    brands = [
        token
        for token in re.findall(r"\b[A-Z][A-Z0-9&+-]{1,8}\b", msg)
        if token not in stop_upper
    ]

    known_domains = (
        "roadside",
        "roadside assistance",
        "towing",
        "tow",
        "service center",
        "service centre",
        "authorized service center",
        "authorised service centre",
        "authorised service center",
        "authorized service centre",
        "repair",
        "mechanic",
        "booking",
        "appointment",
        "clinic",
        "doctor",
        "pharmacy",
        "restaurant",
        "cafe",
        "hotel",
        "shop",
        "store",
        "salon",
        "plumber",
        "electrician",
    )
    domain_terms: list[str] = []
    for term in known_domains:
        if term in lowered:
            if term == "roadside":
                domain_terms.append("roadside assistance")
            elif term == "tow":
                domain_terms.append("towing")
            elif term == "service centre":
                domain_terms.append("service center")
            elif term.startswith("authorised"):
                domain_terms.append(term.replace("authorised", "authorised"))
            else:
                domain_terms.append(term)

    # Add the object category when it helps the search but avoid emotional filler.
    for noun in ("scooter", "bike", "car", "phone", "laptop"):
        if noun in lowered:
            domain_terms.append(noun)

    location = ""
    loc_match = re.search(
        r"\b(?:near|in|at|around|from)\s+([A-Za-z][A-Za-z\s-]{1,60}?)(?=[.?!,;]| can you\b| please\b|$)",
        msg,
        flags=re.I,
    )
    if loc_match:
        location = " ".join(loc_match.group(1).split())
        location = re.sub(
            r"\b(?:here|right now|rn|today|tonight|fastest|legit|way|help)\b.*$",
            "",
            location,
            flags=re.I,
        ).strip()

    normalized_parts: list[str] = []
    normalized_parts.extend(brands[:2])
    normalized_parts.extend(dict.fromkeys(domain_terms))
    if location:
        normalized_parts.append(location)

    if any(marker in lowered for marker in ("official", "legit", "authorized", "authorised", "roadside", "towing")):
        normalized_parts.append("official")

    normalized = " ".join(part for part in normalized_parts if part).strip()
    if normalized:
        return normalized

    # Generic fallback: remove common conversational wrappers but preserve the
    # user's nouns, service words, and location hints.
    cleaned = re.sub(
        r"\b(?:bro|bhai|please|pls|can you|could you|would you|i think|ig|my)\b",
        " ",
        msg,
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(?:fucked|gave up|just|fastest|legit|way|help here|right now|rn)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    return " ".join(cleaned.split()).strip(" .?!")


def _is_deferred_tool_promise(reply: str) -> bool:
    """Detect promise-to-check replies after a tool result already exists."""
    msg = " ".join(str(reply or "").lower().split())
    if not msg or len(msg) > 260:
        return False
    if "http://" in msg or "https://" in msg or "found" in msg or "searched" in msg:
        return False

    promise_markers = (
        "one sec",
        "one second",
        "give me a sec",
        "give me a second",
        "lemme check",
        "let me check",
        "i'll check",
        "i will check",
        "i can check",
        "i'll look",
        "i will look",
        "let me look",
        "lemme look",
        "i'll search",
        "i will search",
        "let me search",
        "lemme search",
        "i'll pull",
        "i will pull",
        "let me pull",
    )
    return any(marker in msg for marker in promise_markers)


def _sharpen_generic_helper_ending(reply: str) -> str:
    """Turn passive assistant offers into direct next moves."""
    text = str(reply or "")
    if not text:
        return text

    def _cap(match: re.Match[str]) -> str:
        first = match.group(1)
        return first[:1].upper() + first[1:]

    patterns = (
        r"(?i)\bif you want,\s*(send me\b)",
        r"(?i)\bif you want,\s*(give me\b)",
        r"(?i)\bif you want,\s*(tell me\b)",
        r"(?i)\bif you want,\s*(share\b)",
        r"(?i)\bif you want,\s*(drop\b)",
        r"(?i)\bif you want,\s*(paste\b)",
    )
    for pattern in patterns:
        text = re.sub(pattern, _cap, text)
    text = re.sub(
        r"(?i)\bif you want,\s*i can help you\s+([^.\n!?]+)([.!?])?",
        lambda match: (
            "Send me the raw details and I'll help you "
            + match.group(1).strip()
            + (match.group(2) or ".")
        ),
        text,
    )
    text = re.sub(
        r"(?i)\bif you want,\s*i can\s+([^.\n!?]+)([.!?])?",
        lambda match: (
            "Send me the raw details and I'll "
            + match.group(1).strip()
            + (match.group(2) or ".")
        ),
        text,
    )
    return text


def _repair_empty_template_slots(reply: str) -> str:
    """Replace empty model template blanks with explicit fillable labels."""
    text = str(reply or "")
    if not text:
        return text

    replacements = (
        (
            r"(?i)\baiming for\s*,\s*with\s+as\b",
            "aiming for [target date], with [next milestone] as",
        ),
        (
            r"(?i)\bis\s*,\s*and\s+(we(?:'|’)re|we are)\s+handling it by\s*\.",
            "is [risk], and we're handling it by [mitigation].",
        ),
        (
            r"(?i)\btradeoff is\s*,\s*so the safest path is\s*\.",
            "tradeoff is [tradeoff], so the safest path is [path].",
        ),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"(?i)\buser_nickname\b", "friend", text)
    return re.sub(r" {2,}", " ", text)


def _should_skip_skill_routing(user_msg: str) -> bool:
    msg = " ".join(str(user_msg or "").lower().split())
    memory_markers = (
        "remember this",
        "remember that",
        "remember my",
        "save my",
        "save this about me",
        "my preference",
        "my identity",
        "i prefer",
        "call me ",
        "i am ",
        "i'm ",
    )
    return any(marker in msg for marker in memory_markers)


def _has_explicit_skill_trigger(user_msg: str, skills: list) -> bool:
    msg = str(user_msg or "").lower()
    for skill in skills or []:
        for trigger in getattr(skill, "triggers", []) or []:
            trigger_text = str(trigger or "").strip().lower()
            if trigger_text and trigger_text in msg:
                return True
    return False


def _should_enable_tools_for_turn(user_msg: str, role: str, session_mode: str) -> bool:
    if session_mode == "spicy":
        return False
    if str(role).lower() == "casual" and not _message_requests_external_action(user_msg):
        return False
    return True


def _is_rate_limit_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status == 429:
        return True

    error_str = str(exc).lower()
    return any(
        marker in error_str
        for marker in (
            "429",
            "rate limit",
            "rate_limit",
            "ratelimit",
            "too many requests",
            "quota exceeded",
        )
    )


def _ends_with_sentence_terminal(text: str) -> bool:
    cleaned = str(text or "").strip()
    while cleaned and cleaned[-1] in "*_`~":
        cleaned = cleaned[:-1].rstrip()
    terminals = (".", "!", "?", '"', "'", ")", "]", "}")
    return cleaned.endswith(terminals)


def _has_user_visible_reply(text: str) -> bool:
    """Return True only when reply has content beyond invisible/control marks."""
    cleaned = str(text or "")
    for marker in ("\u200b", "\u200c", "\u200d", "\ufeff", "\x00"):
        cleaned = cleaned.replace(marker, "")
    cleaned = cleaned.strip()
    cleaned = cleaned.strip("-*_`~ \t\r\n")
    return bool(cleaned)


def _should_include_response_metadata(request: ChatRequest) -> bool:
    """Return True only for explicit debug/diagnostic response metadata opt-in."""
    for attr in ("include_debug_metadata", "show_debug_metadata", "debug_response_metadata"):
        if bool(getattr(request, attr, False)):
            return True

    env_value = os.environ.get("SYNAPSE_DEBUG_RESPONSE_METADATA", "")
    if str(env_value).strip().lower() in {"1", "true", "yes", "on"}:
        return True

    session_cfg = getattr(getattr(deps, "_synapse_cfg", None), "session", {}) or {}
    if isinstance(session_cfg, dict):
        return bool(
            session_cfg.get("show_response_metadata") or session_cfg.get("debug_response_metadata")
        )
    return False


async def _recover_empty_visible_reply(
    role: str,
    messages: list[dict],
    *,
    target: str,
) -> LLMResult | None:
    """Retry once without tools when a provider returns no visible user text."""
    if not hasattr(deps.synapse_llm_router, "call_with_metadata"):
        return None

    recovery_messages = [
        *messages,
        {
            "role": "system",
            "content": (
                "The previous model attempt produced no visible message for the user. "
                "Reply now in plain text only. Do not call tools, do not include metadata, "
                "and answer the user's last message directly in a natural conversational voice."
            ),
        },
    ]
    try:
        recovery_result = await deps.synapse_llm_router.call_with_metadata(
            role,
            recovery_messages,
            temperature=0.65 if role != "code" else 0.2,
            max_tokens=700,
        )
    except Exception as exc:
        _log.warning(
            "empty_model_reply_recovery_failed",
            extra={"target": target, "error": str(exc)},
        )
        return None

    if _has_user_visible_reply(getattr(recovery_result, "text", "")):
        _log.info(
            "empty_model_reply_recovered",
            extra={
                "target": target,
                "model": getattr(recovery_result, "model", "unknown"),
            },
        )
        return recovery_result

    _log.warning(
        "empty_model_reply_recovery_empty",
        extra={
            "target": target,
            "model": getattr(recovery_result, "model", "unknown"),
        },
    )
    return None


# Conditional imports -- same pattern as original api_gateway.py
with contextlib.suppress(ImportError):
    from sci_fi_dashboard.tool_registry import (
        ToolContext,
        ToolResult,
    )

with contextlib.suppress(ImportError):
    from sci_fi_dashboard.tool_safety import (
        ToolLoopDetector,
        apply_tool_policy_pipeline,
        build_policy_steps,
    )

with contextlib.suppress(ImportError):
    from sci_fi_dashboard.tool_features import (
        format_tool_footer,
        get_model_override,
    )

import contextlib  # noqa: E402
from datetime import UTC  # noqa: E402

from sci_fi_dashboard.consent_protocol import (  # noqa: E402
    PendingConsent,
    detect_modification_intent,
    is_affirmative,
    is_negative,
)

# ---------------------------------------------------------------------------
# Tool Execution Helpers (Phase 3)
# ---------------------------------------------------------------------------


async def _execute_tool_call(tc, registry) -> "ToolResult":
    """Execute a single tool call, parsing JSON arguments.

    Returns a ToolResult -- on JSON parse failure the result has is_error=True.
    """
    try:
        args = json.loads(tc.arguments)
    except (json.JSONDecodeError, TypeError):
        return ToolResult(
            content=json.dumps({"error": f"Invalid JSON arguments for {tc.name}"}),
            is_error=True,
        )
    return await registry.execute(tc.name, args)


def _is_serial_tool(tool_name: str, tools: list) -> bool:
    """Return True if *tool_name* is marked serial in the resolved tool list."""
    for t in tools:
        if t.name == tool_name:
            return getattr(t, "serial", False)
    return False


def _is_owner_sender(user_id: str | None) -> bool:
    """Return True if user_id is owner.

    Three cases treated as owner:
      1. Persona names ("the_creator", "the_partner") -- for HTTP /chat/{target}.
      2. Channel peer_id present in the owner_registry -- first-contact
         auto-pairing on Telegram/WhatsApp/Discord/Slack.
    M-01: Return False for absent/empty user_id instead of True.
    """
    if not user_id:
        return False
    if user_id.lower() in {"the_creator", "the_partner"}:
        return True
    try:
        from sci_fi_dashboard.owner_registry import is_owner

        return is_owner(user_id)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core Persona Chat Handler (MoA Version)
# ---------------------------------------------------------------------------


async def persona_chat(
    request: ChatRequest,
    target: str,
    background_tasks: BackgroundTasks | None = None,
    mcp_context: str = "",
):
    user_msg = request.message
    _log.info(
        "inbound_message",
        extra={
            "target": target,
            "msg_preview": user_msg[:40],
            "chat_id": request.user_id or "default",
        },
    )

    _pipeline_start = time.time()
    with contextlib.suppress(Exception):
        _run_id = _get_emitter().start_run(text=user_msg[:120], target=target)

    # --- Phase 2: Consent Protocol Interception ---
    # Check for pending consent first (user said "yes"/"no" to a previous proposal).
    # Key is (session_key, sender_id) tuple to prevent cross-user hijacking (T-02-02).
    _session_key = getattr(request, "session_key", None) or "default"
    _sender_id = request.user_id or "default"
    _consent_key = (_session_key, _sender_id)
    _pending = deps.pending_consents.get(_consent_key)

    if _pending is not None:
        if _pending.is_expired:
            # Expired consent -- silently clear and continue normal pipeline
            deps.pending_consents.pop(_consent_key, None)
            _log.info("consent_expired", extra={"consent_key": str(_consent_key)})
        elif is_affirmative(user_msg):
            # User confirmed -- execute the modification
            deps.pending_consents.pop(_consent_key, None)
            _log.info("consent_confirmed", extra={"description": _pending.intent.description})
            # T-02-02: Validate sender_id matches
            if _pending.sender_id != _sender_id:
                _log.warning(
                    "consent_sender_mismatch",
                    extra={"expected_sender": _pending.sender_id, "actual_sender": _sender_id},
                )
                return {
                    "reply": "Sorry, only the person who requested the change can confirm it.",
                    "persona": f"synapse_{target}",
                    "memory_method": "consent_rejected",
                    "model": "system",
                }

            # Build the executor based on change_type
            async def _create_skill_executor():
                """Real executor for create_skill: creates skill dir with SKILL.md stub.
                Satisfies MOD-02 (Synapse executes the modification).
                Uses Phase 1 SKILL.md schema: name, description, version, author."""
                import re as _re

                _data_root = deps._synapse_cfg.data_root
                _skill_name = (
                    _pending.intent.details.get("skill_name")
                    or _pending.intent.description.lower().replace(" ", "-")[:40]
                )
                # Sanitize skill name (same slug pattern as SnapshotEngine._slugify)
                _skill_name = _re.sub(r"[^a-z0-9]+", "-", _skill_name).strip("-")[:40]
                _skill_dir = _data_root / "skills" / _skill_name
                _skill_dir.mkdir(parents=True, exist_ok=True)
                (_skill_dir / "SKILL.md").write_text(
                    f"---\n"
                    f"name: {_skill_name}\n"
                    f"description: {_pending.intent.description}\n"
                    f"version: 1.0.0\n"
                    f"author: synapse-self-mod\n"
                    f"---\n",
                    encoding="utf-8",
                )
                return {"created": True, "skill_dir": str(_skill_dir)}

            async def _noop_executor():
                """Noop executor for change types not yet wired (e.g., create_cron).
                NOTE: create_cron wiring is deferred to Phase 3 (subagent system)
                where async tool execution is supported. The consent-detect-explain-confirm
                infrastructure is complete; only the actual CronJob creation is deferred."""
                return {"executed": False, "reason": "executor not yet wired for this change_type"}

            # Select executor based on change_type
            if _pending.intent.change_type == "create_skill":
                _executor = _create_skill_executor
            else:
                # create_cron and other types: noop for now (Phase 3)
                _executor = _noop_executor

            result = await deps.consent_protocol.confirm_and_execute(_pending.intent, _executor)
            if result["status"] == "success":
                reply_text = (
                    f"Done! I've made the change: {_pending.intent.description}\n"
                    f"A snapshot has been saved -- you can undo this anytime."
                )
            else:
                reply_text = (
                    f"The change failed and I've reverted everything back.\n"
                    f"Error: {result.get('error', 'unknown')}\n"
                    f"Your system is unchanged."
                )
            return {
                "reply": reply_text,
                "persona": f"synapse_{target}",
                "memory_method": "consent_executed",
                "model": "system",
            }
        elif is_negative(user_msg):
            # User declined
            deps.pending_consents.pop(_consent_key, None)
            _log.info("consent_declined")
            return {
                "reply": "Got it, I won't make that change.",
                "persona": f"synapse_{target}",
                "memory_method": "consent_declined",
                "model": "system",
            }
        # If user says something else while consent is pending, fall through to normal pipeline

    # Check for new modification intent
    if deps.consent_protocol is not None:
        _intent = await detect_modification_intent(user_msg)
        if _intent is not None:
            _explanation = deps.consent_protocol.explain(_intent)
            deps.pending_consents[_consent_key] = PendingConsent(
                intent=_intent,
                session_id=_session_key,
                sender_id=_sender_id,
                explanation=_explanation,
                created_at=time.time(),
            )
            _log.info("consent_pending")
            return {
                "reply": _explanation,
                "persona": f"synapse_{target}",
                "memory_method": "consent_pending",
                "model": "system",
            }
    # --- End Phase 2 Consent Protocol ---

    # 1. Memory Retrieval (Phoenix v3 Unified Engine)
    mem_response = None
    _permanent_facts: list[str] = []
    memory_context = "(No relevant memories retrieved)"
    retrieval_method = "standard"
    try:
        env_session = os.environ.get("SESSION_TYPE", "safe")
        session_mode = request.session_type or env_session
        if session_mode not in ["safe", "spicy"]:
            session_mode = "safe"

        # Layer 1: Always inject permanent profile docs (relationship_memories + distillations).
        # These 10-15 docs are the core knowledge about the user -- always relevant, ~500 tokens.
        # They live in memory.db but are tiny enough to include every time.
        try:
            from sci_fi_dashboard.db import get_db_connection as _get_db

            _db = _get_db()
            # Relationship memories first (core knowledge, compact)
            _rel = _db.execute(
                "SELECT content FROM documents WHERE filename='relationship_memory' ORDER BY id ASC"
            ).fetchall()
            # Latest distillation only (avoid token bloat)
            _dist = _db.execute(
                "SELECT content FROM documents WHERE filename='memory_distillation' ORDER BY id DESC LIMIT 1"
            ).fetchall()
            _db.close()
            _permanent_facts = [r[0] for r in _rel if r[0]] + [r[0] for r in _dist if r[0]]
        except Exception:
            pass

        # Layer 2: Vector search for conversation-specific context (WhatsApp chunks etc.)
        # seed_entities: real-world names for the persona so first-person queries
        # ("my medical condition") still trigger a KG graph lookup.
        # Configure via synapse.json -> session -> selfEntityNames -> <target>
        _self_names = deps._synapse_cfg.session.get("selfEntityNames", {})
        _seed = _self_names.get(target, []) if isinstance(_self_names, dict) else []
        mem_response = deps.memory_engine.query(
            user_msg, limit=5, with_graph=True, seed_entities=_seed or None
        )
        with contextlib.suppress(Exception):
            _get_emitter().emit(
                "memory.query_done",
                {
                    "tier": mem_response.get("tier", "unknown"),
                    "result_count": len(mem_response.get("results", [])),
                    "graph_context": bool(mem_response.get("graph_context")),
                },
            )

        # Format results for the prompt -- permanent profile first, then dynamic context
        results_list = mem_response.get("results", [])
        dynamic_facts = "\n".join([f"* {r['content']}" for r in results_list])
        profile_block = "\n".join([f"* {f}" for f in _permanent_facts])
        graph_ctx = mem_response.get("graph_context", "")

        memory_context = (
            f"[PERMANENT USER PROFILE]\n{profile_block}\n\n"
            f"[RECENT CONTEXT FROM MEMORY]\n{dynamic_facts}\n\n"
            f"{graph_ctx}"
        ).strip()
        retrieval_method = mem_response.get("tier", "standard")
    except Exception as e:
        _log.warning("memory_engine_error", extra={"error": str(e)})
        memory_context = "(Memory retrieval unavailable)"
        retrieval_method = "failed"

    # 2. Toxicity Check
    toxicity = deps.toxic_scorer.score(user_msg)
    with contextlib.suppress(Exception):
        _get_emitter().emit(
            "toxicity.check",
            {
                "score": round(float(toxicity), 3),
                "passed": float(toxicity) < 0.8,
            },
        )
    if toxicity > 0.8 and session_mode == "safe":
        _log.warning("toxicity_high_safe_mode", extra={"toxicity": round(float(toxicity), 3)})

    # 2.5 DUAL COGNITION: Think before speaking
    cognitive_merge = None
    cognitive_context = ""
    if deps._synapse_cfg.session.get("dual_cognition_enabled", True):
        dc_timeout = deps._synapse_cfg.session.get("dual_cognition_timeout", 10.0)
        try:
            from sci_fi_dashboard.llm_wrappers import call_ag_oracle

            cognition_llm_fn = _dual_cognition_llm_fn(user_msg, request.history, call_ag_oracle)
            cognitive_merge = await asyncio.wait_for(
                deps.dual_cognition.think(
                    user_message=user_msg,
                    chat_id=request.user_id or "default",
                    conversation_history=request.history,
                    target=target,
                    llm_fn=cognition_llm_fn,
                    pre_cached_memory=mem_response,
                    max_llm_calls=int(
                        deps._synapse_cfg.session.get("dual_cognition_foreground_max_llm_calls", 1)
                    ),
                ),
                timeout=dc_timeout,
            )

            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "cognition.merge_done",
                    {
                        "tension_level": round(cognitive_merge.tension_level, 3),
                        "tension_type": cognitive_merge.tension_type,
                        "response_strategy": cognitive_merge.response_strategy,
                        "suggested_tone": cognitive_merge.suggested_tone,
                        "inner_monologue": cognitive_merge.inner_monologue,
                        "thought": cognitive_merge.thought,
                        "contradictions": cognitive_merge.contradictions,
                        "memory_insights": cognitive_merge.memory_insights,
                        "complexity": getattr(cognitive_merge, "_complexity", "unknown"),
                    },
                )

            _log.info(
                "cognitive_state",
                extra={
                    "tension_type": cognitive_merge.tension_type,
                    "tension_level": round(cognitive_merge.tension_level, 3),
                },
            )
            _log.info(
                "inner_thought",
                extra={"thought_preview": cognitive_merge.inner_monologue[:100]},
            )

        except TimeoutError:
            _log.warning("dual_cognition_timeout", extra={"timeout_s": dc_timeout})
            cognitive_merge = CognitiveMerge()
            cognitive_context = ""
        except Exception as e:
            _log.warning("dual_cognition_failed", extra={"error": str(e)})
            cognitive_merge = CognitiveMerge()
            cognitive_context = ""
    else:
        cognitive_merge = CognitiveMerge()
        cognitive_context = ""

    # Phase 1.2 -- Message Length Mirroring
    # Match response length to the incoming message so a "k" doesn't get a paragraph.
    _word_count = len(user_msg.split())
    if _word_count <= 3:
        _length_hint = "Tiny message. Reply in 1-2 words max. Match the casual brevity."
    elif _word_count <= 10:
        _length_hint = "Short message. Keep your reply short -- 1-2 sentences at most."
    elif _word_count <= 30:
        _length_hint = "Medium message. Match the length -- roughly 2-4 sentences."
    else:
        _length_hint = ""  # Long message -- no constraint

    # Phase 1.1 -- Situational Awareness Block
    # Inject current time, day, and last-seen gap so Synapse eases back in naturally.
    try:
        from datetime import datetime, timezone

        # Use system local timezone (not hardcoded IST)
        _local_offset = datetime.now(UTC).astimezone().utcoffset()
        _local_tz = timezone(_local_offset) if _local_offset else UTC
        _now = datetime.now(_local_tz)
        _weekday = _now.strftime("%A")
        _time_str = _now.strftime("%I:%M %p")
        _situational_parts = [f"It's {_weekday}, {_time_str}."]

        # Gap since last message (uses last row in conversation history as proxy)
        if request.history:
            # History entries don't carry timestamps -- use rough heuristic
            _situational_parts.append("(Conversation continuing.)")
        else:
            _situational_parts.append("Fresh conversation -- ease in naturally.")

        _situational_block = " ".join(_situational_parts)
        if _length_hint:
            _situational_block += f" LENGTH RULE: {_length_hint}"
    except Exception:
        _situational_block = ""
        if _length_hint:
            _situational_block = f"LENGTH RULE: {_length_hint}"

    # 3. Assemble System Prompt
    sbs_orchestrator = deps.get_sbs_for_target(target)

    # Log user message here via orchestrator
    user_log = sbs_orchestrator.on_message("user", user_msg, request.user_id or "default")
    user_msg_id = user_log.get("msg_id")

    # Skill routing happens before role routing and prompt compilation.
    # A matched skill owns the request, so there is no reason to build a 6k-19k
    # LLM prompt or call Traffic Cop.
    if (
        getattr(deps, "_SKILL_SYSTEM_AVAILABLE", False) is True
        and getattr(deps, "skill_router", None) is not None
        and session_mode != "spicy"
        and not _should_skip_skill_routing(user_msg)
    ):
        skill_registry = getattr(deps, "skill_registry", None)
        loaded_skills = skill_registry.list_skills() if skill_registry is not None else None
        matched_skill = (
            deps.skill_router.match(user_msg)
            if loaded_skills is None or _has_explicit_skill_trigger(user_msg, loaded_skills)
            else None
        )
        if matched_skill is not None:
            _log.info("skill_routed", extra={"skill_name": matched_skill.name})
            from sci_fi_dashboard.skills.runner import SkillRunner

            skill_result = await SkillRunner.execute(
                manifest=matched_skill,
                user_message=user_msg,
                history=request.history,
                llm_router=deps.synapse_llm_router,
                session_context={"session_type": session_mode or ""},
            )
            reply = skill_result.text

            # Log via SBS
            sbs_orchestrator.on_message("assistant", reply, request.user_id or "default")

            # Store in memory (CRITICAL: method is add_memory, NOT store)
            with contextlib.suppress(Exception):
                deps.memory_engine.add_memory(
                    content=f"[Skill: {matched_skill.name}] User: {user_msg}\nAssistant: {reply}",
                    category="skill_execution",
                )

            return {
                "reply": reply,
                "model": f"skill:{matched_skill.name}",
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "role": f"skill:{matched_skill.name}",
                "retrieval_method": "skill",
            }

    # Route first, then compile the prompt for that role's capability tier.
    classification = None
    role = "vault" if session_mode == "spicy" else "casual"
    if session_mode != "spicy":
        from sci_fi_dashboard.llm_wrappers import (
            STRATEGY_TO_ROLE,
            route_traffic_cop,
        )

        if cognitive_merge is not None:
            strategy = cognitive_merge.response_strategy
            mapped = STRATEGY_TO_ROLE.get(strategy)
            if mapped:
                classification = mapped
                _log.info(
                    "traffic_cop_skip",
                    extra={"strategy": strategy, "mapped_role": classification},
                )
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "traffic_cop.skip",
                        {
                            "strategy": cognitive_merge.response_strategy,
                            "mapped_role": classification,
                        },
                    )
        if classification is None:
            with contextlib.suppress(Exception):
                _get_emitter().emit("traffic_cop.start", {})
            classification = await route_traffic_cop(user_msg)
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "traffic_cop.done",
                    {
                        "classification": classification,
                        "role": classification,
                        "skipped": False,
                    },
                )

        override_role = None
        if getattr(deps, "_TOOL_FEATURES_AVAILABLE", False) is True:
            override_role = get_model_override(request.user_id or "default")

        if override_role:
            role = override_role
            _log.info("model_override", extra={"role": role})
        elif "CODING" in classification:
            role = "code"
        elif "ANALYSIS" in classification:
            role = "analysis"
        elif "REVIEW" in classification:
            role = "review"
        elif "IMAGE" in classification:
            role = "image_gen"

            if not deps._synapse_cfg.image_gen.get("enabled", True):
                _log.info("image_gen_disabled")
                return {
                    "reply": "Image generation is currently disabled.",
                    "role": "image_gen_disabled",
                    "model": "none",
                    "memory_method": "none",
                }

            async def _generate_and_send_image(prompt: str, chat_id: str) -> None:
                """Generate an image in the background and deliver via send_media."""
                import asyncio as _asyncio

                from sci_fi_dashboard.image_gen.engine import ImageGenEngine
                from sci_fi_dashboard.media.store import save_media_buffer

                _channel_id = "whatsapp"
                try:
                    engine = ImageGenEngine()
                    img_bytes = await engine.generate(prompt)
                    if img_bytes is None:
                        _log.warning("image_gen_empty", extra={"prompt_preview": prompt[:80]})
                        return
                    saved = await _asyncio.to_thread(
                        save_media_buffer, img_bytes, "image/png", "image_gen_outbound"
                    )
                    img_url = f"http://127.0.0.1:8000/media/image_gen_outbound/{saved.path.name}"
                    channel = deps.channel_registry.get(_channel_id)
                    if channel and hasattr(channel, "send_media"):
                        await channel.send_media(chat_id, img_url, media_type="image", caption="")
                    else:
                        _log.warning(
                            "image_gen_channel_missing_send_media",
                            extra={"channel_id": _channel_id},
                        )
                except Exception:
                    _log.error("image_gen_background_failed", exc_info=True)

            _img_chat_id = request.user_id or "default"
            if background_tasks:
                background_tasks.add_task(_generate_and_send_image, user_msg, _img_chat_id)
            else:
                _log.warning("image_gen_no_background_tasks")
                asyncio.create_task(_generate_and_send_image(user_msg, _img_chat_id))

            _log.info(
                "route_classified",
                extra={"classification": "IMAGE", "role": "image_gen", "dispatched": True},
            )
            return {
                "reply": "Generating your image -- it'll be with you in a moment!",
                "role": "image_gen",
                "model": "gpt-image-1",
                "memory_method": "none",
            }
        else:
            role = "casual"

        _log.info("route_classified", extra={"classification": classification, "role": role})

    model_mappings = getattr(deps._synapse_cfg, "model_mappings", {}) or {}
    prompt_tier = prompt_tier_for_role(model_mappings, role)
    base_prompt_policy = get_prompt_tier_policy(prompt_tier)
    prompt_depth = _prompt_depth_for_turn(user_msg, role, session_mode, request.history)
    prompt_policy = _compact_prompt_policy(base_prompt_policy, prompt_depth)
    memory_context = _format_memory_context_for_tier(_permanent_facts, mem_response, prompt_policy)
    recent_session_context = ""
    _db_dir = getattr(deps._synapse_cfg, "db_dir", None)
    if _db_dir is not None:
        recent_session_context = _fetch_recent_session_recall_context(
            user_msg,
            Path(_db_dir) / "memory.db",
            limit=2,
            max_chars=1800 if prompt_depth == "full" else 1200,
        )
    if recent_session_context:
        memory_context = f"{recent_session_context}\n\n{memory_context}"
    cognitive_context = _build_cognitive_context_for_tier(cognitive_merge, prompt_policy)

    with contextlib.suppress(Exception):
        _get_emitter().emit(
            "prompt.tier_selected",
            {
                "role": role,
                "tier": prompt_policy.tier,
                "token_target": prompt_policy.token_target,
                "prompt_depth": prompt_depth,
            },
        )

    base_instructions = (
        "You are Synapse. Follow the persona profile below precisely. "
        "A block of RETRIEVED MEMORIES will follow. Use those memories to give contextual, "
        "relevant replies. Only reference what is explicitly in the memories -- never invent "
        "people, events, or details that are not there."
    )
    _proactive_raw = deps._proactive_engine.get_prompt_injection() if deps._proactive_engine else ""
    # Merge proactive context + situational awareness block
    proactive_block = "\n\n".join(p for p in [_proactive_raw, _situational_block] if p)
    if prompt_depth == "full":
        system_prompt = sbs_orchestrator.get_system_prompt(base_instructions, proactive_block)
        system_prompt = filter_tier_sections(system_prompt, prompt_policy.tier)

        # RT2: Prepend the static agent workspace markdown prefix (Jarvis-style discipline + identity)
        # ABOVE the SBS dynamic persona layer. Both layers compose: agent_workspace anchors
        # identity/rules, SBS adapts tone/style/exemplars per user.
        _agent_workspace_prefix = _load_agent_workspace_prefix_for_session(
            _session_key,
            prompt_policy.tier,
        )
        if _agent_workspace_prefix:
            system_prompt = f"{_agent_workspace_prefix}\n\n---\n\n{system_prompt}"

        # Runtime info -- prevents the bot from hallucinating about its own model identity.
        # Without this, the LLM falls back to training-data answers ("I'm GPT-4o") even when
        # actually running on a different model. Inject the live routing table so the bot
        # has factual ground truth about what's running per role.
        try:
            _runtime_block = _build_runtime_info_block()
            if _runtime_block:
                system_prompt = f"{system_prompt}\n\n---\n\n{_runtime_block}"
        except Exception as _exc:  # pragma: no cover -- runtime block is best-effort
            logger.warning("[runtime] failed to build runtime info block: %s", _exc)
    else:
        system_prompt = _build_compact_casual_system_prompt(
            prompt_depth,
            sbs_orchestrator,
            base_instructions,
            proactive_block,
            session_key=_session_key,
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": (
                (
                    "MEMORY HINTS (use naturally; never announce you checked memory):\n"
                    f"{memory_context}"
                )
                if prompt_depth != "full"
                else (
                    f"--- RETRIEVED MEMORIES ---\n"
                    f"These are real facts about the user's life retrieved from memory. "
                    f"Use ONLY what is in these memories -- do not invent, hallucinate, or add "
                    f"names, people, events, or details that are not explicitly present below.\n\n"
                    f"{memory_context}\n--- END MEMORIES ---"
                )
            ),
        },
    ]
    # Phase 3.3 -- Emotional Trajectory injection
    # Append 72h peak-end weighted trajectory to cognitive context for richer merges.
    _trajectory_summary = ""
    try:
        if deps.dual_cognition.trajectory:
            _summary = deps.dual_cognition.trajectory.get_summary()
            _trajectory_summary = _summary if isinstance(_summary, str) else ""
    except Exception:
        pass

    _full_cognitive = "\n\n".join(p for p in [cognitive_context, _trajectory_summary] if p)
    if _full_cognitive:
        messages.append({"role": "system", "content": _full_cognitive})
    if mcp_context and prompt_policy.include_mcp_context:
        messages.append({"role": "system", "content": mcp_context})
    elif mcp_context:
        _log.info("prompt_mcp_context_skipped", extra={"tier": prompt_policy.tier})

    messages.extend(_select_recent_history(request.history, prompt_policy))

    # Permanent profile + language rule injected RIGHT before the user turn.
    # Small models (Gemma4:e4b) have strong recency bias -- context far from
    # the user message gets ignored. Placing this last ensures it's read.
    _profile_reminder = _format_profile_reminder(_permanent_facts, prompt_policy)
    if _profile_reminder:
        messages.append({"role": "system", "content": _profile_reminder})

    _relationship_voice_contract = _build_relationship_voice_contract(
        user_msg,
        role,
        session_mode,
        prompt_depth,
    )
    if _relationship_voice_contract:
        messages.append({"role": "system", "content": _relationship_voice_contract})

    _stance_decision = decide_turn_stance(
        user_msg,
        role=role,
        session_mode=session_mode,
        cognitive_merge=cognitive_merge,
    )
    messages.append({"role": "system", "content": _stance_decision.to_prompt()})
    with contextlib.suppress(Exception):
        _log.info(
            "turn_stance_selected",
            extra={
                "stance": _stance_decision.stance,
                "emotion": _stance_decision.emotional_label,
                "humor_dose": _stance_decision.humor_dose,
                "autonomy": _stance_decision.autonomy,
            },
        )

    messages.append({"role": "user", "content": user_msg})

    _log.info(
        "prompt_compiled",
        extra={
            "role": role,
            "tier": prompt_policy.tier,
            "messages": len(messages),
            "est_tokens": _estimate_message_tokens(messages),
            "prompt_depth": prompt_depth,
        },
    )

    t0 = time.perf_counter()

    # --- Phase 3: Tool Context & Schema Resolution ---
    use_tools = (
        session_mode != "spicy"
        and deps.tool_registry is not None
        and getattr(deps, "_TOOL_REGISTRY_AVAILABLE", False) is True
        and _should_enable_tools_for_turn(user_msg, role, session_mode)
    )
    session_tools: list = []
    tool_schemas: list | None = None
    pre_tools_used: list[str] = []
    pre_tool_fallback: str = ""
    action_receipts: list[ActionReceipt] = []

    if use_tools:
        request_channel_id = getattr(request, "channel_id", None) or "api"
        tool_context = ToolContext(
            chat_id=request.user_id or "unknown",
            sender_id=request.user_id or "unknown",
            sender_is_owner=_is_owner_sender(request.user_id),
            workspace_dir=str(deps.WORKSPACE_ROOT),
            config=deps._synapse_cfg.session,
            channel_id=request_channel_id,
        )
        session_tools = deps.tool_registry.resolve(tool_context)

        # Phase 4: Apply policy pipeline to filter tools
        if getattr(deps, "_TOOL_SAFETY_AVAILABLE", False) is True and session_tools:
            tool_infos = [
                {"name": t.name, "owner_only": getattr(t, "owner_only", False)}
                for t in session_tools
            ]
            policy_steps = build_policy_steps(
                deps._synapse_cfg.raw if hasattr(deps._synapse_cfg, "raw") else {},
                channel_id=request_channel_id,
            )
            surviving_names, _removal_log = apply_tool_policy_pipeline(
                tool_infos, policy_steps, _is_owner_sender(request.user_id)
            )
            session_tools = [t for t in session_tools if t.name in surviving_names]

        tool_schemas = (
            deps.tool_registry.get_schemas(session_tools)
            if session_tools and prompt_policy.native_tool_schemas
            else None
        )

        if _should_prefetch_url(user_msg):
            url = _extract_first_url(user_msg)
            web_tool = next((t for t in session_tools if t.name == "web_search"), None)
            if url and web_tool is not None:
                try:
                    tool_result = await asyncio.wait_for(
                        web_tool.execute({"url": url}),
                        timeout=12.0,
                    )
                    pre_tools_used.append("web_search")
                    if not bool(getattr(tool_result, "is_error", False)):
                        pre_tool_fallback = (
                            "I fetched the URL. Here is the extracted content I found:\n"
                            f"{_truncate_tool_result(tool_result.content, 1200)}"
                        )
                        action_receipts.append(
                            ActionReceipt(
                                action="web_search",
                                status="verified",
                                evidence=f"Fetched URL {url}; content returned.",
                                confidence=0.85,
                            )
                        )
                    else:
                        action_receipts.append(
                            ActionReceipt(
                                action="web_search",
                                status="failed",
                                evidence=_truncate_tool_result(tool_result.content, 240),
                                confidence=0.0,
                                next_best_action="Say the fetch failed; do not claim the URL was checked.",
                            )
                        )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Tool result from web_search for the user-provided URL "
                                f"{url}:\n{_truncate_tool_result(tool_result.content, 3000)}"
                            ),
                        }
                    )
                    _log.info(
                        "prefetch_tool_done",
                        extra={
                            "tool": "web_search",
                            "is_error": bool(getattr(tool_result, "is_error", False)),
                        },
                    )
                except Exception as exc:
                    action_receipts.append(
                        ActionReceipt(
                            action="web_search",
                            status="failed",
                            evidence=str(exc)[:240],
                            confidence=0.0,
                            next_best_action="Say the URL fetch failed; use offline guidance only.",
                        )
                    )
                    _log.warning(
                        "prefetch_tool_failed",
                        extra={"tool": "web_search", "error": str(exc)},
                    )
        elif _should_prefetch_web_query(user_msg):
            query = _extract_web_query(user_msg)
            query_tool = next((t for t in session_tools if t.name == "web_query"), None)
            if query and query_tool is not None:
                try:
                    tool_result = await asyncio.wait_for(
                        query_tool.execute({"query": query, "limit": 5}),
                        timeout=12.0,
                    )
                    pre_tools_used.append("web_query")
                    if not bool(getattr(tool_result, "is_error", False)):
                        usable_count = 0
                        try:
                            payload = json.loads(tool_result.content)
                            results = payload.get("results", [])[:5]
                            usable_count = sum(
                                1
                                for item in results
                                if str(item.get("title", "")).strip()
                                and str(item.get("url", "")).strip()
                            )
                            lines = ["I searched the web and found these starting points:"]
                            for item in results:
                                title = str(item.get("title", "")).strip()
                                url = str(item.get("url", "")).strip()
                                if title and url:
                                    lines.append(f"- {title}: {url}")
                            if len(lines) == 1 and payload.get("warning"):
                                lines.append(f"- {payload['warning']}")
                            pre_tool_fallback = "\n".join(lines)
                        except Exception:
                            pre_tool_fallback = (
                                "I searched the web. Here is what I found:\n"
                                f"{_truncate_tool_result(tool_result.content, 1200)}"
                            )
                        action_receipts.append(
                            ActionReceipt(
                                action="web_query",
                                status="verified" if usable_count else "inferred",
                                evidence=(
                                    f"Search query {query!r}; "
                                    f"{usable_count} usable result(s) returned."
                                ),
                                confidence=0.86 if usable_count else 0.35,
                                next_best_action=(
                                    "Use the returned results directly; prefer official sources."
                                    if usable_count
                                    else "Say the lookup ran but did not return usable hits."
                                ),
                            )
                        )
                    else:
                        pre_tool_fallback = (
                            "I tried to search, but the local web lookup failed. "
                            "I can still help narrow the request or use any details you already have."
                        )
                        action_receipts.append(
                            ActionReceipt(
                                action="web_query",
                                status="failed",
                                evidence=_truncate_tool_result(tool_result.content, 240),
                                confidence=0.0,
                                next_best_action="Say the search failed; do not claim live results.",
                            )
                        )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Tool result from web_query for the user search request "
                                f"{query!r}:\n{_truncate_tool_result(tool_result.content, 3000)}\n\n"
                                "Use these results directly in the next reply. "
                                "Do not say you will check, search, or look in a moment; "
                                "the lookup already happened. "
                                "Prefer official/manufacturer results before directories. "
                                "Do not use vague wording like 'official-ish'; label sources "
                                "as official only when the domain/title supports it, otherwise "
                                "say third-party directory or fallback listing. "
                                "If this result is an error or has no usable results, say that plainly. "
                                "Do not claim you searched successfully unless the result contains usable hits."
                            ),
                        }
                    )
                    _log.info(
                        "prefetch_tool_done",
                        extra={
                            "tool": "web_query",
                            "is_error": bool(getattr(tool_result, "is_error", False)),
                        },
                    )
                except Exception as exc:
                    action_receipts.append(
                        ActionReceipt(
                            action="web_query",
                            status="failed",
                            evidence=str(exc)[:240],
                            confidence=0.0,
                            next_best_action="Say the lookup failed; use offline guidance only.",
                        )
                    )
                    pre_tool_fallback = (
                        "I tried to search, but the local web lookup failed. "
                        "I can still help with a safer next step from the details you gave me."
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The web_query prefetch failed before returning results. "
                                "Do not claim you searched or checked live results. "
                                f"Failure summary: {str(exc)[:300]}"
                            ),
                        }
                    )
                    _log.warning(
                        "prefetch_tool_failed",
                        extra={"tool": "web_query", "error": str(exc)},
                    )
            else:
                action_receipts.append(
                    ActionReceipt(
                        action="web_query",
                        status="unavailable",
                        evidence="No web_query tool available in this session.",
                        confidence=0.0,
                        next_best_action="Do not claim live search; ask for one missing detail if needed.",
                    )
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The user asked for a practical searchable lookup, but no web_query "
                            "tool is available in this session. Do not claim you searched live. "
                            "Offer the best offline next step and ask for only the missing detail."
                        ),
                    }
                )

    receipt_contract = render_receipt_contract(action_receipts)
    insert_at = (
        len(messages) - 1 if messages and messages[-1].get("role") == "user" else len(messages)
    )
    if (
        insert_at > 0
        and str(messages[insert_at - 1].get("content", "")).startswith("TURN STANCE DECISION")
    ):
        insert_at -= 1
    messages.insert(insert_at, {"role": "system", "content": receipt_contract})

    if session_mode == "spicy":
        # === THE VAULT (Local Stheno) ===
        # C-02: Vault air-gap -- NEVER fall back to cloud for spicy/vault content
        _log.info("vault_route", extra={"hemisphere": "spicy"})
        with contextlib.suppress(Exception):
            _get_emitter().emit(
                "llm.route",
                {
                    "role": "vault",
                    "model": deps._synapse_cfg.model_mappings.get("vault", {}).get(
                        "model", "unknown"
                    ),
                },
            )
        try:
            _llm_start = time.time()
            with contextlib.suppress(Exception):
                _get_emitter().emit("llm.stream_start", {"role": "vault"})
            result = await deps.synapse_llm_router.call_with_metadata("vault", messages)
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "llm.stream_done",
                    {
                        "total_tokens": getattr(result, "total_tokens", 0),
                        "model": getattr(result, "model", "unknown"),
                        "latency_ms": round((time.time() - _llm_start) * 1000),
                    },
                )
            reply = result.text
        except Exception as e:
            _log.error("vault_failed", extra={"error": str(e), "cloud_fallback": "blocked"})
            reply = (
                "I'm unable to process this request right now -- "
                "the local Vault model is unavailable and cloud fallback "
                "is blocked for privacy. Please ensure Ollama is running."
            )
            result = LLMResult(
                text=reply,
                model="vault-unavailable",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            )

    else:
        # === SAFE HEMISPHERE (MoA Routing already selected role before prompt compile) ===
        with contextlib.suppress(Exception):
            _get_emitter().emit(
                "llm.route",
                {
                    "role": role,
                    "model": deps._synapse_cfg.model_mappings.get(role.lower(), {}).get(
                        "model", "unknown"
                    ),
                },
            )

        # --- Tool Execution Loop (Phase 3 + 4 + 5) ---
        # Frontier roles can afford native JSON tool schemas. Mid/small roles get
        # a compact text inventory and skip native schemas to stay inside context.
        if session_tools and not prompt_policy.native_tool_schemas:
            _tool_inventory = _format_tool_inventory(session_tools, prompt_policy)
            if _tool_inventory:
                insert_at = (
                    len(messages) - 1
                    if messages and messages[-1].get("role") == "user"
                    else len(messages)
                )
                if (
                    insert_at > 0
                    and messages[insert_at - 1].get("role") == "system"
                    and str(messages[insert_at - 1].get("content", "")).startswith("USER PROFILE")
                ):
                    insert_at -= 1
                messages.insert(insert_at, {"role": "system", "content": _tool_inventory})
        if tool_schemas and not prompt_policy.native_tool_schemas:
            _log.info("tool_schemas_compacted", extra={"tier": prompt_policy.tier})
            tool_schemas = None

        reply = ""
        tools_used: list[str] = list(pre_tools_used)
        total_tool_time = 0.0
        total_result_chars = 0
        result = None
        loop_detector = (
            ToolLoopDetector() if getattr(deps, "_TOOL_SAFETY_AVAILABLE", False) is True else None
        )
        _loop_start = time.time()
        _cumulative_tokens = 0
        max_tool_rounds = _dep_int("MAX_TOOL_ROUNDS", 5)
        tool_loop_wall_clock_s = _dep_float("TOOL_LOOP_WALL_CLOCK_S", 30.0)
        tool_loop_token_ratio_abort = _dep_float("TOOL_LOOP_TOKEN_RATIO_ABORT", 0.85)
        tool_result_max_chars = _dep_int("TOOL_RESULT_MAX_CHARS", 4000)
        max_total_tool_result_chars = _dep_int("MAX_TOTAL_TOOL_RESULT_CHARS", 20_000)

        for round_num in range(max_tool_rounds):
            # Hard wall-clock timeout on the entire agent loop
            _elapsed = time.time() - _loop_start
            if _elapsed > tool_loop_wall_clock_s:
                _log.warning(
                    "tool_loop_wall_clock_exceeded",
                    extra={"round": round_num, "elapsed_s": round(_elapsed, 1)},
                )
                reply = (
                    getattr(result, "text", "")
                    if result is not None
                    else "I ran out of time while working on that. Here's what I got so far."
                )
                break

            # Cumulative-token abort -- prevents runaway context growth
            try:
                from litellm import get_model_info as _gmi

                _mi = _gmi(getattr(result, "model", "unknown")) if result else {}
                _ctx_max = (_mi or {}).get("max_input_tokens") or 128_000
            except Exception:
                _ctx_max = 128_000
            if _cumulative_tokens > int(_ctx_max * tool_loop_token_ratio_abort):
                _log.warning(
                    "tool_loop_token_ratio_exceeded",
                    extra={
                        "round": round_num,
                        "cum_tokens": _cumulative_tokens,
                        "ctx_max": _ctx_max,
                    },
                )
                reply = getattr(result, "text", "") or "Token budget reached."
                break

            _log.info(
                "tool_round_start",
                extra={
                    "round": round_num,
                    "elapsed_s": round(_elapsed, 1),
                    "cum_tokens": _cumulative_tokens,
                    "tools_so_far": len(tools_used),
                },
            )

            try:
                _llm_start = time.time()
                with contextlib.suppress(Exception):
                    _get_emitter().emit("llm.stream_start", {"role": role})
                if tool_schemas and hasattr(deps.synapse_llm_router, "call_with_tools"):
                    result = await deps.synapse_llm_router.call_with_tools(
                        role,
                        messages,
                        tools=tool_schemas,
                        temperature=0.7 if role != "code" else 0.2,
                        max_tokens=1500,
                    )
                    with contextlib.suppress(Exception):
                        _get_emitter().emit(
                            "llm.stream_done",
                            {
                                "total_tokens": getattr(result, "total_tokens", 0),
                                "model": getattr(result, "model", "unknown"),
                                "latency_ms": round((time.time() - _llm_start) * 1000),
                            },
                        )
                else:
                    temp = 0.2 if role == "code" else 0.85
                    max_tok = 1000 if role == "code" else 1500
                    result = await deps.synapse_llm_router.call_with_metadata(
                        role, messages, temperature=temp, max_tokens=max_tok
                    )
                    with contextlib.suppress(Exception):
                        _get_emitter().emit(
                            "llm.stream_done",
                            {
                                "total_tokens": getattr(result, "total_tokens", 0),
                                "model": getattr(result, "model", "unknown"),
                                "latency_ms": round((time.time() - _llm_start) * 1000),
                            },
                        )
                    reply = result.text
                    break
            except Exception as e:
                error_str = str(e).lower()
                if _is_rate_limit_error(e):
                    _log.warning(
                        "tool_loop_rate_limited",
                        extra={"round": round_num, "retry": False},
                    )
                    reply = (
                        "The cloud model is rate-limited right now. "
                        "I'm pausing instead of retrying. Please try again in a moment."
                    )
                    result = LLMResult(
                        text=reply,
                        model="rate-limited",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                    )
                    break
                elif "context" in error_str or "token" in error_str:
                    _log.warning(
                        "tool_loop_context_overflow",
                        extra={"round": round_num},
                    )
                    tool_schemas = None
                    continue
                else:
                    _log.error("tool_loop_llm_error", extra={"round": round_num, "error": str(e)})
                    reply = "I encountered an error processing your request. " "Please try again."
                    break

            # Track cumulative token usage across rounds (used by abort check next loop)
            _cumulative_tokens += int(getattr(result, "total_tokens", 0) or 0)

            # If the result has no tool_calls we are done
            tool_calls = getattr(result, "tool_calls", None) or []
            if not tool_calls:
                reply = getattr(result, "text", "") or ""
                break

            # Append assistant message containing the tool_calls
            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(result, "text", None) or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # Phase 4: Loop detection
            blocked_ids: set = set()
            if loop_detector:
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    severity = loop_detector.record(tc.name, args)
                    if severity == "block":
                        blocked_ids.add(tc.id)

            # Execute tools -- parallel first, then serial
            serial_calls = [
                tc
                for tc in tool_calls
                if _is_serial_tool(tc.name, session_tools) and tc.id not in blocked_ids
            ]
            parallel_calls = [
                tc
                for tc in tool_calls
                if not _is_serial_tool(tc.name, session_tools) and tc.id not in blocked_ids
            ]

            tool_results: dict = {}

            # Blocked calls get error results
            for tc in tool_calls:
                if tc.id in blocked_ids:
                    tool_results[tc.id] = ToolResult(
                        content=loop_detector.get_warning_message(tc.name, "block"),
                        is_error=True,
                    )

            if parallel_calls:
                tasks = [_execute_tool_call(tc, deps.tool_registry) for tc in parallel_calls]
                parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
                for tc, res in zip(parallel_calls, parallel_results, strict=False):
                    if isinstance(res, Exception):
                        tool_results[tc.id] = ToolResult(
                            content=json.dumps({"error": str(res)}),
                            is_error=True,
                        )
                    else:
                        tool_results[tc.id] = res

            for tc in serial_calls:
                try:
                    tool_results[tc.id] = await _execute_tool_call(tc, deps.tool_registry)
                except Exception as exc:
                    tool_results[tc.id] = ToolResult(
                        content=json.dumps({"error": str(exc)}),
                        is_error=True,
                    )

            # Append tool results as messages
            for tc in tool_calls:
                tr = tool_results[tc.id]
                t_start = time.time()
                content = tr.content
                if len(content) > tool_result_max_chars:
                    content = content[:tool_result_max_chars] + "\n... [truncated]"
                total_result_chars += len(content)
                total_tool_time += time.time() - t_start
                tools_used.append(tc.name)
                action_receipts.append(
                    ActionReceipt(
                        action=str(tc.name),
                        status="failed" if bool(getattr(tr, "is_error", False)) else "verified",
                        evidence=_truncate_tool_result(content, 240),
                        confidence=0.0 if bool(getattr(tr, "is_error", False)) else 0.82,
                        next_best_action=(
                            "Say the action failed; do not claim success."
                            if bool(getattr(tr, "is_error", False))
                            else "Use this result directly if relevant."
                        ),
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content,
                    }
                )

            # Context overflow guard
            if total_result_chars > max_total_tool_result_chars:
                _log.warning(
                    "tool_result_limit",
                    extra={"total_chars": total_result_chars},
                )
                tool_schemas = None
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Tool result limit reached. Respond with the "
                            "information gathered so far."
                        ),
                    }
                )
        else:
            # MAX_TOOL_ROUNDS exhausted
            reply = (
                getattr(result, "text", "") if result is not None else ""
            ) or "I wasn't able to complete that request."
            _log.warning("tool_loop_exhausted", extra={"max_rounds": max_tool_rounds})

        if tools_used:
            _log.info(
                "tool_loop_done",
                extra={
                    "tool_count": len(tools_used),
                    "total_time_s": round(total_tool_time, 2),
                    "tools": tools_used,
                },
            )

        if pre_tool_fallback and _is_deferred_tool_promise(reply):
            _log.info(
                "prefetched_result_replaced_deferred_promise",
                extra={"tools": tools_used},
            )
            reply = pre_tool_fallback

        reply = _sharpen_generic_helper_ending(reply)
        reply = _repair_empty_template_slots(reply)
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)

    # --- Programmatic Footer Injection ---
    elapsed = time.perf_counter() - t0
    if result is None:
        result = LLMResult(
            text=reply,
            model="unknown",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )

    if not _has_user_visible_reply(reply):
        _log.warning(
            "empty_model_reply",
            extra={
                "target": target,
                "model": getattr(result, "model", "unknown"),
                "prompt_tokens": getattr(result, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(result, "completion_tokens", 0) or 0,
            },
        )
        recovery_result = await _recover_empty_visible_reply(role, messages, target=target)
        if recovery_result is not None:
            result = recovery_result
            reply = recovery_result.text.strip()
        else:
            reply = (
                pre_tool_fallback
                or "I hit an empty response there, but I heard you. Please try again in a moment."
            )

    out_tokens = result.completion_tokens or 0
    in_tokens = result.prompt_tokens or 0
    total_tokens = result.total_tokens or 0
    actual_model = result.model
    model_used = actual_model

    max_context = 1_000_000
    try:
        from litellm import get_model_info

        info = get_model_info(actual_model)
        max_context = info.get("max_input_tokens") or 1_000_000
    except Exception:
        pass

    usage_pct = (total_tokens / max_context) * 100 if max_context else 0

    # Phase 5: Include tool usage info in footer
    tools_footer = ""
    try:
        if session_mode != "spicy" and tools_used:
            if getattr(deps, "_TOOL_FEATURES_AVAILABLE", False) is True:
                tools_footer = format_tool_footer(
                    tools_used,
                    total_tool_time,
                    round_num + 1 if "round_num" in dir() else 1,
                )
            else:
                tools_footer = f"\n**Tools Used:** {', '.join(tools_used)}"
    except NameError:
        pass

    stats_footer = ""
    if _should_include_response_metadata(request):
        stats_footer = (
            f"\n\n---\n"
            f"**Context Usage:** {total_tokens:,} / {max_context:,} ({usage_pct:.1f}%)\n"
            f"**Model:** {actual_model}\n"
            f"**Tokens:** {in_tokens:,} in / {out_tokens:,} out / {total_tokens:,} total\n"
            f"**Response Time:** {elapsed:.1f}s"
            f"{tools_footer}"
        )

    final_reply = reply + stats_footer
    _log.info(
        "response_generated",
        extra={"target": target, "model": model_used, "reply_preview": final_reply[:60]},
    )

    # Log assistant message
    sbs_orchestrator = deps.get_sbs_for_target(target)
    sbs_orchestrator.on_message(
        "assistant", reply, request.user_id or "default", response_to=user_msg_id
    )

    # --- AUTO-CONTINUE LOGIC ---
    is_long = len(reply) > 50
    ends_with_terminal = _ends_with_sentence_terminal(reply)

    if is_long and not ends_with_terminal:
        _log.info("auto_continue_triggered")
        from sci_fi_dashboard.pipeline_helpers import continue_conversation

        if background_tasks:
            background_tasks.add_task(continue_conversation, request.user_id, messages, reply)
        else:
            _log.warning("auto_continue_no_background_tasks")
            asyncio.create_task(continue_conversation(request.user_id, messages, reply))

    result_dict = {
        "reply": final_reply,
        "persona": f"synapse_{target}",
        "memory_method": retrieval_method,
        "model": model_used,
        "action_receipts": [receipt.to_dict() for receipt in action_receipts],
    }
    try:
        if session_mode != "spicy" and tools_used:
            result_dict["tools_used"] = tools_used
            result_dict["tool_rounds"] = round_num + 1
    except NameError:
        pass
    with contextlib.suppress(Exception):
        _get_emitter().end_run(total_latency_ms=round((time.time() - _pipeline_start) * 1000))
    return result_dict
