"""
Tests for Phase 7: Bundled Skills Library.

Covers:
- SKILL-01: 10 bundled skills exist with valid SKILL.md
- SKILL-02: Bundled skills live in workspace/sci_fi_dashboard/skills/bundled/
- SKILL-03: Skills declare cloud_safe metadata; Vault hemisphere enforcement
- SKILL-04: User can disable any bundled skill without affecting others
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sci_fi_dashboard.skills.loader import SkillLoader
from sci_fi_dashboard.skills.registry import SkillRegistry
from sci_fi_dashboard.skills.runner import SkillRunner
from sci_fi_dashboard.skills.schema import SkillManifest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "sci_fi_dashboard" / "skills" / "bundled"

ALL_EXPECTED_SKILLS = [
    "skill-creator",
    "synapse.weather",
    "synapse.reminders",
    "synapse.notes",
    "synapse.translate",
    "synapse.summarize",
    "synapse.web-scrape",
    "synapse.news",
    "synapse.image-describe",
    "synapse.timer",
    "synapse.dictionary",
]

CLOUD_SAFE_FALSE_SKILLS = [
    "synapse.weather",
    "synapse.translate",
    "synapse.summarize",
    "synapse.web-scrape",
    "synapse.news",
    "synapse.image-describe",
    "synapse.dictionary",
]

CLOUD_SAFE_TRUE_SKILLS = [
    "synapse.reminders",
    "synapse.notes",
    "synapse.timer",
]


def _make_skill_md(name: str, *, enabled: bool = True, cloud_safe: bool = True) -> str:
    """Generate minimal valid SKILL.md content."""
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: Test skill\n"
        f"version: '1.0.0'\n"
        f"enabled: {str(enabled).lower()}\n"
        f"cloud_safe: {str(cloud_safe).lower()}\n"
        f"---\n\n"
        f"Test instructions for {name}\n"
    )


# ---------------------------------------------------------------------------
# SKILL-01, SKILL-02: Bundled skills exist
# ---------------------------------------------------------------------------


class TestBundledSkillsExist:
    """SKILL-01: 10 bundled skills at install. SKILL-02: Live in bundled/."""

    def test_bundled_directory_exists(self):
        assert BUNDLED_DIR.exists() and BUNDLED_DIR.is_dir()

    def test_all_ten_bundled_skills_present(self):
        for name in ALL_EXPECTED_SKILLS:
            d = BUNDLED_DIR / name
            assert d.is_dir(), f"Missing bundled skill directory: {name}"
        # At least 10 skill directories
        dirs = [d for d in BUNDLED_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
        assert len(dirs) >= 10

    def test_all_skill_md_files_parse(self):
        for name in ALL_EXPECTED_SKILLS:
            d = BUNDLED_DIR / name
            manifest = SkillLoader.load_skill(d)
            assert manifest.name, f"Empty name in {name}/SKILL.md"

    def test_all_synapse_skills_have_namespace_prefix(self):
        for name in ALL_EXPECTED_SKILLS:
            if not name.startswith("synapse."):
                continue
            manifest = SkillLoader.load_skill(BUNDLED_DIR / name)
            assert manifest.name.startswith(
                "synapse."
            ), f"{name} SKILL.md name '{manifest.name}' missing synapse. prefix"

    def test_directory_name_matches_skill_name(self):
        for name in ALL_EXPECTED_SKILLS:
            if not name.startswith("synapse."):
                continue
            manifest = SkillLoader.load_skill(BUNDLED_DIR / name)
            assert manifest.name == name, f"Directory '{name}' vs SKILL.md name '{manifest.name}'"


# ---------------------------------------------------------------------------
# SKILL-03: cloud_safe metadata + Vault enforcement
# ---------------------------------------------------------------------------


class TestCloudSafeMetadata:
    """SKILL-03: cloud_safe metadata and Vault hemisphere enforcement."""

    def test_cloud_safe_field_exists_on_manifest(self):
        m = SkillManifest(name="test", description="t", version="1.0")
        assert hasattr(m, "cloud_safe")
        assert m.cloud_safe is True  # default

    def test_cloud_safe_false_skills(self):
        for name in CLOUD_SAFE_FALSE_SKILLS:
            manifest = SkillLoader.load_skill(BUNDLED_DIR / name)
            assert manifest.cloud_safe is False, f"{name} should be cloud_safe=False"

    def test_cloud_safe_true_skills(self):
        for name in CLOUD_SAFE_TRUE_SKILLS:
            manifest = SkillLoader.load_skill(BUNDLED_DIR / name)
            assert manifest.cloud_safe is True, f"{name} should be cloud_safe=True"

    def test_vault_blocks_cloud_unsafe_skill(self):
        manifest = SkillManifest(
            name="test-unsafe",
            description="t",
            version="1.0",
            cloud_safe=False,
        )
        mock_router = MagicMock()
        mock_router.call = AsyncMock(return_value="should not reach")

        result = asyncio.get_event_loop().run_until_complete(
            SkillRunner.execute(
                manifest=manifest,
                user_message="hello",
                history=[],
                llm_router=mock_router,
                session_context={"session_type": "spicy"},
            )
        )

        assert "private mode" in result.text
        assert result.error is False
        mock_router.call.assert_not_called()

    def test_vault_allows_cloud_safe_skill(self):
        manifest = SkillManifest(
            name="test-safe",
            description="t",
            version="1.0",
            cloud_safe=True,
        )
        mock_router = MagicMock()
        mock_router.call = AsyncMock(return_value="test response")

        result = asyncio.get_event_loop().run_until_complete(
            SkillRunner.execute(
                manifest=manifest,
                user_message="hello",
                history=[],
                llm_router=mock_router,
                session_context={"session_type": "spicy"},
            )
        )

        assert "private mode" not in result.text
        mock_router.call.assert_called_once()

    def test_normal_session_allows_all_skills(self):
        manifest = SkillManifest(
            name="test-unsafe",
            description="t",
            version="1.0",
            cloud_safe=False,
        )
        mock_router = MagicMock()
        mock_router.call = AsyncMock(return_value="allowed response")

        result = asyncio.get_event_loop().run_until_complete(
            SkillRunner.execute(
                manifest=manifest,
                user_message="hello",
                history=[],
                llm_router=mock_router,
                session_context={"session_type": "safe"},
            )
        )

        assert "private mode" not in result.text
        mock_router.call.assert_called_once()


# ---------------------------------------------------------------------------
# SKILL-04: Skill disable
# ---------------------------------------------------------------------------


class TestSkillDisable:
    """SKILL-04: User can disable any bundled skill without affecting others."""

    def test_enabled_field_exists_on_manifest(self):
        m = SkillManifest(name="test", description="t", version="1.0")
        assert hasattr(m, "enabled")
        assert m.enabled is True  # default

    def test_disabled_skill_not_loaded(self, tmp_path):
        skill_dir = tmp_path / "disabled-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(_make_skill_md("disabled-skill", enabled=False))

        manifests = SkillLoader.scan_directory(tmp_path)
        names = [m.name for m in manifests]
        assert "disabled-skill" not in names

    def test_enabled_skill_loaded(self, tmp_path):
        skill_dir = tmp_path / "enabled-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(_make_skill_md("enabled-skill", enabled=True))

        manifests = SkillLoader.scan_directory(tmp_path)
        names = [m.name for m in manifests]
        assert "enabled-skill" in names

    def test_disabling_one_skill_does_not_affect_others(self, tmp_path):
        # Create two skills: one enabled, one disabled
        for name, enabled in [("alpha", True), ("beta", False)]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(_make_skill_md(name, enabled=enabled))

        manifests = SkillLoader.scan_directory(tmp_path)
        names = [m.name for m in manifests]
        assert "alpha" in names
        assert "beta" not in names


# ---------------------------------------------------------------------------
# Shadow warning (SKILL-01 supplement)
# ---------------------------------------------------------------------------


class TestShadowWarning:
    """Registry warns when user skill shadows bundled synapse.* skill."""

    def test_shadow_warning_logged(self, tmp_path, caplog):
        # Create two skills: 'weather' and 'synapse.weather'
        for name in ["weather", "synapse.weather"]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(_make_skill_md(name))

        with caplog.at_level(logging.WARNING):
            SkillRegistry(tmp_path)

        assert any(
            "shadows" in r.message.lower() for r in caplog.records
        ), "Expected shadow warning in logs"

    def test_no_shadow_warning_without_conflict(self, tmp_path, caplog):
        d = tmp_path / "synapse.weather"
        d.mkdir()
        (d / "SKILL.md").write_text(_make_skill_md("synapse.weather"))

        with caplog.at_level(logging.WARNING):
            SkillRegistry(tmp_path)

        assert not any("shadows" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# seed_bundled_skills (SKILL-01 supplement)
# ---------------------------------------------------------------------------


class TestSeedBundledSkills:
    """seed_bundled_skills copies bundled skills to user dir on first boot."""

    def test_seed_copies_all_bundled_skills(self, tmp_path):
        count = SkillRegistry.seed_bundled_skills(tmp_path)
        # Should copy all dirs from bundled/
        bundled_dirs = [d for d in BUNDLED_DIR.iterdir() if d.is_dir()]
        assert count == len(bundled_dirs)
        # Verify directories exist
        for d in bundled_dirs:
            assert (tmp_path / d.name).is_dir(), f"Missing seeded skill: {d.name}"

    def test_seed_does_not_overwrite(self, tmp_path):
        # Pre-create a skill dir with a marker file
        marker_dir = tmp_path / "synapse.weather"
        marker_dir.mkdir(parents=True)
        marker_file = marker_dir / "marker.txt"
        marker_file.write_text("do not overwrite")

        SkillRegistry.seed_bundled_skills(tmp_path)

        # Marker must survive — seed should not overwrite
        assert marker_file.exists()
        assert marker_file.read_text() == "do not overwrite"
