"""
skills/schema.py — SkillManifest dataclass and SkillValidationError exception.

Defines the data contract for parsed SKILL.md files. Every skill directory
produces a SkillManifest on successful load; invalid directories raise
SkillValidationError with a human-readable message listing missing fields.

Expected skill directory structure (per SKILL-01):
    skill-name/
        SKILL.md        (required — YAML frontmatter + instructions body)
        scripts/        (optional — executable scripts called by the skill)
        references/     (optional — reference documents for the skill)
        assets/         (optional — static assets: images, templates, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Required YAML frontmatter fields — absence of any raises SkillValidationError.
REQUIRED_FIELDS: frozenset[str] = frozenset({"name", "description", "version"})

# Optional subdirectory names that a skill directory may contain per SKILL-01.
# Expected skill directory structure (per SKILL-01):
#   skill-name/
#     SKILL.md        (required — YAML frontmatter + instructions)
#     scripts/        (optional — executable scripts)
#     references/     (optional — reference documents)
#     assets/         (optional — static assets: images, templates, etc.)
OPTIONAL_SUBDIRS: tuple[str, ...] = ("scripts", "references", "assets")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillValidationError(ValueError):
    """Raised when a SKILL.md file fails validation.

    Attributes:
        skill_path:     String path to the skill directory that failed.
        missing_fields: List of required field names that were absent.
    """

    def __init__(
        self,
        skill_path: str,
        missing_fields: list[str],
        extra_msg: str = "",
    ) -> None:
        self.skill_path = skill_path
        self.missing_fields = missing_fields
        self._extra_msg = extra_msg
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [f"Invalid SKILL.md at {self.skill_path}:"]
        if self.missing_fields:
            parts.append(f"missing required fields: {', '.join(self.missing_fields)}.")
        if self._extra_msg:
            parts.append(self._extra_msg)
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillManifest:
    """Parsed and validated representation of a SKILL.md file.

    Required fields (must be present in YAML frontmatter):
        name:           Unique skill identifier, lowercase-hyphenated.
        description:    Human-readable description used for routing.
        version:        Semver string (e.g. "1.0.0").

    Optional fields (default to empty/falsy values when absent):
        author:         Skill author name or handle.
        triggers:       Explicit trigger phrases for exact-match routing bypass.
        model_hint:     Preferred LLM role, e.g. "code", "analysis".
        permissions:    Capability grants, e.g. ["filesystem:write", "network:fetch"].
        instructions:   Full markdown body below the YAML frontmatter block.
        path:           Resolved absolute path to the skill directory on disk.
    """

    # Required
    name: str
    description: str
    version: str

    # Optional
    author: str = ""
    triggers: list[str] = field(default_factory=list)
    model_hint: str = ""
    permissions: list[str] = field(default_factory=list)
    instructions: str = ""
    path: Path = field(default_factory=lambda: Path("."))
