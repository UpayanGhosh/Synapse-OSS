"""
SkillLoader — parses and validates SKILL.md files from skill directories.

Supports the SKILL.md format:
  ---
  name: my-skill
  description: What this skill does
  version: 1.0.0
  ---

  ## Instructions

  Markdown body below the second --- becomes the instructions field.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from sci_fi_dashboard.skills.schema import (
    REQUIRED_FIELDS,
    SkillManifest,
    SkillValidationError,
)

logger = logging.getLogger(__name__)


class SkillLoader:
    """Loads and validates SKILL.md files from skill directories.

    Usage
    -----
    manifest = SkillLoader.load_skill(Path("/path/to/my-skill"))
    manifests = SkillLoader.scan_directory(Path("~/.synapse/skills"))
    """

    SKILL_FILENAME = "SKILL.md"

    @staticmethod
    def load_skill(skill_dir: Path) -> SkillManifest:
        """Parse SKILL.md from a directory, validate required fields, return SkillManifest.

        Parameters
        ----------
        skill_dir : Path
            Directory that should contain a SKILL.md file.

        Returns
        -------
        SkillManifest
            Validated manifest with all fields populated.

        Raises
        ------
        SkillValidationError
            If SKILL.md is missing, has invalid YAML, or is missing required fields.
        """
        skill_file = skill_dir / SkillLoader.SKILL_FILENAME

        if not skill_file.exists():
            raise SkillValidationError(str(skill_dir), [], "SKILL.md not found")

        # Read and parse YAML frontmatter + instructions body
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillValidationError(str(skill_dir), [], f"Cannot read SKILL.md: {exc}") from exc

        # Split on --- delimiters (standard YAML frontmatter)
        # Format: first line is ---, YAML content, second --- ends frontmatter, rest is body
        parts = content.split("---")
        if len(parts) < 3:
            raise SkillValidationError(
                str(skill_dir),
                [],
                "SKILL.md must have YAML frontmatter between --- delimiters",
            )

        yaml_section = parts[1]
        instructions_body = "---".join(parts[2:]).strip()

        # Parse YAML
        try:
            yaml_data = yaml.safe_load(yaml_section)
        except yaml.YAMLError as exc:
            raise SkillValidationError(
                str(skill_dir), [], f"Invalid YAML in SKILL.md: {exc}"
            ) from exc

        if not isinstance(yaml_data, dict):
            raise SkillValidationError(
                str(skill_dir), [], "SKILL.md YAML root must be a mapping (dict)"
            )

        # Validate required fields
        missing = [f for f in sorted(REQUIRED_FIELDS) if f not in yaml_data]
        if missing:
            raise SkillValidationError(str(skill_dir), missing)

        return SkillManifest(
            name=str(yaml_data["name"]),
            description=str(yaml_data["description"]),
            version=str(yaml_data["version"]),
            author=str(yaml_data.get("author", "")),
            triggers=list(yaml_data.get("triggers", [])),
            model_hint=str(yaml_data.get("model_hint", "")),
            permissions=list(yaml_data.get("permissions", [])),
            instructions=instructions_body,
            path=skill_dir.resolve(),
            entry_point=str(yaml_data.get("entry_point", "")),
            cloud_safe=bool(yaml_data.get("cloud_safe", True)),
            enabled=bool(yaml_data.get("enabled", True)),
        )

    @classmethod
    def scan_directory(cls, skills_root: Path) -> list[SkillManifest]:
        """Scan a directory for valid skill subdirectories, return all valid manifests.

        Invalid skill directories are skipped with a logged warning — they never
        crash the registry or prevent other skills from loading.

        Parameters
        ----------
        skills_root : Path
            Root directory containing skill subdirectories.

        Returns
        -------
        list[SkillManifest]
            Sorted list of all successfully loaded manifests (by skill name).
        """
        if not skills_root.exists() or not skills_root.is_dir():
            return []

        manifests: list[SkillManifest] = []

        for entry in sorted(skills_root.iterdir()):
            if not entry.is_dir():
                continue
            # Skip hidden directories (e.g. .git)
            if entry.name.startswith("."):
                continue

            try:
                manifest = cls.load_skill(entry)
                if not manifest.enabled:
                    logger.debug("[Skills] Skipping disabled skill '%s' at %s", manifest.name, entry)
                    continue
                manifests.append(manifest)
                logger.debug("[Skills] Loaded skill '%s' from %s", manifest.name, entry)
            except SkillValidationError as exc:
                logger.warning("[Skills] Skipping invalid skill at %s: %s", entry, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Skills] Unexpected error loading skill at %s: %s", entry, exc)

        return sorted(manifests, key=lambda s: s.name)
