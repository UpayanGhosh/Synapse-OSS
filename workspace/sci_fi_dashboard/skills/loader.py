"""
skills/loader.py — SkillLoader: discover and parse skill directories.

Provides SkillLoader.load_skill() for parsing a single skill directory and
SkillLoader.scan_directory() for discovering all valid skills under a root.

Security mitigations:
- scan_directory() caps at 500 subdirectories (DoS guard, T-01-02).
- load_skill() rejects SKILL.md files larger than 100 KB (T-01-02).
- YAML parsing wrapped in try/except; raw exceptions never escape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import yaml

from sci_fi_dashboard.skills.schema import (
    REQUIRED_FIELDS,
    SkillManifest,
    SkillValidationError,
)

logger = logging.getLogger(__name__)

# Maximum number of skill directories scanned per call (DoS mitigation).
_MAX_SKILLS = 500

# Maximum allowed size of SKILL.md in bytes (100 KB).
_MAX_SKILL_MD_BYTES = 100 * 1024


class SkillLoader:
    """Discovers and parses skill directories, producing SkillManifest objects.

    All methods are class methods — no instance state is required.
    """

    @classmethod
    def load_skill(cls, skill_dir: Path) -> SkillManifest:
        """Parse a skill directory and return a validated SkillManifest.

        Args:
            skill_dir: Path to the skill directory (must contain SKILL.md).

        Returns:
            A fully populated SkillManifest with all parsed fields.

        Raises:
            SkillValidationError: If SKILL.md is missing, exceeds the size
                limit, has invalid YAML, or is missing required frontmatter
                fields.
        """
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            raise SkillValidationError(
                str(skill_dir),
                [],
                "SKILL.md not found",
            )

        # Size guard (T-01-02)
        if skill_md.stat().st_size > _MAX_SKILL_MD_BYTES:
            raise SkillValidationError(
                str(skill_dir),
                [],
                f"SKILL.md exceeds {_MAX_SKILL_MD_BYTES // 1024} KB size limit",
            )

        raw = skill_md.read_text(encoding="utf-8")

        # Parse YAML frontmatter delimited by "---" lines.
        frontmatter: dict = {}
        body: str = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                yaml_block = parts[1]
                body = parts[2].lstrip("\n")
                try:
                    parsed = yaml.safe_load(yaml_block)
                    if isinstance(parsed, dict):
                        frontmatter = parsed
                    # safe_load can return None for empty block — keep {}
                except yaml.YAMLError as exc:
                    raise SkillValidationError(
                        str(skill_dir),
                        [],
                        f"Invalid YAML in SKILL.md: {exc}",
                    ) from exc

        # Validate required fields.
        missing = sorted(f for f in REQUIRED_FIELDS if not frontmatter.get(f))
        if missing:
            raise SkillValidationError(str(skill_dir), missing)

        def _str(key: str) -> str:
            return str(frontmatter.get(key, "") or "")

        def _list(key: str) -> list:
            val = frontmatter.get(key, [])
            if isinstance(val, list):
                return [str(v) for v in val]
            return []

        return SkillManifest(
            name=_str("name"),
            description=_str("description"),
            version=_str("version"),
            author=_str("author"),
            triggers=_list("triggers"),
            model_hint=_str("model_hint"),
            permissions=_list("permissions"),
            instructions=body,
            path=skill_dir.resolve(),
        )

    @classmethod
    def scan_directory(cls, root: Path) -> list[SkillManifest]:
        """Scan a directory for skill subdirectories and return valid manifests.

        Invalid skill directories are skipped with a logged warning rather than
        raising — this lets the caller load all valid skills even if one is
        malformed.

        Args:
            root: Root directory containing skill subdirectories.

        Returns:
            List of SkillManifest objects sorted by name. Returns [] if root
            does not exist or contains no valid skill directories.
        """
        if not root.exists() or not root.is_dir():
            return []

        subdirs = [p for p in root.iterdir() if p.is_dir()]

        # DoS guard: cap at _MAX_SKILLS directories.
        if len(subdirs) > _MAX_SKILLS:
            logger.warning(
                "scan_directory: found %d subdirectories under %s; "
                "capping at %d (DoS mitigation).",
                len(subdirs),
                root,
                _MAX_SKILLS,
            )
            subdirs = subdirs[:_MAX_SKILLS]

        manifests: list[SkillManifest] = []
        for subdir in subdirs:
            try:
                manifest = cls.load_skill(subdir)
                manifests.append(manifest)
            except SkillValidationError as exc:
                logger.warning("Skipping invalid skill at %s: %s", subdir, exc)

        manifests.sort(key=lambda m: m.name)
        return manifests
