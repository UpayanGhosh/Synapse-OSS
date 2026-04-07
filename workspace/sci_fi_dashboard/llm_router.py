"""
SynapseLLMRouter — unified litellm.Router dispatch layer.

Replaces call_gemini_direct() and _call_antigravity().
All LLM calls go through router.acompletion() using provider-prefixed model strings
from synapse.json model_mappings. No hardcoded model strings in this file.

InferenceLoop wraps _do_call() with retry logic driven by classify_llm_error():
context overflow → compact → retry, rate limited → exponential backoff,
auth failed → rotate auth profile, server error → retry once,
model not found → try fallback model.
"""

import asyncio
import copy
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

# Ensure workspace root on path for SynapseConfig import
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from litellm import (  # noqa: E402
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Router,
    ServiceUnavailableError,
    Timeout,
)
from synapse_config import SynapseConfig  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """Structured result from an LLM call, carrying text + usage metadata."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None = None


# --- Tool-call dataclasses ---


@dataclass
class ToolCall:
    """Normalized tool call — provider-agnostic."""

    id: str
    name: str
    arguments: str  # raw JSON string


@dataclass
class LLMToolResult:
    """Result from an LLM call that may include tool invocations."""

    text: str
    tool_calls: list[ToolCall]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None = None

# --- Tool schema normalization ---


def normalize_tool_schemas(tools: list[dict], provider: str) -> list[dict]:
    """Apply provider-specific schema fixes that litellm doesn't handle.

    Each provider has quirks in what JSON Schema keywords it accepts:
    - Gemini rejects ``$schema``, ``$id``, ``examples``, ``default``, ``$defs``
    - xAI / Grok rejects numeric range keywords (``minLength``, ``maximum``, etc.)
    - OpenAI strict mode requires ``additionalProperties: false`` on object schemas

    Args:
        tools: OpenAI-format tool definitions (``{"type": "function", ...}``).
        provider: Provider prefix string (e.g. ``"gemini"``, ``"xai"``).

    Returns:
        Deep-copied list with provider-specific keys removed/added.
    """
    if not tools:
        return tools
    normalized = []
    for tool in tools:
        t = copy.deepcopy(tool)
        schema = t.get("function", {}).get("parameters", {})
        if "gemini" in provider:
            _strip_keys_recursive(
                schema, {"$schema", "$id", "examples", "default", "$defs"}
            )
        if "xai" in provider or "grok" in provider:
            _strip_keys_recursive(
                schema,
                {"minLength", "maxLength", "minimum", "maximum", "multipleOf"},
            )
        if "openai" in provider:
            if (
                schema.get("type") == "object"
                and "additionalProperties" not in schema
            ):
                schema["additionalProperties"] = False
        normalized.append(t)
    return normalized


def _strip_keys_recursive(obj: dict, keys: set) -> None:
    """Remove *keys* from *obj* and all nested dicts/lists, in place."""
    if not isinstance(obj, dict):
        return
    for key in keys:
        obj.pop(key, None)
    for value in obj.values():
        if isinstance(value, dict):
            _strip_keys_recursive(value, keys)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_keys_recursive(item, keys)


# --- Tool call response normalization ---


def normalize_tool_calls(raw_tool_calls: list | None) -> list[ToolCall]:
    """Parse litellm tool-call objects into provider-agnostic :class:`ToolCall` list.

    Handles missing IDs (generates one), whitespace in function names, and
    malformed JSON in arguments (attempts lightweight repair).
    """
    if not raw_tool_calls:
        return []
    calls: list[ToolCall] = []
    for tc in raw_tool_calls:
        name = (tc.function.name or "").strip()
        if not name:
            continue
        args = tc.function.arguments or "{}"
        try:
            json.loads(args)
        except json.JSONDecodeError:
            args = _attempt_json_repair(args)
        calls.append(
            ToolCall(
                id=tc.id or f"call_{uuid4().hex[:8]}",
                name=name,
                arguments=args,
            )
        )
    return calls


def _attempt_json_repair(raw: str) -> str:
    """Best-effort fix for truncated JSON from streaming tool calls.

    Adds missing closing braces.  Returns ``"{}"`` when repair fails.
    """
    raw = raw.rstrip()
    if not raw.endswith("}"):
        raw += "}"
    open_count = raw.count("{") - raw.count("}")
    if open_count > 0:
        raw += "}" * open_count
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        return "{}"


# --- Provider key injection ---

# Maps synapse.json provider name → litellm-expected env var name.
# Bedrock handled separately (uses AWS_* env vars, not a single api_key).
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
    "zai": "ZAI_API_KEY",  # Zhipu Z.AI — prefix is zai/, NOT zhipu/
    "volcengine": "VOLCENGINE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
}

_BEDROCK_MAP: dict[str, str] = {
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "aws_region_name": "AWS_REGION_NAME",
}


def _inject_provider_keys(providers: dict) -> None:
    """
    Inject provider API keys from synapse.json into os.environ for litellm.
    litellm reads credentials from os.environ at call time (per-call lookup).
    Must be called before the first acompletion() call.
    """
    for provider_name, env_var in _KEY_MAP.items():
        prov_cfg = providers.get(provider_name, {})
        if isinstance(prov_cfg, dict):
            api_key = prov_cfg.get("api_key")
        elif isinstance(prov_cfg, str):
            api_key = prov_cfg
        else:
            api_key = None
        if api_key and env_var not in os.environ:
            # Only inject if not already set (env var takes precedence)
            os.environ[env_var] = api_key

    # Bedrock: multiple AWS credentials, no single api_key field
    bedrock_cfg = providers.get("bedrock", {})
    if isinstance(bedrock_cfg, dict):
        for aws_key, env_key in _BEDROCK_MAP.items():
            val = bedrock_cfg.get(aws_key)
            if val and env_key not in os.environ:
                os.environ[env_key] = val


# Ollama chat prefix sentinel — centralised so no bare provider strings appear at call sites
_OLLAMA_CHAT_PREFIX = "ollama_chat/"  # allowed: constant-definition

# --- Router builder ---


def _get_copilot_token() -> str:
    """Get a valid GitHub Copilot API token, refreshing automatically if expired."""
    from litellm.llms.github_copilot.authenticator import Authenticator  # noqa: PLC0415

    try:
        return Authenticator().get_api_key()
    except Exception as exc:
        logger.warning("GitHub Copilot token refresh failed: %s", exc)
        return "missing"


def _copilot_litellm_params(model_suffix: str) -> dict:
    """Build litellm_params for a github_copilot/ model via the openai/ shim.

    litellm's Router doesn't apply Copilot auth headers automatically, so we
    rewrite github_copilot/gpt-4o → openai/gpt-4o with the Copilot API base
    and required headers injected directly.
    """
    from litellm.llms.github_copilot.common_utils import (  # noqa: PLC0415
        GITHUB_COPILOT_API_BASE,
        get_copilot_default_headers,
    )

    api_key = _get_copilot_token()

    return {
        "model": f"openai/{model_suffix}",
        "api_key": api_key,
        "api_base": GITHUB_COPILOT_API_BASE,
        "extra_headers": get_copilot_default_headers(api_key),
        "timeout": 60,
        "stream": False,
    }


_GITHUB_COPILOT_PREFIX = "github_copilot/"
_CLAUDE_MAX_PREFIX = "claude_max/"

# Full Claude Code request signature required for OAuth tokens.
# Anthropic fingerprints requests — Sonnet/Opus reject anything that doesn't
# look exactly like the official Claude Code CLI. Haiku has looser checks.
_CLAUDE_MAX_BETA_HEADERS = (
    "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14"
)
_CLAUDE_MAX_USER_AGENT = "claude-cli/1.0.0 (external, cli)"


def _get_claude_max_token() -> str:
    """Read the OAuth token from Claude CLI credentials file."""
    import json
    import pathlib

    creds_path = pathlib.Path.home() / ".claude" / ".credentials.json"
    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            raise ValueError("No accessToken found in credentials")
        return token
    except Exception as exc:
        logger.warning("Claude Max credentials read failed: %s", exc)
        return "missing"


def _claude_max_litellm_params(model_suffix: str) -> dict:
    """Build litellm_params for a claude_max/ model using Claude OAuth token.

    The request must match Claude Code CLI's exact signature:
    - Full beta header set including interleaved-thinking
    - User-Agent and x-app headers matching claude-cli
    - No temperature field (added via extra_body exclusions)
    - Empty tools array present
    - metadata.user_id present
    - system as content block array (handled by chat_pipeline.py)
    """
    token = _get_claude_max_token()
    return {
        "model": f"anthropic/{model_suffix}",
        "api_key": token,
        "extra_headers": {
            "anthropic-beta": _CLAUDE_MAX_BETA_HEADERS,
            "User-Agent": _CLAUDE_MAX_USER_AGENT,
            "x-app": "cli",
        },
        "timeout": 60,
        "stream": False,
    }


def build_router(model_mappings: dict, providers: dict) -> Router:
    """
    Build a litellm.Router from synapse.json model_mappings.

    model_mappings structure:
      {"casual": {"model": "gemini/gemini-2.0-flash", "fallback": "groq/llama-3.3-70b-versatile"}, ...}

    Ollama models MUST use ollama_chat/ prefix (not ollama/).
    api_base for Ollama is read from providers.ollama.api_base (default: http://localhost:11434).
    """
    ollama_api_base = (providers.get("ollama") or {}).get("api_base", "http://localhost:11434")
    qianfan_api_base = (providers.get("qianfan") or {}).get(
        "api_base", "https://qianfan.baidubce.com/v2"
    )
    vllm_api_base = (providers.get("vllm") or {}).get("api_base", "http://localhost:8000")

    model_list: list[dict] = []
    fallbacks: list[dict] = []

    for role, cfg in model_mappings.items():
        primary_model: str = cfg["model"]

        if primary_model.startswith(_CLAUDE_MAX_PREFIX):
            litellm_params = _claude_max_litellm_params(
                primary_model[len(_CLAUDE_MAX_PREFIX):]
            )
        elif primary_model.startswith(_GITHUB_COPILOT_PREFIX):
            litellm_params = _copilot_litellm_params(
                primary_model[len(_GITHUB_COPILOT_PREFIX):]
            )
        elif primary_model.startswith(_OLLAMA_CHAT_PREFIX):
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = ollama_api_base
            # Prevent repetition loops common in small local models like Gemma4
            litellm_params["extra_body"] = {"options": {"repeat_penalty": 1.15, "temperature": 0.7}}
        elif primary_model.startswith("ollama/"):
            raise ValueError(
                f"Role '{role}' uses ollama/ prefix — must be {_OLLAMA_CHAT_PREFIX} for chat calls. "
                f"Got: {primary_model}"
            )
        elif primary_model.startswith("hosted_vllm/"):
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = vllm_api_base
        elif primary_model.startswith("openai/") and providers.get("qianfan") and role == "qianfan":
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = qianfan_api_base
        else:
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}

        model_list.append({"model_name": role, "litellm_params": litellm_params})

        # Fallback model (optional)
        fallback_model = cfg.get("fallback")
        if fallback_model:
            fallback_role = f"{role}_fallback"
            if fallback_model.startswith(_CLAUDE_MAX_PREFIX):
                fallback_params = _claude_max_litellm_params(
                    fallback_model[len(_CLAUDE_MAX_PREFIX):]
                )
            elif fallback_model.startswith(_GITHUB_COPILOT_PREFIX):
                fallback_params = _copilot_litellm_params(
                    fallback_model[len(_GITHUB_COPILOT_PREFIX):]
                )
            else:
                fallback_params = {"model": fallback_model, "timeout": 60, "stream": False}
                if fallback_model.startswith(_OLLAMA_CHAT_PREFIX):
                    fallback_params["api_base"] = ollama_api_base
                    fallback_params["extra_body"] = {"options": {"repeat_penalty": 1.15, "temperature": 0.7}}
            model_list.append({"model_name": fallback_role, "litellm_params": fallback_params})
            fallbacks.append({role: [fallback_role]})

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=0,
        retry_after=0,
    )


# --- Session tracking ---


def _write_session(role: str, model: str, usage) -> None:
    """
    Write one row to the sessions table in memory.db.
    Non-fatal: caller must wrap in try/except.

    Args:
        role:  The router role name (e.g., 'casual', 'vault').
        model: The actual model string returned by the provider.
        usage: litellm.Usage object or None.
    """
    from sci_fi_dashboard.db import DB_PATH  # noqa: PLC0415

    input_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens: int = getattr(usage, "completion_tokens", 0) or 0
    total_tokens: int = getattr(usage, "total_tokens", 0) or 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, role, model, input_tokens, output_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), role, model, input_tokens, output_tokens, total_tokens),
        )
        conn.commit()


# --- Environment variable resolution ---

_ENV_VAR_RE = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")


def resolve_env_var(value: str) -> str:
    """Resolve ${ENV_VAR} syntax to the actual environment variable value.

    If value matches the pattern ${SOME_VAR}, look up SOME_VAR in os.environ.
    If the env var is not set, return the original string unchanged.

    Args:
        value: A string that may contain ${ENV_VAR} syntax.

    Returns:
        The resolved value, or the original string if no match or env var not set.
    """
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


# --- LLM Error Classification ---


class AuthProfileFailureReason(StrEnum):
    """Classifies LLM API failures for key-rotation decision-making.

    Retryable failures (RATE_LIMIT, OVERLOADED, TIMEOUT) trigger rotation
    to the next API key. Non-retryable failures (AUTH_PERMANENT, FORMAT,
    BILLING, MODEL_NOT_FOUND) are raised immediately.
    """

    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    FORMAT = "format"
    OVERLOADED = "overloaded"
    RATE_LIMIT = "rate_limit"
    BILLING = "billing"
    TIMEOUT = "timeout"
    MODEL_NOT_FOUND = "model_not_found"
    UNKNOWN = "unknown"


# Retryable failure reasons — rotation to the next key is worthwhile
_RETRYABLE_REASONS = frozenset({
    AuthProfileFailureReason.RATE_LIMIT,
    AuthProfileFailureReason.OVERLOADED,
    AuthProfileFailureReason.TIMEOUT,
})


def classify_llm_error(error: Exception) -> AuthProfileFailureReason:
    """Map a litellm exception to an AuthProfileFailureReason.

    Args:
        error: The exception raised by litellm.

    Returns:
        The classified failure reason.
    """
    if isinstance(error, RateLimitError):
        return AuthProfileFailureReason.RATE_LIMIT
    if isinstance(error, AuthenticationError):
        return AuthProfileFailureReason.AUTH
    if isinstance(error, BadRequestError):
        return AuthProfileFailureReason.FORMAT
    if isinstance(error, Timeout):
        return AuthProfileFailureReason.TIMEOUT
    if isinstance(error, ServiceUnavailableError):
        return AuthProfileFailureReason.OVERLOADED
    if isinstance(error, APIConnectionError):
        return AuthProfileFailureReason.TIMEOUT
    return AuthProfileFailureReason.UNKNOWN


# --- API Key Rotation ---


async def execute_with_api_key_rotation(
    provider: str,
    api_keys: list[str],
    execute_fn,  # Callable[[str], Awaitable[T]]
    should_retry_fn=None,  # Callable[[Exception, int], bool] | None
):
    """Try each API key in order; on retryable failure, advance to the next key.

    Deduplicates keys (preserving order), strips empty/None entries. For each key,
    calls execute_fn(key). On failure, classifies the error: if retryable
    (RATE_LIMIT, OVERLOADED, TIMEOUT) and more keys are available, moves to the
    next key. Otherwise re-raises.

    Args:
        provider: Provider name (for logging and error messages).
        api_keys: List of API keys to try in order.
        execute_fn: Async callable that takes an API key string and returns a result.
        should_retry_fn: Optional override for retry logic. Takes (exception, key_index)
            and returns True if the next key should be tried. Defaults to checking
            whether the classified error is in _RETRYABLE_REASONS.

    Returns:
        The result from the first successful execute_fn call.

    Raises:
        ValueError: If no valid API keys are provided after deduplication.
        Exception: The last exception encountered if all keys are exhausted.
    """
    # Dedupe keys, remove empty/None, preserve order
    seen: set[str] = set()
    unique_keys: list[str] = []
    for k in api_keys:
        if k and isinstance(k, str) and k.strip() and k not in seen:
            seen.add(k)
            unique_keys.append(k)

    if not unique_keys:
        raise ValueError(f"No API keys configured for {provider}")

    last_error: Exception | None = None

    for idx, key in enumerate(unique_keys):
        try:
            return await execute_fn(key)
        except Exception as exc:
            last_error = exc
            reason = classify_llm_error(exc)
            is_last_key = idx >= len(unique_keys) - 1

            # Check if we should retry with the next key
            if should_retry_fn is not None:
                should_retry = should_retry_fn(exc, idx)
            else:
                should_retry = reason in _RETRYABLE_REASONS

            if should_retry and not is_last_key:
                logger.warning(
                    "Key %d/%d for %s failed (%s: %s) — rotating to next key",
                    idx + 1,
                    len(unique_keys),
                    provider,
                    reason.value,
                    exc,
                )
                continue

            # Non-retryable or last key — raise immediately
            logger.error(
                "Key %d/%d for %s failed (%s: %s) — no more keys to try",
                idx + 1,
                len(unique_keys),
                provider,
                reason.value,
                exc,
            )
            raise

    # Should not reach here, but satisfy type checker
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No API keys available for {provider}")  # pragma: no cover


# --- Helpers ---


def _provider_from_model(model_string: str) -> str | None:
    """Extract the provider prefix from a litellm model string.

    e.g. "gemini/gemini-2.0-flash" -> "gemini",
         "ollama_chat/mistral" -> "ollama"
    Returns None if no prefix found.
    """
    if "/" in model_string:
        prefix = model_string.split("/", 1)[0]
        return "ollama" if prefix == "ollama_chat" else prefix
    return None


# --- SynapseLLMRouter ---


class SynapseLLMRouter:
    """
    Unified litellm.Router wrapper. One instance per FastAPI lifespan.
    Thread-safe: litellm.Router is async-safe for concurrent calls.

    Usage:
        router = SynapseLLMRouter()
        text = await router.call("casual", messages)
        text = await router.call("vault", messages)
    """

    def __init__(self, config: SynapseConfig | None = None) -> None:
        self._config = config or SynapseConfig.load()
        _inject_provider_keys(self._config.providers)
        self._router = build_router(self._config.model_mappings, self._config.providers)
        self._uses_copilot = any(
            v.get("model", "").startswith(_GITHUB_COPILOT_PREFIX)
            for v in self._config.model_mappings.values()
        )
        # C-09: Lock to prevent concurrent Copilot token refresh races
        self._copilot_refresh_lock = asyncio.Lock()
        logger.info(
            "SynapseLLMRouter initialized with %d roles",
            len(self._config.model_mappings),
        )

    def _rebuild_router(self) -> None:
        """Rebuild the litellm Router (e.g. after a Copilot token refresh)."""
        self._router = build_router(self._config.model_mappings, self._config.providers)
        logger.info("Router rebuilt with fresh credentials")

    def _model_string_for_role(self, role: str) -> str | None:
        """Return the provider-prefixed model string for a role, or None."""
        cfg = self._config.model_mappings.get(role)
        return cfg.get("model") if cfg else None

    def _apply_profile_credentials(self, profile, role: str) -> None:
        """Inject credentials from an AuthProfile into os.environ.

        litellm reads API keys from os.environ at call time, so overwriting
        the env var before the acompletion() call rotates the active key.
        """
        model_str = self._model_string_for_role(role)
        if not model_str:
            return
        provider = _provider_from_model(model_str)
        if not provider:
            return
        api_key = profile.credentials.get("api_key") or profile.credentials.get("access_token")
        if not api_key:
            return
        env_var = _KEY_MAP.get(provider)
        if env_var:
            os.environ[env_var] = api_key
            logger.debug("Applied credentials from profile %s to %s", profile.id, env_var)

    async def _do_call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ):
        """
        Internal: route to the litellm model for the given role and return the raw
        litellm response object. Handles error classification and session tracking.
        Extra **kwargs (e.g. response_format) are forwarded to litellm acompletion.
        """
        try:
            response = await self._router.acompletion(
                model=role,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            finish_reason = choice.finish_reason
            if finish_reason not in ("stop", "end_turn", "length", None):
                logger.warning("Unexpected finish_reason '%s' for role '%s'", finish_reason, role)
            # SESS-01: Write token usage to sessions table (non-fatal side effect)
            try:
                _write_session(
                    role=role,
                    model=response.model or role,
                    usage=getattr(response, "usage", None),
                )
            except Exception as session_exc:
                logger.debug("Session write failed (non-fatal): %s", session_exc)
            return response
        except AuthenticationError as exc:
            logger.error("Auth failed for role '%s': %s", role, exc)
            raise
        except RateLimitError as exc:
            logger.warning("Rate limit hit for role '%s': %s", role, exc)
            raise
        except Timeout as exc:
            logger.error("Timeout for role '%s': %s", role, exc)
            raise
        except (APIConnectionError, ServiceUnavailableError) as exc:
            logger.error("Provider unavailable for role '%s': %s", role, exc)
            raise
        except BadRequestError as exc:
            logger.error("Bad request for role '%s': %s", role, exc)
            raise
        except Exception as exc:
            # Copilot tokens are short-lived — on "forbidden" errors, refresh
            # the token and retry once before giving up.
            # C-09: Use lock to prevent concurrent double-refresh races.
            if self._uses_copilot and "forbidden" in str(exc).lower():
                if self._copilot_refresh_lock.locked():
                    # Another coroutine is already refreshing — wait for it
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning(
                            "Copilot token rejected — refreshing and retrying"
                        )
                        _get_copilot_token()  # triggers Authenticator refresh
                        self._rebuild_router()
                return await self._router.acompletion(
                    model=role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            raise

    async def call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        """
        Route to the litellm model for the given role (e.g., 'casual', 'vault').
        Falls back to fallback model on AuthenticationError or RateLimitError.
        Returns extracted text string; raises on unrecoverable errors.

        stream=False enforced — Phase 2 does not stream (see 02-RESEARCH.md Pitfall 4).
        """
        mapping = self._config.model_mappings.get(role, {})
        if mapping.get("model", "").startswith(_CLAUDE_MAX_PREFIX):
            result = await self.call_with_metadata(role, messages, temperature, max_tokens, **kwargs)
            return result.text
        response = await self._do_call(role, messages, temperature, max_tokens, **kwargs)
        return response.choices[0].message.content or ""

    async def _call_claude_cli(
        self,
        model_suffix: str,
        messages: list[dict],
        max_tokens: int = 1000,
    ) -> LLMResult:
        """Call Claude via the CLI subprocess — bypasses direct API fingerprinting.

        The claude binary handles OAuth auth internally with the correct headers
        and request structure that Anthropic requires for Max subscription access.
        """
        import asyncio
        import json
        import shutil

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH")

        # Flatten messages into a single prompt for -p mode.
        # System prompts are prepended to the user prompt (avoids CLI arg length limits).
        system_parts = []
        conversation_parts = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role_name = msg.get("role", "")
            content = msg.get("content", "")
            # Handle content blocks (list format) as well as plain strings
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            elif not isinstance(content, str):
                content = str(content)
            if role_name == "system":
                system_parts.append(content)
            elif role_name == "user":
                conversation_parts.append(content)
            elif role_name == "assistant":
                conversation_parts.append(f"[Previous response: {content[:200]}]")

        # Build final prompt: system context + last user message
        system_block = "\n\n".join(system_parts)
        user_block = "\n".join(conversation_parts)
        if system_block:
            prompt = f"{system_block}\n\n---\n\n{user_block}"
        else:
            prompt = user_block

        cmd = [
            claude_bin, "-p",
            "--output-format", "json",
            "--model", model_suffix,
        ]

        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDECODE"}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=120,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {stderr.decode(errors='replace')[:300]}")

        # Parse JSONL output — find the result line
        text = ""
        total_input = 0
        total_output = 0
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "result" and obj.get("subtype") == "success":
                    text = obj.get("result", "")
                    usage = obj.get("usage", {})
                    total_input = usage.get("input_tokens", 0) or 0
                    total_output = usage.get("output_tokens", 0) or 0
            except json.JSONDecodeError:
                continue

        return LLMResult(
            text=text,
            model=model_suffix,
            prompt_tokens=total_input,
            completion_tokens=total_output,
            total_tokens=total_input + total_output,
            finish_reason="stop",
        )

    async def call_with_metadata(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ) -> LLMResult:
        """
        Same as call() but returns an LLMResult with text + usage metadata.
        For claude_max roles, uses CLI subprocess to bypass API fingerprinting.
        Extra **kwargs (e.g. response_format) are forwarded to the underlying call.
        """
        # Check if this role uses claude_max — if so, use CLI subprocess
        mapping = self._config.model_mappings.get(role, {})
        model_str = mapping.get("model", "")
        if model_str.startswith(_CLAUDE_MAX_PREFIX):
            model_suffix = model_str[len(_CLAUDE_MAX_PREFIX):]
            try:
                return await self._call_claude_cli(model_suffix, messages, max_tokens)
            except Exception as cli_exc:
                logger.warning("claude CLI failed (%s) — falling back to litellm", cli_exc)
                # Fall through to normal litellm path

        response = await self._do_call(role, messages, temperature, max_tokens, **kwargs)
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=response.choices[0].message.content or "",
            model=response.model or "unknown",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            finish_reason=response.choices[0].finish_reason,
        )

    async def call_model(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        api_base: str | None = None,
    ) -> str:
        """
        Direct call with explicit litellm model string (bypasses Router role lookup).
        Used by tools server, validation pings in onboarding wizard, and Ollama local calls.
        """
        import litellm  # noqa: PLC0415

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": 60.0,
            "stream": False,
        }
        if api_base:
            kwargs["api_base"] = api_base

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        return choice.message.content or ""

    # --- Tool execution support (Phase 2) ---

    def _resolve_provider(self, role: str) -> str:
        """Extract the provider prefix from the model string mapped to *role*.

        Returns the portion before the first ``/`` (e.g. ``"gemini"`` for
        ``"gemini/gemini-2.0-flash"``), or ``"unknown"`` if no slash is present.
        """
        mapping = self._config.model_mappings.get(role, {})
        model_str = mapping.get("model", "")
        return model_str.split("/")[0] if "/" in model_str else "unknown"

    async def call_with_tools(
        self,
        role: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        tool_choice: str = "auto",
    ) -> LLMToolResult:
        """Route an LLM call that includes tool definitions.

        Normalizes tool schemas for the target provider, forwards the call
        through ``litellm.Router.acompletion``, and parses any tool-call
        objects in the response into provider-agnostic :class:`ToolCall`
        instances.

        Args:
            role: Router role name (must exist in ``model_mappings``).
            messages: Chat-format message list.
            tools: OpenAI-format tool definitions.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
            tool_choice: ``"auto"`` | ``"none"`` | ``"required"`` | specific
                tool name dict.

        Returns:
            :class:`LLMToolResult` with text, parsed tool calls, and usage.
        """
        # For claude_max roles, redirect to CLI subprocess (tools not supported via CLI,
        # but we get the text response which is what matters for persona chat)
        mapping = self._config.model_mappings.get(role, {})
        model_str = mapping.get("model", "") if isinstance(mapping, dict) else getattr(mapping, "model", "")
        if model_str.startswith(_CLAUDE_MAX_PREFIX):
            model_suffix = model_str[len(_CLAUDE_MAX_PREFIX):]
            try:
                llm_result = await self._call_claude_cli(model_suffix, messages, max_tokens)
                return LLMToolResult(
                    text=llm_result.text,
                    tool_calls=[],
                    model=llm_result.model,
                    prompt_tokens=llm_result.prompt_tokens,
                    completion_tokens=llm_result.completion_tokens,
                    total_tokens=llm_result.total_tokens,
                    finish_reason="stop",
                )
            except Exception as cli_exc:
                import traceback
                logger.warning("claude CLI failed in call_with_tools (%s)\n%s", cli_exc, traceback.format_exc())

        provider = self._resolve_provider(role)
        normalized_tools = normalize_tool_schemas(tools, provider)

        kwargs: dict = {
            "model": role,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": normalized_tools,
            "tool_choice": tool_choice,
        }

        try:
            response = await self._router.acompletion(**kwargs)
        except AuthenticationError as exc:
            logger.error("Auth failed for role '%s' (tools): %s", role, exc)
            raise
        except RateLimitError as exc:
            logger.warning("Rate limit for role '%s' (tools): %s", role, exc)
            raise
        except Timeout as exc:
            logger.error("Timeout for role '%s' (tools): %s", role, exc)
            raise
        except (APIConnectionError, ServiceUnavailableError) as exc:
            logger.error(
                "Provider unavailable for role '%s' (tools): %s", role, exc
            )
            raise
        except BadRequestError as exc:
            logger.error("Bad request for role '%s' (tools): %s", role, exc)
            raise
        except Exception as exc:
            # M-03: Copilot 403 refresh — same logic as _do_call()
            if self._uses_copilot and "forbidden" in str(exc).lower():
                if self._copilot_refresh_lock.locked():
                    async with self._copilot_refresh_lock:
                        pass
                else:
                    async with self._copilot_refresh_lock:
                        logger.warning(
                            "Copilot token rejected (tools) — refreshing"
                        )
                        _get_copilot_token()
                        self._rebuild_router()
                response = await self._router.acompletion(**kwargs)
            else:
                raise

        message = response.choices[0].message
        usage = getattr(response, "usage", None) or type(
            "U",
            (),
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )()

        # SESS-01: Write token usage (non-fatal)
        try:
            _write_session(
                role=role,
                model=response.model or role,
                usage=usage,
            )
        except Exception as session_exc:
            logger.debug("Session write failed (non-fatal): %s", session_exc)

        return LLMToolResult(
            text=message.content or "",
            tool_calls=normalize_tool_calls(message.tool_calls),
            model=response.model or "unknown",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            finish_reason=response.choices[0].finish_reason,
        )


# --- Inference Loop ---


class InferenceLoop:
    """Multi-attempt inference loop wrapping SynapseLLMRouter._do_call().

    Drives retry decisions based on classify_llm_error():
    - CONTEXT_OVERFLOW (FORMAT with context cues): compact_fn → retry
    - RATE_LIMIT: exponential backoff (2s, 4s, 8s + jitter) → retry
    - AUTH / AUTH_PERMANENT: rotate auth profile via AuthProfileStore → retry
    - OVERLOADED / TIMEOUT: retry once with backoff
    - MODEL_NOT_FOUND: try fallback model, no retry
    - FORMAT / BILLING / UNKNOWN: raise immediately

    Args:
        router: The SynapseLLMRouter instance to use for calls.
        max_attempts: Maximum number of retry attempts (default 3).
        compact_fn: Optional async callable to compact messages on context overflow.
            Signature: async (messages: list[dict]) -> list[dict].
            If None, context overflow retries are skipped.
        tool_loop_cb: Optional callback invoked after each attempt (for observability).
            Signature: (attempt: int, error: Exception | None) -> None.
        auth_store: Optional AuthProfileStore for auth profile rotation.
    """

    def __init__(
        self,
        router: SynapseLLMRouter,
        max_attempts: int = 3,
        compact_fn: Callable | None = None,
        tool_loop_cb: Callable | None = None,
        auth_store: Any | None = None,  # AuthProfileStore — lazy import to avoid circular
    ) -> None:
        self._router = router
        self._max_attempts = max(1, max_attempts)
        self._compact_fn = compact_fn
        self._tool_loop_cb = tool_loop_cb
        self._auth_store = auth_store

    @staticmethod
    def _is_context_overflow(error: Exception) -> bool:
        """Detect context overflow from error message heuristics.

        litellm maps context overflow to BadRequestError (FORMAT), so we
        inspect the message for common overflow indicators.
        """
        msg = str(error).lower()
        indicators = [
            "context_length_exceeded",
            "context length",
            "maximum context",
            "too many tokens",
            "token limit",
            "max_tokens",
            "content too large",
            "request too large",
        ]
        return any(ind in msg for ind in indicators)

    @staticmethod
    def _is_model_not_found(error: Exception) -> bool:
        """Detect model-not-found errors from message heuristics."""
        msg = str(error).lower()
        indicators = [
            "model_not_found",
            "model not found",
            "does not exist",
            "no such model",
            "invalid model",
            "unknown model",
        ]
        return any(ind in msg for ind in indicators)

    async def run(
        self,
        role: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResult:
        """Execute an LLM call with automatic retries and error-driven recovery.

        Args:
            role: The router role (e.g., "casual", "code", "vault").
            messages: The chat messages to send.
            **kwargs: Additional kwargs passed to _do_call (temperature, max_tokens).

        Returns:
            LLMResult with text and usage metadata.

        Raises:
            The last exception encountered if all attempts are exhausted.
        """
        last_error: Exception | None = None
        current_messages = list(messages)  # shallow copy — compact_fn may mutate
        server_error_retried = False

        # Select and apply the initial auth profile BEFORE the first call.
        # active_profile tracks which profile's credentials are in os.environ
        # so we report success/failure against the correct profile.
        active_profile = None
        if self._auth_store is not None:
            active_profile = self._auth_store.select_best(role)
            if active_profile is not None:
                self._router._apply_profile_credentials(active_profile, role)

        for attempt in range(self._max_attempts):
            try:
                response = await self._router._do_call(
                    role, current_messages, **kwargs
                )
                # Build LLMResult from raw response
                usage = getattr(response, "usage", None)
                result = LLMResult(
                    text=response.choices[0].message.content or "",
                    model=response.model or "unknown",
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    finish_reason=response.choices[0].finish_reason,
                )

                # Report success for the profile that actually handled the call
                if self._auth_store is not None and active_profile is not None:
                    self._auth_store.report_success(active_profile.id, model=role)

                if self._tool_loop_cb is not None:
                    self._tool_loop_cb(attempt, None)

                return result

            except Exception as exc:
                last_error = exc
                reason = classify_llm_error(exc)

                if self._tool_loop_cb is not None:
                    self._tool_loop_cb(attempt, exc)

                logger.warning(
                    "InferenceLoop attempt %d/%d for role=%s failed: %s (%s)",
                    attempt + 1,
                    self._max_attempts,
                    role,
                    reason.value,
                    exc,
                )

                # --- Context overflow (FORMAT with context cues) ---
                if reason == AuthProfileFailureReason.FORMAT and self._is_context_overflow(exc):
                    if self._compact_fn is not None:
                        logger.info("Context overflow — compacting messages")
                        current_messages = await self._compact_fn(current_messages)
                        continue
                    else:
                        logger.error("Context overflow but no compact_fn — raising")
                        raise

                # --- Model not found ---
                if reason == AuthProfileFailureReason.FORMAT and self._is_model_not_found(exc):
                    # Try fallback role if it exists, but don't retry
                    fallback_role = f"{role}_fallback"
                    try:
                        response = await self._router._do_call(
                            fallback_role, current_messages, **kwargs
                        )
                        usage = getattr(response, "usage", None)
                        return LLMResult(
                            text=response.choices[0].message.content or "",
                            model=response.model or "unknown",
                            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                            total_tokens=getattr(usage, "total_tokens", 0) or 0,
                            finish_reason=response.choices[0].finish_reason,
                        )
                    except Exception:
                        raise exc from None  # raise original model_not_found

                # --- Rate limited ---
                if reason == AuthProfileFailureReason.RATE_LIMIT:
                    if attempt < self._max_attempts - 1:
                        base_delay = 2 ** (attempt + 1)  # 2, 4, 8
                        jitter = random.uniform(0, base_delay * 0.5)
                        delay = base_delay + jitter
                        logger.info(
                            "Rate limited — backing off %.1fs before retry", delay
                        )
                        if self._auth_store is not None and active_profile is not None:
                            self._auth_store.report_failure(
                                active_profile.id,
                                AuthProfileFailureReason.RATE_LIMIT,
                                model=role,
                            )
                        await asyncio.sleep(delay)
                        continue
                    raise

                # --- Auth failed ---
                if reason == AuthProfileFailureReason.AUTH:
                    if self._auth_store is not None and active_profile is not None:
                        self._auth_store.report_failure(
                            active_profile.id,
                            AuthProfileFailureReason.AUTH,
                            model=role,
                        )
                        next_profile = self._auth_store.select_best(role)
                        if next_profile is not None:
                            active_profile = next_profile
                            self._router._apply_profile_credentials(
                                active_profile, role
                            )
                            logger.info(
                                "Auth failed — rotated to profile %s",
                                active_profile.id,
                            )
                            continue
                    raise

                # --- Server error / overloaded / timeout ---
                if reason in (
                    AuthProfileFailureReason.OVERLOADED,
                    AuthProfileFailureReason.TIMEOUT,
                ):
                    if not server_error_retried and attempt < self._max_attempts - 1:
                        server_error_retried = True
                        delay = 2.0 + random.uniform(0, 1.0)
                        logger.info(
                            "Server error — backing off %.1fs before single retry",
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

                # --- Non-retryable (FORMAT without context cues, BILLING, UNKNOWN) ---
                raise

        # All attempts exhausted
        if last_error is not None:
            raise last_error
        raise RuntimeError(
            f"InferenceLoop exhausted {self._max_attempts} attempts for role={role}"
        )
