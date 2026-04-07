"""
Skill system public API — consolidated exports from all sub-modules.

Usage:
    from sci_fi_dashboard.skills import SkillManifest, SkillLoader, SkillRunner
"""

from sci_fi_dashboard.skills.schema import SkillManifest, SkillValidationError
from sci_fi_dashboard.skills.loader import SkillLoader
from sci_fi_dashboard.skills.registry import SkillRegistry
from sci_fi_dashboard.skills.watcher import SkillWatcher
from sci_fi_dashboard.skills.router import SkillRouter
from sci_fi_dashboard.skills.runner import SkillRunner, SkillResult

__all__ = [
    "SkillManifest",
    "SkillValidationError",
    "SkillLoader",
    "SkillRegistry",
    "SkillWatcher",
    "SkillRouter",
    "SkillRunner",
    "SkillResult",
]
