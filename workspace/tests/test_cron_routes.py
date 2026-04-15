"""
Tests for cron API routes (DASH-02) and dashboard DASH-05 compliance.

Covers:
- DASH-02: GET /api/cron/jobs returns correct JSON (empty, with data, no service)
- DASH-02: Auth enforcement on GET and POST endpoints
- DASH-05: No node_modules or npm references in dashboard static files
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sci_fi_dashboard.routes.cron import router

# ---------------------------------------------------------------------------
# Test app fixture
# ---------------------------------------------------------------------------
_TEST_TOKEN = "test-gateway-token-1234"


def _make_app(cron_service=None) -> FastAPI:
    """Create a minimal FastAPI app with the cron router included."""
    app = FastAPI()
    app.include_router(router)

    # Wire a cron_service (or None) onto app.state
    app.state.cron_service = cron_service

    return app


def _auth_headers() -> dict:
    """Return a valid gateway auth header using the test token."""
    return {"Authorization": f"Bearer {_TEST_TOKEN}"}


def _patched_auth():
    """Context manager: patch SynapseConfig.load so _require_gateway_auth uses our test token.

    _require_gateway_auth uses a lazy `from synapse_config import SynapseConfig` — we need
    to patch the class on the synapse_config module directly.
    """
    mock_cfg = MagicMock()
    mock_cfg.gateway = {"token": _TEST_TOKEN}
    return patch("synapse_config.SynapseConfig.load", return_value=mock_cfg)


# ---------------------------------------------------------------------------
# DASH-02: Job listing
# ---------------------------------------------------------------------------


class TestListCronJobs:
    def test_list_cron_jobs_empty(self):
        """GET /api/cron/jobs returns {jobs: [], count: 0} when service has no jobs (DASH-02)."""
        mock_svc = MagicMock()
        mock_svc.list.return_value = []
        app = _make_app(cron_service=mock_svc)

        with _patched_auth(), TestClient(app) as client:
            resp = client.get("/api/cron/jobs", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_list_cron_jobs_with_data(self):
        """GET /api/cron/jobs returns job data with count when service has jobs (DASH-02)."""
        # Build two plain-dict jobs (cron_service.py stores jobs as plain dicts)
        job1 = {"id": "job-aaa", "name": "daily-digest", "enabled": True}
        job2 = {"id": "job-bbb", "name": "weekly-report", "enabled": False}

        mock_svc = MagicMock()
        mock_svc.list.return_value = [job1, job2]
        app = _make_app(cron_service=mock_svc)

        with _patched_auth(), TestClient(app) as client:
            resp = client.get("/api/cron/jobs", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["jobs"]) == 2
        job_names = [j["name"] for j in data["jobs"]]
        assert "daily-digest" in job_names
        assert "weekly-report" in job_names

    def test_list_cron_jobs_no_service(self):
        """GET /api/cron/jobs returns {jobs: [], error: ...} when cron_service is None (DASH-02)."""
        app = _make_app(cron_service=None)

        with _patched_auth(), TestClient(app) as client:
            resp = client.get("/api/cron/jobs", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert "CronService not running" in data.get("error", "")

    def test_list_cron_jobs_requires_auth(self):
        """GET /api/cron/jobs without auth header returns 401 (DASH-02)."""
        mock_svc = MagicMock()
        mock_svc.list.return_value = []
        app = _make_app(cron_service=mock_svc)

        with _patched_auth(), TestClient(app) as client:
            resp = client.get("/api/cron/jobs")  # No auth header

        assert resp.status_code == 401

    def test_run_cron_job_requires_auth(self):
        """POST /api/cron/jobs/{id}/run without auth header returns 401 (DASH-02)."""
        mock_svc = MagicMock()
        mock_svc.run = AsyncMock(return_value={"status": "ok"})
        app = _make_app(cron_service=mock_svc)

        with _patched_auth(), TestClient(app) as client:
            resp = client.post("/api/cron/jobs/test-job/run")  # No auth header

        assert resp.status_code == 401

    def test_run_cron_job_with_auth(self):
        """POST /api/cron/jobs/{id}/run with valid auth succeeds (DASH-02)."""
        mock_svc = MagicMock()
        mock_svc.run = AsyncMock(return_value={"status": "ok", "job_id": "test-job"})
        app = _make_app(cron_service=mock_svc)

        with _patched_auth(), TestClient(app) as client:
            resp = client.post("/api/cron/jobs/test-job/run", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# DASH-05: No npm/node_modules in dashboard files
# ---------------------------------------------------------------------------


class TestDashboardNpmFree:
    def _dashboard_dir(self) -> str:
        here = os.path.dirname(__file__)
        return os.path.join(here, "..", "sci_fi_dashboard", "static", "dashboard")

    def test_index_html_no_node_modules(self):
        """index.html contains no node_modules references (DASH-05)."""
        path = os.path.join(self._dashboard_dir(), "index.html")
        assert os.path.exists(path), f"index.html not found at {path}"
        with open(path, encoding="utf-8") as _f:
            content = _f.read()
        assert "node_modules" not in content, "index.html references node_modules"

    def test_index_html_no_npm_script_tags(self):
        """index.html has no <script src=> pointing to local npm packages (DASH-05)."""
        path = os.path.join(self._dashboard_dir(), "index.html")
        with open(path, encoding="utf-8") as _f:
            content = _f.read()
        # Detect patterns like <script src="./node_modules/..." or <script src="/node_modules/..."
        import re

        npm_script = re.search(r'<script[^>]+src=["\'][^"\']*node_modules', content)
        assert npm_script is None, f"index.html has npm script tag: {npm_script}"

    def test_synapse_js_no_require_calls(self):
        """synapse.js has no CommonJS require() calls (DASH-05)."""
        path = os.path.join(self._dashboard_dir(), "synapse.js")
        assert os.path.exists(path), f"synapse.js not found at {path}"
        with open(path, encoding="utf-8") as _f:
            content = _f.read()
        assert (
            "require(" not in content
        ), "synapse.js contains require() — suggests CommonJS/npm bundle"

    def test_synapse_js_no_node_modules_imports(self):
        """synapse.js has no ES module imports from node_modules (DASH-05)."""
        path = os.path.join(self._dashboard_dir(), "synapse.js")
        with open(path, encoding="utf-8") as _f:
            content = _f.read()
        import re

        npm_import = re.search(r'import\s+.*from\s+["\'][^"\']*node_modules', content)
        assert npm_import is None, f"synapse.js has node_modules import: {npm_import}"
