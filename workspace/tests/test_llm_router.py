"""
test_llm_router.py — RED phase test scaffold for LLM-01 through LLM-18

All tests in this file are SKIPPED until Plan 02 creates
workspace/sci_fi_dashboard/llm_router.py with SynapseLLMRouter.

Once the router exists (GREEN phase), the pytestmark skipif guard is removed
and all tests must pass against the real implementation.

Requirements covered:
  LLM-01: litellm.acompletion() is the sole LLM call site (not urllib/requests)
  LLM-02: Anthropic provider uses "anthropic/" prefix
  LLM-03: OpenAI provider uses "openai/" prefix
  LLM-04: Gemini provider uses "gemini/" prefix
  LLM-05: Groq provider uses "groq/" prefix
  LLM-06: Ollama provider uses "ollama_chat/" prefix (NOT "ollama/")
  LLM-07: OpenRouter provider uses "openrouter/" prefix
  LLM-08: Mistral provider uses "mistral/" prefix
  LLM-09: Together AI provider uses "together_ai/" prefix
  LLM-10: xAI (Grok) provider uses "xai/" prefix
  LLM-11: AWS Bedrock provider uses "bedrock/" prefix
  LLM-12: Zhipu Z.AI provider uses "zai/" prefix (NOT "zhipu/")
  LLM-13: Volcengine provider uses "volcengine/" prefix
  LLM-14: Hosted vLLM provider uses "hosted_vllm/" prefix
  LLM-15: GitHub Copilot provider uses "github_copilot/" prefix
  LLM-16: No hardcoded model strings remain in workspace/sci_fi_dashboard/ or workspace/skills/
  LLM-17: AuthenticationError and RateLimitError both trigger fallback provider
  LLM-18: Routing selects correct model role (casual, vault)
"""

import subprocess
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd (mirrors test_config.py)
sys.path.insert(0, str(Path(__file__).parent.parent))

from synapse_config import SynapseConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Conditional import: RED phase guard
#
# Until Plan 02 creates sci_fi_dashboard/llm_router.py, ROUTER_AVAILABLE=False
# and all tests in this file are skipped.  That is the correct RED state.
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.llm_router import SynapseLLMRouter, build_router, _inject_provider_keys

    ROUTER_AVAILABLE = True
except ImportError:
    ROUTER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not ROUTER_AVAILABLE,
    reason="SynapseLLMRouter not yet implemented — RED phase (Plan 02 will create it)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(__file__).parent.parent.parent


def _make_config(role: str, model: str, fallback: str | None = None) -> SynapseConfig:
    """Build a minimal SynapseConfig with a single model_mappings entry for testing."""
    return SynapseConfig(
        data_root=Path("/tmp/synapse_test"),
        db_dir=Path("/tmp/synapse_test/workspace/db"),
        sbs_dir=Path("/tmp/synapse_test/workspace/sci_fi_dashboard/synapse_data"),
        log_dir=Path("/tmp/synapse_test/logs"),
        providers={},
        channels={},
        model_mappings={
            role: {"model": model, "fallback": fallback},
        },
    )


def _get_model_arg(mock_acompletion) -> str:
    """Extract the 'model' keyword argument from the first call to mock_acompletion."""
    call_kwargs = mock_acompletion.call_args
    if call_kwargs is None:
        raise AssertionError("litellm.acompletion was never called")
    # acompletion(model=..., messages=...) — keyword call
    if call_kwargs.kwargs:
        return call_kwargs.kwargs.get("model", call_kwargs.args[0] if call_kwargs.args else "")
    return call_kwargs.args[0] if call_kwargs.args else ""


_TEST_MESSAGES = [{"role": "user", "content": "Hello"}]


# ---------------------------------------------------------------------------
# LLM-01: litellm.acompletion is the call site
# ---------------------------------------------------------------------------


async def test_acompletion_called(mock_acompletion):
    """LLM-01: SynapseLLMRouter.call() must use litellm.acompletion (not urllib/requests)."""
    config = _make_config("casual", "gemini/gemini-2.0-flash", "groq/llama-3.3-70b-versatile")
    router = SynapseLLMRouter(config)
    await router.call("casual", _TEST_MESSAGES)
    assert mock_acompletion.called is True, (
        "litellm.acompletion must be called — no urllib.request or requests.post allowed"
    )


