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
    "togetherai": "together_ai/meta-llama/Llama-3-8b-chat-hf",
    "minimax": "minimax/abab6.5s-chat",
    "moonshot": "moonshot/moonshot-v1-8k",
    "zai": "zai/glm-4-flash",
    "volcengine": "volcengine/doubao-lite-4k",
    "bedrock": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "huggingface": "huggingface/microsoft/DialoGPT-medium",
    "nvidia_nim": "nvidia_nim/meta/llama-3.1-8b-instruct",
    "qianfan": "qianfan/ERNIE-Speed-128K",
    # ollama: no litellm call — use validate_ollama() instead
    # github_copilot: no live call — OAuth device flow IS the validation
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
    "minimax": "MINIMAX_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "zai": "ZAI_API_KEY",
    "volcengine": "VOLCENGINE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "qianfan": "QIANFAN_AK",  # Baidu Qianfan uses two keys; primary is AK
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
            {"key": "togetherai", "label": "Together AI"},
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
            {"key": "huggingface", "label": "HuggingFace Inference Endpoints"},
            {"key": "nvidia_nim", "label": "NVIDIA NIM"},
            {"key": "github_copilot", "label": "GitHub Copilot (OAuth device flow)"},
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
    """
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


def validate_ollama(api_base: str = "http://localhost:11434") -> ValidationResult:
    """Validate Ollama availability via a synchronous httpx GET to /api/version.

    No litellm call is made — Ollama requires no API key.

    Returns:
      ValidationResult(ok=True)  — HTTP 200
      ValidationResult(ok=False, error="http_error")      — non-200 response
      ValidationResult(ok=False, error="not_running")     — connection refused
      ValidationResult(ok=False, error="timeout")         — 5 s timeout exceeded
    """
    try:
        resp = httpx.get(f"{api_base}/api/version", timeout=5.0)
        if resp.status_code == 200:
            version = resp.json().get("version", "unknown")
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
