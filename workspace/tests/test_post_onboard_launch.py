import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.chat_types import ChatLaunchOptions
from cli.post_onboard_launch import build_post_onboard_chat_options, should_offer_cli_chat


def test_should_offer_cli_chat_only_for_interactive_success():
    assert should_offer_cli_chat(non_interactive=False, launch_chat=None)
    assert not should_offer_cli_chat(non_interactive=True, launch_chat=None)
    assert should_offer_cli_chat(non_interactive=True, launch_chat=True)
    assert not should_offer_cli_chat(non_interactive=False, launch_chat=False)


def test_should_offer_cli_chat_accepts_positional_args():
    assert should_offer_cli_chat(False, None)
    assert not should_offer_cli_chat(True, None)


def test_build_options_keeps_bootstrap_pending_without_auto_message(tmp_path, monkeypatch):
    (tmp_path / "BOOTSTRAP.md").write_text("ritual", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("- Name:\n", encoding="utf-8")
    opts = build_post_onboard_chat_options(workspace_dir=tmp_path, port=8123)
    assert isinstance(opts, ChatLaunchOptions)
    assert opts.port == 8123
    assert opts.initial_message is None
    assert opts.workspace_dir == tmp_path


def test_build_options_accepts_positional_workspace_and_port(tmp_path):
    opts = build_post_onboard_chat_options(tmp_path, 8124)
    assert isinstance(opts, ChatLaunchOptions)
    assert opts.target == "the_creator"
    assert opts.user_id == "local_cli"
    assert opts.port == 8124