# ---------------------------------------------------------------------------
# LLM-02 through LLM-15: Provider prefix assertions
# ---------------------------------------------------------------------------


async def test_anthropic_prefix(mock_acompletion):
    """LLM-02: Anthropic model string must start with 'anthropic/'."""
    config = _make_config("code", "anthropic/claude-sonnet-4-6", "openai/gpt-4o")
    router = SynapseLLMRouter(config)
    await router.call("code", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("anthropic/"), f"Expected 'anthropic/' prefix, got: {model!r}"


async def test_openai_prefix(mock_acompletion):
    """LLM-03: OpenAI model string must start with 'openai/'."""
    config = _make_config("review", "openai/gpt-4o", "anthropic/claude-haiku-4-5")
    router = SynapseLLMRouter(config)
    await router.call("review", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("openai/"), f"Expected 'openai/' prefix, got: {model!r}"


async def test_gemini_prefix(mock_acompletion):
    """LLM-04: Gemini model string must start with 'gemini/'."""
    config = _make_config("casual", "gemini/gemini-2.0-flash", "groq/llama-3.3-70b-versatile")
    router = SynapseLLMRouter(config)
    await router.call("casual", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("gemini/"), f"Expected 'gemini/' prefix, got: {model!r}"


async def test_groq_prefix(mock_acompletion):
    """LLM-05: Groq model string must start with 'groq/'."""
    config = _make_config("fast", "groq/llama-3.3-70b-versatile", None)
    router = SynapseLLMRouter(config)
    await router.call("fast", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("groq/"), f"Expected 'groq/' prefix, got: {model!r}"


async def test_ollama_chat_prefix(mock_acompletion):
    """LLM-06: Ollama model must use 'ollama_chat/' prefix — NOT bare 'ollama/'.

    litellm distinguishes these: 'ollama/' uses the /api/generate endpoint (non-chat),
    while 'ollama_chat/' uses /api/chat (structured messages).  Using 'ollama/' would
    break multi-turn conversation support.
    """
    config = _make_config("vault", "ollama_chat/stheno:latest", None)
    router = SynapseLLMRouter(config)
    await router.call("vault", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("ollama_chat/"), (
        f"Ollama must use 'ollama_chat/' prefix (not 'ollama/'), got: {model!r}"
    )
    assert not model.startswith("ollama/"), (
        f"Must NOT use bare 'ollama/' prefix — breaks chat format, got: {model!r}"
    )


async def test_openrouter_prefix(mock_acompletion):
    """LLM-07: OpenRouter model string must start with 'openrouter/'."""
    config = _make_config("fallback", "openrouter/auto", None)
    router = SynapseLLMRouter(config)
    await router.call("fallback", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("openrouter/"), f"Expected 'openrouter/' prefix, got: {model!r}"


async def test_mistral_prefix(mock_acompletion):
    """LLM-08: Mistral model string must start with 'mistral/'."""
    config = _make_config("creative", "mistral/mistral-large-latest", None)
    router = SynapseLLMRouter(config)
    await router.call("creative", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("mistral/"), f"Expected 'mistral/' prefix, got: {model!r}"


async def test_togetherai_prefix(mock_acompletion):
    """LLM-09: Together AI model string must start with 'together_ai/'."""
    config = _make_config("together", "together_ai/meta-llama/Llama-3-70b-chat-hf", None)
    router = SynapseLLMRouter(config)
    await router.call("together", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("together_ai/"), f"Expected 'together_ai/' prefix, got: {model!r}"


async def test_xai_prefix(mock_acompletion):
    """LLM-10: xAI (Grok) model string must start with 'xai/'."""
    config = _make_config("grok", "xai/grok-2-latest", None)
    router = SynapseLLMRouter(config)
    await router.call("grok", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("xai/"), f"Expected 'xai/' prefix, got: {model!r}"


async def test_bedrock_prefix(mock_acompletion):
    """LLM-11: AWS Bedrock model string must start with 'bedrock/'."""
    config = _make_config(
        "bedrock_role",
        "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
        None,
    )
    router = SynapseLLMRouter(config)
    await router.call("bedrock_role", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("bedrock/"), f"Expected 'bedrock/' prefix, got: {model!r}"


async def test_zai_prefix(mock_acompletion):
    """LLM-12: Zhipu Z.AI model string must start with 'zai/' — NOT 'zhipu/'.

    litellm's provider prefix for Zhipu AI is 'zai/', not 'zhipu/'.
    Using 'zhipu/' would cause a ProviderNotFoundException at runtime.
    """
    config = _make_config("zhipu", "zai/glm-4-plus", None)
    router = SynapseLLMRouter(config)
    await router.call("zhipu", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("zai/"), (
        f"Zhipu Z.AI must use 'zai/' prefix (not 'zhipu/'), got: {model!r}"
    )
    assert not model.startswith("zhipu/"), (
        f"Must NOT use 'zhipu/' prefix — use 'zai/' for litellm compatibility, got: {model!r}"
    )


async def test_volcengine_prefix(mock_acompletion):
    """LLM-13: Volcengine (Doubao) model string must start with 'volcengine/'."""
    config = _make_config("doubao", "volcengine/doubao-pro-4k", None)
    router = SynapseLLMRouter(config)
    await router.call("doubao", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("volcengine/"), f"Expected 'volcengine/' prefix, got: {model!r}"


async def test_hosted_vllm_prefix(mock_acompletion):
    """LLM-14: Hosted vLLM model string must start with 'hosted_vllm/'."""
    config = _make_config("vllm_role", "hosted_vllm/my-model", None)
    router = SynapseLLMRouter(config)
    await router.call("vllm_role", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("hosted_vllm/"), f"Expected 'hosted_vllm/' prefix, got: {model!r}"


async def test_github_copilot_prefix(mock_acompletion):
    """LLM-15: GitHub Copilot model string must start with 'github_copilot/'."""
    config = _make_config("copilot", "github_copilot/gpt-4o", None)
    router = SynapseLLMRouter(config)
    await router.call("copilot", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("github_copilot/"), (
        f"Expected 'github_copilot/' prefix, got: {model!r}"
    )


# ---------------------------------------------------------------------------
# LLM-16: No hardcoded model strings in source (xfail until Plan 04)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "LLM-16: Hardcoded model strings will be replaced in Plan 04 (sweep call sites). "
        "This test is expected to fail until Plan 04 completes the migration."
    ),
    strict=False,
)
def test_no_hardcoded_models():
    """LLM-16: No hardcoded litellm model strings in workspace/sci_fi_dashboard/ or workspace/skills/.

    Checks for common provider prefixes embedded directly in Python source files.
    After Plan 04, all call sites must read from SynapseConfig.model_mappings — zero
    hardcoded strings should remain.
    """
    workspace_root = Path(__file__).parent.parent
    sci_fi_dir = workspace_root / "sci_fi_dashboard"
    skills_dir = workspace_root / "skills"

    # Patterns that represent hardcoded litellm model strings in Python source
    patterns = [
        r"anthropic/claude",
        r"gemini/gemini",
        r"groq/llama",
        r"ollama_chat/",
        r"openai/gpt",
        r"openrouter/",
        r"mistral/mistral",
    ]

    found_hardcoded = []
    for search_dir in [sci_fi_dir, skills_dir]:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            result = subprocess.run(
                ["grep", "-r", "--include=*.py", "-l", pattern, str(search_dir)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                found_hardcoded.append(
                    f"Pattern '{pattern}' found in: {result.stdout.strip()}"
                )

    assert not found_hardcoded, (
        "Hardcoded LLM model strings found — Plan 04 must replace these with "
        "SynapseConfig.model_mappings lookups:\n" + "\n".join(found_hardcoded)
    )


# ---------------------------------------------------------------------------
# LLM-17: Fallback on AuthenticationError and RateLimitError
# ---------------------------------------------------------------------------


async def test_fallback_on_auth_error(mock_acompletion):
    """LLM-17a: When primary model raises AuthenticationError, router must call fallback model."""
    import litellm

    primary_model = "gemini/gemini-2.0-flash"
    fallback_model = "groq/llama-3.3-70b-versatile"
    config = _make_config("casual", primary_model, fallback_model)
    router = SynapseLLMRouter(config)

    # First call raises AuthenticationError; second call (fallback) succeeds
    mock_acompletion.side_effect = [
        litellm.AuthenticationError(
            message="Invalid API key",
            llm_provider="gemini",
            model=primary_model,
        ),
        mock_acompletion.return_value,
    ]
    # Reset side_effect return value — second call uses return_value
    mock_acompletion.return_value = unittest_mock_make_response()

    await router.call("casual", _TEST_MESSAGES)

    assert mock_acompletion.call_count == 2, (
        f"Expected 2 calls (primary + fallback), got {mock_acompletion.call_count}"
    )
    second_call_model = mock_acompletion.call_args_list[1].kwargs.get(
        "model",
        mock_acompletion.call_args_list[1].args[0] if mock_acompletion.call_args_list[1].args else "",
    )
    assert second_call_model.startswith("groq/"), (
        f"Fallback must use groq/ model, got: {second_call_model!r}"
    )


async def test_fallback_on_rate_limit(mock_acompletion):
    """LLM-17b: When primary model raises RateLimitError, router must call fallback model."""
    import litellm

    primary_model = "anthropic/claude-sonnet-4-6"
    fallback_model = "openai/gpt-4o"
    config = _make_config("code", primary_model, fallback_model)
    router = SynapseLLMRouter(config)

    mock_acompletion.side_effect = [
        litellm.RateLimitError(
            message="Rate limit exceeded",
            llm_provider="anthropic",
            model=primary_model,
        ),
        mock_acompletion.return_value,
    ]
    mock_acompletion.return_value = unittest_mock_make_response()

    await router.call("code", _TEST_MESSAGES)

    assert mock_acompletion.call_count == 2, (
        f"Expected 2 calls (primary + fallback), got {mock_acompletion.call_count}"
    )
    second_call_model = mock_acompletion.call_args_list[1].kwargs.get(
        "model",
        mock_acompletion.call_args_list[1].args[0] if mock_acompletion.call_args_list[1].args else "",
    )
    assert second_call_model.startswith("openai/"), (
        f"Fallback must use openai/ model, got: {second_call_model!r}"
    )


# ---------------------------------------------------------------------------
# LLM-18: Role-based routing
# ---------------------------------------------------------------------------


async def test_casual_route(mock_acompletion):
    """LLM-18a: SynapseLLMRouter called with role='casual' must use model_mappings['casual']['model']."""
    config = SynapseConfig(
        data_root=Path("/tmp/synapse_test"),
        db_dir=Path("/tmp/synapse_test/workspace/db"),
        sbs_dir=Path("/tmp/synapse_test/workspace/sci_fi_dashboard/synapse_data"),
        log_dir=Path("/tmp/synapse_test/logs"),
        providers={},
        channels={},
        model_mappings={
            "casual": {"model": "gemini/gemini-2.0-flash", "fallback": "groq/llama-3.3-70b-versatile"},
            "vault": {"model": "ollama_chat/stheno:latest", "fallback": None},
        },
    )
    router = SynapseLLMRouter(config)
    await router.call("casual", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model == "gemini/gemini-2.0-flash", (
        f"casual route must use gemini/gemini-2.0-flash from model_mappings, got: {model!r}"
    )


async def test_vault_route(mock_acompletion):
    """LLM-18b: SynapseLLMRouter called with role='vault' must use ollama_chat/ model."""
    config = SynapseConfig(
        data_root=Path("/tmp/synapse_test"),
        db_dir=Path("/tmp/synapse_test/workspace/db"),
        sbs_dir=Path("/tmp/synapse_test/workspace/sci_fi_dashboard/synapse_data"),
        log_dir=Path("/tmp/synapse_test/logs"),
        providers={},
        channels={},
        model_mappings={
            "casual": {"model": "gemini/gemini-2.0-flash", "fallback": "groq/llama-3.3-70b-versatile"},
            "vault": {"model": "ollama_chat/stheno:latest", "fallback": None},
        },
    )
    router = SynapseLLMRouter(config)
    await router.call("vault", _TEST_MESSAGES)
    model = _get_model_arg(mock_acompletion)
    assert model.startswith("ollama_chat/"), (
        f"vault route must use ollama_chat/ model, got: {model!r}"
    )


# ---------------------------------------------------------------------------
# Helper: build a mock response object (needed inside test bodies)
# ---------------------------------------------------------------------------


def unittest_mock_make_response():
    """Build a minimal mock litellm response for use as return_value."""
    import unittest.mock

    resp = unittest.mock.MagicMock()
    resp.choices = [unittest.mock.MagicMock()]
    resp.choices[0].message.content = "Hello from mock LLM"
    resp.choices[0].message.role = "assistant"
    resp.choices[0].finish_reason = "stop"
    return resp
