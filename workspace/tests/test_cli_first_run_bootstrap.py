import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.first_run_bootstrap import bootstrap_kickoff_message, needs_first_run_bootstrap


def test_needs_bootstrap_when_bootstrap_exists_and_identity_empty(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("ritual", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("- Name:\n- Creature:\n", encoding="utf-8")
    assert needs_first_run_bootstrap(tmp_path)


def test_no_bootstrap_when_identity_has_name(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("ritual", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("- Name: Synapse\n", encoding="utf-8")
    assert not needs_first_run_bootstrap(tmp_path)


def test_kickoff_message_mentions_bootstrap_and_one_question():
    msg = bootstrap_kickoff_message()
    assert "BOOTSTRAP.md" in msg
    assert "one question at a time" in msg
    assert "What should I call you" in msg
