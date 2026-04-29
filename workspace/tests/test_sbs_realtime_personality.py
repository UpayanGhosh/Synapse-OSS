import sys
from pathlib import Path

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


def test_user_mood_updates_profile_immediately(tmp_path):
    from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator

    orchestrator = SBSOrchestrator(data_dir=str(tmp_path / "sbs_data"))
    result = orchestrator.on_message(role="user", content="need to implement and debug this quickly")

    assert result["rt_mood_signal"] == "focused"

    emotional = orchestrator.profile_mgr.load_layer("emotional_state")
    assert emotional["current_dominant_mood"] == "focused"
    assert len(emotional["mood_history"]) == 1
