"""
SynapseLLMRouter — unified litellm.Router dispatch layer.

Replaces call_gemini_direct() and _call_antigravity().
All LLM calls go through router.acompletion() using provider-prefixed model strings
from synapse.json model_mappings. No hardcoded model strings in this file.
"""

import logging
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from enum import StrEnum

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

        if primary_model.startswith(_GITHUB_COPILOT_PREFIX):
            litellm_params = _copilot_litellm_params(
                primary_model[len(_GITHUB_COPILOT_PREFIX):]
            )
        elif primary_model.startswith(_OLLAMA_CHAT_PREFIX):
            litellm_params = {"model": primary_model, "timeout": 60, "stream": False}
            litellm_params["api_base"] = ollama_api_base
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
            if fallback_model.startswith(_GITHUB_COPILOT_PREFIX):
                fallback_params = _copilot_litellm_params(
                    fallback_model[len(_GITHUB_COPILOT_PREFIX):]
                )
            else:
                fallback_params = {"model": fallback_model, "timeout": 60, "stream": False}
                if fallback_model.startswith(_OLLAMA_CHAT_PREFIX):
                    fallback_params["api_base"] = ollama_api_base
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
        logger.info(
            "SynapseLLMRouter initialized with %d roles",
            len(self._config.model_mappings),
        )

    def _rebuild_router(self) -> None:
        """Rebuild the litellm Router (e.g. after a Copilot token refresh)."""
        self._router = build_router(self._config.model_mappings, self._config.providers)
        logger.info("Router rebuilt with fresh credentials")

    async def _do_call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ):
        """
        Internal: route to the litellm model for the given role and return the raw
        litellm response object. Handles error classification and session tracking.
        """
        try:
            response = await self._router.acompletion(
                model=role,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
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
            if self._uses_copilot and "forbidden" in str(exc).lower():
                logger.warning("Copilot token rejected — refreshing and retrying")
                _get_copilot_token()  # triggers Authenticator refresh
                self._rebuild_router()
                return await self._router.acompletion(
                    model=role,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            raise

    async def call(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """
        Route to the litellm model for the given role (e.g., 'casual', 'vault').
        Falls back to fallback model on AuthenticationError or RateLimitError.
        Returns extracted text string; raises on unrecoverable errors.

        stream=False enforced — Phase 2 does not stream (see 02-RESEARCH.md Pitfall 4).
        """
        response = await self._do_call(role, messages, temperature, max_tokens)
        return response.choices[0].message.content or ""

    async def call_with_metadata(
        self,
        role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResult:
        """
        Same as call() but returns an LLMResult with text + usage metadata.
        """
        response = await self._do_call(role, messages, temperature, max_tokens)
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
