"""Core chat pipeline -- persona_chat() and tool execution helpers."""

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path

from fastapi import BackgroundTasks

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.dual_cognition import CognitiveMerge
from sci_fi_dashboard.llm_router import LLMResult
from sci_fi_dashboard.observability import get_child_logger
from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter
from sci_fi_dashboard.schemas import ChatRequest

logger = logging.getLogger(__name__)
_log = get_child_logger("pipeline.chat")  # OBS-01 structured logger carrying runId

# ---------------------------------------------------------------------------
# Agent Workspace Prefix (RT2)
# ---------------------------------------------------------------------------
# Static markdown discipline + identity layer (Jarvis-style backbone).
# Concatenated into the system prompt at the top — sits ABOVE the SBS dynamic
# persona layer so SBS adaptation still wins for tone/style while these files
# anchor the bot's identity, rules, and tool discipline.
#
# Resolution order per file:
#   1. ~/.synapse/workspace/<NAME>.md            (user override)
#   2. ~/.synapse/workspace/<NAME>.md.template   (runtime fallback)
#   3. <repo>/agent_workspace/<NAME>.md.template (repo default)

_AGENT_WORKSPACE_FILES: tuple[str, ...] = (
    "SOUL",
    "CORE",
    "IDENTITY",
    "USER",
    "TOOLS",
    "MEMORY",
    "AGENTS",  # AGENTS last — discipline rules are freshest before dynamic layer
)

_REPO_AGENT_WORKSPACE: Path = Path(__file__).parent / "agent_workspace"
_USER_AGENT_WORKSPACE: Path = Path.home() / ".synapse" / "workspace"

# Module-level cache keyed by file mtimes for cheap invalidation.
_agent_workspace_cache: dict = {"content": "", "mtimes": {}}


