"""
channel_steps.py — Per-channel credential collection and validation for the Synapse onboarding wizard.

Provides:
  - CHANNEL_LIST               : flat list of supported channel keys
  - validate_telegram_token()  : GET api.telegram.org/bot{token}/getMe → dict or ValueError
  - validate_discord_token()   : GET discord.com/api/v10/users/@me → dict or ValueError
  - validate_slack_tokens()    : prefix check + POST slack.com/api/auth.test → dict or ValueError
  - run_whatsapp_qr_flow()     : synchronous QR + scan flow using Baileys subprocess
  - setup_telegram()           : interactive / non-interactive token collection + validation
  - setup_discord()            : interactive / non-interactive token collection + validation
  - setup_slack()              : interactive / non-interactive token pair collection + validation
  - setup_whatsapp()           : interactive QR flow / non-interactive config-only

All network calls use httpx (sync). No asyncio. Designed to be tested independently.
"""

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import qrcode

# ---------------------------------------------------------------------------
# Conditional rich import — fall back to plain print if not installed
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False
    Console = None  # type: ignore[assignment,misc]
    Panel = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

CHANNEL_LIST: list[str] = ["whatsapp", "telegram", "discord", "slack"]

BRIDGE_PORT: int = 5010
BRIDGE_STARTUP_WAIT: float = 5.0  # seconds to wait after Popen before polling
QR_POLL_INTERVAL: float = 2.0
QR_TIMEOUT: float = 30.0
SCAN_TIMEOUT: float = 120.0
SCAN_POLL_INTERVAL: float = 3.0
QR_REFRESH_INTERVAL: float = 30.0  # re-render QR if string changes during polling


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def validate_telegram_token(token: str) -> dict:
    """
    Validate a Telegram bot token by calling api.telegram.org/bot{token}/getMe.

    Args:
        token: The Telegram bot token to validate.

    Returns:
        {"username": str, "id": int} on success.

    Raises:
        ValueError: On network error, 401 Unauthorized, or API-level failure.
    """
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10.0)
    except httpx.RequestError as exc:
        raise ValueError(f"Network error reaching Telegram API: {exc}") from exc

    if r.status_code == 401:
        raise ValueError(
            "Invalid Telegram token (401 Unauthorized).\n"
            "Get a valid token from @BotFather: https://t.me/BotFather"
        )

    data = r.json()
    if not data.get("ok"):
        raise ValueError(f"Telegram API error: {data.get('description', 'unknown')}")

    result = data.get("result", {})
    return {"username": result.get("username"), "id": result.get("id")}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


def validate_discord_token(token: str) -> dict:
    """
    Validate a Discord bot token by calling discord.com/api/v10/users/@me.

    The Authorization header MUST use the "Bot " prefix (capital B, space after)
    as required by the Discord API.

    Args:
        token: The Discord bot token to validate.

    Returns:
        {"username": str, "id": str} on success.

    Raises:
        ValueError: On network error, 401 Unauthorized, or non-2xx response.
    """
    try:
        r = httpx.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise ValueError(f"Network error reaching Discord API: {exc}") from exc

    if r.status_code == 401:
        raise ValueError(
            "Invalid Discord bot token (401 Unauthorized).\n"
            "Get token from: https://discord.com/developers/applications"
        )

    if not r.is_success:
        raise ValueError(f"Discord API error {r.status_code}: {r.text[:200]}")

    data = r.json()
    return {"username": data.get("username"), "id": data.get("id")}


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def validate_slack_tokens(bot_token: str, app_token: str) -> dict:
    """
    Validate Slack token pair: prefix check (fail-fast, no network) then auth.test.

    Step 1 (no network): prefix check.
      bot_token must start with 'xoxb-'.
      app_token must start with 'xapp-'.

    Step 2 (network): POST to slack.com/api/auth.test with the bot_token.
      (xapp- has no API validation endpoint.)

    Args:
        bot_token: Slack bot OAuth token. Must start with 'xoxb-'.
        app_token: Slack app-level token. Must start with 'xapp-'.

    Returns:
        {"team": str, "user": str, "bot_id": str} on success.

    Raises:
        ValueError: On prefix mismatch, network error, or auth.test failure.
    """
    # --- Step 1: Fail-fast prefix validation (no network) ---
    if not bot_token.startswith("xoxb-"):
        raise ValueError(
            f"Bot token must start with 'xoxb-', got: {bot_token[:12]!r}\n"
            "Find it at: Slack App → OAuth & Permissions → Bot User OAuth Token"
        )
    if not app_token.startswith("xapp-"):
        raise ValueError(
            f"App token must start with 'xapp-', got: {app_token[:12]!r}\n"
            "Create at: Slack App → Basic Information → App-Level Tokens (connections:write scope)"
        )

    # --- Step 2: auth.test for bot_token ---
    try:
        r = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise ValueError(f"Network error reaching Slack API: {exc}") from exc

    data = r.json()
    if not data.get("ok"):
        error = data.get("error", "unknown")
        if error == "invalid_auth":
            raise ValueError(
                "Slack bot token rejected (invalid_auth).\n"
                "Verify the xoxb- token in Slack App → OAuth & Permissions."
            )
        raise ValueError(f"Slack auth.test error: {error}")

    return {
        "team": data.get("team"),
        "user": data.get("user"),
        "bot_id": data.get("bot_id"),
    }


