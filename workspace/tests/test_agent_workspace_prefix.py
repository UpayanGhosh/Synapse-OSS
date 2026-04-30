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
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _NoopEmitter:
    def start_run(self, **_kwargs):
        return "test-run"

    def emit(self, *_args, **_kwargs):
        return None


class _DummyLLMResult:
    def __init__(self, content="", **kwargs):
        self.content = content
        self.text = content
        for key, value in kwargs.items():
            setattr(self, key, value)


class _NoopFlood:
    def set_callback(self, callback):
        self.callback = callback


class _NoopQueue:
    async def enqueue(self, task):
        self.last_task = task


class _NoopSBS:
    def on_message(self, *_args, **_kwargs):
        return {"msg_id": "test-msg"}

    def get_system_prompt(self, base_instructions, proactive_block=""):
        return "\n".join(part for part in [base_instructions, proactive_block] if part)


class _NoopMemory:
    def query(self, *_args, **_kwargs):
        return {"results": [], "tier": "unit", "graph_context": ""}

    def add_memory(self, **_kwargs):
        return None


class _NoopToxic:
    def score(self, *_args, **_kwargs):
        return 0.0


class _NoopRouter:
    async def call_with_metadata(self, *_args, **_kwargs):
        return _DummyLLMResult("ok", model="test/mock", total_tokens=0)


class _NoopDualCognition:
    trajectory = None

    def build_cognitive_context(self, *_args, **_kwargs):
        return ""

    async def think(self, *_args, **_kwargs):
        return types.SimpleNamespace(
            tension_level=0.0,
            tension_type="none",
            response_strategy="acknowledge",
            suggested_tone="warm",
            inner_monologue="",
            thought="",
            contradictions=[],
            memory_insights=[],
        )


_deps_stub = types.SimpleNamespace(
    pending_consents={},
    consent_protocol=None,
    _SKILL_SYSTEM_AVAILABLE=False,
    skill_registry=None,
    skill_router=None,
    tool_registry=None,
    _TOOL_REGISTRY_AVAILABLE=False,
    _TOOL_SAFETY_AVAILABLE=False,
    _TOOL_FEATURES_AVAILABLE=False,
    _proactive_engine=None,
    _synapse_cfg=types.SimpleNamespace(
        data_root=Path("."),
        raw={},
        image_gen={"enabled": False},
        session={
            "dual_cognition_enabled": False,
            "dual_cognition_timeout": 0.01,
            "selfEntityNames": {},
        },
        model_mappings={},
    ),
    memory_engine=_NoopMemory(),
    toxic_scorer=_NoopToxic(),
    dual_cognition=_NoopDualCognition(),
    synapse_llm_router=_NoopRouter(),
    get_sbs_for_target=lambda _target: _NoopSBS(),
    channel_registry=types.SimpleNamespace(get=lambda _channel_id: None),
    conversation_cache=types.SimpleNamespace(
        get=lambda _key: None,
        put=lambda *_args, **_kwargs: None,
        append=lambda *_args, **_kwargs: None,
        invalidate=lambda *_args, **_kwargs: None,
    ),
    diary_engine=None,
    agent_runner=None,
    agent_registry=None,
    _resolve_target=lambda _chat_id: "the_creator",
    task_queue=_NoopQueue(),
    flood=_NoopFlood(),
    brain=types.SimpleNamespace(prune_graph=lambda: None),
    conflicts=types.SimpleNamespace(prune_conflicts=lambda: None),
    sbs_registry={},
    WORKSPACE_ROOT=Path("."),
    MAX_TOOL_ROUNDS=12,
    TOOL_RESULT_MAX_CHARS=4000,
    MAX_TOTAL_TOOL_RESULT_CHARS=20_000,
    TOOL_LOOP_WALL_CLOCK_S=30.0,
    TOOL_LOOP_TOKEN_RATIO_ABORT=0.85,
)
sys.modules.setdefault("sci_fi_dashboard._deps", _deps_stub)
sys.modules.setdefault(
    "sci_fi_dashboard.dual_cognition",
    types.SimpleNamespace(CognitiveMerge=object),
)
sys.modules.setdefault(
    "sci_fi_dashboard.llm_router",
    types.SimpleNamespace(LLMResult=_DummyLLMResult),
)
sys.modules.setdefault(
    "sci_fi_dashboard.pipeline_emitter",
    types.SimpleNamespace(get_emitter=lambda: _NoopEmitter()),
)

from sci_fi_dashboard import chat_pipeline


@pytest.fixture(autouse=True)
def _reset_agent_workspace_cache():
    """Clear the module-level cache between tests so each starts clean."""
    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["content_by_tier"] = {}
    chat_pipeline._agent_workspace_cache["mtimes"] = {}
    chat_pipeline._agent_workspace_session_cache.clear()
    yield
    chat_pipeline._agent_workspace_cache["content"] = ""
    chat_pipeline._agent_workspace_cache["content_by_tier"] = {}
    chat_pipeline._agent_workspace_cache["mtimes"] = {}
    chat_pipeline._agent_workspace_session_cache.clear()


@pytest.mark.unit
def test_load_agent_workspace_prefix_returns_content():
    """Loader returns non-empty content with all 7 file sections."""
    prefix = chat_pipeline._load_agent_workspace_prefix()
    assert isinstance(prefix, str)
    assert len(prefix) > 500, f"Expected >500 chars, got {len(prefix)}"
    for name in [
        "INSTRUCTIONS",
        "SOUL",
        "CORE",
        "CODE",
        "IDENTITY",
        "USER",
        "TOOLS",
        "MEMORY",
        "AGENTS",
    ]:
        assert name in prefix, f"{name} section missing from prefix"
        assert f"# ===== {name}.md =====" in prefix, f"{name} section header missing"


