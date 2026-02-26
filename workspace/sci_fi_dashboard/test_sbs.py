import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sbs.orchestrator import SBSOrchestrator


def test_sbs_conversation_ingestion():
    """SBS orchestrator should ingest messages and update mood profile."""
    test_dir = Path(tempfile.mkdtemp()) / "sbs_data"

    try:
        orchestrator = SBSOrchestrator(data_dir=str(test_dir))

        messages = [
            ("user", "hey synapse, what's up?"),
            ("assistant", "Not much, just waiting for commands."),
            ("user", "khub pressure jacche ajke"),
            ("assistant", "I understand. Let's take it easy. What can I help with?"),
            ("user", "why are you so formal"),
            ("assistant", "My bad the_brother, ki obostha bol?"),
            ("user", "darun! tui code ta lekhto ebar"),
            ("assistant", "Ekdom, writing the code now."),
        ]

        for role, content in messages:
            orchestrator.on_message(role, content)

        current_mood = orchestrator.get_profile_summary()["current_mood"]
        assert current_mood in [
            "stressed",
            "playful",
            "neutral",
        ], f"Unexpected mood: {current_mood}"
    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_sbs_batch_processing():
    """SBS batch processing should count all messages after full rebuild."""
    test_dir = Path(tempfile.mkdtemp()) / "sbs_data"

    try:
        orchestrator = SBSOrchestrator(data_dir=str(test_dir))

        messages = [
            ("user", "hey synapse, what's up?"),
            ("assistant", "Not much, just waiting for commands."),
            ("user", "khub pressure jacche ajke"),
            ("assistant", "I understand. Let's take it easy."),
            ("user", "why are you so formal"),
            ("assistant", "My bad the_brother, ki obostha bol?"),
            ("user", "darun! tui code ta lekhto ebar"),
            ("assistant", "Ekdom, writing the code now."),
        ]

        for role, content in messages:
            orchestrator.on_message(role, content)

        orchestrator.force_batch(full_rebuild=True)
        summary = orchestrator.get_profile_summary()
        assert summary["total_messages"] == 8
    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_sbs_prompt_compilation():
    """SBS should compile a system prompt with required sections."""
    test_dir = Path(tempfile.mkdtemp()) / "sbs_data"

    try:
        orchestrator = SBSOrchestrator(data_dir=str(test_dir))
        orchestrator.on_message("user", "hello")
        orchestrator.on_message("assistant", "hi there")

        prompt = orchestrator.get_system_prompt("BASE INSTRUCTIONS")
        assert "[IDENTITY]" in prompt, "Prompt missing [IDENTITY] section"
        assert "[EMOTIONAL CONTEXT]" in prompt, "Prompt missing [EMOTIONAL CONTEXT] section"
    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
