"""
health.py — Gateway health probing for Synapse-OSS.

Provides synchronous health probe helpers used by the onboarding wizard
after daemon install to confirm the gateway came up.

NOTE: This is a minimal implementation to support onboard.py.
      The full doctor/health CLI commands are implemented in Subtask 6.

Exports:
  probe_gateway_reachable()      Single HTTP probe; returns True on HTTP 200
  wait_for_gateway_reachable()   Polls probe until deadline or success
  health_command()               CLI-level health display (returns dict)
"""

from __future__ import annotations

import time

import httpx

# ---------------------------------------------------------------------------
# Conditional rich import
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

    _RICH_AVAILABLE = True
    _console = Console()
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False
    _console = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment,misc]


def _print(msg: str) -> None:
    if _RICH_AVAILABLE and _console is not None:
        _console.print(msg)
    else:
        import re  # noqa: PLC0415

        print(re.sub(r"\[/?[^\]]*\]", "", msg))


# ---------------------------------------------------------------------------
# probe_gateway_reachable
# ---------------------------------------------------------------------------


def probe_gateway_reachable(port: int = 8000, token: str | None = None) -> bool:
    """Single HTTP health probe against the gateway /health endpoint.

    Args:
        port:  Gateway port (default 8000).
        token: Optional bearer token for Authorization header.

    Returns:
        True if the gateway responds with HTTP 200, False on any error.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        r = httpx.get(
            f"http://127.0.0.1:{port}/health",
            headers=headers,
            timeout=3.0,
        )
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# wait_for_gateway_reachable
# ---------------------------------------------------------------------------


def wait_for_gateway_reachable(
    port: int = 8000,
    token: str | None = None,
    deadline_secs: float = 15.0,
) -> bool:
    """Poll the gateway until it responds or deadline expires.

    Args:
        port:          Gateway port.
        token:         Optional bearer token.
        deadline_secs: How long to wait before giving up (default 15s).

    Returns:
        True if gateway became reachable within the deadline, False on timeout.
    """
    deadline = time.time() + deadline_secs
    while time.time() < deadline:
        if probe_gateway_reachable(port=port, token=token):
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# health_command
# ---------------------------------------------------------------------------


def health_command(port: int = 8000, token: str | None = None) -> dict:
    """Call the gateway /health endpoint and display results.

    Args:
        port:  Gateway port.
        token: Optional bearer token.

    Returns:
        dict with health response data, or {"error": str} on failure.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        r = httpx.get(
            f"http://127.0.0.1:{port}/health",
            headers=headers,
            timeout=5.0,
        )
        is_json = r.headers.get("content-type", "").startswith("application/json")
        data: dict = r.json() if is_json else {"status": r.text}
        data["http_status"] = r.status_code

        if _RICH_AVAILABLE and Table is not None and _console is not None:
            tbl = Table(title=f"Gateway Health (port {port})")
            tbl.add_column("Key")
            tbl.add_column("Value")
            for k, v in data.items():
                tbl.add_row(str(k), str(v))
            _console.print(tbl)
        else:
            for k, v in data.items():
                print(f"{k}: {v}")

        return data

    except httpx.RequestError as exc:
        err = {"error": str(exc)}
        _print(f"[red]Gateway unreachable: {exc}[/]")
        return err
