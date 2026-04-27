"""
provider_steps.py — Provider validation module for the Synapse-OSS onboarding wizard.

Defines:
  - ValidationResult dataclass
  - VALIDATION_MODELS: cheapest model per provider for max_tokens=1 validation ping
  - _KEY_MAP: env var names per provider (mirrors llm_router.py exactly)
  - PROVIDER_GROUPS: grouped provider list for questionary.checkbox() display
  - PROVIDER_LIST: flat list of all 19 provider keys
  - validate_provider(): litellm.acompletion validation call for cloud providers
  - validate_ollama(): httpx GET /api/version health check (no litellm)
  - github_copilot_device_flow(): OAuth device code flow for GitHub Copilot
  - openai_codex_device_flow(): OAuth device code flow for OpenAI Codex (ChatGPT subscription)

All validation functions return ValidationResult — never raise exceptions.
"""

import asyncio
import json
import os
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import httpx
from litellm import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of a provider validation attempt.

    Fields:
      ok     — True if the key is usable (even if quota is exceeded).
      error  — Short error code: "invalid_key" | "quota_exceeded" | "timeout"
               | "network_error" | "bad_request" | "http_error" | "not_running" | "unknown"
      detail — Raw exception / HTTP message for display in the wizard.
    """

    ok: bool
    error: str | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# VALIDATION_MODELS — cheapest / fastest model per provider for the ping call
# ---------------------------------------------------------------------------

VALIDATION_MODELS: dict[str, str] = {
    "anthropic": "anthropic/claude-haiku-4-5",
    "openai": "openai/gpt-4o-mini",
    "gemini": "gemini/gemini-2.0-flash",
    "groq": "groq/llama-3.3-70b-versatile",
    "openrouter": "openrouter/auto",
    "mistral": "mistral/mistral-small-latest",
    "xai": "xai/grok-2-latest",
    "cohere": "cohere/command-r-plus",
    "togetherai": "together_ai/meta-llama/Llama-3-8b-chat-hf",
    "minimax": "minimax/abab6.5s-chat",
    "moonshot": "moonshot/moonshot-v1-8k",
    "zai": "zai/glm-4-flash",
    "volcengine": "volcengine/doubao-lite-4k",
    "bedrock": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "vertex_ai": "vertex_ai/gemini-2.0-flash-001",
    "huggingface": "huggingface/microsoft/DialoGPT-medium",
    "nvidia_nim": "nvidia_nim/meta/llama-3.1-8b-instruct",
    "qianfan": "qianfan/ERNIE-Speed-128K",
    "deepseek": "deepseek/deepseek-chat",
    # ollama: no litellm call — use validate_ollama() instead
    # github_copilot: no live call — OAuth device flow IS the validation
    # openai_codex: no live call — OAuth device flow IS the validation
    # vllm: no litellm call — httpx health check
}

# ---------------------------------------------------------------------------
# _KEY_MAP — env var names per provider (mirrors llm_router.py exactly)
# ---------------------------------------------------------------------------

_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "togetherai": "TOGETHERAI_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "zai": "ZAI_API_KEY",
    "volcengine": "VOLCENGINE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "qianfan": "QIANFAN_AK",  # Baidu Qianfan uses two keys; primary is AK
    "deepseek": "DEEPSEEK_API_KEY",
}

# ---------------------------------------------------------------------------
# PROVIDER_GROUPS — for questionary.checkbox() grouped display
# ---------------------------------------------------------------------------

PROVIDER_GROUPS: list[dict] = [
    {
        "separator": "--- Major Cloud (US) ---",
        "providers": [
            {"key": "anthropic", "label": "Anthropic Claude"},
            {"key": "openai", "label": "OpenAI GPT"},
            {"key": "gemini", "label": "Google Gemini"},
            {"key": "groq", "label": "Groq (fast inference)"},
            {"key": "openrouter", "label": "OpenRouter (multi-provider)"},
            {"key": "mistral", "label": "Mistral AI"},
            {"key": "xai", "label": "xAI Grok"},
            {"key": "cohere", "label": "Cohere"},
            {"key": "togetherai", "label": "Together AI"},
            {"key": "deepseek", "label": "DeepSeek"},
        ],
    },
    {
        "separator": "--- Chinese Providers ---",
        "providers": [
            {"key": "minimax", "label": "MiniMax"},
            {"key": "moonshot", "label": "Moonshot / Kimi"},
            {"key": "zai", "label": "Zhipu Z.AI (zai/ prefix)"},
            {"key": "volcengine", "label": "Volcano Engine / BytePlus"},
            {"key": "qianfan", "label": "Baidu Qianfan (ERNIE)"},
        ],
    },
    {
        "separator": "--- Self-Hosted / Special ---",
        "providers": [
            {"key": "ollama", "label": "Ollama (local models)"},
            {"key": "vllm", "label": "vLLM (self-hosted)"},
            {"key": "bedrock", "label": "AWS Bedrock"},
            {"key": "vertex_ai", "label": "Google Vertex AI"},
            {"key": "huggingface", "label": "HuggingFace Inference Endpoints"},
            {"key": "nvidia_nim", "label": "NVIDIA NIM"},
            {"key": "github_copilot", "label": "GitHub Copilot (OAuth device flow)"},
            {"key": "openai_codex", "label": "OpenAI Codex (ChatGPT subscription OAuth)"},
            {"key": "google_antigravity", "label": "Google Antigravity (Gemini 3 via OAuth)"},
            {"key": "claude_cli", "label": "Claude Code CLI (Pro/Max subscription via local `claude` binary)"},
        ],
    },
]

# Flat list for non-interactive mode lookups
PROVIDER_LIST: list[str] = [p["key"] for group in PROVIDER_GROUPS for p in group["providers"]]

# ---------------------------------------------------------------------------
# GitHub Copilot OAuth constants
# ---------------------------------------------------------------------------

# Public GitHub Copilot client_id per litellm community sources
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"

# ---------------------------------------------------------------------------
# Internal async helpers
# ---------------------------------------------------------------------------


async def _validate_async(provider: str, api_key: str) -> ValidationResult:
    """Internal async validation call via litellm.acompletion.

    Called by validate_provider() via asyncio.run().
    """
    import litellm  # noqa: PLC0415

    model = VALIDATION_MODELS[provider]
    try:
        await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1,
            timeout=5.0,
            num_retries=0,
        )
        return ValidationResult(ok=True)
    except AuthenticationError as exc:
        return ValidationResult(ok=False, error="invalid_key", detail=str(exc))
    except RateLimitError as exc:
        # Rate limit means the key IS valid — quota is exhausted
        return ValidationResult(ok=True, error="quota_exceeded", detail=str(exc))
    except Timeout as exc:
        return ValidationResult(ok=False, error="timeout", detail=str(exc))
    except APIConnectionError as exc:
        return ValidationResult(ok=False, error="network_error", detail=str(exc))
    except BadRequestError as exc:
        return ValidationResult(ok=False, error="bad_request", detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(ok=False, error="unknown", detail=str(exc))


# ---------------------------------------------------------------------------
# Public validation functions
# ---------------------------------------------------------------------------


def validate_provider(provider: str, api_key: str) -> ValidationResult:
    """Validate a cloud provider API key via a max_tokens=1 litellm.acompletion ping.

    Temporarily sets the provider's env var to api_key for the duration of the call,
    then restores the original value (or removes the var if it was unset before).

    Returns ValidationResult — never raises.

    Special case: RateLimitError → ok=True, error="quota_exceeded".
    The key is accepted with a warning; the user can still configure the provider.

    Vertex AI is handled specially: it uses GCP ADC / service-account JSON credentials
    already set in the environment by the caller (VERTEXAI_PROJECT, VERTEXAI_LOCATION,
    GOOGLE_APPLICATION_CREDENTIALS). The api_key arg is ignored (the caller may pass
    the project_id for logging purposes).
    """
    if provider == "vertex_ai":
        # Vertex AI uses GCP ADC / SA creds already injected into env by the caller.
        return asyncio.run(_validate_async(provider, api_key))
    env_var = _KEY_MAP[provider]
    old = os.environ.get(env_var)
    os.environ[env_var] = api_key
    try:
        return asyncio.run(_validate_async(provider, api_key))
    finally:
        if old is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = old


def validate_ollama(
    api_base: str = "http://localhost:11434", model: str | None = None
) -> ValidationResult:
    """Validate Ollama availability via a synchronous httpx GET to /api/version.

    No litellm call is made — Ollama requires no API key.

    If *model* is provided, also queries GET /api/tags to verify the model is
    downloaded locally.  Ollama tag suffixes (e.g. ``:latest``) are ignored when
    matching so ``"llama3.3"`` matches ``"llama3.3:latest"``.

    Returns:
      ValidationResult(ok=True)  — HTTP 200 (and model present if requested)
      ValidationResult(ok=True,  error="model_not_found") — Ollama running but
                                  model not downloaded; detail contains pull hint
      ValidationResult(ok=False, error="http_error")      — non-200 response
      ValidationResult(ok=False, error="not_running")     — connection refused
      ValidationResult(ok=False, error="timeout")         — 5 s timeout exceeded
    """
    try:
        resp = httpx.get(f"{api_base}/api/version", timeout=5.0)
        if resp.status_code == 200:
            version = resp.json().get("version", "unknown")

            if model is not None:
                try:
                    tags_resp = httpx.get(f"{api_base}/api/tags", timeout=5.0)
                    if tags_resp.status_code == 200:
                        models_data = tags_resp.json().get("models", [])
                        model_names = [m.get("name", "") for m in models_data]
                        model_base = model.split(":")[0]
                        found = any(
                            name == model or name.startswith(f"{model_base}:")
                            for name in model_names
                        )
                        if not found:
                            return ValidationResult(
                                ok=True,
                                error="model_not_found",
                                detail=(
                                    f"Model '{model}' not found locally. "
                                    f"Run: ollama pull {model}"
                                ),
                            )
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass  # /api/tags unreachable — skip model check, Ollama is up

            return ValidationResult(ok=True, detail=f"Ollama {version} running")
        return ValidationResult(
            ok=False,
            error="http_error",
            detail=f"HTTP {resp.status_code}",
        )
    except httpx.ConnectError:
        return ValidationResult(
            ok=False,
            error="not_running",
            detail=f"Ollama not reachable at {api_base}",
        )
    except httpx.TimeoutException:
        return ValidationResult(ok=False, error="timeout", detail="5s timeout")


async def github_copilot_device_flow(console) -> str | None:
    """Run the GitHub OAuth device code flow to obtain a GitHub Copilot token.

    Steps:
      1. POST to GitHub device code endpoint → get device_code, user_code, verification_uri.
      2. Print/open the verification URI and display the user code.
      3. Poll the access_token endpoint until granted, expired, or denied.
      4. On success: write token to GITHUB_COPILOT_TOKEN_DIR/api-key.json.

    Args:
      console: Rich Console (or any object with a .print() method) for output.

    Returns:
      Access token string on success, None on timeout/denial.
    """
    device_endpoint = "https://github.com/login/device/code"
    token_endpoint = "https://github.com/login/oauth/access_token"

    async with httpx.AsyncClient() as client:
        # Step 1: Request device code
        try:
            resp = await client.post(
                device_endpoint,
                json={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
                headers={"Accept": "application/json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]GitHub device code request failed: {exc}[/red]")
            return None

        device_code = data.get("device_code")
        user_code = data.get("user_code")
        verification_uri = data.get("verification_uri", "https://github.com/login/device")
        interval = int(data.get("interval", 5))

        # Step 2: Prompt user
        console.print(f"\nVisit [bold]{verification_uri}[/bold]")
        console.print(f"Enter code: [bold yellow]{user_code}[/bold yellow]\n")
        webbrowser.open(verification_uri)

        # Step 3: Poll for token (max 5 minutes)
        deadline = time.time() + 300
        while time.time() < deadline:
            await asyncio.sleep(interval)

            try:
                poll_resp = await client.post(
                    token_endpoint,
                    json={
                        "client_id": GITHUB_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers={"Accept": "application/json"},
                    timeout=10.0,
                )
                poll_data = poll_resp.json()
            except Exception as exc:  # noqa: BLE001
                console.print(f"[yellow]Poll error (retrying): {exc}[/yellow]")
                continue

            if "access_token" in poll_data:
                access_token = poll_data["access_token"]

                # Step 4: Write token file
                token_dir_env = os.environ.get("GITHUB_COPILOT_TOKEN_DIR")
                if token_dir_env:
                    token_dir = Path(token_dir_env)
                else:
                    token_dir = Path.home() / ".config" / "litellm" / "github_copilot"
                token_dir.mkdir(parents=True, exist_ok=True)
                token_file = token_dir / "api-key.json"
                token_file.write_text(
                    json.dumps(
                        {
                            "token": access_token,
                            "expires_at": time.time() + 28800,  # 8 hours
                            "endpoints": {"api": "https://api.githubcopilot.com"},
                        }
                    )
                )
                return access_token

            error = poll_data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            else:
                # expired_token, access_denied, or other terminal errors
                console.print(f"[red]GitHub authorization failed: {error}[/red]")
                break

    console.print("[red]GitHub Copilot authorization timed out or was denied.[/red]")
    return None


async def openai_codex_device_flow(console) -> dict | None:
    """Run OpenAI Codex OAuth device flow and persist credentials locally.

    This wraps ``openai_codex_oauth.login_device_code`` in ``asyncio.to_thread``
    because the OAuth helper is synchronous and blocks while polling.

    Args:
      console: Rich Console (or compatible object with ``print``/``input``).

    Returns:
      Metadata dict on success:
        {"email": str, "profile_name": str, "account_id": str}
      None on failure.
    """
    try:
        from sci_fi_dashboard import openai_codex_oauth  # noqa: PLC0415
    except ImportError as exc:
        console.print(f"[red]Cannot import openai_codex_oauth: {exc}[/red]")
        return None

    printed_code = {"done": False}

    def _code_sink(code) -> None:
        verification_uri = (
            getattr(code, "verification_uri", None)
            or openai_codex_oauth.OPENAI_CODEX_DEVICE_VERIFY_URL
        )
        user_code = getattr(code, "user_code", None) or ""
        console.print("\nOpenAI Codex uses ChatGPT subscription OAuth (no API key).")
        console.print(f"Visit [bold]{verification_uri}[/bold]")
        if user_code:
            console.print(f"Enter code: [bold yellow]{user_code}[/bold yellow]\n")
        printed_code["done"] = True

    creds = None
    for attempt in range(2):
        try:
            creds = await asyncio.to_thread(
                openai_codex_oauth.login_device_code,
                open_browser=True,
                code_sink=_code_sink,
            )
            break
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            lowered = detail.lower()
            unknown_device_auth = (
                "device authorization is unknown" in lowered
                or "device authorization unknown" in lowered
            )
            if unknown_device_auth and attempt == 0:
                console.print(
                    "[yellow]OpenAI device authorization was not recognized. "
                    "Requesting a fresh code and retrying once...[/yellow]"
                )
                printed_code["done"] = False
                continue
            if unknown_device_auth:
                console.print(
                    "[yellow]Enable Device Code Authorization for Codex in "
                    "ChatGPT Security Settings, then retry this flow with a "
                    "fresh device code.[/yellow]"
                )
            console.print(f"[red]OpenAI Codex authorization failed: {exc}[/red]")
            return None

    if creds is None:
        console.print("[red]OpenAI Codex authorization failed: unknown OAuth error[/red]")
        return None

    if not printed_code["done"]:
        # Defensive fallback: login helper normally calls code_sink before polling.
        console.print(
            f"\nVisit [bold]{openai_codex_oauth.OPENAI_CODEX_DEVICE_VERIFY_URL}[/bold] "
            "to complete OpenAI Codex login."
        )

    console.print(
        "[green]OpenAI Codex OAuth complete.[/green] "
        f"{creds.email or '(email unavailable)'}"
    )
    return {
        "email": creds.email,
        "profile_name": creds.profile_name,
        "account_id": creds.account_id,
    }


# ---------------------------------------------------------------------------
# Google Antigravity / Gemini CLI OAuth (PKCE + localhost callback)
# ---------------------------------------------------------------------------


async def google_antigravity_oauth_flow(console) -> dict | None:
    """Run the Google Antigravity OAuth flow and persist the credentials.

    Mirrors OpenClaw's Gemini-CLI OAuth path: builds a PKCE auth URL using a
    client_id/secret discovered from the locally installed Gemini CLI (or env
    vars), captures the redirect on localhost:8085, exchanges the code for
    access + refresh tokens, then resolves a Cloud project ID via
    cloudcode-pa.googleapis.com.

    Returns a small metadata dict (email, project_id, tier) on success — the
    actual access/refresh tokens are saved to ~/.synapse/state/google-oauth.json
    by ``google_oauth.save_credentials``. Returns None on failure or user opt-out.
    """
    try:
        from sci_fi_dashboard import google_oauth  # noqa: PLC0415
    except ImportError as exc:
        console.print(
            f"[red]Cannot import google_oauth module: {exc}[/red]"
        )
        return None

    console.print(
        "\n[yellow]"
        "Heads up: Google Antigravity OAuth is an unofficial integration and is\n"
        "not endorsed by Google. Some users have reported account restrictions\n"
        "or suspensions after using third-party Gemini CLI / Antigravity OAuth\n"
        "clients. Proceed only if you understand and accept this risk."
        "[/yellow]"
    )

    try:
        client_id, _ = google_oauth.resolve_oauth_client_config()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return None
    console.print(f"[dim]OAuth client_id resolved: {client_id[:24]}…[/dim]")

    console.print(
        "\nOpening browser for Google sign-in. Callback will be captured on\n"
        f"[bold]http://localhost:{google_oauth.REDIRECT_PORT}{google_oauth.REDIRECT_PATH}[/bold]"
    )

    def _print_url(url: str) -> None:
        console.print(f"[dim]Auth URL: {url}[/dim]")

    def _paste_fallback(url: str) -> str:
        console.print(
            "\n[yellow]Localhost callback unavailable (port 8085 busy or "
            "WSL2 detected). Sign in in your browser, then paste the FULL "
            "redirect URL (or just the ?code=... query string) here.[/yellow]"
        )
        return console.input("Paste redirect URL: ")

    try:
        creds = await asyncio.to_thread(
            google_oauth.login_pkce,
            headless=False,
            open_browser=True,
            auth_url_sink=_print_url,
            code_input=_paste_fallback,
        )
    except RuntimeError as exc:
        console.print(f"[red]Google Antigravity OAuth failed: {exc}[/red]")
        return None
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Unexpected error during OAuth: {exc}[/red]")
        return None

    target = google_oauth.save_credentials(creds)
    console.print(
        f"[green]Google Antigravity OAuth complete: {creds.email or '(unknown email)'} "
        f"tier={creds.tier or 'unknown'}[/green]"
    )
    console.print(f"[dim]Credentials saved to {target}[/dim]")
    return {
        "email": creds.email,
        "project_id": creds.project_id,
        "tier": creds.tier,
    }


# ---------------------------------------------------------------------------
# Claude Code CLI subscription provider — uses the local `claude` binary so
# Pro/Max subscription auth happens inside Claude Code itself; Synapse never
# sees an API key.
# ---------------------------------------------------------------------------


def claude_cli_setup(console) -> dict | None:
    """Detect the local ``claude`` binary and confirm subscription auth.

    No interactive prompts here — the OAuth dance happens in Claude Code itself
    (``claude /login`` from a terminal). Synapse's only job is to verify the
    binary is on PATH and the user actually wants to wire it through.

    Returns a small metadata dict on success, or ``None`` if the binary is
    missing / the user opts out.
    """
    import shutil  # noqa: PLC0415

    claude_bin = shutil.which("claude")
    if not claude_bin:
        console.print(
            "[red]`claude` binary not found in PATH.[/red]\n"
            "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code\n"
            "Then run `claude /login` in a terminal once to authorize your "
            "Pro/Max subscription before configuring this provider in Synapse."
        )
        return None

    console.print(
        "[green]Found `claude` binary at:[/green] " + claude_bin + "\n"
        "[dim]Synapse will spawn this binary headlessly per chat request, so "
        "your Pro/Max subscription auth is handled inside Claude Code — no API "
        "key is stored or transmitted by Synapse. Make sure you've run "
        "`claude /login` at least once.[/dim]"
    )
    return {"binary_path": claude_bin}