@pytest.mark.unit
def test_load_agent_workspace_prefix_section_order():
    """Sections appear in the documented order — AGENTS comes LAST."""
    prefix = chat_pipeline._load_agent_workspace_prefix()
    expected_order = [
        "INSTRUCTIONS",
        "SOUL",
        "CORE",
        "CODE",
        "IDENTITY",
        "USER",
        "TOOLS",
        "MEMORY",
        "AGENTS",
    ]
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
    files = [
        "INSTRUCTIONS",
        "SOUL",
        "CORE",
        "CODE",
        "IDENTITY",
        "USER",
        "TOOLS",
        "MEMORY",
        "AGENTS",
    ]
    for name in files:
        filename = (
            f"{name}.md"
            if name in {"INSTRUCTIONS", "CORE", "AGENTS"}
            else f"{name}.md.template"
        )
        (fake_repo_dir / filename).write_text(
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
def test_agent_workspace_prefix_is_frozen_per_session(tmp_path, monkeypatch):
    """A session reads identity files once, then keeps the same backbone."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    files = [
        "INSTRUCTIONS",
        "SOUL",
        "CORE",
        "CODE",
        "IDENTITY",
        "USER",
        "TOOLS",
        "MEMORY",
        "AGENTS",
    ]
    for name in files:
        filename = (
            f"{name}.md"
            if name in {"INSTRUCTIONS", "CORE", "AGENTS"}
            else f"{name}.md.template"
        )
        (fake_repo_dir / filename).write_text(
            f"# {name} initial content\n\nbody for {name}",
            encoding="utf-8",
        )

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)
    chat_pipeline._agent_workspace_session_cache.clear()

    first = chat_pipeline._load_agent_workspace_prefix_for_session("session-a", "frontier")
    assert "SOUL initial content" in first

    soul_path = fake_repo_dir / "SOUL.md.template"
    new_mtime = time.time() + 10
    soul_path.write_text("# SOUL updated content\n\nbody for SOUL", encoding="utf-8")
    os.utime(soul_path, (new_mtime, new_mtime))

    same_session = chat_pipeline._load_agent_workspace_prefix_for_session("session-a", "frontier")
    new_session = chat_pipeline._load_agent_workspace_prefix_for_session("session-b", "frontier")

    assert "SOUL initial content" in same_session
    assert "SOUL updated content" not in same_session
    assert "SOUL updated content" in new_session


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
def test_resolve_agent_workspace_path_uses_single_repo_core(tmp_path, monkeypatch):
    """CORE has one repo source of truth: agent_workspace/CORE.md."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    canonical_core = fake_repo_dir / "CORE.md"
    canonical_core.write_text("canonical core", encoding="utf-8")
    stale_core_template = fake_repo_dir / "CORE.md.template"
    stale_core_template.write_text("stale duplicate core", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("CORE")
    assert resolved == canonical_core


@pytest.mark.unit
def test_resolve_agent_workspace_path_uses_single_repo_agents(tmp_path, monkeypatch):
    """AGENTS has one repo source of truth: agent_workspace/AGENTS.md."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    canonical_agents = fake_repo_dir / "AGENTS.md"
    canonical_agents.write_text("canonical agents", encoding="utf-8")
    stale_agents_template = fake_repo_dir / "AGENTS.md.template"
    stale_agents_template.write_text("stale duplicate agents", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("AGENTS")
    assert resolved == canonical_agents


@pytest.mark.unit
def test_resolve_agent_workspace_path_uses_single_repo_instructions(tmp_path, monkeypatch):
    """INSTRUCTIONS has one repo source of truth: agent_workspace/INSTRUCTIONS.md."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    canonical_instructions = fake_repo_dir / "INSTRUCTIONS.md"
    canonical_instructions.write_text("canonical instructions", encoding="utf-8")
    stale_instructions_template = fake_repo_dir / "INSTRUCTIONS.md.template"
    stale_instructions_template.write_text("stale duplicate instructions", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("INSTRUCTIONS")
    assert resolved == canonical_instructions


@pytest.mark.unit
def test_resolve_agent_workspace_path_falls_back_to_repo(tmp_path, monkeypatch):
    """Repo default is the last-resort tier 3."""
    fake_user_dir = tmp_path / "user_workspace"
    fake_repo_dir = tmp_path / "repo_workspace"
    fake_user_dir.mkdir()
    fake_repo_dir.mkdir()

    repo_tpl = fake_repo_dir / "MEMORY.md.template"
    repo_tpl.write_text("repo memory", encoding="utf-8")

    monkeypatch.setattr(chat_pipeline, "_USER_AGENT_WORKSPACE", fake_user_dir)
    monkeypatch.setattr(chat_pipeline, "_REPO_AGENT_WORKSPACE", fake_repo_dir)

    resolved = chat_pipeline._resolve_agent_workspace_path("MEMORY")
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
    assert "_load_agent_workspace_prefix_for_session(" in source
    # Composes ABOVE the existing system prompt with a separator
    assert '"---"' in source or "---" in source


@pytest.mark.integration
def test_sbs_orchestrator_get_system_prompt_still_called():
    """SBS persona assembly is preserved — get_system_prompt() still invoked."""
    pipeline_path = Path(chat_pipeline.__file__)
    source = pipeline_path.read_text(encoding="utf-8")
    assert "sbs_orchestrator.get_system_prompt(base_instructions, proactive_block)" in source
