---
phase: 12
plan: 2
status: complete
wave: 2
---

## Plan 02 — WA-FIX-04 / WA-FIX-05

### Changes

**workspace/sci_fi_dashboard/pipeline_helpers.py**
- Task 1 (WA-FIX-04): Replaced inline `f"{metadata.get('channel_id', 'whatsapp')}:{chat_type}:{chat_id}"` in `on_batch_ready` with canonical `build_session_key(agent_id=target, channel=channel_id, peer_id=chat_id, peer_kind=..., account_id=channel_id, dm_scope=..., main_key="whatsapp:dm", identity_links=...)`. `_resolve_target` is a pure dict scan (OQ-1 confirmed) — safe to call inline. Two callers now share one builder, eliminating silent key-shape divergence.

**workspace/sci_fi_dashboard/chat_pipeline.py** (43 lines deleted)
- Task 2 (WA-FIX-05): Block #1 (lines 479-520) updated with defensive `getattr(deps, "_SKILL_SYSTEM_AVAILABLE", False)`, `getattr(deps, "skill_router", None)` guards, and `session_context={"session_type": session_mode or ""}` kwarg on `SkillRunner.execute`. WA-FIX-05 anchor comment added. Block #2 (former lines 557-597 — unreachable dead code because block #1 always early-returns on a skill match) deleted entirely. Line count: 1079 → 1036 (−43 lines).

### Before / After
- `grep -c "matched_skill = deps.skill_router.match" chat_pipeline.py`: 2 → **1**
- `grep -c "build_session_key(" pipeline_helpers.py`: 1 → **2** (both callers)

### Test Results
- `test_chat_pipeline_skill_routing.py::TestSessionKeyCanonical` ✅ green (WA-FIX-04)
- `test_chat_pipeline_skill_routing.py::TestSkillRoutingSource::test_persona_chat_has_single_skill_routing_block` ✅ green (WA-FIX-05 primary)
- `test_chat_pipeline_skill_routing.py::TestSkillRouting::test_skill_fires_exactly_once` ✅ green (regression guard)
- `test_skill_pipeline.py` ✅ 12/12 no regression
- `test_channel_pipeline.py` ✅ 12/12 no regression
- `test_conversation_cache.py` ✅ no regression

### Acceptance Criteria Verification
- `grep -c "matched_skill = deps.skill_router.match" chat_pipeline.py` = **1** ✅
- `grep -c 'session_context={"session_type"' chat_pipeline.py` = **1** ✅
- `grep -c 'getattr(deps, "_SKILL_SYSTEM_AVAILABLE"' chat_pipeline.py` = **1** ✅
- `grep -n "WA-FIX-05" chat_pipeline.py` → line 483 ✅
- `grep -c "build_session_key(" pipeline_helpers.py` = **2** ✅
- `ruff check` + `black --check` both files → clean ✅
