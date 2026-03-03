"""
SynapseLLMRouter — unified litellm.Router dispatch layer.

Replaces OpenClaw proxy (port 8080), call_gemini_direct(), and _call_antigravity().
All LLM calls go through router.acompletion() using provider-prefixed model strings
from synapse.json model_mappings. No hardcoded model strings in this file.
"""

import logging
import os
import sqlite3
import sys
import uuid

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

        # Ollama: validate prefix and inject api_base
        litellm_params: dict = {"model": primary_model, "timeout": 60, "stream": False}
        if primary_model.startswith(_OLLAMA_CHAT_PREFIX):
            litellm_params["api_base"] = ollama_api_base
        elif primary_model.startswith("ollama/"):
            raise ValueError(
                f"Role '{role}' uses ollama/ prefix — must be {_OLLAMA_CHAT_PREFIX} for chat calls. "
                f"Got: {primary_model}"
            )
        elif primary_model.startswith("hosted_vllm/"):
            litellm_params["api_base"] = vllm_api_base
        elif primary_model.startswith("openai/") and providers.get("qianfan") and role == "qianfan":
            # Baidu Qianfan uses openai/ + api_base override
            # Only applied when provider config is "qianfan" role
            litellm_params["api_base"] = qianfan_api_base

        model_list.append({"model_name": role, "litellm_params": litellm_params})

        # Fallback model (optional)
        fallback_model = cfg.get("fallback")
        if fallback_model:
            fallback_role = f"{role}_fallback"
            fallback_params: dict = {"model": fallback_model, "timeout": 60, "stream": False}
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
        logger.info(
            "SynapseLLMRouter initialized with %d roles",
            len(self._config.model_mappings),
        )

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
            text = choice.message.content or ""
            # SESS-01: Write token usage to sessions table (non-fatal side effect)
            try:
                _write_session(
                    role=role,
                    model=response.model or role,
                    usage=getattr(response, "usage", None),
                )
            except Exception as session_exc:
                logger.debug("Session write failed (non-fatal): %s", session_exc)
            return text
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
