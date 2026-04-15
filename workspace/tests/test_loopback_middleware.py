"""
Tests for LoopbackOnlyMiddleware (DASH-04).

Verifies that:
- Requests from loopback IPs (127.0.0.1, ::1, localhost) can access /dashboard
- Requests from non-loopback IPs receive 403 for /dashboard routes
- Non-dashboard routes are not restricted
- /static/dashboard/* is also protected
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sci_fi_dashboard.middleware import LOOPBACK_HOSTS, LoopbackOnlyMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with LoopbackOnlyMiddleware and test routes."""
    app = FastAPI()
    app.add_middleware(LoopbackOnlyMiddleware)

    @app.get("/dashboard")
    async def dashboard():
        return {"page": "dashboard"}

    @app.get("/static/dashboard/synapse.js")
    async def static_asset():
        return {"file": "synapse.js"}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# DASH-04: Loopback-only enforcement
# ---------------------------------------------------------------------------


class TestLoopbackOnlyMiddleware:
    def test_loopback_ipv4_allowed(self):
        """A request with client.host == 127.0.0.1 is allowed to reach /dashboard (DASH-04)."""
        import asyncio

        middleware = LoopbackOnlyMiddleware(app=MagicMock())

        async def fake_call_next(req):
            return JSONResponse({"page": "dashboard"}, status_code=200)

        async def run_test():
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = "/dashboard"
            mock_request.client = MagicMock()
            mock_request.client.host = "127.0.0.1"
            return await middleware.dispatch(mock_request, fake_call_next)

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(run_test())
        finally:
            loop.close()
        assert response.status_code == 200

    def test_non_loopback_returns_403(self):
        """A non-loopback client IP results in 403 for /dashboard (DASH-04)."""
        app = _make_app()

        # Patch LoopbackOnlyMiddleware.dispatch to simulate non-loopback request
        original_dispatch = LoopbackOnlyMiddleware.dispatch

        async def patched_dispatch(self, request: Request, call_next):
            # Override the client host to simulate an external IP
            mock_client = MagicMock()
            mock_client.host = "192.168.1.100"
            request._client = mock_client  # type: ignore[attr-defined]
            return await original_dispatch(self, request, call_next)

        with (
            patch.object(LoopbackOnlyMiddleware, "dispatch", patched_dispatch),
            TestClient(app, raise_server_exceptions=True) as client,
        ):
            resp = client.get("/dashboard")

        assert resp.status_code == 403
        assert "Dashboard restricted to localhost" in resp.json().get("detail", "")

    def test_non_dashboard_route_unaffected(self):
        """Non-dashboard routes are accessible from any IP (DASH-04)."""
        app = _make_app()

        original_dispatch = LoopbackOnlyMiddleware.dispatch

        async def patched_dispatch(self, request: Request, call_next):
            mock_client = MagicMock()
            mock_client.host = "192.168.1.100"
            request._client = mock_client  # type: ignore[attr-defined]
            return await original_dispatch(self, request, call_next)

        with (
            patch.object(LoopbackOnlyMiddleware, "dispatch", patched_dispatch),
            TestClient(app, raise_server_exceptions=True) as client,
        ):
            resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_static_dashboard_also_protected(self):
        """/static/dashboard/* returns 403 for non-loopback IPs (DASH-04)."""
        app = _make_app()

        original_dispatch = LoopbackOnlyMiddleware.dispatch

        async def patched_dispatch(self, request: Request, call_next):
            mock_client = MagicMock()
            mock_client.host = "10.0.0.1"
            request._client = mock_client  # type: ignore[attr-defined]
            return await original_dispatch(self, request, call_next)

        with (
            patch.object(LoopbackOnlyMiddleware, "dispatch", patched_dispatch),
            TestClient(app, raise_server_exceptions=True) as client,
        ):
            resp = client.get("/static/dashboard/synapse.js")

        assert resp.status_code == 403
        assert "Dashboard restricted to localhost" in resp.json().get("detail", "")

    def test_ipv6_loopback_allowed(self):
        """IPv6 loopback address (::1) is accepted and can access /dashboard (DASH-04)."""
        import asyncio

        middleware = LoopbackOnlyMiddleware(app=MagicMock())

        async def fake_call_next(req):
            return Response("ok", status_code=200)

        async def run_test():
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = "/dashboard"
            mock_request.client = MagicMock()
            mock_request.client.host = "::1"  # IPv6 loopback

            return await middleware.dispatch(mock_request, fake_call_next)

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(run_test())
        finally:
            loop.close()

        assert response.status_code == 200

    def test_loopback_hosts_constant_contains_expected_values(self):
        """LOOPBACK_HOSTS frozenset contains all three loopback representations."""
        assert "127.0.0.1" in LOOPBACK_HOSTS
        assert "::1" in LOOPBACK_HOSTS
        assert "localhost" in LOOPBACK_HOSTS

    def test_dispatch_directly_with_mock_request(self):
        """Unit-test dispatch() directly using a mock Request — no HTTP overhead."""
        import asyncio

        middleware = LoopbackOnlyMiddleware(app=MagicMock())

        async def fake_call_next(req):
            return Response("ok", status_code=200)

        async def run_test():
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = "/dashboard"
            mock_request.client = MagicMock()
            mock_request.client.host = "203.0.113.5"  # External IP (TEST-NET-3)

            response = await middleware.dispatch(mock_request, fake_call_next)
            return response

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(run_test())
        finally:
            loop.close()
        assert response.status_code == 403
