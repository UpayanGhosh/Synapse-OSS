"""
Tests for SkillManifest schema, SkillValidationError, and SkillLoader.

Covers:
- Task 1: SkillManifest dataclass fields and SkillValidationError exception
- Task 2: SkillLoader.load_skill() and SkillLoader.scan_directory()
"""

from __future__ import annotations

import os
import sys

# Ensure workspace is on path when running from workspace/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import textwrap
from pathlib import Path

import pytest
from sci_fi_dashboard.skills.loader import SkillLoader
from sci_fi_dashboard.skills.schema import (
    OPTIONAL_SUBDIRS,
    REQUIRED_FIELDS,
    SkillManifest,
    SkillValidationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_dir(
    tmp_path: Path,
    name: str = "my-skill",
    description: str = "A test skill",
    version: str = "1.0.0",
    extra_yaml: str = "",
    body: str = "## Instructions\n\nDo something useful.",
    missing_skill_md: bool = False,
) -> Path:
    """Create a minimal skill directory with a SKILL.md file."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    if not missing_skill_md:
        frontmatter_lines = []
        if name is not None:
            frontmatter_lines.append(f"name: {name}")
        if description is not None:
            frontmatter_lines.append(f"description: {description}")
        if version is not None:
            frontmatter_lines.append(f"version: {version}")
        if extra_yaml:
            frontmatter_lines.append(extra_yaml)

        content = "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    return skill_dir


# ---------------------------------------------------------------------------
# Task 1: SkillManifest dataclass tests
# ---------------------------------------------------------------------------


class TestSkillManifest:
    """Tests for SkillManifest dataclass creation and fields."""

    def test_manifest_required_fields(self):
        """Test 1: SkillManifest with required fields creates a valid frozen dataclass."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
        )
        assert manifest.name == "test"
        assert manifest.description == "A test skill"
        assert manifest.version == "1.0.0"

    def test_manifest_optional_fields_have_defaults(self):
        """Test 2: SkillManifest has optional fields with correct defaults."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
        )
        assert manifest.author == ""
        assert manifest.triggers == []
        assert manifest.model_hint == ""
        assert manifest.permissions == []

    def test_manifest_instructions_field(self):
        """Test 3: SkillManifest.instructions stores the markdown body."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
            instructions="## Instructions\n\nDo something.",
        )
        assert manifest.instructions == "## Instructions\n\nDo something."

    def test_manifest_is_frozen(self):
        """SkillManifest is frozen — cannot set attributes after creation."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
        )
        with pytest.raises((AttributeError, TypeError)):
            manifest.name = "changed"  # type: ignore[misc]

    def test_manifest_path_field_default(self):
        """SkillManifest.path field has a default value (Path)."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
        )
        assert isinstance(manifest.path, Path)

    def test_manifest_custom_optional_fields(self):
        """Test 2 (extended): Optional fields can be set explicitly."""
        manifest = SkillManifest(
            name="test",
            description="A test skill",
            version="1.0.0",
            author="TestAuthor",
            triggers=["hey synapse", "hey bot"],
            model_hint="code",
            permissions=["filesystem:write"],
        )
        assert manifest.author == "TestAuthor"
        assert manifest.triggers == ["hey synapse", "hey bot"]
        assert manifest.model_hint == "code"
        assert manifest.permissions == ["filesystem:write"]


class TestSkillValidationError:
    """Tests for SkillValidationError exception."""

    def test_validation_error_is_value_error(self):
        """Test 4: SkillValidationError is a subclass of ValueError."""
        err = SkillValidationError("/path/to/skill", ["name", "version"])
        assert isinstance(err, ValueError)

    def test_validation_error_missing_fields_attribute(self):
        """Test 5: SkillValidationError stores a missing_fields list attribute."""
        err = SkillValidationError("/path/to/skill", ["name", "version"])
        assert err.missing_fields == ["name", "version"]

    def test_validation_error_skill_path_attribute(self):
        """SkillValidationError stores skill_path attribute."""
        err = SkillValidationError("/path/to/skill", ["name"])
        assert err.skill_path == "/path/to/skill"

    def test_validation_error_str_format(self):
        """SkillValidationError __str__ mentions missing fields and path."""
        err = SkillValidationError("/skills/my-skill", ["name", "description"])
        msg = str(err)
        assert "/skills/my-skill" in msg
        assert "name" in msg
        assert "description" in msg

    def test_validation_error_extra_msg(self):
        """SkillValidationError extra_msg appears in string output."""
        err = SkillValidationError("/skills/my-skill", [], "SKILL.md not found")
        assert "SKILL.md not found" in str(err)

    def test_validation_error_empty_missing_fields(self):
        """SkillValidationError with empty missing_fields list is valid."""
        err = SkillValidationError("/path/to/skill", [], "SKILL.md not found")
        assert err.missing_fields == []


