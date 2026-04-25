import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard import claude_cli_provider as claude_cli
from sci_fi_dashboard.llm_router import SynapseLLMRouter
from synapse_config import SynapseConfig


def _make_config(role: str, model: str, fallback: str | None = None) -> SynapseConfig:
    return SynapseConfig(
        data_root=Path("/tmp/synapse_test"),
        db_dir=Path("/tmp/synapse_test/workspace/db"),
        sbs_dir=Path("/tmp/synapse_test/workspace/sci_fi_dashboard/synapse_data"),
        log_dir=Path("/tmp/synapse_test/logs"),
        providers={"claude_cli": {}},
        channels={},
        model_mappings={role: {"model": model, "fallback": fallback}},
    )


@pytest.mark.parametrize(
    ("model_ref", "expected"),
    [
        ("claude_cli/sonnet", "sonnet"),
        ("claude-cli/claude-sonnet-4-6", "sonnet"),
        ("claude_max/claude-opus-4-7", "opus"),
        ("claude_cli/haiku-3.5", "haiku"),
        ("claude_cli/claude-future-model", "claude-future-model"),
    ],
)
def test_normalize_claude_cli_model_aliases(model_ref, expected):
    assert claude_cli.normalize_claude_cli_model(model_ref) == expected


def test_parse_claude_code_2_json_array_output():
    payload = [
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "ignored once result exists"}],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "result": "SYNAPSE_CLAUDE_OK",
            "stop_reason": "end_turn",
            "session_id": "session-1",
            "usage": {
                "input_tokens": 3,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 7,
                "output_tokens": 11,
            },
            "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 3}},
        },
    ]

    parsed = claude_cli.parse_claude_cli_output(json.dumps(payload), "sonnet")

    assert parsed.text == "SYNAPSE_CLAUDE_OK"
    assert parsed.model == "claude-sonnet-4-6"
    assert parsed.prompt_tokens == 15
    assert parsed.completion_tokens == 11
    assert parsed.total_tokens == 26
    assert parsed.finish_reason == "end_turn"
    assert parsed.session_id == "session-1"


def test_claude_cli_env_only_sets_supported_output_caps(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    client = claude_cli.ClaudeCliClient()

    small_cap_env = client._build_env(64)
    large_cap_env = client._build_env(2048)

    assert "ANTHROPIC_API_KEY" not in small_cap_env
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in small_cap_env
    assert large_cap_env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "2048"


@pytest.mark.asyncio
async def test_chat_completion_invokes_cli_with_subscription_safe_env(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self, input):
            captured["stdin"] = input.decode("utf-8")
            payload = [
                {
                    "type": "result",
                    "subtype": "success",
                    "result": "ok",
                    "usage": {"input_tokens": 2, "output_tokens": 3},
                }
            ]
            return json.dumps(payload).encode("utf-8"), b""

        def kill(self):
            captured["killed"] = True

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs["env"]
        return FakeProc()

    monkeypatch.setattr(claude_cli.shutil, "which", lambda command: "C:/bin/claude.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")

    client = claude_cli.ClaudeCliClient(command="claude", timeout=5)
    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Ping"},
        ],
        model="claude_cli/claude-sonnet-4-6",
        temperature=0,
        max_tokens=123,
    )

    assert result.text == "ok"
    assert captured["cmd"][:6] == [
        "C:/bin/claude.exe",
        "-p",
        "--output-format",
        "json",
        "--model",
        "sonnet",
    ]
    assert "--no-session-persistence" in captured["cmd"]
    assert "--setting-sources" in captured["cmd"]
    assert "--disable-slash-commands" in captured["cmd"]
    assert "--tools" in captured["cmd"]
    # System prompt must REPLACE Claude Code's default agent prompt (not
    # be appended on top), otherwise the default "I am Claude Code agent"
    # system message dominates and Synapse's persona feels hollow / AI-ish.
    # Pass via temp file because Synapse's persona regularly exceeds the
    # ~32k Windows CreateProcess argv cap.
    assert "--system-prompt" not in captured["cmd"]
    assert "--append-system-prompt-file" not in captured["cmd"]
    assert "--system-prompt-file" in captured["cmd"]
    sp_idx = captured["cmd"].index("--system-prompt-file")
    sp_path = captured["cmd"][sp_idx + 1]
    assert "synapse-claude-system-prompt-" in sp_path
    assert "User: Ping" in captured["stdin"]
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in captured["env"]


@pytest.mark.asyncio
async def test_router_dispatches_claude_cli_without_litellm(monkeypatch):
    config = _make_config("code", "claude_cli/sonnet")
    router = SynapseLLMRouter(config)
    called = {}

    async def fake_chat_completion(self, *, messages, model, temperature=None, max_tokens=None):
        called["model"] = model
        return claude_cli.ClaudeCliResponse(
            text="from cli",
            model="claude-sonnet-4-6",
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            finish_reason="end_turn",
        )

    async def fail_litellm(*args, **kwargs):
        raise AssertionError("litellm should not be used for claude_cli roles")

    monkeypatch.setattr(claude_cli.ClaudeCliClient, "chat_completion", fake_chat_completion)
    monkeypatch.setattr("litellm.acompletion", fail_litellm)

    text = await router.call("code", [{"role": "user", "content": "hi"}])

    assert text == "from cli"
    assert called["model"] == "claude_cli/sonnet"
