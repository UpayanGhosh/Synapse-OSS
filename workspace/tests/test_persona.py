"""
test_persona.py — Tests for the PersonaManager class.

Covers:
  - Initialization and file path setup
  - Dictionary loading (found, missing, malformed)
  - File reading (found, missing, error)
  - Random word selection from dictionary
  - System prompt assembly
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from sci_fi_dashboard.persona import PersonaManager


@pytest.fixture
def persona_dir(tmp_path):
    """Create a minimal workspace structure for PersonaManager."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills_dir = workspace / "skills" / "language"
    skills_dir.mkdir(parents=True)

    # Create banglish dict
    banglish = {"bhalobasha": "love", "achha": "okay", "arrey": "hey"}
    (skills_dir / "banglish_dict.json").write_text(json.dumps(banglish))

    # Create identity files
    (workspace / "INSTRUCTIONS.MD").write_text("You are Synapse.")
    (workspace / "SOUL.md").write_text("Soul description")
    (workspace / "CORE.md").write_text("Core identity")
    (workspace / "AGENTS.md").write_text("Agent guidelines")
    (workspace / "IDENTITY.md").write_text("Identity metadata")
    (workspace / "USER.md").write_text("User profile")

    return tmp_path


@pytest.fixture
def manager(persona_dir):
    """PersonaManager with a valid workspace."""
    return PersonaManager(workspace_root=str(persona_dir))


class TestPersonaManagerInit:
    """Tests for PersonaManager initialization."""

    def test_init_with_workspace(self, persona_dir):
        """Should initialize with given workspace root."""
        mgr = PersonaManager(workspace_root=str(persona_dir))
        assert mgr.root == str(persona_dir)

    def test_init_creates_file_paths(self, persona_dir):
        """Should set up file paths dict."""
        mgr = PersonaManager(workspace_root=str(persona_dir))
        assert "instructions" in mgr.files
        assert "soul" in mgr.files
        assert "core" in mgr.files
        assert "agents" in mgr.files
        assert "identity" in mgr.files
        assert "user" in mgr.files

    def test_init_default_workspace(self):
        """Init without workspace_root should use SynapseConfig."""
        with patch("sci_fi_dashboard.persona.SynapseConfig") as mock_cfg:
            mock_cfg.load.return_value = MagicMock(data_root="/fake/path")
            mgr = PersonaManager()
            assert mgr.root == "/fake/path"


class TestLoadDictionary:
    """Tests for dictionary loading."""

    def test_loads_valid_dict(self, manager):
        """Should load banglish dictionary when file exists."""
        assert isinstance(manager.banglish_data, dict)
        assert "bhalobasha" in manager.banglish_data

    def test_missing_dict_returns_empty(self, tmp_path):
        """Missing dict file should return empty dict."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        mgr = PersonaManager(workspace_root=str(tmp_path))
        assert mgr.banglish_data == {}

    def test_malformed_dict_returns_empty(self, tmp_path):
        """Malformed JSON dict should return empty dict."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        skills_dir = workspace / "skills" / "language"
        skills_dir.mkdir(parents=True)
        (skills_dir / "banglish_dict.json").write_text("not valid json{{{")

        mgr = PersonaManager(workspace_root=str(tmp_path))
        assert mgr.banglish_data == {}


class TestReadFile:
    """Tests for the read_file method."""

    def test_reads_existing_file(self, manager):
        """Should read existing identity files."""
        content = manager.read_file("instructions")
        assert "You are Synapse." in content

    def test_reads_soul_file(self, manager):
        """Should read soul file."""
        assert "Soul description" in manager.read_file("soul")

    def test_missing_key_returns_empty(self, manager):
        """Unknown key should return empty string."""
        assert manager.read_file("nonexistent_key") == ""

    def test_missing_file_returns_empty(self, tmp_path):
        """File that doesn't exist should return empty string."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        mgr = PersonaManager(workspace_root=str(tmp_path))
        assert mgr.read_file("soul") == ""


class TestGetRandomWords:
    """Tests for the get_random_words method."""

    def test_returns_list(self, manager):
        """Should return a list."""
        words = manager.get_random_words(3)
        assert isinstance(words, list)

    def test_correct_count(self, manager):
        """Should return requested count (or fewer if dict is smaller)."""
        words = manager.get_random_words(2)
        assert len(words) <= 2

    def test_count_exceeds_dict_size(self, manager):
        """Requesting more than dict size should return all keys."""
        words = manager.get_random_words(100)
        assert len(words) == len(manager.banglish_data)

    def test_empty_dict_returns_empty(self, tmp_path):
        """Empty dict should return empty list."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        mgr = PersonaManager(workspace_root=str(tmp_path))
        assert mgr.get_random_words(5) == []


class TestGetSystemPrompt:
    """Tests for the get_system_prompt method."""

    def test_returns_string(self, manager):
        """Should return a non-empty string."""
        prompt = manager.get_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_identity_sections(self, manager):
        """Prompt should contain all identity sections."""
        prompt = manager.get_system_prompt()
        assert "You are Synapse." in prompt
        assert "<SOUL>" in prompt
        assert "<CORE>" in prompt
        assert "<USER_PROFILE>" in prompt
        assert "<WORKSPACE_GUIDELINES>" in prompt
        assert "<IDENTITY_METADATA>" in prompt

    def test_contains_dynamic_vocabulary(self, manager):
        """Prompt should contain the vocabulary injection section."""
        prompt = manager.get_system_prompt()
        assert "DYNAMIC_VOCABULARY_INJECTION" in prompt
        assert "Required Bengali/Banglish Keywords" in prompt

    def test_contains_context_loading(self, manager):
        """Prompt should have context loading separator."""
        prompt = manager.get_system_prompt()
        assert "CONTEXT LOADING" in prompt

    def test_prompt_includes_file_contents(self, manager):
        """Prompt should include actual file contents."""
        prompt = manager.get_system_prompt()
        assert "Soul description" in prompt
        assert "Core identity" in prompt
        assert "User profile" in prompt

    def test_empty_workspace_produces_prompt(self, tmp_path):
        """Even with missing files, should produce a valid (if sparse) prompt."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        mgr = PersonaManager(workspace_root=str(tmp_path))
        prompt = mgr.get_system_prompt()
        assert isinstance(prompt, str)
        assert "DYNAMIC_VOCABULARY_INJECTION" in prompt
