"""Integration tests for GET /snapshots API endpoint."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Stub out sci_fi_dashboard._deps BEFORE importing the route module so that
# the heavy dependency chain (_deps → memory_engine → pyarrow) is never loaded.
# This is safe because the tests replace deps.snapshot_engine per-test anyway.
# ---------------------------------------------------------------------------
if "sci_fi_dashboard._deps" not in sys.modules:
    _stub = ModuleType("sci_fi_dashboard._deps")
    _stub.snapshot_engine = None
    _stub.consent_protocol = None
    _stub.pending_consents = {}
    sys.modules["sci_fi_dashboard._deps"] = _stub

from sci_fi_dashboard.middleware import _require_gateway_auth  # noqa: E402
from sci_fi_dashboard.routes.snapshots import router  # noqa: E402 (deps already stubbed)
from sci_fi_dashboard.snapshot_engine import SnapshotEngine  # noqa: E402

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _client(engine: SnapshotEngine | None) -> TestClient:
    """Build an isolated FastAPI app with auth bypassed and engine injected."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_require_gateway_auth] = lambda: None

    # Patch the deps reference already loaded inside routes.snapshots
    with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
        mock_deps.snapshot_engine = engine
        return TestClient(app), mock_deps


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotsAPI:
    """Tests for GET /snapshots."""

    def test_list_snapshots_empty(self, tmp_path):
        """Returns [] when no snapshots exist."""
        engine = SnapshotEngine(data_root=tmp_path, zone2_paths=("skills",), max_snapshots=10)

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[_require_gateway_auth] = lambda: None

        with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
            mock_deps.snapshot_engine = engine
            resp = TestClient(app).get("/snapshots")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_snapshots_returns_all_entries(self, tmp_path):
        """Returns all snapshots sorted newest-first."""
        skills_dir = tmp_path / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("name: test-skill\n")

        engine = SnapshotEngine(data_root=tmp_path, zone2_paths=("skills",), max_snapshots=10)
        engine.create("first change", "create_skill")
        engine.create("second change", "create_cron")

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[_require_gateway_auth] = lambda: None

        with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
            mock_deps.snapshot_engine = engine
            resp = TestClient(app).get("/snapshots")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["description"] == "second change"  # newest first
        assert data[1]["description"] == "first change"

    def test_list_snapshots_required_fields_present(self, tmp_path):
        """Each entry includes all required metadata fields."""
        engine = SnapshotEngine(data_root=tmp_path, zone2_paths=("skills",), max_snapshots=10)
        engine.create("my change", "create_skill")

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[_require_gateway_auth] = lambda: None

        with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
            mock_deps.snapshot_engine = engine
            resp = TestClient(app).get("/snapshots")

        data = resp.json()
        assert len(data) == 1
        for field in (
            "id",
            "timestamp",
            "description",
            "change_type",
            "zone2_paths",
            "pre_snapshot_id",
        ):
            assert field in data[0], f"Missing field: {field}"

    def test_list_snapshots_engine_not_initialized_returns_503(self):
        """Returns 503 when snapshot_engine is None (not yet initialized)."""
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[_require_gateway_auth] = lambda: None

        with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
            mock_deps.snapshot_engine = None
            resp = TestClient(app).get("/snapshots")

        assert resp.status_code == 503

    def test_list_snapshots_zone2_paths_is_json_list(self, tmp_path):
        """zone2_paths is serialized as a JSON list, not a tuple."""
        # Create Zone 2 content so SnapshotEngine includes the path in the snapshot
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("name: test-skill\n")

        engine = SnapshotEngine(data_root=tmp_path, zone2_paths=("skills",), max_snapshots=10)
        engine.create("change", "create_skill")

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[_require_gateway_auth] = lambda: None

        with patch("sci_fi_dashboard.routes.snapshots.deps") as mock_deps:
            mock_deps.snapshot_engine = engine
            resp = TestClient(app).get("/snapshots")

        data = resp.json()
        assert isinstance(data[0]["zone2_paths"], list)
        assert "skills" in data[0]["zone2_paths"]
