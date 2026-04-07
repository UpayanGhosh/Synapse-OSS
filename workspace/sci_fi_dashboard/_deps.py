"""
sci_fi_dashboard/_deps.py — Shared singleton registry for the skill architecture phase.

This stub exposes the singletons needed by the skill system (Plans 01-04).
The full _deps.py with all gateway singletons lives in the main codebase and
will be merged back during wave integration.

Singletons managed here:
    skill_registry  — SkillRegistry instance (set during lifespan startup)
    skill_router    — SkillRouter instance (set during lifespan startup)
    skill_watcher   — SkillWatcher instance (started/stopped in lifespan)

All three are None until the skill system is initialised. Callers must guard:
    if deps.skill_router is not None:
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.skills.registry import SkillRegistry
    from sci_fi_dashboard.skills.router import SkillRouter
    from sci_fi_dashboard.skills.watcher import SkillWatcher

# ---------------------------------------------------------------------------
# Phase 1 (v2.0): Skill Architecture (optional)
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.skills.registry import SkillRegistry as _SkillRegistry
    from sci_fi_dashboard.skills.router import SkillRouter as _SkillRouter
    from sci_fi_dashboard.skills.watcher import SkillWatcher as _SkillWatcher
    from sci_fi_dashboard.skills.runner import SkillRunner as _SkillRunner

    _SKILL_SYSTEM_AVAILABLE = True
except ImportError:
    _SKILL_SYSTEM_AVAILABLE = False

# Singletons — initialized in lifespan if skill system is available.
# Set to None on init failure (non-fatal: server starts normally).
skill_registry: "SkillRegistry | None" = None
skill_router: "SkillRouter | None" = None
skill_watcher: "SkillWatcher | None" = None