# ---------------------------------------------------------------------------
# WhatsApp QR flow
# ---------------------------------------------------------------------------


def run_whatsapp_qr_flow(
    bridge_dir: "str | Path",
    console: "Console | None" = None,
) -> bool:
    """
    Run the synchronous WhatsApp QR pairing flow using the Baileys bridge subprocess.

    Steps:
      1. Validate Node.js 18+ on PATH.
      2. Check if bridge is already running on BRIDGE_PORT — reuse if so.
      3. If not running: spawn via subprocess.Popen(['node', 'index.js']).
      4. Wait BRIDGE_STARTUP_WAIT seconds for bridge to initialise.
      5. Poll GET /qr until QR string available (QR_TIMEOUT deadline).
      6. Render QR as ASCII art via qrcode.QRCode.print_ascii().
      7. Poll GET /health until connectionState == 'connected' (SCAN_TIMEOUT deadline).
      8. Return True on success, False on timeout / logged_out.
      9. ALWAYS: terminate bridge in finally block (only if wizard started it).

    Windows QR fix: reconfigures stdout to UTF-8 before printing ASCII art.

    Args:
        bridge_dir: Path to the baileys-bridge directory containing index.js.
        console:    Optional Rich Console for styled output. Falls back to plain print.

    Returns:
        True if WhatsApp successfully paired (connectionState == 'connected').
        False on any failure, timeout, or if Node.js is missing/too old.
    """
    bridge_dir = Path(bridge_dir)

    def _print(msg: str) -> None:
        if console is not None and _RICH_AVAILABLE:
            console.print(msg)
        else:
            print(msg)

    # --- Step 1: Validate Node.js 18+ ---
    node_path = shutil.which("node")
    if not node_path:
        _print(
            "[red]Node.js is not installed or not on PATH.[/red]\n"
            "The Baileys WhatsApp bridge requires Node.js 18+.\n"
            "Install from: https://nodejs.org/en/download/"
        )
        return False

    result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
    version_str = result.stdout.strip().lstrip("v")  # e.g. "22.14.0"
    try:
        major = int(version_str.split(".")[0])
    except (ValueError, IndexError):
        _print(f"Could not parse Node.js version: {version_str!r}")
        return False

    if major < 18:
        _print(
            f"Node.js {version_str} found but Node.js 18+ is required.\n"
            "Upgrade from: https://nodejs.org/en/download/"
        )
        return False

    # --- Step 2: Check if bridge is already running ---
    proc = None
    bridge_was_started_by_wizard = False

    try:
        existing = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=3.0)
        if existing.status_code == 200:
            _print(f"[green]Reusing existing bridge on port {BRIDGE_PORT}.[/green]")
    except httpx.RequestError:
        # Bridge not running — start it
        _print(f"Starting Baileys bridge on port {BRIDGE_PORT}...")
        proc = subprocess.Popen(
            ["node", "index.js"],
            cwd=str(bridge_dir),
            env={
                **os.environ,
                "BRIDGE_PORT": str(BRIDGE_PORT),
                "PYTHON_WEBHOOK_URL": "http://127.0.0.1:8000/channels/whatsapp/webhook",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        bridge_was_started_by_wizard = True
        time.sleep(BRIDGE_STARTUP_WAIT)

    try:
        # --- Step 5: Poll GET /qr until available ---
        qr_deadline = time.monotonic() + QR_TIMEOUT
        qr_string: str | None = None
        while time.monotonic() < qr_deadline:
            try:
                qr_resp = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/qr", timeout=5.0)
                if qr_resp.status_code == 200:
                    candidate = qr_resp.json().get("qr")
                    if candidate:
                        qr_string = candidate
                        break
            except httpx.RequestError:
                pass
            time.sleep(QR_POLL_INTERVAL)

        if qr_string is None:
            _print(
                "[red]Timed out waiting for WhatsApp QR code "
                f"({QR_TIMEOUT:.0f}s). Is the bridge running?[/red]"
            )
            return False

        # --- Step 6: Render QR as ASCII art ---
        # Windows: reconfigure stdout to UTF-8 to prevent garbled box-drawing chars
        if sys.platform == "win32":
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

        qr_obj = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr_obj.add_data(qr_string)
        qr_obj.make(fit=True)
        f = io.StringIO()
        qr_obj.print_ascii(out=f, invert=True)
        f.seek(0)
        ascii_art = f.read()

        if console is not None and _RICH_AVAILABLE:
            console.print(
                Panel(
                    ascii_art,
                    title="SCAN WITH WHATSAPP",
                    subtitle="WhatsApp → Linked Devices → Link a Device",
                )
            )
        else:
            print("\n" + ascii_art)
            print("SCAN WITH WHATSAPP → Linked Devices → Link a Device")

        _print(
            f"Waiting for scan ({SCAN_TIMEOUT:.0f} second timeout)...\n"
            "Keep this window open until WhatsApp shows 'Linked device'."
        )

        # --- Step 7: Poll GET /health until connectionState == 'connected' ---
        scan_deadline = time.monotonic() + SCAN_TIMEOUT
        last_qr_string = qr_string
        last_qr_refresh = time.monotonic()

        while time.monotonic() < scan_deadline:
            try:
                health_resp = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=5.0)
                if health_resp.status_code == 200:
                    health_data = health_resp.json()
                    state = health_data.get("connectionState", "")

                    if state == "connected":
                        _print(
                            "[green]WhatsApp paired successfully![/green] "
                            "Your session is saved in baileys-bridge/auth_state/"
                        )
                        return True

                    if state == "logged_out":
                        _print(
                            "[red]WhatsApp reported 'logged_out' — "
                            "pairing was rejected or timed out on the phone.[/red]"
                        )
                        return False
            except httpx.RequestError:
                pass

            # QR refresh: re-render if bridge rotated the QR string
            now = time.monotonic()
            if now - last_qr_refresh >= QR_REFRESH_INTERVAL:
                try:
                    refresh_resp = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/qr", timeout=5.0)
                    if refresh_resp.status_code == 200:
                        new_qr = refresh_resp.json().get("qr")
                        if new_qr and new_qr != last_qr_string:
                            last_qr_string = new_qr
                            qr_obj2 = qrcode.QRCode(
                                error_correction=qrcode.constants.ERROR_CORRECT_L
                            )
                            qr_obj2.add_data(new_qr)
                            qr_obj2.make(fit=True)
                            f2 = io.StringIO()
                            qr_obj2.print_ascii(out=f2, invert=True)
                            f2.seek(0)
                            _print("\n[Refreshed QR]\n" + f2.read())
                except httpx.RequestError:
                    pass
                last_qr_refresh = now

            time.sleep(SCAN_POLL_INTERVAL)

        _print(
            f"[red]Timed out waiting for WhatsApp scan ({SCAN_TIMEOUT:.0f}s).[/red]\n"
            "You can run the wizard again, or scan the QR from the Synapse dashboard."
        )
        return False

    finally:
        # Always terminate the bridge if wizard started it
        if bridge_was_started_by_wizard and proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# setup_telegram()
# ---------------------------------------------------------------------------


def setup_telegram(non_interactive: bool = False) -> "dict | None":
    """
    Collect and validate a Telegram bot token.

    Interactive mode: prompts user via questionary. Skippable.
    Non-interactive mode: reads SYNAPSE_TELEGRAM_TOKEN env var. Returns None if absent.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.

    Returns:
        {"token": str} on success, None if skipped or validation fails.
    """
    console = Console() if _RICH_AVAILABLE else None

    def _print(msg: str) -> None:
        if console is not None:
            console.print(msg)
        else:
            print(msg)

    if non_interactive:
        token = os.environ.get("SYNAPSE_TELEGRAM_TOKEN", "").strip()
        if not token:
            return None
    else:
        # Lazy import — questionary not needed for non-interactive or unit tests
        try:
            import questionary  # type: ignore[import]
        except ImportError:
            _print(
                "[yellow]questionary not installed — cannot run interactive Telegram setup.[/yellow]"
            )
            return None

        choice = questionary.select("Telegram:", choices=["Configure", "Skip"]).ask()
        if choice != "Configure":
            return None

        token_raw = questionary.password("Enter Telegram bot token:").ask()
        if not token_raw:
            return None
        token = token_raw.strip()

    # Validate
    status_ctx = console.status("Validating Telegram token...") if console else None
    try:
        if status_ctx:
            with status_ctx:
                info = validate_telegram_token(token)
        else:
            _print("Validating Telegram token...")
            info = validate_telegram_token(token)
        _print(f"[green]Telegram OK[/green] — @{info.get('username')} (id={info.get('id')})")
        return {"token": token}
    except ValueError as exc:
        _print(f"[red]Telegram validation failed:[/red] {exc}")
        return None


# ---------------------------------------------------------------------------
# setup_discord()
# ---------------------------------------------------------------------------

_DISCORD_INTENT_INSTRUCTION = """\
ACTION REQUIRED — Discord MESSAGE_CONTENT Intent:
  1. Go to: https://discord.com/developers/applications
  2. Select your bot → Bot → Privileged Gateway Intents
  3. Enable: MESSAGE CONTENT INTENT
  Without this, the bot will receive empty messages and disable itself."""


def setup_discord(non_interactive: bool = False) -> "dict | None":
    """
    Collect and validate a Discord bot token. Shows MESSAGE_CONTENT intent instruction.

    Interactive mode: prompts user via questionary. Skippable.
    Non-interactive mode: reads SYNAPSE_DISCORD_TOKEN env var. Returns None if absent.

    After successful validation, always displays the MESSAGE_CONTENT intent instruction.
    In interactive mode, pauses for user confirmation.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.

    Returns:
        {"token": str, "allowed_channel_ids": list[int]} on success, None if skipped.
    """
    console = Console() if _RICH_AVAILABLE else None

    def _print(msg: str) -> None:
        if console is not None:
            console.print(msg)
        else:
            print(msg)

    if non_interactive:
        token = os.environ.get("SYNAPSE_DISCORD_TOKEN", "").strip()
        if not token:
            return None
        channel_ids: list[int] = []
        raw_ids = os.environ.get("SYNAPSE_DISCORD_CHANNEL_IDS", "").strip()
        if raw_ids:
            channel_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
    else:
        try:
            import questionary  # type: ignore[import]
        except ImportError:
            _print(
                "[yellow]questionary not installed — cannot run interactive Discord setup.[/yellow]"
            )
            return None

        choice = questionary.select("Discord:", choices=["Configure", "Skip"]).ask()
        if choice != "Configure":
            return None

        token_raw = questionary.password("Enter Discord bot token:").ask()
        if not token_raw:
            return None
        token = token_raw.strip()
        channel_ids = []

    # Validate
    status_ctx = console.status("Validating Discord token...") if console else None
    try:
        if status_ctx:
            with status_ctx:
                info = validate_discord_token(token)
        else:
            _print("Validating Discord token...")
            info = validate_discord_token(token)
        _print(f"[green]Discord OK[/green] — {info.get('username')} (id={info.get('id')})")
    except ValueError as exc:
        _print(f"[red]Discord validation failed:[/red] {exc}")
        return None

    # Always show MESSAGE_CONTENT intent instruction
    if console is not None and _RICH_AVAILABLE:
        console.print(
            Panel(
                _DISCORD_INTENT_INSTRUCTION,
                title="[bold yellow]ACTION REQUIRED[/bold yellow]",
                border_style="yellow",
            )
        )
    else:
        print(_DISCORD_INTENT_INSTRUCTION)

    if not non_interactive:
        try:
            import questionary  # type: ignore[import]

            questionary.press_any_key_to_continue("Press Enter when done...").ask()
        except (ImportError, Exception):
            input("Press Enter when done...")

        # Collect optional allowed_channel_ids in interactive mode
        try:
            import questionary  # type: ignore[import]

            raw = questionary.text(
                "Allowed channel IDs (comma-separated, or leave blank for all):"
            ).ask()
        except (ImportError, Exception):
            raw = input("Allowed channel IDs (comma-separated, or leave blank for all): ")

        if raw and raw.strip():
            channel_ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

    return {"token": token, "allowed_channel_ids": channel_ids}


# ---------------------------------------------------------------------------
# setup_slack()
# ---------------------------------------------------------------------------


def setup_slack(non_interactive: bool = False) -> "dict | None":
    """
    Collect and validate a Slack bot+app token pair.

    Interactive mode: prompts user via questionary. Skippable.
    Non-interactive mode: reads SYNAPSE_SLACK_BOT_TOKEN and SYNAPSE_SLACK_APP_TOKEN.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.

    Returns:
        {"bot_token": str, "app_token": str} on success, None if skipped or invalid.
    """
    console = Console() if _RICH_AVAILABLE else None

    def _print(msg: str) -> None:
        if console is not None:
            console.print(msg)
        else:
            print(msg)

    if non_interactive:
        bot_token = os.environ.get("SYNAPSE_SLACK_BOT_TOKEN", "").strip()
        app_token = os.environ.get("SYNAPSE_SLACK_APP_TOKEN", "").strip()
        if not bot_token or not app_token:
            return None
    else:
        try:
            import questionary  # type: ignore[import]
        except ImportError:
            _print(
                "[yellow]questionary not installed — cannot run interactive Slack setup.[/yellow]"
            )
            return None

        choice = questionary.select("Slack:", choices=["Configure", "Skip"]).ask()
        if choice != "Configure":
            return None

        _print(
            "Bot token: found in Slack App → OAuth & Permissions → Bot User OAuth Token\n"
            "App token: found in Slack App → Basic Information → App-Level Tokens\n"
            "          (must have connections:write scope)"
        )
        bot_raw = questionary.password("Enter Slack bot token (xoxb-...):").ask()
        if not bot_raw:
            return None
        bot_token = bot_raw.strip()

        app_raw = questionary.password("Enter Slack app token (xapp-...):").ask()
        if not app_raw:
            return None
        app_token = app_raw.strip()

    # Validate (prefix check first, then auth.test)
    status_ctx = console.status("Validating Slack tokens...") if console else None
    try:
        if status_ctx:
            with status_ctx:
                info = validate_slack_tokens(bot_token, app_token)
        else:
            _print("Validating Slack tokens...")
            info = validate_slack_tokens(bot_token, app_token)
        _print(
            f"[green]Slack OK[/green] — team={info.get('team')} "
            f"user={info.get('user')} bot_id={info.get('bot_id')}"
        )
        return {"bot_token": bot_token, "app_token": app_token}
    except ValueError as exc:
        _print(f"[red]Slack validation failed:[/red] {exc}")
        return None


# ---------------------------------------------------------------------------
# setup_whatsapp()
# ---------------------------------------------------------------------------


def setup_whatsapp(
    bridge_dir: "str | Path",
    non_interactive: bool = False,
) -> "dict | None":
    """
    Configure the WhatsApp channel.

    Interactive mode: runs the full QR pairing flow. Returns config dict if paired,
    None if skipped or flow failed.

    Non-interactive mode: WhatsApp QR cannot be automated. Returns the config dict
    immediately (enables the channel so it can be paired later at runtime) if the
    WHATSAPP_BRIDGE_TOKEN env var is set OR if the auth_state directory already exists
    (indicating a prior pairing). Otherwise returns the config dict with a note — the
    user can pair later via the running Synapse dashboard.

    Args:
        bridge_dir:       Path to the baileys-bridge directory.
        non_interactive:  If True, skip QR flow and return config without validation.

    Returns:
        {"enabled": True, "bridge_port": BRIDGE_PORT} on success or non-interactive,
        None if skipped (interactive) or flow failed.
    """
    console = Console() if _RICH_AVAILABLE else None

    def _print(msg: str) -> None:
        if console is not None:
            console.print(msg)
        else:
            print(msg)

    bridge_dir = Path(bridge_dir)

    if non_interactive:
        # In non-interactive mode, always return the config; QR is done at runtime.
        return {"enabled": True, "bridge_port": BRIDGE_PORT}

    # Interactive: skip gate
    try:
        import questionary  # type: ignore[import]
    except ImportError:
        _print(
            "[yellow]questionary not installed — cannot run interactive WhatsApp setup.[/yellow]"
        )
        return None

    choice = questionary.select("WhatsApp:", choices=["Configure (scan QR now)", "Skip"]).ask()
    if choice != "Configure (scan QR now)":
        return None

    _print("Starting WhatsApp QR pairing flow...")
    success = run_whatsapp_qr_flow(bridge_dir, console=console)

    if success:
        return {"enabled": True, "bridge_port": BRIDGE_PORT}
    return None
