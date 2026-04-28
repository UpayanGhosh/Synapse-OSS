"""Tests for the agent workspace markdown prefix loader (RT2).

Covers:
    - _load_agent_workspace_prefix returns non-empty content with all 7 sections
    - Section ordering: SOUL → CORE → IDENTITY → USER → TOOLS → MEMORY → AGENTS
    - mtime-based cache invalidation reloads when a template file changes
    - Path resolution prefers user override over runtime template over repo template
    - The prefix is wired into persona_chat() system prompt assembly (and the old
      5-rule nudge has been removed)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard import chat_pipeline


@pytest.fixture(autouse=True)
def _reset_agent_workspace_cache():
    """Clear the module-level cache between tests so each starts clean."""
    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["content_by_tier"] = {}
    chat_pipeline._agent_workspace_cache["mtimes"] = {}
    yield
    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["content_by_tier"] = {}
    chat_pipeline._agent_workspace_cache["mtimes"] = {}


@pytest.mark.unit
def test_load_agent_workspace_prefix_returns_content():
    """Loader returns non-empty content with all 7 file sections."""
    prefix = chat_pipeline._load_agent_workspace_prefix()
    assert isinstance(prefix, str)
    assert len(prefix) > 500, f"Expected >500 chars, got {len(prefix)}"
    for name in ["SOUL", "CORE", "CODE", "IDENTITY", "USER", "TOOLS", "MEMORY", "AGENTS"]:
        assert name in prefix, f"{name} section missing from prefix"
        assert f"# ===== {name}.md =====" in prefix, f"{name} section header missing"


@pytest.mark.unit
def test_load_agent_workspace_prefix_section_order():
    """Sections appear in the documented order — AGENTS comes LAST."""
    prefix = chat_pipeline._load_agent_workspace_prefix()
    expected_order = ["SOUL", "CORE", "CODE", "IDENTITY", "USER", "TOOLS", "MEMORY", "AGENTS"]
    indices = [prefix.find(f"# ===== {name}.md =====") for name in expected_order]
    assert all(i >= 0 for i in indices), "All section headers should be present"
    assert indices == sorted(indices), (
        f"Sections out of order: {list(zip(expected_order, indices, strict=False))}"
    )


@pytest.mark.unit
def test_load_agent_workspace_prefix_uses_cache():
    """Repeated calls hit the cache — same string identity unless mtime changes."""
    first = chat_pipeline._load_agent_workspace_prefix()
    second = chat_pipeline._load_agent_workspace_prefix()
    assert first == second
    assert chat_pipeline._agent_workspace_cache["content"] == first


@pytest.mark.unit
def test_load_agent_workspace_prefix_mtime_cache_invalidation(tmp_path, monkeypatch):
    """Editing a template file invalidates the cache and reloads content."""
    # Redirect repo + user dirs to a tmp_path so we control the files entirely.
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    # Seed all guidance files in the repo dir.
    files = ["SOUL", "CORE", "CODE", "IDENTITY", "USER", "TOOLS", "MEMORY", "AGENTS"]
    for name in files:
        (fake_repo_dir / f"{name}.md.template").write_text(
            f"# {name} initial content\n\nbody for {name}",
            encoding="utf-8",
        )

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    # Reset cache so this test sees a cold start.
    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["mtimes"] = {}

    first = chat_pipeline._load_agent_workspace_prefix()
    assert "SOUL initial content" in first

    # Touch the SOUL file with a new mtime + new content.
    soul_path = fake_repo_dir / "SOUL.md.template"
    new_mtime = time.time() + 10
    soul_path.write_text("# SOUL updated content\n\nbody for SOUL", encoding="utf-8")
    os.utime(soul_path, (new_mtime, new_mtime))

    second = chat_pipeline._load_agent_workspace_prefix()
    assert "SOUL updated content" in second
    assert "SOUL initial content" not in second
    assert second != first


@pytest.mark.unit
def test_resolve_agent_workspace_path_prefers_user_override(tmp_path, monkeypatch):
    """User override (~/.synapse/workspace/<NAME>.md) wins over repo default."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    # Repo has SOUL.md.template, user has SOUL.md (override).
    (fake_repo_dir / "SOUL.md.template").write_text("repo soul", encoding="utf-8")
    user_override = fake_user_dir / "SOUL.md"
    user_override.write_text("user override", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("SOUL")
    assert resolved == user_override


@pytest.mark.unit
def test_resolve_agent_workspace_path_falls_back_to_runtime_template(tmp_path, monkeypatch):
    """Runtime template (~/.synapse/workspace/<NAME>.md.template) is tier 2."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    runtime_tpl = fake_user_dir / "CORE.md.template"
    runtime_tpl.write_text("runtime tpl", encoding="utf-8")
    (fake_repo_dir / "CORE.md.template").write_text("repo tpl", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("CORE")
    assert resolved == runtime_tpl


@pytest.mark.unit
def test_resolve_agent_workspace_path_falls_back_to_repo(tmp_path, monkeypatch):
    """Repo default is the last-resort tier 3."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    repo_tpl = fake_repo_dir / "AGENTS.md.template"
    repo_tpl.write_text("repo agents", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("AGENTS")
    assert resolved == repo_tpl


@pytest.mark.unit
def test_load_agent_workspace_prefix_returns_empty_when_nothing_resolves(tmp_path, monkeypatch):
    """No files anywhere → empty string, no crash."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["mtimes"] = {}

    prefix = chat_pipeline._load_agent_workspace_prefix()
    assert prefix == ""


# ---------------------------------------------------------------------------
# Integration sanity checks — wiring + old nudge removal
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_old_nudge_is_removed_from_chat_pipeline():
    """The old 5-rule ad-hoc CORE RULES nudge must be GONE from chat_pipeline source."""
    pipeline_path = Path(chat_pipeline.__file__)
    source = pipeline_path.read_text(encoding="utf-8")
    # The literal multi-line nudge text — must not appear in any system message body.
    assert '"CORE RULES:\\n"' not in source, "Old CORE RULES nudge string still present"
    assert "do NOT surrender and report the error" not in source, (
        "Old surrender nudge still present"
    )
    assert "Chain multiple tool calls across rounds" not in source, (
        "Old chain-tools nudge still present"
    )


@pytest.mark.integration
def test_agent_workspace_loader_is_wired_in_persona_chat():
    """The loader is referenced in persona_chat's system prompt assembly."""
    pipeline_path = Path(chat_pipeline.__file__)
    source = pipeline_path.read_text(encoding="utf-8")
    # The wiring call site
    assert "_load_agent_workspace_prefix(prompt_policy.tier)" in source
    # Composes ABOVE the existing system prompt with a separator
    assert '"---"' in source or "---" in source


@pytest.mark.integration
def test_sbs_orchestrator_get_system_prompt_still_called():
    """SBS persona assembly is preserved — get_system_prompt() still invoked."""
    pipeline_path = Path(chat_pipeline.__file__)
    source = pipeline_path.read_text(encoding="utf-8")
    assert "sbs_orchestrator.get_system_prompt(base_instructions, proactive_block)" in source
