"""
Skill schema definitions — SkillManifest dataclass and SkillValidationError.

Defines the data model for skill metadata loaded from SKILL.md files.
Every skill in ~/.synapse/skills/ must have a SKILL.md with valid YAML frontmatter
matching this schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Required fields that every SKILL.md must declare
REQUIRED_FIELDS: set[str] = {"name", "description", "version"}

# Expected skill directory structure (per SKILL-01):
#   skill-name/
#     SKILL.md        (required — YAML frontmatter + instructions)
#     scripts/        (optional — executable scripts)
#     references/     (optional — reference documents)
#     assets/         (optional — static assets: images, templates, etc.)
OPTIONAL_SUBDIRS = ("scripts", "references", "assets")


class SkillValidationError(ValueError):
    """Raised when a SKILL.md file fails validation.

    Attributes
    ----------
    skill_path : str
        Path to the skill directory that failed validation.
    missing_fields : list[str]
        List of required field names that were absent.
    """

    def __init__(self, skill_path: str, missing_fields: list[str], extra_msg: str = "") -> None:
        self.skill_path = skill_path
        self.missing_fields = missing_fields
        self.extra_msg = extra_msg
        super().__init__(str(self))

    def __str__(self) -> str:
        base = f"Invalid SKILL.md at {self.skill_path}"
        if self.missing_fields:
            base += f": missing required fields: {', '.join(self.missing_fields)}"
        if self.extra_msg:
            base += f". {self.extra_msg}"
        return base


@dataclass(frozen=True)
class SkillManifest:
    """Parsed and validated metadata from a skill's SKILL.md file.

    Required fields (must be in YAML frontmatter):
        name        — unique skill identifier, lowercase-hyphenated
        description — human-readable description, used for routing
        version     — semver string (e.g. "1.0.0")

    Optional fields:
        author      — skill author name or handle
        triggers    — explicit trigger phrases for exact-match routing bypass
        model_hint  — preferred LLM role ("code", "analysis", "casual", etc.)
        permissions — declared capabilities (e.g. ["filesystem:write", "network:fetch"])
        instructions — markdown body below YAML frontmatter (the skill's system prompt)
        path        — resolved absolute path to the skill directory
        entry_point — optional pre-processing entrypoint: "scripts/skill.py:function_name"
                      Used by SkillRunner to call a function before the LLM call.
                      Format: relative path from skill directory : function name
        cloud_safe  — True (default) = skill makes no external cloud calls and is safe in any
                      hemisphere. False = skill calls external cloud APIs; it is blocked in the
                      Vault (spicy) hemisphere to enforce zero cloud-leakage.
        enabled     — False = skill is skipped during scan_directory and never enters the
                      registry. Allows users to disable a skill without deleting it.
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
    entry_point: str = ""
    cloud_safe: bool = True
    # True  = skill is safe to run in any hemisphere (no external cloud calls)
    # False = skill calls external cloud APIs; blocked in Vault (spicy) hemisphere
    enabled: bool = True
    # False = skill is skipped during scan_directory; never enters the registry
