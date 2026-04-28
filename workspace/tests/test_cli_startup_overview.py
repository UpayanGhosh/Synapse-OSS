import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.chat_types import ChatLaunchOptions
from cli.onboard import _format_ready_summary
from cli.startup_overview import build_startup_overview, collect_startup_diagnostics


class ReachableClient:
    def probe_health(self):
        return True, "ok"


class UnreachableClient:
    def probe_health(self):
        return False, "connection refused"


def test_startup_overview_valid_config_normalizes_codex_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "providers": {"openai_codex": {}},
                "model_mappings": {"casual": {"model": "openai_codex/codex-mini-latest"}},
                "gateway": {"port": 8123},
            }
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("- **Name:**\n", encoding="utf-8")
    (workspace / "BOOTSTRAP.md").write_text("first run", encoding="utf-8")

    diagnostics = collect_startup_diagnostics(
        ChatLaunchOptions(target="the_creator", port=8123, workspace_dir=workspace),
        client=ReachableClient(),
    )
    overview = build_startup_overview(diagnostics)

    assert "Hi, I'm Synapse" in overview
    assert "Use this shell when setup, model routing, gateway, or local chat feels off." in overview
    assert "openai_codex/gpt-5.4" in overview
    assert f"Config: valid ({tmp_path / 'synapse.json'})" in overview
    assert "Persona/default target: the_creator" in overview
    assert "Gateway: reachable at http://127.0.0.1:8123 (ok)" in overview
    assert "First-run: pending" in overview
    assert "Next: send a message" in overview


def test_startup_overview_missing_config_and_unreachable_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    diagnostics = collect_startup_diagnostics(
        ChatLaunchOptions(target="friend", port=9001, workspace_dir=tmp_path / "workspace"),
        client=UnreachableClient(),
    )
    overview = build_startup_overview(diagnostics)

    assert "Safe-chat model: not configured" in overview
    assert f"Config: missing ({tmp_path / 'synapse.json'})" in overview
    assert "Gateway: unreachable at http://127.0.0.1:9001 (connection refused)" in overview
    assert "First-run: complete" in overview
    assert "synapse onboard" in overview


def test_startup_overview_uses_synapse_config_load_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text(
        json.dumps({"model_mappings": {"casual": {"model": "raw/ignored"}}}),
        encoding="utf-8",
    )

    from synapse_config import SynapseConfig

    monkeypatch.setattr(
        SynapseConfig,
        "load",
        lambda: SimpleNamespace(
            providers={"gemini": {}},
            channels={},
            model_mappings={"casual": {"model": "gemini/from-pipeline"}},
            gateway={"port": 8123},
            session={},
        ),
    )

    diagnostics = collect_startup_diagnostics(
        ChatLaunchOptions(target="the_creator", port=8123),
        client=ReachableClient(),
    )

    assert diagnostics.config_status == "valid"
    assert diagnostics.safe_chat_model == "gemini/from-pipeline"


def test_startup_overview_non_dict_config_is_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text("[]", encoding="utf-8")

    diagnostics = collect_startup_diagnostics(
        ChatLaunchOptions(target="the_creator", port=8123),
        client=ReachableClient(),
    )

    assert diagnostics.config_status == "invalid"


def test_startup_overview_invalid_requested_file_not_masked_by_loader(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text("[]", encoding="utf-8")

    from synapse_config import SynapseConfig

    monkeypatch.setattr(
        SynapseConfig,
        "load",
        lambda: SimpleNamespace(
            providers={"gemini": {}},
            channels={},
            model_mappings={"casual": {"model": "gemini/from-pipeline"}},
            gateway={"port": 8123},
            session={},
        ),
    )

    diagnostics = collect_startup_diagnostics(
        ChatLaunchOptions(target="the_creator", port=8123),
        client=ReachableClient(),
    )

    assert diagnostics.config_status == "invalid"
    assert diagnostics.safe_chat_model is None


def test_ready_summary_next_command_includes_non_default_port(tmp_path):
    summary = _format_ready_summary(
        {
            "providers": {"gemini": {"api_key": "fake"}},
            "channels": {},
            "gateway": {"port": 8123},
            "model_mappings": {"casual": {"model": "gemini/gemini-2.0-flash"}},
        },
        tmp_path / "synapse.json",
    )

    assert "Next: python workspace\\synapse_cli.py chat --port 8123" in summary
