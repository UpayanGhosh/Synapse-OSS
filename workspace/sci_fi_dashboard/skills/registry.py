"""
skills/registry.py — SkillRegistry: thread-safe singleton that manages loaded skills.

Provides:
  - SkillRegistry(skills_dir) — scan at init, call reload() to refresh
  - list_skills() — sorted list of all loaded SkillManifest objects
  - get_skill(name) — single manifest lookup by name, or None
  - reload() — re-scan skills_dir; adds new, removes deleted, updates changed

Security mitigations (T-01-07):
  - RLock acquired for all state-mutating operations
  - SkillLoader.scan_directory validates each SKILL.md before accepting (DoS guards inherited)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from sci_fi_dashboard.skills.loader import SkillLoader
from sci_fi_dashboard.skills.schema import SkillManifest

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Thread-safe registry of loaded skills.

    Designed as a long-lived singleton (one per process). Multiple concurrent
    calls to reload() are serialised via an RLock — partial reads from
    list_skills() / get_skill() also acquire the lock so consumers never see
    an inconsistent intermediate state.

    Usage::

        registry = SkillRegistry(Path("~/.synapse/skills").expanduser())
        # At startup all valid skills are already loaded.
        manifest = registry.get_skill("code-reviewer")
        # After new skill dropped on disk:
        registry.reload()
    """

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir: Path = skills_dir
        self._skills: dict[str, SkillManifest] = {}
        self._lock = threading.RLock()
        self.scan()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Initial scan — load all valid skills from skills_dir.

        Called automatically by __init__. Safe to call again to do a full
        reset (use reload() for incremental diff + logging).
        """
        manifests = SkillLoader.scan_directory(self._skills_dir)
        with self._lock:
            self._skills = {m.name: m for m in manifests}
        names = sorted(self._skills)
        logger.info("[Skills] Loaded %d skills: %s", len(names), names)

    def reload(self) -> None:
        """Re-scan skills_dir; add new skills, remove deleted ones, update changed ones.

        Logs a summary of changes. Thread-safe: acquires RLock before mutating state.
        Mitigation for T-01-04 (debounce handled by SkillWatcher before calling reload).
        """
        fresh_manifests = SkillLoader.scan_directory(self._skills_dir)
        fresh: dict[str, SkillManifest] = {m.name: m for m in fresh_manifests}

        with self._lock:
            old_names = set(self._skills)
            new_names = set(fresh)

            added = new_names - old_names
            removed = old_names - new_names

            self._skills = fresh

        if added or removed:
            logger.info(
                "[Skills] Hot-reload: +%d -%d (added=%s, removed=%s)",
                len(added),
                len(removed),
                sorted(added),
                sorted(removed),
            )
        else:
            logger.debug("[Skills] Hot-reload: no changes detected")

    def list_skills(self) -> list[SkillManifest]:
        """Return all loaded skill manifests, sorted by name."""
        with self._lock:
            return sorted(self._skills.values(), key=lambda s: s.name)

    def get_skill(self, name: str) -> SkillManifest | None:
        """Return a single skill by name, or None if not loaded."""
        with self._lock:
            return self._skills.get(name)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def skills_dir(self) -> Path:
        """The root directory this registry monitors."""
        return self._skills_dir

    # ------------------------------------------------------------------
    # Bundled skill seeding
    # ------------------------------------------------------------------

    @staticmethod
    def seed_bundled_skills(skills_dir: Path) -> int:
        """Copy bundled skills to the user's skills_dir if they don't already exist.

        Called once at startup (in api_gateway lifespan) so every user gets the
        built-in skills like skill-creator on their first run.

        Security: only copies from the ``bundled/`` directory inside this package.
        Never overwrites existing skill directories — user customisations are
        preserved (T-01-20).

        Args:
            skills_dir: Target directory (typically ~/.synapse/skills/).

        Returns:
            Number of bundled skills actually copied (0 if all already exist).
        """
        import shutil

        bundled_dir = Path(__file__).parent / "bundled"
        if not bundled_dir.exists():
            return 0

        seeded = 0
        for skill_src in sorted(bundled_dir.iterdir()):
            if not skill_src.is_dir():
                continue
            skill_dst = skills_dir / skill_src.name
            if skill_dst.exists():
                continue  # Preserve any user customisation — T-01-20
            shutil.copytree(skill_src, skill_dst)
            logger.info("[Skills] Seeded bundled skill: %s", skill_src.name)
            seeded += 1

        return seeded
