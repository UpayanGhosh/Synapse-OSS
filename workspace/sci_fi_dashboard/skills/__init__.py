"""
skills — Synapse-OSS skill system package.

Provides SkillManifest dataclass, SkillValidationError exception, and
SkillLoader for discovering and validating skill directories.
"""

from sci_fi_dashboard.skills.schema import SkillManifest, SkillValidationError
from sci_fi_dashboard.skills.loader import SkillLoader

__all__ = ["SkillManifest", "SkillValidationError", "SkillLoader"]
