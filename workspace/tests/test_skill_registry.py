"""
tests/test_skill_registry.py — Unit tests for SkillRegistry, SkillWatcher, and GET /skills endpoint.

Covers:
  - SkillRegistry.scan() discovers valid skills at init
  - SkillRegistry with empty dir returns no skills
  - SkillRegistry.get_skill() by name
  - SkillRegistry.reload() picks up new skill
  - SkillRegistry.reload() removes deleted skill
  - SkillRegistry thread safety (RLock)
  - SkillWatcher triggers registry.reload() on file events
  - GET /skills endpoint returns correct JSON shape
  - GET /skills when registry is not initialized
"""

from __future__ import annotations

import textwrap
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers for creating temporary skill directories
# ---------------------------------------------------------------------------

def _make_skill(tmp_path: Path, name: str, version: str = "1.0.0") -> Path:
    """Create a minimal valid skill directory under tmp_path."""
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        textwrap.dedent(f"""\
            ---
            name: {name}
            description: A test skill called {name}
            version: {version}
            ---
            Instructions for {name}.
        """),
        encoding="utf-8",
    )
    return skill_dir


# ---------------------------------------------------------------------------
# TestSkillRegistry — core registry behaviour
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_scan_discovers_valid_skills(self, tmp_path):
        """SkillRegistry constructed with 2 valid skill dirs -> list_skills() returns 2 manifests."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        _make_skill(tmp_path, "alpha")
        _make_skill(tmp_path, "beta")

        registry = SkillRegistry(tmp_path)
        skills = registry.list_skills()

        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"alpha", "beta"}

    def test_scan_empty_dir_returns_no_skills(self, tmp_path):
        """SkillRegistry with empty dir -> list_skills() returns []."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        registry = SkillRegistry(tmp_path)
        assert registry.list_skills() == []

    def test_get_skill_returns_correct_manifest(self, tmp_path):
        """SkillRegistry.get_skill('alpha') returns the SkillManifest for alpha."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        _make_skill(tmp_path, "alpha")
        registry = SkillRegistry(tmp_path)

        manifest = registry.get_skill("alpha")
        assert manifest is not None
        assert manifest.name == "alpha"
        assert manifest.version == "1.0.0"

    def test_get_skill_missing_returns_none(self, tmp_path):
        """SkillRegistry.get_skill('missing') returns None when not loaded."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        registry = SkillRegistry(tmp_path)
        assert registry.get_skill("missing") is None

    def test_reload_picks_up_new_skill(self, tmp_path):
        """After reload(), a newly added skill directory is discovered."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        _make_skill(tmp_path, "alpha")
        registry = SkillRegistry(tmp_path)
        assert len(registry.list_skills()) == 1

        # Add a second skill
        _make_skill(tmp_path, "beta")
        registry.reload()

        assert len(registry.list_skills()) == 2
        assert registry.get_skill("beta") is not None

    def test_reload_removes_deleted_skill(self, tmp_path):
        """After reload(), a skill whose directory was deleted is removed from the registry."""
        from sci_fi_dashboard.skills.registry import SkillRegistry
        import shutil

        _make_skill(tmp_path, "alpha")
        _make_skill(tmp_path, "beta")
        registry = SkillRegistry(tmp_path)
        assert len(registry.list_skills()) == 2

        # Delete one skill directory
        shutil.rmtree(tmp_path / "alpha")
        registry.reload()

        assert len(registry.list_skills()) == 1
        assert registry.get_skill("alpha") is None
        assert registry.get_skill("beta") is not None

    def test_reload_is_thread_safe(self, tmp_path):
        """Concurrent reload() calls do not corrupt registry state (RLock protection)."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        for i in range(5):
            _make_skill(tmp_path, f"skill-{i:02d}")

        registry = SkillRegistry(tmp_path)

        errors: list[Exception] = []

        def _reload():
            try:
                registry.reload()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_reload) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(registry.list_skills()) == 5

    def test_list_skills_sorted_by_name(self, tmp_path):
        """list_skills() returns manifests sorted alphabetically by name."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        for name in ("zebra", "apple", "mango"):
            _make_skill(tmp_path, name)

        registry = SkillRegistry(tmp_path)
        names = [s.name for s in registry.list_skills()]
        assert names == sorted(names)

    def test_skills_dir_property(self, tmp_path):
        """registry.skills_dir returns the path passed to the constructor."""
        from sci_fi_dashboard.skills.registry import SkillRegistry

        registry = SkillRegistry(tmp_path)
        assert registry.skills_dir == tmp_path


# ---------------------------------------------------------------------------
# TestSkillWatcher — filesystem watcher triggers reload
# ---------------------------------------------------------------------------


class TestSkillWatcher:
    def test_watcher_triggers_reload_on_file_create(self, tmp_path):
        """SkillWatcher.start() then creating a SKILL.md triggers registry.reload() within 3s."""
        from sci_fi_dashboard.skills.watcher import SkillWatcher
        from sci_fi_dashboard.skills.registry import SkillRegistry

        mock_registry = MagicMock(spec=SkillRegistry)
        watcher = SkillWatcher(tmp_path, mock_registry, debounce_seconds=0.1)

        try:
            watcher.start()
            # Give watcher a moment to initialise
            time.sleep(0.2)

            # Create a new SKILL.md — should trigger reload
            skill_dir = tmp_path / "new-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: new-skill\ndescription: New\nversion: 1.0.0\n---\n",
                encoding="utf-8",
            )

            # Wait up to 3s for reload to be called
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if mock_registry.reload.called:
                    break
                time.sleep(0.1)

            assert mock_registry.reload.called, "reload() was not triggered within 3s"
        finally:
            watcher.stop()

    def test_watcher_stop_does_not_raise(self, tmp_path):
        """SkillWatcher.stop() on a started watcher does not raise."""
        from sci_fi_dashboard.skills.watcher import SkillWatcher

        mock_registry = MagicMock()
        watcher = SkillWatcher(tmp_path, mock_registry, debounce_seconds=0.1)
        watcher.start()
        time.sleep(0.1)
        # Should not raise
        watcher.stop()

    def test_watcher_stop_before_start_does_not_raise(self, tmp_path):
        """SkillWatcher.stop() before start() does not raise."""
        from sci_fi_dashboard.skills.watcher import SkillWatcher

        mock_registry = MagicMock()
        watcher = SkillWatcher(tmp_path, mock_registry)
        watcher.stop()  # Should not raise


# ---------------------------------------------------------------------------
# TestSkillsEndpoint — GET /skills FastAPI endpoint
# ---------------------------------------------------------------------------


class TestSkillsEndpoint:
    def test_skills_endpoint_returns_loaded_skills(self, tmp_path):
        """GET /skills returns 200 with 2 skills when registry has 2 manifests."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from sci_fi_dashboard.routes import skills as skills_route
        from sci_fi_dashboard.skills.schema import SkillManifest
        from sci_fi_dashboard.skills.registry import SkillRegistry
        from sci_fi_dashboard import _deps as deps

        app = FastAPI()
        app.include_router(skills_route.router)

        _make_skill(tmp_path, "alpha")
        _make_skill(tmp_path, "beta")

        real_registry = SkillRegistry(tmp_path)

        with patch.object(deps, "skill_registry", real_registry, create=True):
            client = TestClient(app)
            resp = client.get("/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["skills"]) == 2
        # Verify shape of each item
        for item in data["skills"]:
            assert "name" in item
            assert "description" in item
            assert "version" in item
            assert "author" in item

    def test_skills_endpoint_registry_not_initialized(self):
        """GET /skills returns 200 with count 0 when registry is None."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from sci_fi_dashboard.routes import skills as skills_route
        from sci_fi_dashboard import _deps as deps

        app = FastAPI()
        app.include_router(skills_route.router)

        with patch.object(deps, "skill_registry", None, create=True):
            client = TestClient(app)
            resp = client.get("/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["skills"] == []
        assert data.get("status") == "skill_system_not_initialized"
