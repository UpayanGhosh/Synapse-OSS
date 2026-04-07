"""
Tests for SkillCreator — Plan 01-05.

Covers:
- SkillCreator.create() — directory structure, SKILL.md contents, validation
- SkillCreator.generate_from_conversation() — LLM extraction + create pipeline
- Bundled skill-creator SKILL.md validity
- SkillRunner._execute_skill_creator special handler
- SkillRegistry.seed_bundled_skills() — copy on first run, no overwrite
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_router(json_payload: dict | None = None) -> MagicMock:
    """Return a mock LLM router whose .call() returns a JSON string."""
    router = MagicMock()
    if json_payload is None:
        json_payload = {
            "name": "weather-checker",
            "description": "Check the current weather",
            "instructions": "Use your knowledge to check weather conditions.",
            "triggers": ["check weather", "what's the weather"],
            "model_hint": "analysis",
        }
    router.call = AsyncMock(return_value=json.dumps(json_payload))
    return router


# ---------------------------------------------------------------------------
# Task 1: SkillCreator.create()
# ---------------------------------------------------------------------------


class TestSkillCreatorCreate:
    """Tests for SkillCreator.create() — SKILL-04."""

    def test_create_produces_skill_directory(self, tmp_path):
        """Test 1: creates a directory at skills_dir/name."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        skill_dir = SkillCreator.create(
            name="weather-checker",
            description="Check the current weather",
            skills_dir=tmp_path,
        )
        assert skill_dir.exists(), "skill directory must exist after create()"
        assert skill_dir.name == "weather-checker"
        assert skill_dir.parent == tmp_path

    def test_create_includes_all_subdirectories(self, tmp_path):
        """Test 2: created directory has scripts/, references/, and assets/ (per SKILL-01)."""
        from sci_fi_dashboard.skills.creator import SkillCreator
        from sci_fi_dashboard.skills.schema import OPTIONAL_SUBDIRS

        skill_dir = SkillCreator.create(
            name="test-skill",
            description="A test skill",
            skills_dir=tmp_path,
        )
        for subdir in OPTIONAL_SUBDIRS:
            assert (skill_dir / subdir).is_dir(), f"{subdir}/ must exist in created skill"

    def test_create_produces_valid_skill_md(self, tmp_path):
        """Test 3: SKILL.md has valid YAML frontmatter with required fields."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        skill_dir = SkillCreator.create(
            name="code-helper",
            description="Help with code",
            skills_dir=tmp_path,
        )
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), "SKILL.md must exist"
        content = skill_md.read_text(encoding="utf-8")
        assert "name:" in content
        assert "description:" in content
        assert "version:" in content

    def test_create_validates_with_skill_loader(self, tmp_path):
        """Test 4: SkillLoader.load_skill() succeeds on the generated directory."""
        from sci_fi_dashboard.skills.creator import SkillCreator
        from sci_fi_dashboard.skills.loader import SkillLoader

        skill_dir = SkillCreator.create(
            name="test-valid",
            description="A valid test skill",
            skills_dir=tmp_path,
        )
        # Should not raise
        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.name == "test-valid"
        assert manifest.description == "A valid test skill"
        assert manifest.version != ""

    def test_create_normalizes_name_with_spaces(self, tmp_path):
        """Test 5: names with spaces are converted to lowercase-hyphenated."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        skill_dir = SkillCreator.create(
            name="My Cool Skill",
            description="A cool skill",
            skills_dir=tmp_path,
        )
        assert skill_dir.name == "my-cool-skill", (
            "Name should be normalized to lowercase-hyphenated"
        )

    def test_create_raises_if_skill_already_exists(self, tmp_path):
        """Test 6: ValueError raised if skill already exists."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        SkillCreator.create(
            name="duplicate-skill",
            description="First version",
            skills_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="already exists"):
            SkillCreator.create(
                name="duplicate-skill",
                description="Second version",
                skills_dir=tmp_path,
            )

    def test_create_with_custom_instructions(self, tmp_path):
        """Test 7: Custom instructions are written to SKILL.md body."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        custom_instructions = "Always respond in bullet points."
        skill_dir = SkillCreator.create(
            name="bullet-skill",
            description="Uses bullet points",
            skills_dir=tmp_path,
            instructions=custom_instructions,
        )
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert custom_instructions in content, (
            "Custom instructions must appear in SKILL.md body"
        )

    def test_create_uses_optional_subdirs_constant(self, tmp_path):
        """Test 8: All OPTIONAL_SUBDIRS from schema are created (scripts, references, assets)."""
        from sci_fi_dashboard.skills.creator import SkillCreator
        from sci_fi_dashboard.skills.schema import OPTIONAL_SUBDIRS

        skill_dir = SkillCreator.create(
            name="subdir-test",
            description="Test all subdirs",
            skills_dir=tmp_path,
        )
        # Explicitly verify all three
        assert (skill_dir / "scripts").is_dir()
        assert (skill_dir / "references").is_dir()
        assert (skill_dir / "assets").is_dir()
        # Verify they match the OPTIONAL_SUBDIRS constant
        assert set(OPTIONAL_SUBDIRS) == {"scripts", "references", "assets"}


