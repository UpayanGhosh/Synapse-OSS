"""
SkillRegistry — thread-safe registry of loaded SkillManifest objects.

Provides scan (initial load), reload (hot-reload), list_skills, and get_skill.
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

    Scans skills_dir at construction time. Call reload() to pick up changes
    (typically triggered by SkillWatcher on filesystem events).
    """

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._skills: dict[str, SkillManifest] = {}
        self._lock = threading.RLock()
        self.scan()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Initial scan — load all valid skills from skills_dir."""
        manifests = SkillLoader.scan_directory(self._skills_dir)
        with self._lock:
            self._skills = {m.name: m for m in manifests}
        names = sorted(self._skills)
        logger.info(
            "[Skills] Loaded %d skill(s): %s",
            len(names),
            ", ".join(names) if names else "(none)",
        )

    def reload(self) -> None:
        """Re-scan skills_dir, add new, remove deleted, update changed."""
        new_manifests = SkillLoader.scan_directory(self._skills_dir)
        new_by_name = {m.name: m for m in new_manifests}

        with self._lock:
            old_names = set(self._skills)
            new_names = set(new_by_name)

            added = new_names - old_names
            removed = old_names - new_names
            updated = {
                n for n in old_names & new_names
                if new_by_name[n] != self._skills[n]
            }

            self._skills = new_by_name

        if added or removed or updated:
            logger.info(
                "[Skills] Hot-reload: +%d added, -%d removed, ~%d updated",
                len(added),
                len(removed),
                len(updated),
            )
        else:
            logger.debug("[Skills] Hot-reload: no changes detected")

    def list_skills(self) -> list[SkillManifest]:
        """Return all loaded skill manifests, sorted by name."""
        with self._lock:
            return sorted(self._skills.values(), key=lambda s: s.name)

    def get_skill(self, name: str) -> SkillManifest | None:
        """Return a single skill by name, or None."""
        with self._lock:
            return self._skills.get(name)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir
