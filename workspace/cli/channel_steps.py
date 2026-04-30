"""
channel_steps.py — Per-channel credential collection and validation for the Synapse onboarding
wizard.

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

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

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
# Exceptions
# ---------------------------------------------------------------------------


class NodeJsMissingError(Exception):
    """Raised when Node.js 18+ is unavailable and auto-install could not resolve it.

    Auto-install via winget is attempted first. This exception is only raised when:
    - winget is not available and no node found, OR
    - winget installed/upgraded but PATH refresh still can't resolve node (restart needed), OR
    - version after upgrade is still < 18.

    The exception message always includes the next action for the user.
    """


# ---------------------------------------------------------------------------
# Node.js auto-installer
# ---------------------------------------------------------------------------

_NODE_KNOWN_PATHS_WIN = [
    r"C:\Program Files\nodejs\node.exe",
    r"C:\Program Files (x86)\nodejs\node.exe",
]


def _try_auto_install_nodejs(_print) -> bool:  # noqa: ANN001
    """Attempt to auto-install Node.js LTS via winget (Windows only).

    Prints progress messages via ``_print``. Returns True if winget exited 0,
    False otherwise. Does NOT update PATH — caller handles that.
    """
    if sys.platform != "win32":
        return False

    winget = shutil.which("winget")
    if not winget:
        return False

    _print("[cyan]Node.js not found — attempting auto-install via winget...[/cyan]")
    try:
        result = subprocess.run(
            [
                "winget",
                "install",
                "OpenJS.NodeJS.LTS",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            timeout=300,  # 5 minutes max for download + install
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _try_auto_upgrade_nodejs(_print) -> bool:  # noqa: ANN001
    """Attempt to upgrade Node.js to LTS via winget (Windows only).

    Returns True if winget exited 0, False otherwise.
    """
    if sys.platform != "win32":
        return False

    winget = shutil.which("winget")
    if not winget:
        return False

    _print("[cyan]Upgrading Node.js to LTS via winget...[/cyan]")
    try:
        result = subprocess.run(
            [
                "winget",
                "upgrade",
                "OpenJS.NodeJS.LTS",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            timeout=300,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _refresh_node_path() -> str | None:
    """Re-check for node on PATH and well-known install locations after auto-install.

    If found in a known location that isn't on PATH yet, injects the directory
    into os.environ["PATH"] so subsequent subprocess calls work without restart.

    Returns the resolved node path, or None if still not found.
    """
    # Re-check PATH first (install may have already been in PATH)
    node = shutil.which("node")
    if node:
        return node

    # Check known Windows install locations
    for candidate in _NODE_KNOWN_PATHS_WIN:
        if os.path.isfile(candidate):
            node_dir = os.path.dirname(candidate)
            os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "")
            return candidate

    return None


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

CHANNEL_LIST: list[str] = ["whatsapp", "telegram", "discord", "slack"]

BRIDGE_PORT: int = 5010
BRIDGE_STARTUP_WAIT: float = 8.0  # seconds to wait after Popen before polling
QR_POLL_INTERVAL: float = 2.0
QR_TIMEOUT: float = 60.0  # Baileys can take 30-60s to connect to WA servers on first run
SCAN_TIMEOUT: float = 120.0
SCAN_POLL_INTERVAL: float = 3.0
QR_REFRESH_INTERVAL: float = 30.0  # re-render QR if string changes during polling

# Authoritative source: DmPolicy StrEnum in channels/security.py.
# Keep this list in sync with that enum.
_DM_POLICY_CHOICES: list[str] = ["pairing", "allowlist", "open", "disabled"]
_DM_POLICY_DEFAULT: str = "pairing"


def _prompt_dm_policy(
    channel_name: str,
    non_interactive: bool,
    env_var_name: str,
    _print,
) -> str:
    """Prompt the user to select a DM security policy for a channel.

    Non-interactive: reads the env var (falls back to 'pairing').
    Interactive: uses questionary.select().

    Returns one of _DM_POLICY_CHOICES (always a valid string).
    """
    if non_interactive:
        value = os.environ.get(env_var_name, _DM_POLICY_DEFAULT)
        if value not in _DM_POLICY_CHOICES:
            _print(
                f"[yellow]Warning: {env_var_name}={value!r} is not valid "
                f"({', '.join(_DM_POLICY_CHOICES)}). Defaulting to '{_DM_POLICY_DEFAULT}'.[/yellow]"
            )
            return _DM_POLICY_DEFAULT
        return value

    try:
        import questionary  # type: ignore[import]
    except ImportError:
        return _DM_POLICY_DEFAULT

    result = questionary.select(
        f"{channel_name} DM security policy:",
        choices=_DM_POLICY_CHOICES,
        default=_DM_POLICY_DEFAULT,
    ).ask()
    return result if result is not None else _DM_POLICY_DEFAULT


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
      6. Bridge prints QR directly to terminal via qrcode-terminal (Node.js).
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

    # --- Step 1: Validate Node.js 18+ (auto-install if missing) ---
    node_path = shutil.which("node")
    if not node_path:
        installed = _try_auto_install_nodejs(_print)
        if not installed:
            raise NodeJsMissingError(
                "Node.js is not installed and auto-install failed (winget not available).\n"
                "Install Node.js 18+ manually from: https://nodejs.org/en/download/\n"
                "Then re-run: .\\synapse_onboard.bat"
            )
        # winget succeeded — refresh PATH before continuing
        node_path = _refresh_node_path()
        if not node_path:
            raise NodeJsMissingError(
                "Node.js was installed but requires a terminal restart to take effect.\n"
                "Please close this window and re-run: .\\synapse_onboard.bat"
            )
        _print("[green]Node.js installed successfully.[/green]")

    result = subprocess.run([node_path, "--version"], capture_output=True, text=True, timeout=5)
    version_str = result.stdout.strip().lstrip("v")  # e.g. "22.14.0"
    try:
        major = int(version_str.split(".")[0])
    except (ValueError, IndexError) as exc:
        raise NodeJsMissingError(f"Could not parse Node.js version: {version_str!r}") from exc

    if major < 18:
        _print(f"[yellow]Node.js {version_str} found — upgrading to LTS (18+ required)...[/yellow]")
        upgraded = _try_auto_upgrade_nodejs(_print)
        if not upgraded:
            raise NodeJsMissingError(
                f"Node.js {version_str} is too old (18+ required) and auto-upgrade failed.\n"
                "Upgrade manually from: https://nodejs.org/en/download/\n"
                "Then re-run: .\\synapse_onboard.bat"
            )
        # Re-resolve node path after upgrade
        node_path = _refresh_node_path() or node_path
        result = subprocess.run([node_path, "--version"], capture_output=True, text=True, timeout=5)
        version_str = result.stdout.strip().lstrip("v")
        try:
            major = int(version_str.split(".")[0])
        except (ValueError, IndexError):
            major = 0
        if major < 18:
            raise NodeJsMissingError(
                "Node.js upgrade completed but version is still below 18. "
                "Please restart your terminal and re-run: .\\synapse_onboard.bat"
            )
        _print(f"[green]Node.js upgraded to {version_str}.[/green]")

    # --- Step 2: Install bridge dependencies if node_modules is missing ---
    node_modules = bridge_dir / "node_modules"
    if not node_modules.exists():
        _print("[cyan]Installing Baileys bridge dependencies (npm install)...[/cyan]")
        npm = shutil.which("npm")
        if not npm:
            # npm ships with Node.js — fall back to sibling of resolved node
            npm = str(Path(node_path).parent / "npm")
        npm_result = subprocess.run(
            [npm, "install", "--prefer-offline"],
            cwd=str(bridge_dir),
            timeout=300,
        )
        if npm_result.returncode != 0:
            raise NodeJsMissingError(
                f"npm install failed in the WhatsApp bridge at {bridge_dir}.\n"
                "Check your internet connection and re-run: synapse onboard"
            )
        _print("[green]Bridge dependencies installed.[/green]")

    # --- Step 3: Clear stale auth_state so Baileys generates a fresh QR ---
    # During onboarding we always want a new QR scan. If auth_state/ exists from a
    # previous attempt, Baileys will try to restore the old session instead of emitting
    # a QR event — the terminal stays blank. Wipe it unconditionally before pairing.
    import shutil as _shutil  # noqa: PLC0415

    from cli.install_home import whatsapp_state_dir  # noqa: PLC0415

    state_dir = whatsapp_state_dir()
    auth_state_dir = state_dir / "auth_state"
    media_cache_dir = state_dir / "media_cache"
    if auth_state_dir.exists():
        _shutil.rmtree(auth_state_dir, ignore_errors=True)
        _print("[dim]Cleared previous auth state — generating fresh QR...[/dim]")

    # --- Step 4: Check if bridge is already running ---
    proc = None
    bridge_was_started_by_wizard = False

    try:
        existing = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=3.0)
        if existing.status_code == 200:
            _print(f"[green]Reusing existing bridge on port {BRIDGE_PORT}.[/green]")
    except httpx.RequestError:
        # Bridge not running — start it.
        # stdout=None: bridge output (including the QR rendered by qrcode-terminal) flows
        # directly to this terminal so the user sees it immediately without any delay.
        # stderr=PIPE: captured for crash diagnostics only.
        _print(f"[dim]Starting Baileys bridge on port {BRIDGE_PORT}...[/dim]")
        proc = subprocess.Popen(
            ["node", "index.js"],
            cwd=str(bridge_dir),
            env={
                **os.environ,
                "BRIDGE_PORT": str(BRIDGE_PORT),
                "SYNAPSE_AUTH_DIR": str(auth_state_dir),
                "MEDIA_CACHE_DIR": str(media_cache_dir),
                "PYTHON_WEBHOOK_URL": "http://127.0.0.1:8000/channels/whatsapp/webhook",
            },
            stdout=None,  # inherit — QR prints itself to terminal via qrcode-terminal
            stderr=subprocess.PIPE,
        )
        bridge_was_started_by_wizard = True

        # Poll /health until bridge responds (up to BRIDGE_STARTUP_WAIT seconds)
        startup_deadline = time.monotonic() + BRIDGE_STARTUP_WAIT
        bridge_ready = False
        while time.monotonic() < startup_deadline:
            if proc.poll() is not None:
                break  # process exited — crash handled below
            try:
                httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=1.0)
                bridge_ready = True
                break
            except httpx.RequestError:
                time.sleep(0.5)

        if not bridge_ready and proc.poll() is not None:
            stderr_out = proc.stderr.read().decode(errors="replace").strip()
            _print(
                "[red]Baileys bridge crashed on startup.[/red]\n"
                + (stderr_out if stderr_out else "(no output captured)")
            )
            return False
            # Bridge is slow to start but still running — continue to QR wait

    try:
        # --- Step 5: Wait for QR to appear (bridge prints it directly to terminal) ---
        # Poll /health until connectionState becomes 'awaiting_qr' or 'connected'.
        _print("[dim]Waiting for WhatsApp QR code — it will appear above when ready...[/dim]")
        qr_deadline = time.monotonic() + QR_TIMEOUT
        got_qr = False

        while time.monotonic() < qr_deadline:
            # Detect bridge crash mid-wait
            if proc is not None and proc.poll() is not None:
                stderr_out = proc.stderr.read().decode(errors="replace").strip()
                _print(
                    "[red]Baileys bridge crashed while connecting.[/red]\n"
                    + (stderr_out if stderr_out else "(no output captured)")
                )
                return False

            try:
                health_resp = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=5.0)
                if health_resp.status_code == 200:
                    state = health_resp.json().get("connectionState", "")
                    if state == "awaiting_qr":
                        got_qr = True
                        break
                    if state == "connected":
                        # Already authenticated (saved session)
                        _print("[green]WhatsApp session restored — already connected.[/green]")
                        return True
            except httpx.RequestError:
                pass
            time.sleep(QR_POLL_INTERVAL)

        if not got_qr:
            if proc is not None and proc.poll() is not None:
                stderr_out = proc.stderr.read().decode(errors="replace").strip()
                _print(
                    "[red]Baileys bridge crashed.[/red]\n"
                    + (stderr_out if stderr_out else "(no output captured)")
                )
            else:
                _print(
                    "[red]Timed out waiting for WhatsApp QR code "
                    f"({QR_TIMEOUT:.0f}s).\n"
                    "This usually means the bridge couldn't reach WhatsApp servers.\n"
                    "Check your internet connection and try again.[/red]"
                )
            return False

        # QR is now visible in the terminal (printed by qrcode-terminal in index.js)
        _print(
            "\n[bold cyan]Scan the QR code above with WhatsApp:[/bold cyan]\n"
            "  WhatsApp → ⋮ Menu → Linked Devices → Link a Device\n"
            f"[dim]Waiting up to {SCAN_TIMEOUT:.0f}s for scan...[/dim]"
        )

        # --- Step 6: Poll /health until connectionState == 'connected' ---
        scan_deadline = time.monotonic() + SCAN_TIMEOUT
        while time.monotonic() < scan_deadline:
            try:
                health_resp = httpx.get(f"http://127.0.0.1:{BRIDGE_PORT}/health", timeout=5.0)
                if health_resp.status_code == 200:
                    state = health_resp.json().get("connectionState", "")
                    if state == "connected":
                        _print(
                            "[green]WhatsApp paired successfully![/green] "
                            f"Your session is saved in {auth_state_dir}"
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
            time.sleep(SCAN_POLL_INTERVAL)

        _print(
            f"[red]Timed out waiting for WhatsApp scan ({SCAN_TIMEOUT:.0f}s).[/red]\n"
            "Run the wizard again to get a fresh QR code."
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


def setup_telegram(
    non_interactive: bool = False,
    prompter: "object | None" = None,
) -> "dict | None":
    """
    Collect and validate a Telegram bot token.

    Interactive mode: prompts user via questionary (or via prompter if provided). Skippable.
    Non-interactive mode: reads SYNAPSE_TELEGRAM_TOKEN env var. Returns None if absent.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.
        prompter:        Optional WizardPrompter instance. When provided, all interactive
                         prompts are delegated to it instead of calling questionary directly.

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
    elif prompter is not None:
        # Delegate to WizardPrompter
        choice = prompter.select("Telegram:", choices=["Configure", "Skip"])  # type: ignore[attr-defined]
        if choice != "Configure":
            return None
        token = prompter.text("Enter Telegram bot token:", password=True)  # type: ignore[attr-defined]
        if not token:
            return None
        token = token.strip()
    else:
        # Lazy import — questionary not needed for non-interactive or unit tests
        try:
            import questionary  # type: ignore[import]
        except ImportError:
            _print(
                "[yellow]questionary not installed — "
                "cannot run interactive Telegram setup.[/yellow]"
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
        dm_policy = _prompt_dm_policy(
            "Telegram", non_interactive, "SYNAPSE_TELEGRAM_DM_POLICY", _print
        )
        return {"token": token, "dm_policy": dm_policy}
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


def setup_discord(
    non_interactive: bool = False,
    prompter: "object | None" = None,
) -> "dict | None":
    """
    Collect and validate a Discord bot token. Shows MESSAGE_CONTENT intent instruction.

    Interactive mode: prompts user via questionary (or via prompter if provided). Skippable.
    Non-interactive mode: reads SYNAPSE_DISCORD_TOKEN env var. Returns None if absent.

    After successful validation, always displays the MESSAGE_CONTENT intent instruction.
    In interactive mode, pauses for user confirmation.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.
        prompter:        Optional WizardPrompter instance for test injection.

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
    elif prompter is not None:
        choice = prompter.select("Discord:", choices=["Configure", "Skip"])  # type: ignore[attr-defined]
        if choice != "Configure":
            return None
        token = prompter.text("Enter Discord bot token:", password=True)  # type: ignore[attr-defined]
        if not token:
            return None
        token = token.strip()
        channel_ids = []
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

    dm_policy = _prompt_dm_policy("Discord", non_interactive, "SYNAPSE_DISCORD_DM_POLICY", _print)
    return {"token": token, "allowed_channel_ids": channel_ids, "dm_policy": dm_policy}


# ---------------------------------------------------------------------------
# setup_slack()
# ---------------------------------------------------------------------------


def setup_slack(
    non_interactive: bool = False,
    prompter: "object | None" = None,
) -> "dict | None":
    """
    Collect and validate a Slack bot+app token pair.

    Interactive mode: prompts user via questionary (or via prompter if provided). Skippable.
    Non-interactive mode: reads SYNAPSE_SLACK_BOT_TOKEN and SYNAPSE_SLACK_APP_TOKEN.

    Args:
        non_interactive: If True, skip interactive prompts and use env vars.
        prompter:        Optional WizardPrompter instance for test injection.

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
    elif prompter is not None:
        choice = prompter.select("Slack:", choices=["Configure", "Skip"])  # type: ignore[attr-defined]
        if choice != "Configure":
            return None
        _print(
            "Bot token: found in Slack App → OAuth & Permissions → Bot User OAuth Token\n"
            "App token: found in Slack App → Basic Information → App-Level Tokens\n"
            "          (must have connections:write scope)"
        )
        bot_token = prompter.text("Enter Slack bot token (xoxb-...):", password=True)  # type: ignore[attr-defined]
        if not bot_token:
            return None
        bot_token = bot_token.strip()
        app_token = prompter.text("Enter Slack app token (xapp-...):", password=True)  # type: ignore[attr-defined]
        if not app_token:
            return None
        app_token = app_token.strip()
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
        dm_policy = _prompt_dm_policy("Slack", non_interactive, "SYNAPSE_SLACK_DM_POLICY", _print)
        return {"bot_token": bot_token, "app_token": app_token, "dm_policy": dm_policy}
    except ValueError as exc:
        _print(f"[red]Slack validation failed:[/red] {exc}")
        return None


# ---------------------------------------------------------------------------
# setup_whatsapp()
# ---------------------------------------------------------------------------


def setup_whatsapp(
    bridge_dir: "str | Path",
    non_interactive: bool = False,
    prompter: "object | None" = None,
) -> "dict | None":
    """
    Configure the WhatsApp channel.

    Interactive mode: runs the full QR pairing flow (or via prompter if provided).
    Returns config dict if paired, None if skipped or flow failed.

    Non-interactive mode: WhatsApp QR cannot be automated. Returns the config dict
    immediately (enables the channel so it can be paired later at runtime) if the
    WHATSAPP_BRIDGE_TOKEN env var is set OR if the auth_state directory already exists
    (indicating a prior pairing). Otherwise returns the config dict with a note — the
    user can pair later via the running Synapse dashboard.

    Args:
        bridge_dir:       Path to the baileys-bridge directory.
        non_interactive:  If True, skip QR flow and return config without validation.
        prompter:         Optional WizardPrompter instance for test injection.

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
        policy = _prompt_dm_policy("WhatsApp", True, "SYNAPSE_WHATSAPP_DM_POLICY", _print)
        return {"enabled": True, "bridge_port": BRIDGE_PORT, "dm_policy": policy}

    # WhatsApp is mandatory — no skip gate. Raises NodeJsMissingError if Node.js absent.
    _print("Starting WhatsApp QR pairing flow...")
    success = run_whatsapp_qr_flow(bridge_dir, console=console)

    if success:
        dm_policy = _prompt_dm_policy("WhatsApp", False, "SYNAPSE_WHATSAPP_DM_POLICY", _print)
        return {"enabled": True, "bridge_port": BRIDGE_PORT, "dm_policy": dm_policy}
    return None
