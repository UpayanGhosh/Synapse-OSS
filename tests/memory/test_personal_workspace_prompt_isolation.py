from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

try:
    from sci_fi_dashboard import chat_pipeline
except ModuleNotFoundError as exc:
    if exc.name != "pyarrow":
        raise
    # The prefix helpers do not use the heavyweight runtime singleton. Keep
    # their production implementation under test while bypassing its optional
    # database-provider import, which is absent in this local test runtime.
    sys.modules["sci_fi_dashboard._deps"] = ModuleType("sci_fi_dashboard._deps")
    from sci_fi_dashboard import chat_pipeline

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "workspace-prompts"


@pytest.fixture
def workspace_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    root = TEST_DATA_ROOT / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    paths: dict[str, Path] = {}
    for name in chat_pipeline._AGENT_WORKSPACE_FILES:
        path = root / f"{name}.md"
        path.write_text(f"{name}-SAFE-CONTENT\n", encoding="utf-8")
        paths[name] = path

    monkeypatch.setattr(chat_pipeline, "_resolve_agent_workspace_path", lambda name: paths[name])
    chat_pipeline._agent_workspace_cache.update(content="", content_by_tier={}, mtimes={})
    chat_pipeline.clear_agent_workspace_session_prefix()
    yield paths
    chat_pipeline._agent_workspace_cache.update(content="", content_by_tier={}, mtimes={})
    chat_pipeline.clear_agent_workspace_session_prefix()


def _safe_flag_kwargs(function) -> dict[str, bool]:
    if "include_personal_documents" in inspect.signature(function).parameters:
        return {"include_personal_documents": False}
    return {}


def test_full_fallback_workspace_prefix_excludes_shared_personal_files(workspace_files) -> None:
    prefix = chat_pipeline._load_agent_workspace_prefix(
        "frontier", **_safe_flag_kwargs(chat_pipeline._load_agent_workspace_prefix)
    )

    assert "USER-SAFE-CONTENT" not in prefix
    assert "MEMORY-SAFE-CONTENT" not in prefix
    for name in ("INSTRUCTIONS", "SOUL", "CORE", "CODE", "IDENTITY", "TOOLS", "AGENTS"):
        assert f"{name}-SAFE-CONTENT" in prefix


def test_cached_session_prefix_is_sanitized_before_compact_prompt_use() -> None:
    session = "alice-session"
    tier = chat_pipeline.get_prompt_tier_policy("small").tier
    chat_pipeline._agent_workspace_session_cache[(session, tier)] = (
        "# ===== INSTRUCTIONS.md =====\nINSTRUCTIONS-SAFE\n"
        "# ===== SOUL.md =====\nSOUL-SAFE\n"
        "# ===== CORE.md =====\nCORE-SAFE\n"
        "# ===== CODE.md =====\nCODE-SAFE\n"
        "# ===== IDENTITY.md =====\nIDENTITY-SAFE\n"
        "# ===== USER.md =====\nAlice private profile USER-PRIVATE-ALICE\n"
        "# ===== TOOLS.md =====\nTOOLS-SAFE\n"
        "# ===== MEMORY.md =====\nAlice private memory MEMORY-PRIVATE-ALICE\n"
        "# ===== AGENTS.md =====\nAGENTS-SAFE\n"
    )

    prefix = chat_pipeline._load_agent_workspace_prefix_for_session(
        session,
        "small",
        **_safe_flag_kwargs(chat_pipeline._load_agent_workspace_prefix_for_session),
    )
    compact = chat_pipeline._build_compact_workspace_excerpt(prefix)

    assert "USER-PRIVATE-ALICE" not in prefix
    assert "MEMORY-PRIVATE-ALICE" not in prefix
    assert "USER-PRIVATE-ALICE" not in compact
    assert "MEMORY-PRIVATE-ALICE" not in compact
    for marker in (
        "INSTRUCTIONS-SAFE",
        "SOUL-SAFE",
        "CORE-SAFE",
        "CODE-SAFE",
        "IDENTITY-SAFE",
        "TOOLS-SAFE",
        "AGENTS-SAFE",
    ):
        assert marker in compact


def test_compact_prompt_error_fallback_does_not_reuse_personal_workspace(monkeypatch) -> None:
    def fail_personal_workspace(*_args, **_kwargs):
        raise RuntimeError("synthetic workspace read failure")

    class EmptySbs:
        def get_system_prompt(self, *_args):
            return ""

    monkeypatch.setattr(
        chat_pipeline,
        "_load_agent_workspace_prefix_for_session",
        fail_personal_workspace,
    )
    prompt = chat_pipeline._build_compact_casual_system_prompt(
        "casual_light",
        EmptySbs(),
        "Stable bot instructions.",
        "",
        session_key="alice-session",
    )

    assert "USER-PRIVATE-ALICE" not in prompt
    assert "MEMORY-PRIVATE-ALICE" not in prompt
    assert "Stable bot instructions." not in prompt