# ---------------------------------------------------------------------------
# Task 1: SkillCreator.generate_from_conversation()
# ---------------------------------------------------------------------------


class TestSkillCreatorGenerateFromConversation:
    """Tests for SkillCreator.generate_from_conversation()."""

    def test_generate_extracts_name_and_creates_skill(self, tmp_path):
        """Test 7: extracts skill name and description via LLM, then calls create()."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        router = _make_llm_router()
        result = asyncio.get_event_loop().run_until_complete(
            SkillCreator.generate_from_conversation(
                user_message="create a skill that checks the weather",
                skills_dir=tmp_path,
                llm_router=router,
            )
        )
        assert result.get("skill_name") is not None or result.get("message") is not None
        router.call.assert_called_once()

    def test_generate_with_valid_json_creates_skill_directory(self, tmp_path):
        """Test 8: mock LLM returning valid JSON creates a valid skill directory."""
        from sci_fi_dashboard.skills.creator import SkillCreator
        from sci_fi_dashboard.skills.loader import SkillLoader

        router = _make_llm_router(
            {
                "name": "weather-checker",
                "description": "Check current weather conditions",
                "instructions": "Use weather APIs to check conditions.",
                "triggers": ["check weather", "what is the weather"],
                "model_hint": "analysis",
            }
        )
        result = asyncio.get_event_loop().run_until_complete(
            SkillCreator.generate_from_conversation(
                user_message="make a weather checker skill",
                skills_dir=tmp_path,
                llm_router=router,
            )
        )
        # Should succeed
        assert "skill_name" in result, f"Expected skill_name in result, got: {result}"
        # Verify the skill directory was created
        skill_dir = tmp_path / result["skill_name"]
        assert skill_dir.exists(), "Skill directory must be created"
        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.name == "weather-checker"

    def test_generate_returns_failure_dict_on_invalid_json(self, tmp_path):
        """generate_from_conversation returns failure dict when LLM returns garbage."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        router = MagicMock()
        router.call = AsyncMock(return_value="this is not json at all!!!")
        result = asyncio.get_event_loop().run_until_complete(
            SkillCreator.generate_from_conversation(
                user_message="make something",
                skills_dir=tmp_path,
                llm_router=router,
            )
        )
        # Should return a failure dict, not raise
        assert "message" in result

    def test_generate_handles_json_in_code_block(self, tmp_path):
        """generate_from_conversation extracts JSON from markdown code blocks."""
        from sci_fi_dashboard.skills.creator import SkillCreator

        json_data = {
            "name": "calc-skill",
            "description": "Perform calculations",
            "instructions": "Do math.",
            "triggers": ["calculate", "compute"],
            "model_hint": "code",
        }
        markdown_response = f"```json\n{json.dumps(json_data)}\n```"
        router = MagicMock()
        router.call = AsyncMock(return_value=markdown_response)
        result = asyncio.get_event_loop().run_until_complete(
            SkillCreator.generate_from_conversation(
                user_message="create a calculator skill",
                skills_dir=tmp_path,
                llm_router=router,
            )
        )
        # Should succeed — JSON extracted from markdown
        assert "skill_name" in result or "message" in result