def _resolve_agent_workspace_path(name: str) -> Path | None:
    """Resolve a single agent workspace file using the 3-tier override order.

    Returns the first existing path or ``None`` if no copy is reachable.
    """
    candidates = (
        _USER_AGENT_WORKSPACE / f"{name}.md",
        _USER_AGENT_WORKSPACE / f"{name}.md.template",
        _REPO_AGENT_WORKSPACE / f"{name}.md.template",
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _load_agent_workspace_prefix() -> str:
    """Load and concatenate the 7 agent workspace markdown files into a stable prompt prefix.

    Files loaded in order: SOUL → CORE → IDENTITY → USER → TOOLS → MEMORY → AGENTS.
    AGENTS comes LAST so its discipline rules are the freshest thing the LLM sees
    before the dynamic SBS persona layer.

    The result is cached at module level. The cache invalidates when ANY of the
    7 resolved file mtimes changes — letting users edit ``~/.synapse/workspace/SOUL.md``
    and see changes on the next message without restart.

    Returns one big string with file boundaries marked by ``# ===== <NAME>.md =====``
    headers. Empty string if none of the files resolve (logged at WARNING level).
    """
    resolved: dict[str, Path] = {}
    for name in _AGENT_WORKSPACE_FILES:
        path = _resolve_agent_workspace_path(name)
        if path is not None:
            resolved[name] = path

    if not resolved:
        if _agent_workspace_cache["content"]:
            return _agent_workspace_cache["content"]
        _log.warning(
            "agent_workspace_empty",
            extra={
                "user_dir": str(_USER_AGENT_WORKSPACE),
                "repo_dir": str(_REPO_AGENT_WORKSPACE),
            },
        )
        return ""

    # mtime-based cache invalidation — reload if ANY resolved file changed.
    current_mtimes: dict[Path, float] = {}
    for path in resolved.values():
        try:
            current_mtimes[path] = path.stat().st_mtime
        except OSError:
            current_mtimes[path] = 0.0

    if (
        _agent_workspace_cache["content"]
        and _agent_workspace_cache["mtimes"] == current_mtimes
    ):
        return _agent_workspace_cache["content"]

    sections: list[str] = []
    for name in _AGENT_WORKSPACE_FILES:
        path = resolved.get(name)
        if path is None:
            continue
        try:
            body = path.read_text(encoding="utf-8").strip()
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
    synapse.json plus OS/time. Best-effort — returns empty string on read
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
            "Active model routing — Traffic Cop selects role per turn based on "
            "message content, then the role's model handles the LLM call. "
            "If asked about your model, answer from this table — do NOT guess "
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
      1. Persona names ("the_creator", "the_partner") — for HTTP /chat/{target}.
      2. Channel peer_id present in the owner_registry — first-contact
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
            # Expired consent — silently clear and continue normal pipeline
            deps.pending_consents.pop(_consent_key, None)
            _log.info("consent_expired", extra={"consent_key": str(_consent_key)})
        elif is_affirmative(user_msg):
            # User confirmed — execute the modification
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
                    f"A snapshot has been saved — you can undo this anytime."
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
    try:
        env_session = os.environ.get("SESSION_TYPE", "safe")
        session_mode = request.session_type or env_session
        if session_mode not in ["safe", "spicy"]:
            session_mode = "safe"

        # Layer 1: Always inject permanent profile docs (relationship_memories + distillations).
        # These 10-15 docs are the core knowledge about the user — always relevant, ~500 tokens.
        # They live in memory.db but are tiny enough to include every time.
        _permanent_facts = []
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
        # Configure via synapse.json → session → selfEntityNames → <target>
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

        # Format results for the prompt — permanent profile first, then dynamic context
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
    if deps._synapse_cfg.session.get("dual_cognition_enabled", True):
        dc_timeout = deps._synapse_cfg.session.get("dual_cognition_timeout", 5.0)
        try:
            from sci_fi_dashboard.llm_wrappers import call_ag_oracle

            cognitive_merge = await asyncio.wait_for(
                deps.dual_cognition.think(
                    user_message=user_msg,
                    chat_id=request.user_id or "default",
                    conversation_history=request.history,
                    target=target,
                    llm_fn=call_ag_oracle,
                    pre_cached_memory=mem_response,
                ),
                timeout=dc_timeout,
            )

            cognitive_context = deps.dual_cognition.build_cognitive_context(cognitive_merge)
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

    # Phase 1.2 — Message Length Mirroring
    # Match response length to the incoming message so a "k" doesn't get a paragraph.
    _word_count = len(user_msg.split())
    if _word_count <= 3:
        _length_hint = "Tiny message. Reply in 1-2 words max. Match the casual brevity."
    elif _word_count <= 10:
        _length_hint = "Short message. Keep your reply short — 1-2 sentences at most."
    elif _word_count <= 30:
        _length_hint = "Medium message. Match the length — roughly 2-4 sentences."
    else:
        _length_hint = ""  # Long message — no constraint

    # Phase 1.1 — Situational Awareness Block
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
            # History entries don't carry timestamps — use rough heuristic
            _situational_parts.append("(Conversation continuing.)")
        else:
            _situational_parts.append("Fresh conversation — ease in naturally.")

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

    base_instructions = (
        "You are Synapse. Follow the persona profile below precisely. "
        "A block of RETRIEVED MEMORIES will follow. Use those memories to give contextual, "
        "relevant replies. Only reference what is explicitly in the memories — never invent "
        "people, events, or details that are not there."
    )
    _proactive_raw = deps._proactive_engine.get_prompt_injection() if deps._proactive_engine else ""
    # Merge proactive context + situational awareness block
    proactive_block = "\n\n".join(p for p in [_proactive_raw, _situational_block] if p)
    system_prompt = sbs_orchestrator.get_system_prompt(base_instructions, proactive_block)

    # RT2: Prepend the static agent workspace markdown prefix (Jarvis-style discipline + identity)
    # ABOVE the SBS dynamic persona layer. Both layers compose: agent_workspace anchors
    # identity/rules, SBS adapts tone/style/exemplars per user.
    _agent_workspace_prefix = _load_agent_workspace_prefix()
    if _agent_workspace_prefix:
        system_prompt = f"{_agent_workspace_prefix}\n\n---\n\n{system_prompt}"

    # Runtime info — prevents the bot from hallucinating about its own model identity.
    # Without this, the LLM falls back to training-data answers ("I'm GPT-4o") even when
    # actually running on a different model. Inject the live routing table so the bot
    # has factual ground truth about what's running per role.
    try:
        _runtime_block = _build_runtime_info_block()
        if _runtime_block:
            system_prompt = f"{system_prompt}\n\n---\n\n{_runtime_block}"
    except Exception as _exc:  # pragma: no cover — runtime block is best-effort
        logger.warning("[runtime] failed to build runtime info block: %s", _exc)

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": (
                f"--- RETRIEVED MEMORIES ---\n"
                f"These are real facts about the user's life retrieved from memory. "
                f"Use ONLY what is in these memories — do not invent, hallucinate, or add "
                f"names, people, events, or details that are not explicitly present below.\n\n"
                f"{memory_context}\n--- END MEMORIES ---"
            ),
        },
    ]
    # Phase 3.3 — Emotional Trajectory injection
    # Append 72h peak-end weighted trajectory to cognitive context for richer merges.
    _trajectory_summary = ""
    try:
        if deps.dual_cognition.trajectory:
            _trajectory_summary = deps.dual_cognition.trajectory.get_summary()
    except Exception:
        pass

    _full_cognitive = "\n\n".join(p for p in [cognitive_context, _trajectory_summary] if p)
    if _full_cognitive:
        messages.append({"role": "system", "content": _full_cognitive})
    if mcp_context:
        messages.append({"role": "system", "content": mcp_context})

    messages.extend(request.history)

    # Permanent profile + language rule injected RIGHT before the user turn.
    # Small models (Gemma4:e4b) have strong recency bias — context far from
    # the user message gets ignored. Placing this last ensures it's read.
    if _permanent_facts:
        _profile_lines = "\n".join([f"- {f}" for f in _permanent_facts])
        messages.append(
            {
                "role": "system",
                "content": (
                    f"USER PROFILE (always true, use this to personalize your reply):\n"
                    f"{_profile_lines}"
                ),
            }
        )

    messages.append({"role": "user", "content": user_msg})

    t0 = time.perf_counter()

    # --- Phase 1 (v2.0): Skill Routing ---
    # Check if message matches a skill BEFORE traffic cop routing.
    # Skills handle the message entirely — skip MoA pipeline if matched.
    # Skills are NEVER triggered in spicy hemisphere (T-01-14 privacy boundary).
    # WA-FIX-05: single skill-routing block (block #2 at former lines 546-586 deleted).
    if (
        getattr(deps, "_SKILL_SYSTEM_AVAILABLE", False)
        and getattr(deps, "skill_router", None) is not None
        and session_mode != "spicy"
    ):
        matched_skill = deps.skill_router.match(user_msg)
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
            sbs_orchestrator = deps.get_sbs_for_target(target)
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

    # --- Phase 3: Tool Context & Schema Resolution ---
    use_tools = (
        session_mode != "spicy" and deps.tool_registry is not None and deps._TOOL_REGISTRY_AVAILABLE
    )
    session_tools: list = []
    tool_schemas: list | None = None

    if use_tools:
        tool_context = ToolContext(
            chat_id=request.user_id or "unknown",
            sender_id=request.user_id or "unknown",
            sender_is_owner=_is_owner_sender(request.user_id),
            workspace_dir=str(deps.WORKSPACE_ROOT),
            config=deps._synapse_cfg.session,
            channel_id="api",
        )
        session_tools = deps.tool_registry.resolve(tool_context)

        # Phase 4: Apply policy pipeline to filter tools
        if deps._TOOL_SAFETY_AVAILABLE and session_tools:
            tool_infos = [
                {"name": t.name, "owner_only": getattr(t, "owner_only", False)}
                for t in session_tools
            ]
            policy_steps = build_policy_steps(
                deps._synapse_cfg.raw if hasattr(deps._synapse_cfg, "raw") else {},
                channel_id="api",
            )
            surviving_names, _removal_log = apply_tool_policy_pipeline(
                tool_infos, policy_steps, _is_owner_sender(request.user_id)
            )
            session_tools = [t for t in session_tools if t.name in surviving_names]

        tool_schemas = deps.tool_registry.get_schemas(session_tools) if session_tools else None

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
        # === SAFE HEMISPHERE (MoA Routing) ===
        from sci_fi_dashboard.llm_wrappers import (
            STRATEGY_TO_ROLE,
            route_traffic_cop,
        )

        classification = None
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

        # Phase 5: Check model override before traffic cop
        override_role = None
        if deps._TOOL_FEATURES_AVAILABLE:
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

            # --- IMAGE branch: enabled check → Vault block → BackgroundTask dispatch ---

            # 1. Enabled check (image_gen.enabled in synapse.json)
            if not deps._synapse_cfg.image_gen.get("enabled", True):
                _log.info("image_gen_disabled")
                return {
                    "reply": "Image generation is currently disabled.",
                    "role": "image_gen_disabled",
                    "model": "none",
                    "memory_method": "none",
                }

            # 2. Vault hemisphere block — NEVER make cloud API calls for spicy sessions
            if session_mode == "spicy":
                _log.info("image_gen_vault_blocked")
                return {
                    "reply": "Image generation isn't available in private mode.",
                    "role": "image_blocked",
                    "model": "none",
                    "memory_method": "none",
                }

            # 3. Background helper — defined inline, following auto-continue pattern
            async def _generate_and_send_image(prompt: str, chat_id: str) -> None:
                """Generate an image in the background and deliver via send_media."""
                import asyncio as _asyncio

                from sci_fi_dashboard.image_gen.engine import ImageGenEngine
                from sci_fi_dashboard.media.store import save_media_buffer

                # TODO: multi-channel support — resolve channel_id from request context
                # Hardcoded to "whatsapp" — matches continue_conversation() default at
                # pipeline_helpers.py:151 — only channel that exposes send_media() today.
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

            # 4. Dispatch BackgroundTask
            _img_chat_id = request.user_id or "default"
            if background_tasks:
                background_tasks.add_task(_generate_and_send_image, user_msg, _img_chat_id)
            else:
                _log.warning("image_gen_no_background_tasks")
                asyncio.create_task(_generate_and_send_image(user_msg, _img_chat_id))

            # 5. Return immediate acknowledgment — user gets text response instantly
            _log.info(
                "route_classified",
                extra={"classification": "IMAGE", "role": "image_gen", "dispatched": True},
            )
            return {
                "reply": "Generating your image — it'll be with you in a moment!",
                "role": "image_gen",
                "model": "gpt-image-1",
                "memory_method": "none",
            }
        else:
            role = "casual"

        _log.info("route_classified", extra={"classification": classification, "role": role})

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
        # Tool discipline now lives in agent_workspace/AGENTS.md.template (TURN BUDGET,
        # Resourcefulness, ON TOOL ERROR rules) — prepended to the system prompt at the
        # top of persona_chat() via _load_agent_workspace_prefix(). We still note the
        # available tool names here so the LLM has a concrete, current inventory.
        if tool_schemas:
            _tool_names = ", ".join(t.name for t in session_tools)
            messages.append(
                {
                    "role": "system",
                    "content": f"Available tools this turn: {_tool_names}.",
                }
            )

        reply = ""
        tools_used: list[str] = []
        total_tool_time = 0.0
        total_result_chars = 0
        result = None
        loop_detector = ToolLoopDetector() if deps._TOOL_SAFETY_AVAILABLE else None
        _loop_start = time.time()
        _cumulative_tokens = 0

        for round_num in range(deps.MAX_TOOL_ROUNDS):
            # Hard wall-clock timeout on the entire agent loop
            _elapsed = time.time() - _loop_start
            if _elapsed > deps.TOOL_LOOP_WALL_CLOCK_S:
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

            # Cumulative-token abort — prevents runaway context growth
            try:
                from litellm import get_model_info as _gmi
                _mi = _gmi(getattr(result, "model", "unknown")) if result else {}
                _ctx_max = (_mi or {}).get("max_input_tokens") or 128_000
            except Exception:
                _ctx_max = 128_000
            if _cumulative_tokens > int(_ctx_max * deps.TOOL_LOOP_TOKEN_RATIO_ABORT):
                _log.warning(
                    "tool_loop_token_ratio_exceeded",
                    extra={"round": round_num, "cum_tokens": _cumulative_tokens, "ctx_max": _ctx_max},
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
                if "context" in error_str or "token" in error_str:
                    _log.warning(
                        "tool_loop_context_overflow",
                        extra={"round": round_num},
                    )
                    tool_schemas = None
                    continue
                elif "rate" in error_str:
                    _log.warning("tool_loop_rate_limited", extra={"round": round_num})
                    await asyncio.sleep(2)
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
                if len(content) > deps.TOOL_RESULT_MAX_CHARS:
                    content = content[: deps.TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"
                total_result_chars += len(content)
                total_tool_time += time.time() - t_start
                tools_used.append(tc.name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content,
                    }
                )

            # Context overflow guard
            if total_result_chars > deps.MAX_TOTAL_TOOL_RESULT_CHARS:
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
            _log.warning("tool_loop_exhausted", extra={"max_rounds": deps.MAX_TOOL_ROUNDS})

        if tools_used:
            _log.info(
                "tool_loop_done",
                extra={
                    "tool_count": len(tools_used),
                    "total_time_s": round(total_tool_time, 2),
                    "tools": tools_used,
                },
            )

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
            if deps._TOOL_FEATURES_AVAILABLE:
                tools_footer = format_tool_footer(
                    tools_used,
                    total_tool_time,
                    round_num + 1 if "round_num" in dir() else 1,
                )
            else:
                tools_footer = f"\n**Tools Used:** {', '.join(tools_used)}"
    except NameError:
        pass

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
    terminals = [".", "!", "?", '"', "'", ")", "]", "}"]
    is_long = len(reply) > 50
    cleaned_reply = reply.strip()
    ends_with_terminal = any(cleaned_reply.endswith(t) for t in terminals)

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
