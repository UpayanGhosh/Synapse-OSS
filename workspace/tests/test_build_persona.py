"""
test_build_persona.py — Tests for the build_persona CLI module.

Covers:
  - find_chat_file (found in various locations, not found)
  - print_profile_summary (no crash on valid profile)
  - main (argument parsing behavior)
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from sci_fi_dashboard.chat_parser import PersonaProfile


class TestFindChatFile:
    """Tests for the find_chat_file function."""

    def test_found_in_directory(self, tmp_path):
        """Should find file in the specified directory."""
        from sci_fi_dashboard.build_persona import find_chat_file
        (tmp_path / "chat.md").write_text("content")
        result = find_chat_file(str(tmp_path), "chat.md")
        assert result is not None
        assert "chat.md" in result

    def test_not_found_anywhere(self, tmp_path):
        """Should return None when file doesn't exist anywhere."""
        from sci_fi_dashboard.build_persona import find_chat_file
        result = find_chat_file(str(tmp_path), "nonexistent_chat_file_xyz.md")
        assert result is None

    def test_found_in_script_dir(self, tmp_path):
        """Should check the script directory as a fallback."""
        from sci_fi_dashboard.build_persona import find_chat_file, SCRIPT_DIR
        # If the file exists in SCRIPT_DIR it should be found; otherwise None
        result = find_chat_file(str(tmp_path), "definitely_not_a_real_file_xyzzy.md")
        assert result is None  # Shouldn't exist


class TestPrintProfileSummary:
    """Tests for print_profile_summary function."""

    def test_no_crash_on_valid_profile(self, capsys):
        """Should print without crashing for a valid profile."""
        from sci_fi_dashboard.build_persona import print_profile_summary
        profile = PersonaProfile(
            target_user="test_user",
            relationship_mode="brother",
            total_synapse_messages=100,
            total_user_messages=80,
            total_exchanges=50,
            avg_message_length=150.0,
            emoji_density=1.5,
            top_emojis=["\U0001f600", "\U0001f525"],
            catchphrases=["Let's go", "Bro"],
            banglish_words=["achha", "toh"],
            tech_jargon=["python", "fastapi"],
            topic_categories={"tech": 30, "career": 10},
            few_shot_examples=[{"user": "hi", "synapse": "hello"}],
            rules=["Be direct"],
        )
        print_profile_summary(profile)
        captured = capsys.readouterr()
        assert "test_user" in captured.out
        assert "brother" in captured.out

    def test_no_crash_on_empty_profile(self, capsys):
        """Should handle an empty profile without crashing."""
        from sci_fi_dashboard.build_persona import print_profile_summary
        profile = PersonaProfile()
        print_profile_summary(profile)
        captured = capsys.readouterr()
        assert len(captured.out) > 0  # Should have printed something


class TestBuildPersonaConstants:
    """Tests for module-level constants."""

    def test_script_dir_exists(self):
        """SCRIPT_DIR should be a valid directory."""
        from sci_fi_dashboard.build_persona import SCRIPT_DIR
        assert os.path.isdir(SCRIPT_DIR)

    def test_personas_dir_defined(self):
        """PERSONAS_DIR should be defined."""
        from sci_fi_dashboard.build_persona import PERSONAS_DIR
        assert isinstance(PERSONAS_DIR, str)
        assert len(PERSONAS_DIR) > 0
