import sys
from pathlib import Path
from unittest.mock import patch

# Ensure workspace/ is on import path regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.sbs.ingestion.schema import RawMessage
from sci_fi_dashboard.sbs.processing.realtime import RealtimeProcessor
from sci_fi_dashboard.sbs.profile.manager import ProfileManager


def _processor(tmp_path):
    return RealtimeProcessor(ProfileManager(tmp_path / "profiles"))


def test_neutral_text_is_not_playful(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(
        RawMessage(role="user", content="I reviewed the notes and will send an update tomorrow.")
    )
    assert result["rt_mood_signal"] is None


def test_literal_lol_sets_playful(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(RawMessage(role="user", content="lol"))
    assert result["rt_mood_signal"] == "playful"


def test_common_anxiety_language_sets_anxious(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(
        RawMessage(
            role="user",
            content=(
                "I am scared this birthday dinner will get awkward and my stomach "
                "is doing nonsense."
            ),
        )
    )
    assert result["rt_mood_signal"] == "anxious"


def test_common_relationship_language_sets_affectionate(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(
        RawMessage(role="user", content="I think I have a crush and I really like her.")
    )
    assert result["rt_mood_signal"] == "affectionate"


def test_common_anger_language_sets_angry(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(
        RawMessage(role="user", content="I am so angry, that whole thing felt unfair.")
    )
    assert result["rt_mood_signal"] == "angry"


def test_practical_help_language_sets_problem_solving(tmp_path):
    processor = _processor(tmp_path)
    result = processor.process(
        RawMessage(
            role="user",
            content="Can you check the safest official TVS service or towing route?",
        )
    )
    assert result["rt_mood_signal"] == "problem_solving"


def test_user_mood_updates_profile_immediately(tmp_path):
    from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator

    orchestrator = SBSOrchestrator(data_dir=str(tmp_path / "sbs_data"))
    result = orchestrator.on_message(role="user", content="need to implement and debug this quickly")

    assert result["rt_mood_signal"] == "focused"

    emotional = orchestrator.profile_mgr.load_layer("emotional_state")
    assert emotional["current_dominant_mood"] == "focused"
    assert len(emotional["mood_history"]) == 1


def test_flush_failure_retries_on_subsequent_processing(tmp_path):
    processor = _processor(tmp_path)
    processor._FLUSH_BATCH = 1
    processor._FLUSH_INTERVAL = 0

    original_flush = processor._flush_emotional_state
    call_count = {"n": 0}

    def _flaky_flush():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated flush failure")
        return original_flush()

    with patch.object(processor, "_flush_emotional_state", side_effect=_flaky_flush):
        first = processor.process(RawMessage(role="user", content="lol"))
        second = processor.process(RawMessage(role="assistant", content="ack"))

    assert first["rt_mood_signal"] == "playful"
    assert second["rt_mood_signal"] is None
    assert call_count["n"] >= 2

    emotional = processor.profile_mgr.load_layer("emotional_state")
    assert emotional["current_dominant_mood"] == "playful"
    assert len(emotional["mood_history"]) == 1


def test_on_message_does_not_raise_when_flush_fails(tmp_path):
    from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator

    orchestrator = SBSOrchestrator(data_dir=str(tmp_path / "sbs_data"))

    with patch.object(orchestrator.realtime, "flush", side_effect=RuntimeError("flush boom")):
        result = orchestrator.on_message(role="user", content="lol")

    assert result["rt_mood_signal"] == "playful"
    assert "msg_id" in result
