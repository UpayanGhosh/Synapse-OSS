"""Middleware and authentication dependencies."""

import collections
import hmac
import logging
import os
import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Body Size Limit (H-12)
# ---------------------------------------------------------------------------
MAX_BODY_SIZE = 1_048_576  # 1 MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large (limit: 1MB)"},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Rate Limiting (H-04)
# ---------------------------------------------------------------------------
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60  # seconds
_rate_limit_store: dict[str, collections.deque] = {}


def _check_rate_limit(request: Request) -> None:
    """Sliding-window rate limiter. Raises 429 if exceeded."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = collections.deque()
    dq = _rate_limit_store[client_ip]
    # Evict expired entries
    while dq and dq[0] < now - RATE_LIMIT_WINDOW:
        dq.popleft()
    if len(dq) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded (60 requests/minute). Try again later.",
        )
    dq.append(now)


# ---------------------------------------------------------------------------
# Gateway Auth Guard (H-02)
# ---------------------------------------------------------------------------


def _expected_gateway_token() -> str:
    env_token = os.environ.get("SYNAPSE_GATEWAY_TOKEN")
    if env_token is not None:
        return env_token.strip()

    try:
        from synapse_config import SynapseConfig  # noqa: PLC0415

        _cfg = SynapseConfig.load()
        token = _cfg.gateway.get("token", "")
    except Exception as exc:
        logger.warning("Failed to load gateway auth config", exc_info=exc)
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    return str(token or "").strip()


def _require_gateway_auth(request: Request) -> None:
    """
    Dependency that enforces SYNAPSE_GATEWAY_TOKEN on sensitive endpoints.
    Reads token from Authorization header (Bearer) or x-api-key header.
    Uses hmac.compare_digest for timing-safe comparison.
    """
    expected = _expected_gateway_token()
    if not expected:
        return  # No token configured — skip auth (dev mode)
    provided = ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:]
    if not provided:
        provided = request.headers.get("x-api-key", "")
    if not provided or not hmac.compare_digest(str(provided), str(expected)):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Bridge Token Validation
# ---------------------------------------------------------------------------


def validate_bridge_token(request: Request) -> None:
    # C-03: Use hmac.compare_digest for timing-safe token comparison
    bridge_token = os.environ.get("WHATSAPP_BRIDGE_TOKEN")
    if bridge_token:
        provided = request.headers.get("x-bridge-token") or ""
        if not hmac.compare_digest(str(provided), str(bridge_token)):
            raise HTTPException(status_code=401, detail="Invalid bridge token")


def validate_api_key(request: Request) -> None:
    """Validates the gateway token for protected endpoints."""
    # C-03: Use hmac.compare_digest for timing-safe token comparison
    api_key = _expected_gateway_token()
    if api_key:
        provided = request.headers.get("x-api-key") or ""
        if not hmac.compare_digest(str(provided), str(api_key)):
            raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Loopback-Only Guard for Dashboard (DASH-04)
# ---------------------------------------------------------------------------
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DASHBOARD_PREFIXES = ("/dashboard", "/static/dashboard")


class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    """Restrict /dashboard and /static/dashboard/ to loopback-only access.

    Returns 403 for any request from a non-loopback IP to dashboard routes.
    This is defense-in-depth — the server already binds to 127.0.0.1 by default.
    """

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in _DASHBOARD_PREFIXES):
            client_host = request.client.host if request.client else ""
            if client_host not in LOOPBACK_HOSTS:
                return JSONResponse(
                    {"detail": "Dashboard restricted to localhost"},
                    status_code=403,
                )
        return await call_next(request)
