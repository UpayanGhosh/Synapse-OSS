"""
sci_fi_dashboard/_deps.py — Shared singleton registry stub for skill architecture phase.

This is a minimal stub scoped to the 01-skill-architecture plans. The full
_deps.py (with all gateway singletons) lives in the main codebase and will be
merged back. This stub only exposes the attributes needed by the skills subsystem.

Attributes:
    skill_registry: SkillRegistry | None
        Set to a SkillRegistry instance during application startup.
        None until the skill system is initialised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.skills.registry import SkillRegistry

# Module-level singleton reference — set by lifespan / startup handler.
skill_registry: "SkillRegistry | None" = None
