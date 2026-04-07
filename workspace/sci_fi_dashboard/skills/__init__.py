"""
skills — Synapse-OSS skill system package.

Consolidated exports for all skill system classes from Plans 01-04.
Plans 02 and 03 ran in Wave 2 (parallel) and intentionally deferred __init__.py
updates to avoid write conflicts. This module consolidates all exports now that
all Wave 2 plans are complete.

Public API:
    SkillManifest       — frozen dataclass for parsed SKILL.md files
    SkillValidationError — raised when SKILL.md fails validation
    SkillLoader         — classmethods for loading/scanning skill directories
    SkillRegistry       — thread-safe singleton managing loaded skills
    SkillWatcher        — watchdog-based filesystem watcher with hot-reload
    SkillRouter         — embedding-based intent routing (two-stage matching)
    SkillRunner         — LLM execution engine with exception isolation
    SkillResult         — result dataclass returned by SkillRunner.execute()
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