class TestSchemaConstants:
    """Tests for module-level constants in schema.py."""

    def test_required_fields_contains_mandatory(self):
        """REQUIRED_FIELDS contains name, description, version."""
        assert "name" in REQUIRED_FIELDS
        assert "description" in REQUIRED_FIELDS
        assert "version" in REQUIRED_FIELDS

    def test_optional_subdirs_contains_all(self):
        """OPTIONAL_SUBDIRS contains scripts, references, and assets."""
        assert "scripts" in OPTIONAL_SUBDIRS
        assert "references" in OPTIONAL_SUBDIRS
        assert "assets" in OPTIONAL_SUBDIRS


# ---------------------------------------------------------------------------
# Task 2: SkillLoader tests
# ---------------------------------------------------------------------------


class TestSkillLoaderLoadSkill:
    """Tests for SkillLoader.load_skill()."""

    def test_load_valid_skill_returns_manifest(self, tmp_path: Path):
        """Test 1: load_skill on valid directory returns SkillManifest with all fields."""
        skill_dir = _make_skill_dir(tmp_path)
        manifest = SkillLoader.load_skill(skill_dir)
        assert isinstance(manifest, SkillManifest)
        assert manifest.name == "my-skill"
        assert manifest.description == "A test skill"
        assert manifest.version == "1.0.0"

    def test_load_missing_skill_md_raises(self, tmp_path: Path):
        """Test 2: load_skill on directory without SKILL.md raises SkillValidationError."""
        skill_dir = _make_skill_dir(tmp_path, missing_skill_md=True)
        with pytest.raises(SkillValidationError) as exc_info:
            SkillLoader.load_skill(skill_dir)
        assert "SKILL.md not found" in str(exc_info.value)

    def test_load_missing_name_raises_with_field(self, tmp_path: Path):
        """Test 3: SKILL.md missing 'name' raises SkillValidationError with missing_fields=['name']."""
        skill_dir = tmp_path / "no-name-skill"
        skill_dir.mkdir()
        content = "---\ndescription: A skill\nversion: 1.0.0\n---\nBody here."
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        with pytest.raises(SkillValidationError) as exc_info:
            SkillLoader.load_skill(skill_dir)
        assert "name" in exc_info.value.missing_fields

    def test_load_missing_multiple_required_fields(self, tmp_path: Path):
        """Test 4: SKILL.md missing multiple required fields lists all in SkillValidationError."""
        skill_dir = tmp_path / "bare-skill"
        skill_dir.mkdir()
        content = "---\nauthor: someone\n---\nBody here."
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        with pytest.raises(SkillValidationError) as exc_info:
            SkillLoader.load_skill(skill_dir)

        missing = exc_info.value.missing_fields
        assert "name" in missing
        assert "description" in missing
        assert "version" in missing

    def test_load_skill_parses_yaml_frontmatter_and_body(self, tmp_path: Path):
        """Test 5: SKILL.md with YAML between --- delimiters and body after second --- parses both."""
        skill_dir = tmp_path / "split-skill"
        skill_dir.mkdir()
        content = textwrap.dedent("""\
            ---
            name: split-skill
            description: Has both sections
            version: 2.0.0
            ---
            # Instructions

            This is the body.
        """)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.name == "split-skill"
        assert "Instructions" in manifest.instructions

    def test_load_skill_instructions_from_body(self, tmp_path: Path):
        """Test 6: load_skill correctly populates instructions from markdown body (not YAML)."""
        body = "## How to use\n\nCall me maybe."
        skill_dir = _make_skill_dir(tmp_path, name="body-skill", body=body)
        manifest = SkillLoader.load_skill(skill_dir)
        assert "Call me maybe" in manifest.instructions
        # YAML keys should NOT appear in instructions
        assert "name:" not in manifest.instructions

    def test_load_skill_path_is_resolved_absolute(self, tmp_path: Path):
        """Test 7: load_skill sets path field to the resolved absolute directory path."""
        skill_dir = _make_skill_dir(tmp_path)
        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.path.is_absolute()
        assert manifest.path == skill_dir.resolve()

    def test_load_skill_invalid_yaml_raises_validation_error(self, tmp_path: Path):
        """Test 10: SKILL.md with invalid YAML raises SkillValidationError (not yaml.YAMLError)."""
        skill_dir = tmp_path / "bad-yaml"
        skill_dir.mkdir()
        content = "---\n: invalid: yaml: {{{\n---\nBody here."
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        with pytest.raises(SkillValidationError):
            SkillLoader.load_skill(skill_dir)

    def test_load_skill_full_optional_fields(self, tmp_path: Path):
        """load_skill parses optional YAML fields into manifest."""
        skill_dir = tmp_path / "full-skill"
        skill_dir.mkdir()
        content = textwrap.dedent("""\
            ---
            name: full-skill
            description: A complete skill
            version: 1.2.3
            author: TestAuthor
            triggers:
              - hey synapse
              - quick help
            model_hint: code
            permissions:
              - filesystem:write
            ---
            Do the thing.
        """)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.author == "TestAuthor"
        assert manifest.triggers == ["hey synapse", "quick help"]
        assert manifest.model_hint == "code"
        assert manifest.permissions == ["filesystem:write"]