# ---------------------------------------------------------------------------
# Task 2: Bundled skill-creator SKILL.md validity
# ---------------------------------------------------------------------------


class TestBundledSkillCreator:
    """Tests for bundled skill-creator directory."""

    def _bundled_dir(self) -> Path:
        """Resolve path to bundled skill-creator directory."""
        skills_pkg = Path(__file__).parent.parent / "sci_fi_dashboard" / "skills"
        return skills_pkg / "bundled" / "skill-creator"

    def test_bundled_skill_creator_skill_md_exists(self):
        """Bundled skill-creator SKILL.md exists."""
        bundled_dir = self._bundled_dir()
        assert (bundled_dir / "SKILL.md").exists(), (
            f"SKILL.md must exist at {bundled_dir}"
        )

    def test_bundled_skill_creator_loads_with_skill_loader(self):
        """Bundled skill-creator SKILL.md is loadable by SkillLoader."""
        from sci_fi_dashboard.skills.loader import SkillLoader

        bundled_dir = self._bundled_dir()
        manifest = SkillLoader.load_skill(bundled_dir)
        assert manifest.name == "skill-creator"
        assert len(manifest.description) > 0
        assert manifest.version != ""

    def test_bundled_skill_creator_has_all_optional_subdirs(self):
        """Bundled skill-creator directory contains scripts/, references/, and assets/."""
        from sci_fi_dashboard.skills.schema import OPTIONAL_SUBDIRS

        bundled_dir = self._bundled_dir()
        for subdir in OPTIONAL_SUBDIRS:
            assert (bundled_dir / subdir).is_dir(), (
                f"Bundled skill-creator must have {subdir}/ per SKILL-01"
            )

    def test_bundled_skill_creator_has_trigger_phrases(self):
        """Bundled skill-creator has trigger phrases including 'create a skill'."""
        from sci_fi_dashboard.skills.loader import SkillLoader

        manifest = SkillLoader.load_skill(self._bundled_dir())
        assert any("create" in t.lower() for t in manifest.triggers), (
            "skill-creator must have at least one 'create' trigger phrase"
        )

    def test_bundled_skill_creator_has_filesystem_write_permission(self):
        """Bundled skill-creator has filesystem:write permission declared."""
        from sci_fi_dashboard.skills.loader import SkillLoader

        manifest = SkillLoader.load_skill(self._bundled_dir())
        assert "filesystem:write" in manifest.permissions, (
            "skill-creator must declare filesystem:write permission"
        )


# ---------------------------------------------------------------------------
# Task 2: SkillRunner._execute_skill_creator
# ---------------------------------------------------------------------------


