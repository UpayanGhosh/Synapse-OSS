"""Core chat pipeline -- persona_chat() and tool execution helpers."""
import asyncio
import json
import logging
import os
import time
import uuid

from fastapi import BackgroundTasks

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.dual_cognition import CognitiveMerge
from sci_fi_dashboard.llm_router import LLMResult
from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

logger = logging.getLogger(__name__)
_tool_logger = logging.getLogger(__name__ + ".tools")

# Conditional imports -- same pattern as original api_gateway.py
try:
    from sci_fi_dashboard.tool_registry import (
        ToolRegistry,
        ToolContext,
        ToolResult,
        SynapseTool,
    )
except ImportError:
    pass

try:
    from sci_fi_dashboard.tool_safety import (
        apply_tool_policy_pipeline,
        build_policy_steps,
        ToolLoopDetector,
    )
except ImportError:
    pass

try:
    from sci_fi_dashboard.tool_features import (
        format_tool_footer,
        get_model_override,
        parse_command_shortcut,
    )
except ImportError:
    pass

from sci_fi_dashboard.consent_protocol import (
    detect_modification_intent,
    is_affirmative,
    is_negative,
    PendingConsent,
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
    """Heuristic: treat the_creator / the_partner as owner.
    M-01: Return False for absent/empty user_id instead of True."""
    if not user_id:
        return False
    return user_id.lower() in {"the_creator", "the_partner"}


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
    print(f"[MAIL] [{target.upper()}] Inbound: {user_msg[:80]}...")

    _pipeline_start = time.time()
    try:
        _run_id = _get_emitter().start_run(text=user_msg[:120], target=target)
    except Exception:
        pass

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
            logger.info("[CONSENT] Expired pending consent cleared for %s", _consent_key)
        elif is_affirmative(user_msg):
            # User confirmed — execute the modification
            deps.pending_consents.pop(_consent_key, None)
            logger.info("[CONSENT] User confirmed modification: %s", _pending.intent.description)
            # T-02-02: Validate sender_id matches
            if _pending.sender_id != _sender_id:
                logger.warning(
                    "[CONSENT] Sender mismatch: expected %s, got %s",
                    _pending.sender_id, _sender_id,
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
                from pathlib import Path as _Path

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

            result = await deps.consent_protocol.confirm_and_execute(
                _pending.intent, _executor
            )
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
            logger.info("[CONSENT] User declined modification")
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
            logger.info("[CONSENT] Modification intent detected, awaiting confirmation")
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
        mem_response = deps.memory_engine.query(user_msg, limit=5, with_graph=True, seed_entities=_seed or None)
        try:
            _get_emitter().emit("memory.query_done", {
                "tier": mem_response.get("tier", "unknown"),
                "result_count": len(mem_response.get("results", [])),
                "graph_context": bool(mem_response.get("graph_context")),
            })
        except Exception:
            pass

        # Format results for the prompt — permanent profile first, then dynamic context
        results_list = mem_response.get("results", [])
        dynamic_facts = "\n".join(
            [f"* {r['content']}" for r in results_list]
        )
        profile_block = "\n".join([f"* {f}" for f in _permanent_facts])
        graph_ctx = mem_response.get("graph_context", "")

        memory_context = (
            f"[PERMANENT USER PROFILE]\n{profile_block}\n\n"
            f"[RECENT CONTEXT FROM MEMORY]\n{dynamic_facts}\n\n"
            f"{graph_ctx}"
        ).strip()
        retrieval_method = mem_response.get("tier", "standard")
    except Exception as e:
        print(f"[WARN] Memory Engine Error: {e}")
        memory_context = "(Memory retrieval unavailable)"
        retrieval_method = "failed"

    # 2. Toxicity Check
    toxicity = deps.toxic_scorer.score(user_msg)
    try:
        _get_emitter().emit("toxicity.check", {
            "score": round(float(toxicity), 3),
            "passed": float(toxicity) < 0.8,
        })
    except Exception:
        pass
    if toxicity > 0.8 and session_mode == "safe":
        print(
            f"[WARN] High Toxicity ({toxicity:.2f}) detected in Safe Mode. "
            "Remaining Safe (Architectural Decision)."
        )

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

            cognitive_context = deps.dual_cognition.build_cognitive_context(
                cognitive_merge
            )
            try:
                _get_emitter().emit("cognition.merge_done", {
                    "tension_level": round(cognitive_merge.tension_level, 3),
                    "tension_type": cognitive_merge.tension_type,
                    "response_strategy": cognitive_merge.response_strategy,
                    "suggested_tone": cognitive_merge.suggested_tone,
                    "inner_monologue": cognitive_merge.inner_monologue,
                    "thought": cognitive_merge.thought,
                    "contradictions": cognitive_merge.contradictions,
                    "memory_insights": cognitive_merge.memory_insights,
                    "complexity": getattr(cognitive_merge, "_complexity", "unknown"),
                })
            except Exception:
                pass

            print(
                f"[MEM] Cognitive State: {cognitive_merge.tension_type} "
                f"(tension={cognitive_merge.tension_level:.2f})"
            )
            _safe_thought = (
                cognitive_merge.inner_monologue[:100]
                .encode("ascii", errors="replace")
                .decode()
            )
            print(f"[THOUGHT] Inner thought: {_safe_thought}")

        except asyncio.TimeoutError:
            print(f"[WARN] Dual cognition timed out after {dc_timeout}s")
            cognitive_merge = CognitiveMerge()
            cognitive_context = ""
        except Exception as e:
            print(f"[WARN] Dual cognition failed: {e}")
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
        from datetime import datetime, timezone, timedelta
        _IST = timezone(timedelta(hours=5, minutes=30))
        _now = datetime.now(_IST)
        _weekday = _now.strftime("%A")
        _time_str = _now.strftime("%I:%M %p")
        _situational_parts = [f"It's {_weekday}, {_time_str} IST."]

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
    user_log = sbs_orchestrator.on_message(
        "user", user_msg, request.user_id or "default"
    )
    user_msg_id = user_log.get("msg_id")

    base_instructions = (
        "You are Synapse. Follow the persona profile below precisely. "
        "A block of RETRIEVED MEMORIES will follow. Use those memories to give contextual, "
        "relevant replies. Only reference what is explicitly in the memories — never invent "
        "people, events, or details that are not there."
    )
    _proactive_raw = (
        deps._proactive_engine.get_prompt_injection()
        if deps._proactive_engine
        else ""
    )
    # Merge proactive context + situational awareness block
    proactive_block = "\n\n".join(p for p in [_proactive_raw, _situational_block] if p)
    system_prompt = sbs_orchestrator.get_system_prompt(
        base_instructions, proactive_block
    )
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
        messages.append({
            "role": "system",
            "content": (
                f"USER PROFILE (always true, use this to personalize your reply):\n"
                f"{_profile_lines}"
            ),
        })

    messages.append({"role": "user", "content": user_msg})

    t0 = time.perf_counter()

    # --- Phase 1 (v2.0): Skill Routing ---
    # Check if message matches a skill BEFORE traffic cop routing.
    # Skills handle the message entirely — skip MoA pipeline if matched.
    # Skills are NEVER triggered in spicy hemisphere (T-01-14 privacy boundary).
    if (
        deps._SKILL_SYSTEM_AVAILABLE
        and deps.skill_router is not None
        and session_mode != "spicy"
    ):
        matched_skill = deps.skill_router.match(user_msg)
        if matched_skill is not None:
            logger.info("[Skills] Message routed to skill '%s'", matched_skill.name)
            from sci_fi_dashboard.skills.runner import SkillRunner

            skill_result = await SkillRunner.execute(
                manifest=matched_skill,
                user_message=user_msg,
                history=request.history,
                llm_router=deps.synapse_llm_router,
            )
            reply = skill_result.text

            # Log via SBS
            sbs_orchestrator = deps.get_sbs_for_target(target)
            sbs_orchestrator.on_message("assistant", reply, request.user_id or "default")

            # Store in memory (CRITICAL: method is add_memory, NOT store)
            try:
                deps.memory_engine.add_memory(
                    content=(
                        f"[Skill: {matched_skill.name}] "
                        f"User: {user_msg}\nAssistant: {reply}"
                    ),
                    category="skill_execution",
                )
            except Exception:
                pass

            return {
                "reply": reply,
                "model": f"skill:{matched_skill.name}",
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "role": f"skill:{matched_skill.name}",
                "retrieval_method": "skill",
            }

    # --- Phase 3: Tool Context & Schema Resolution ---
    use_tools = (
        session_mode != "spicy"
        and deps.tool_registry is not None
        and deps._TOOL_REGISTRY_AVAILABLE
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
                deps._synapse_cfg.raw
                if hasattr(deps._synapse_cfg, "raw")
                else {},
                channel_id="api",
            )
            surviving_names, _removal_log = apply_tool_policy_pipeline(
                tool_infos, policy_steps, _is_owner_sender(request.user_id)
            )
            session_tools = [
                t for t in session_tools if t.name in surviving_names
            ]

        tool_schemas = (
            deps.tool_registry.get_schemas(session_tools)
            if session_tools
            else None
        )

    # --- Phase 1 (v2.0): Skill Routing ---
    # Check if message matches a skill BEFORE traffic cop routing.
    # Skills handle the message entirely — skip MoA pipeline if matched.
    # Skills are NEVER triggered in spicy hemisphere (privacy boundary).
    if (
        getattr(deps, "_SKILL_SYSTEM_AVAILABLE", False)
        and getattr(deps, "skill_router", None) is not None
        and session_mode != "spicy"
    ):
        matched_skill = deps.skill_router.match(user_msg)
        if matched_skill is not None:
            logger.info("[Skills] Message routed to skill '%s'", matched_skill.name)
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

            # Store in memory (method is add_memory, NOT store)
            try:
                deps.memory_engine.add_memory(
                    content=f"[Skill: {matched_skill.name}] User: {user_msg}\nAssistant: {reply}",
                    category="skill_execution",
                )
            except Exception:
                pass

            return {
                "reply": reply,
                "model": f"skill:{matched_skill.name}",
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "role": f"skill:{matched_skill.name}",
                "retrieval_method": "skill",
            }

    if session_mode == "spicy":
        # === THE VAULT (Local Stheno) ===
        # C-02: Vault air-gap -- NEVER fall back to cloud for spicy/vault content
        print("[HOT] Routing to THE VAULT (Local Stheno)")
        try:
            _get_emitter().emit("llm.route", {
                "role": "vault",
                "model": deps._synapse_cfg.model_mappings.get("vault", {}).get("model", "unknown"),
            })
        except Exception:
            pass
        try:
            _llm_start = time.time()
            try:
                _get_emitter().emit("llm.stream_start", {"role": "vault"})
            except Exception:
                pass
            result = await deps.synapse_llm_router.call_with_metadata(
                "vault", messages
            )
            try:
                _get_emitter().emit("llm.stream_done", {
                    "total_tokens": getattr(result, "total_tokens", 0),
                    "model": getattr(result, "model", "unknown"),
                    "latency_ms": round((time.time() - _llm_start) * 1000),
                })
            except Exception:
                pass
            reply = result.text
        except Exception as e:
            print(
                f"[ERROR] Vault failed: {e}. Cloud fallback BLOCKED (air-gap policy)."
            )
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
            route_traffic_cop,
            STRATEGY_TO_ROLE,
        )

        classification = None
        if cognitive_merge is not None:
            strategy = cognitive_merge.response_strategy
            mapped = STRATEGY_TO_ROLE.get(strategy)
            if mapped:
                classification = mapped
                print(
                    f"[SIGNAL] Traffic Cop SKIPPED -- strategy "
                    f"'{strategy}' -> {classification}"
                )
                try:
                    _get_emitter().emit("traffic_cop.skip", {
                        "strategy": cognitive_merge.response_strategy,
                        "mapped_role": classification,
                    })
                except Exception:
                    pass
        if classification is None:
            try:
                _get_emitter().emit("traffic_cop.start", {})
            except Exception:
                pass
            classification = await route_traffic_cop(user_msg)
            try:
                _get_emitter().emit("traffic_cop.done", {
                    "classification": classification,
                    "role": classification,
                    "skipped": False,
                })
            except Exception:
                pass

        # Phase 5: Check model override before traffic cop
        override_role = None
        if deps._TOOL_FEATURES_AVAILABLE:
            override_role = get_model_override(request.user_id or "default")

        if override_role:
            role = override_role
            print(f"[ROUTE] Model override active: role={role}")
        elif "CODING" in classification:
            role = "code"
        elif "ANALYSIS" in classification:
            role = "analysis"
        elif "REVIEW" in classification:
            role = "review"
        else:
            role = "casual"

        print(f"[ROUTE] Classification={classification} -> role={role}")

        try:
            _get_emitter().emit("llm.route", {
                "role": role,
                "model": deps._synapse_cfg.model_mappings.get(role.lower(), {}).get("model", "unknown"),
            })
        except Exception:
            pass

        # --- Tool Execution Loop (Phase 3 + 4 + 5) ---
        reply = ""
        tools_used: list[str] = []
        total_tool_time = 0.0
        total_result_chars = 0
        result = None
        loop_detector = (
            ToolLoopDetector() if deps._TOOL_SAFETY_AVAILABLE else None
        )

        for round_num in range(deps.MAX_TOOL_ROUNDS):
            try:
                _llm_start = time.time()
                try:
                    _get_emitter().emit("llm.stream_start", {"role": role})
                except Exception:
                    pass
                if tool_schemas and hasattr(
                    deps.synapse_llm_router, "call_with_tools"
                ):
                    result = await deps.synapse_llm_router.call_with_tools(
                        role,
                        messages,
                        tools=tool_schemas,
                        temperature=0.7 if role != "code" else 0.2,
                        max_tokens=1500,
                    )
                    try:
                        _get_emitter().emit("llm.stream_done", {
                            "total_tokens": getattr(result, "total_tokens", 0),
                            "model": getattr(result, "model", "unknown"),
                            "latency_ms": round((time.time() - _llm_start) * 1000),
                        })
                    except Exception:
                        pass
                else:
                    temp = 0.2 if role == "code" else 0.85
                    max_tok = 1000 if role == "code" else 1500
                    result = await deps.synapse_llm_router.call_with_metadata(
                        role, messages, temperature=temp, max_tokens=max_tok
                    )
                    try:
                        _get_emitter().emit("llm.stream_done", {
                            "total_tokens": getattr(result, "total_tokens", 0),
                            "model": getattr(result, "model", "unknown"),
                            "latency_ms": round((time.time() - _llm_start) * 1000),
                        })
                    except Exception:
                        pass
                    reply = result.text
                    break
            except Exception as e:
                error_str = str(e).lower()
                if "context" in error_str or "token" in error_str:
                    _tool_logger.warning(
                        "Context overflow in round %d -- retrying without tools",
                        round_num,
                    )
                    tool_schemas = None
                    continue
                elif "rate" in error_str:
                    _tool_logger.warning(
                        "Rate limit in round %d -- waiting 2s", round_num
                    )
                    await asyncio.sleep(2)
                    continue
                else:
                    _tool_logger.error(
                        "LLM call failed in round %d: %s", round_num, e
                    )
                    reply = (
                        "I encountered an error processing your request. "
                        "Please try again."
                    )
                    break

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
                if _is_serial_tool(tc.name, session_tools)
                and tc.id not in blocked_ids
            ]
            parallel_calls = [
                tc
                for tc in tool_calls
                if not _is_serial_tool(tc.name, session_tools)
                and tc.id not in blocked_ids
            ]

            tool_results: dict = {}

            # Blocked calls get error results
            for tc in tool_calls:
                if tc.id in blocked_ids:
                    tool_results[tc.id] = ToolResult(
                        content=loop_detector.get_warning_message(
                            tc.name, "block"
                        ),
                        is_error=True,
                    )

            if parallel_calls:
                tasks = [
                    _execute_tool_call(tc, deps.tool_registry)
                    for tc in parallel_calls
                ]
                parallel_results = await asyncio.gather(
                    *tasks, return_exceptions=True
                )
                for tc, res in zip(parallel_calls, parallel_results):
                    if isinstance(res, Exception):
                        tool_results[tc.id] = ToolResult(
                            content=json.dumps({"error": str(res)}),
                            is_error=True,
                        )
                    else:
                        tool_results[tc.id] = res

            for tc in serial_calls:
                try:
                    tool_results[tc.id] = await _execute_tool_call(
                        tc, deps.tool_registry
                    )
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
                    content = (
                        content[: deps.TOOL_RESULT_MAX_CHARS]
                        + "\n... [truncated]"
                    )
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
                _tool_logger.warning(
                    "Tool result limit reached (%d chars) -- disabling tools",
                    total_result_chars,
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
            _tool_logger.warning(
                "Tool loop exhausted after %d rounds", deps.MAX_TOOL_ROUNDS
            )

        if tools_used:
            _tool_logger.info(
                "Tool loop completed: %d tools in %.2fs -- %s",
                len(tools_used),
                total_tool_time,
                ", ".join(tools_used),
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
    _safe_preview = (
        final_reply[:60].encode("ascii", errors="replace").decode()
    )
    print(
        f"[SPARK] [{target.upper()}] Response via {model_used}: {_safe_preview}..."
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
        print("[CUT] DETECTED CUT-OFF! Triggering Auto-Continue...")
        from sci_fi_dashboard.pipeline_helpers import continue_conversation

        if background_tasks:
            background_tasks.add_task(
                continue_conversation, request.user_id, messages, reply
            )
        else:
            print(
                "[WARN] No BackgroundTasks object available. Using asyncio.create_task."
            )
            asyncio.create_task(
                continue_conversation(request.user_id, messages, reply)
            )

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
    try:
        _get_emitter().end_run(
            total_latency_ms=round((time.time() - _pipeline_start) * 1000)
        )
    except Exception:
        pass
    return result_dict