class TestSkillLoaderScanDirectory:
    """Tests for SkillLoader.scan_directory()."""

    def test_scan_valid_skills(self, tmp_path: Path):
        """Test 8: scan_directory returns list of SkillManifest for all valid subdirs."""
        _make_skill_dir(tmp_path, name="skill-a")
        _make_skill_dir(tmp_path, name="skill-b")
        results = SkillLoader.scan_directory(tmp_path)
        names = [m.name for m in results]
        assert "skill-a" in names
        assert "skill-b" in names

    def test_scan_empty_directory_returns_empty(self, tmp_path: Path):
        """Test 9: scan_directory on empty directory returns []."""
        results = SkillLoader.scan_directory(tmp_path)
        assert results == []

    def test_scan_skips_invalid_skills(self, tmp_path: Path):
        """Test 8 (partial): scan_directory skips invalid subdirs with logged warnings."""
        _make_skill_dir(tmp_path, name="good-skill")
        bad_dir = tmp_path / "bad-skill"
        bad_dir.mkdir()
        # No SKILL.md — should be skipped

        results = SkillLoader.scan_directory(tmp_path)
        assert len(results) == 1
        assert results[0].name == "good-skill"

    def test_scan_nonexistent_directory_returns_empty(self, tmp_path: Path):
        """scan_directory on a non-existent directory returns []."""
        results = SkillLoader.scan_directory(tmp_path / "does_not_exist")
        assert results == []

    def test_scan_returns_sorted_by_name(self, tmp_path: Path):
        """scan_directory returns manifests sorted by name."""
        _make_skill_dir(tmp_path, name="z-skill")
        _make_skill_dir(tmp_path, name="a-skill")
        _make_skill_dir(tmp_path, name="m-skill")
        results = SkillLoader.scan_directory(tmp_path)
        names = [m.name for m in results]
        assert names == sorted(names)

    def test_scan_skips_files_not_dirs(self, tmp_path: Path):
        """scan_directory skips plain files, only processes subdirectories."""
        _make_skill_dir(tmp_path, name="good-skill")
        (tmp_path / "not-a-dir.txt").write_text("hello")
        results = SkillLoader.scan_directory(tmp_path)
        assert len(results) == 1

    def test_scan_caps_at_500_directories(self, tmp_path: Path):
        """Test T-01-02: scan_directory caps at 500 skill directories (DoS mitigation)."""
        # Create 502 skill directories
        for i in range(502):
            skill_dir = tmp_path / f"skill-{i:04d}"
            skill_dir.mkdir()
            content = (
                f"---\nname: skill-{i:04d}\ndescription: Skill {i}\nversion: 1.0.0\n---\nBody."
            )
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        results = SkillLoader.scan_directory(tmp_path)
        assert len(results) <= 500

    def test_scan_skips_large_skill_md(self, tmp_path: Path):
        """Test T-01-02: scan_directory skips SKILL.md files larger than 100KB."""
        skill_dir = tmp_path / "huge-skill"
        skill_dir.mkdir()
        # Create a SKILL.md larger than 100KB
        large_body = "x" * (101 * 1024)
        content = f"---\nname: huge-skill\ndescription: Too big\nversion: 1.0.0\n---\n{large_body}"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        results = SkillLoader.scan_directory(tmp_path)
        assert len(results) == 0