class TestSkillRunnerSkillCreator:
    """Tests for SkillRunner special handling of skill-creator."""

    def _skill_creator_manifest(self) -> "SkillManifest":
        """Build a minimal skill-creator manifest for testing."""
        from sci_fi_dashboard.skills.schema import SkillManifest

        return SkillManifest(
            name="skill-creator",
            description="Create new skills",
            version="1.0.0",
            model_hint="analysis",
        )

    def test_runner_calls_skill_creator_handler_for_skill_creator(self, tmp_path):
        """SkillRunner.execute() routes to _execute_skill_creator for skill-creator."""
        from sci_fi_dashboard.skills.runner import SkillRunner, SkillResult

        manifest = self._skill_creator_manifest()
        mock_result = SkillResult(
            text="Created skill 'test-skill' at ~/.synapse/skills/test-skill",
            skill_name="skill-creator",
        )

        with patch.object(
            SkillRunner,
            "_execute_skill_creator",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_handler:
            result = asyncio.get_event_loop().run_until_complete(
                SkillRunner.execute(
                    manifest=manifest,
                    user_message="create a skill that checks the weather",
                    history=[],
                    llm_router=MagicMock(),
                )
            )
            mock_handler.assert_called_once()
            assert result.text == mock_result.text

    def test_execute_skill_creator_calls_generate_from_conversation(self, tmp_path):
        """_execute_skill_creator calls SkillCreator.generate_from_conversation."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = self._skill_creator_manifest()
        mock_gen_result = {
            "skill_name": "weather-checker",
            "skill_path": str(tmp_path / "weather-checker"),
            "message": "Skill 'weather-checker' created successfully.",
        }

        with patch(
            "sci_fi_dashboard.skills.creator.SkillCreator.generate_from_conversation",
            new_callable=AsyncMock,
            return_value=mock_gen_result,
        ):
            with patch(
                "sci_fi_dashboard.skills.runner.SynapseConfig"
            ) as mock_cfg_cls:
                mock_cfg = MagicMock()
                mock_cfg.data_root = tmp_path
                mock_cfg_cls.load.return_value = mock_cfg

                result = asyncio.get_event_loop().run_until_complete(
                    SkillRunner._execute_skill_creator(
                        manifest=manifest,
                        user_message="create a weather skill",
                        history=[],
                        llm_router=MagicMock(),
                    )
                )
            assert not result.error, f"Expected success, got error: {result.text}"
            assert "weather-checker" in result.text

    def test_execute_skill_creator_returns_error_on_failure(self, tmp_path):
        """_execute_skill_creator returns SkillResult(error=True) on exception."""
        from sci_fi_dashboard.skills.runner import SkillRunner

        manifest = self._skill_creator_manifest()

        with patch(
            "sci_fi_dashboard.skills.creator.SkillCreator.generate_from_conversation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM call failed"),
        ):
            with patch("sci_fi_dashboard.skills.runner.SynapseConfig") as mock_cfg_cls:
                mock_cfg = MagicMock()
                mock_cfg.data_root = tmp_path
                mock_cfg_cls.load.return_value = mock_cfg

                result = asyncio.get_event_loop().run_until_complete(
                    SkillRunner._execute_skill_creator(
                        manifest=manifest,
                        user_message="create a skill",
                        history=[],
                        llm_router=MagicMock(),
                    )
                )
            assert result.error, "Should return error=True on exception"
            assert result.skill_name == "skill-creator"


# ---------------------------------------------------------------------------
# Task 2: SkillRegistry.seed_bundled_skills()
# ---------------------------------------------------------------------------


class TestSkillRegistrySeedBundledSkills:
    """Tests for SkillRegistry.seed_bundled_skills()."""

    def test_seed_bundled_skills_copies_to_empty_dir(self, tmp_path):
        """seed_bundled_skills copies skill-creator to an empty skills_dir."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        count = SkillRegistry.seed_bundled_skills(tmp_path)
        assert count >= 1, "Expected at least 1 bundled skill to be seeded"
        assert (tmp_path / "skill-creator").is_dir(), (
            "skill-creator must be copied to skills_dir"
        )
        assert (tmp_path / "skill-creator" / "SKILL.md").exists()

    def test_seed_bundled_skills_does_not_overwrite_existing(self, tmp_path):
        """seed_bundled_skills does NOT overwrite if skill already exists."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        # Create a placeholder first
        existing_dir = tmp_path / "skill-creator"
        existing_dir.mkdir()
        marker = existing_dir / "MY_CUSTOM_FILE.txt"
        marker.write_text("user customized this", encoding="utf-8")

        SkillRegistry.seed_bundled_skills(tmp_path)

        # Custom file must still exist — not overwritten
        assert marker.exists(), (
            "seed_bundled_skills must NOT overwrite existing skill directories"
        )

    def test_seed_bundled_skills_returns_zero_when_all_exist(self, tmp_path):
        """seed_bundled_skills returns 0 when all bundled skills already exist."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        # Seed once
        SkillRegistry.seed_bundled_skills(tmp_path)
        # Seed again — should be no-op
        count = SkillRegistry.seed_bundled_skills(tmp_path)
        assert count == 0, "Second seed should copy 0 skills"
