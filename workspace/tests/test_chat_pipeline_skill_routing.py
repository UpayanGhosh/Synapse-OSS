"""Phase 12 — WA-FIX-04 (canonical session key in on_batch_ready) and WA-FIX-05
(duplicate skill-routing block removed; skill fires exactly once).

Wave 0: FAILING stubs. Wave 2 Plans 12-02 flip them green.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _fake_config_with_identity_links():
    cfg = MagicMock()
    cfg.session = {
        "identityLinks": {
            "the_creator": ["919876543210@s.whatsapp.net"],
            "the_partner": ["919111111111@s.whatsapp.net"],
        }
    }
    return cfg


class TestSessionKeyCanonical:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_on_batch_ready_uses_canonical_builder(self, monkeypatch):
        from sci_fi_dashboard import _deps
        from sci_fi_dashboard.pipeline_helpers import on_batch_ready

        monkeypatch.setattr(
            "synapse_config.SynapseConfig.load",
            classmethod(lambda cls: _fake_config_with_identity_links()),
        )

        captured: dict = {}

        async def _fake_enqueue(task):
            captured["session_key"] = task.session_key

        monkeypatch.setattr(_deps.task_queue, "enqueue", _fake_enqueue)

        await on_batch_ready(
            "919876543210@s.whatsapp.net",
            "hi",
            {
                "channel_id": "whatsapp",
                "is_group": False,
                "message_id": "m1",
                "sender_name": "Alice",
            },
        )
        key = captured.get("session_key", "")
        assert key.startswith("agent:"), f"Expected canonical key, got {key!r}"
        assert "whatsapp:dm:" in key


class TestSkillRouting:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_skill_fires_exactly_once(self, monkeypatch):
        from sci_fi_dashboard import _deps
        from sci_fi_dashboard.chat_pipeline import persona_chat
        from sci_fi_dashboard.schemas import ChatRequest

        fake_skill = MagicMock(name="Weather")
        fake_skill.name = "weather"

        monkeypatch.setattr(_deps, "_SKILL_SYSTEM_AVAILABLE", True)
        fake_router = MagicMock()
        fake_router.match = MagicMock(return_value=fake_skill)
        monkeypatch.setattr(_deps, "skill_router", fake_router)

        from sci_fi_dashboard.skills import runner as runner_mod

        exec_mock = AsyncMock()
        exec_mock.return_value = MagicMock(text="mocked reply")
        monkeypatch.setattr(runner_mod.SkillRunner, "execute", exec_mock)

        # Phase 2 consent protocol — not set at module level; inject empty stubs so
        # the consent-check block (chat_pipeline.py line 111) does not AttributeError.
        # pending_consents: empty dict → .get() returns None → falls through immediately.
        # consent_protocol: None → the "if deps.consent_protocol is not None" guard skips.
        # raising=False creates the attribute even if it doesn't exist on the module yet.
        monkeypatch.setattr(_deps, "pending_consents", {}, raising=False)
        monkeypatch.setattr(_deps, "consent_protocol", None, raising=False)

        fake_sbs = MagicMock()
        fake_sbs.on_message = MagicMock()
        monkeypatch.setattr(_deps, "get_sbs_for_target", lambda t: fake_sbs)

        fake_mem = MagicMock()
        fake_mem.add_memory = MagicMock()
        fake_mem.query = MagicMock(return_value={"results": [], "tier": "standard"})
        monkeypatch.setattr(_deps, "memory_engine", fake_mem)

        req = ChatRequest(message="what's the weather", user_id="test_user", history=[])
        await persona_chat(req, "the_creator", None)

        assert (
            exec_mock.await_count == 1
        ), f"Skill executed {exec_mock.await_count} times — expected exactly 1"


def test_memory_identity_turns_skip_skill_routing():
    from sci_fi_dashboard.chat_pipeline import _should_skip_skill_routing

    assert _should_skip_skill_routing(
        "Remember this: I am Aarav and I prefer short calm replies."
    )
    assert _should_skip_skill_routing("Save my preference: no long explanations.")
    assert not _should_skip_skill_routing("summarize this article for me")


def test_skill_routing_requires_explicit_trigger():
    from types import SimpleNamespace

    from sci_fi_dashboard.chat_pipeline import _has_explicit_skill_trigger

    skills = [
        SimpleNamespace(name="synapse.summarize", triggers=["summarize", "tldr"]),
        SimpleNamespace(name="synapse.weather", triggers=["what's the weather"]),
    ]

    assert _has_explicit_skill_trigger("what's the weather in Bangalore?", skills)
    assert not _has_explicit_skill_trigger(
        "I am scared Kestrel is another almost-startup.", skills
    )


def test_relationship_voice_contract_for_personal_turns():
    from sci_fi_dashboard.chat_pipeline import (
        _build_relationship_voice_contract,
        _is_relationship_voice_turn,
    )

    user_msg = (
        "Personal update: I think I have a real crush on Naina now. "
        "Please don't make this dramatic; keep me grounded."
    )

    assert _is_relationship_voice_turn(user_msg, "casual", "safe")
    contract = _build_relationship_voice_contract(
        user_msg,
        "casual",
        "safe",
        "casual_reflective",
    )
    assert "close friend" in contract
    assert "leg-pull" in contract
    assert "Avoid bot phrases" in contract
    assert "therapy-template" in contract


def test_relationship_voice_contract_skips_tool_and_code_turns():
    from sci_fi_dashboard.chat_pipeline import _build_relationship_voice_contract

    assert (
        _build_relationship_voice_contract(
            "search the web for current onboarding ideas",
            "casual",
            "safe",
            "full",
        )
        == ""
    )


def test_relationship_voice_contract_keeps_memory_turns_warm():
    from sci_fi_dashboard.chat_pipeline import _build_relationship_voice_contract

    contract = _build_relationship_voice_contract(
        "Remember that impulse-buying audio gear is my weakness when I am anxious.",
        "casual",
        "safe",
        "full",
    )

    assert "close friend" in contract
    assert "one next action" in contract
    assert (
        _build_relationship_voice_contract(
            "I feel this parser is broken, debug the code",
            "code",
            "safe",
            "full",
        )
        == ""
    )


def test_relationship_voice_contract_joins_fair_vent_but_keeps_spine():
    from sci_fi_dashboard.chat_pipeline import _build_relationship_voice_contract

    contract = _build_relationship_voice_contract(
        "I am pissed. Rohan dumped the demo cleanup on me and I need to vent.",
        "casual",
        "safe",
        "casual_reflective",
    )

    assert "rant with them" in contract
    assert "contradict them with care" in contract
    assert "share a real opinion" in contract


class TestSkillRoutingSource:
    """WA-FIX-05 red→green source-level signal.

    A2 (TestSkillRouting::test_skill_fires_exactly_once) is a regression guard —
    passes today because block #1 returns on match, making block #2 dead code.
    This test FAILS today because persona_chat's source contains TWO skill_router.match
    calls (the duplicate block WA-FIX-05 removes); passes after Wave 2 Plan 12-02 deletes
    the dead block and only ONE call remains.
    """

    @pytest.mark.unit
    def test_persona_chat_has_single_skill_routing_block(self):
        import inspect

        from sci_fi_dashboard.chat_pipeline import persona_chat

        src = inspect.getsource(persona_chat)
        count = src.count("skill_router.match")
        # FAILS TODAY — current code has 2 matches (lines 477 and 555).
        # PASSES after Wave 2 Plan 12-02 deletes the dead second block.
        assert count == 1, (
            f"Expected exactly one skill_router.match call in persona_chat; "
            f"got {count}. WA-FIX-05 must remove the duplicate skill-routing block."
        )
