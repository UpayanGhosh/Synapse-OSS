"""
test_sbs_bootstrap.py — Tests for the SBS bootstrap module.

Covers:
  - bootstrap_sbs function with mock data
  - Handles missing files gracefully
  - Processes chat messages into SBS orchestrator
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


class TestBootstrapSbs:
    """Tests for the bootstrap_sbs function."""

    def test_skips_missing_files(self, tmp_path, capsys):
        """Should skip files that don't exist in archive dir."""
        with (
            patch("sci_fi_dashboard.sbs_bootstrap.WORKSPACE_ROOT", str(tmp_path)),
            patch("sci_fi_dashboard.sbs_bootstrap.CURRENT_DIR", str(tmp_path / "sci_fi_dashboard")),
        ):
            os.makedirs(tmp_path / "_archived_memories", exist_ok=True)
            # Don't create the chat files
            mock_sbs = MagicMock()
            with patch("sci_fi_dashboard.sbs_bootstrap.SBSOrchestrator", return_value=mock_sbs):
                from sci_fi_dashboard.sbs_bootstrap import bootstrap_sbs

                bootstrap_sbs()
                captured = capsys.readouterr()
                assert "Skipping" in captured.out or "WARN" in captured.out

    def test_processes_existing_file(self, tmp_path, capsys):
        """Should process chat files that exist."""
        # Create archive dir with a chat file
        archive_dir = tmp_path / "_archived_memories"
        archive_dir.mkdir()
        chat_content = """[2024-10-25 14:00] primary_user:
Hey, how are you?

[2024-10-25 14:01] Synapse:
Hey bro! I'm doing great. Working on some python stuff.
"""
        (archive_dir / "Chat_with_primary_user_LLM.md").write_text(chat_content, encoding="utf-8")

        mock_sbs = MagicMock()
        mock_sbs.logger = MagicMock()
        mock_sbs.force_batch = MagicMock()

        with (
            patch("sci_fi_dashboard.sbs_bootstrap.WORKSPACE_ROOT", str(tmp_path)),
            patch("sci_fi_dashboard.sbs_bootstrap.CURRENT_DIR", str(tmp_path / "sci_fi_dashboard")),
            patch("sci_fi_dashboard.sbs_bootstrap.SBSOrchestrator", return_value=mock_sbs),
        ):
            from sci_fi_dashboard.sbs_bootstrap import bootstrap_sbs

            bootstrap_sbs()

            # Should have logged messages
            assert mock_sbs.logger.log.call_count >= 1
            # Should have triggered force_batch
            mock_sbs.force_batch.assert_called()

    def test_bootstrap_prints_completion(self, tmp_path, capsys):
        """Should print completion message."""
        with (
            patch("sci_fi_dashboard.sbs_bootstrap.WORKSPACE_ROOT", str(tmp_path)),
            patch("sci_fi_dashboard.sbs_bootstrap.CURRENT_DIR", str(tmp_path / "sci_fi_dashboard")),
        ):
            os.makedirs(tmp_path / "_archived_memories", exist_ok=True)
            mock_sbs = MagicMock()
            with patch("sci_fi_dashboard.sbs_bootstrap.SBSOrchestrator", return_value=mock_sbs):
                from sci_fi_dashboard.sbs_bootstrap import bootstrap_sbs

                bootstrap_sbs()
                captured = capsys.readouterr()
                assert "Bootstrap Complete" in captured.out or "Complete" in captured.out
