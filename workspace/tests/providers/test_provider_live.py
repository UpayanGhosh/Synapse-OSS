"""Opt-in live smoke tests for LLM providers.

These tests intentionally skip by default. Run them only when you want to spend real
provider quota and have credentials in the environment:

    pytest workspace/tests/providers/test_provider_live.py --run-live-providers
    pytest workspace/tests/providers/test_provider_live.py --run-live-providers --live-provider gemini
"""

from __future__ import annotations

import os

import pytest

from cli import provider_steps


STANDARD_LIVE_PROVIDERS = sorted(
    set(provider_steps.VALIDATION_MODELS) - {"bedrock", "vertex_ai"}
)


def _configured_provider(provider: str) -> dict:
    try:
        from synapse_config import SynapseConfig

        cfg = SynapseConfig.load()
    except Exception:
        return {}
    provider_cfg = (getattr(cfg, "providers", None) or {}).get(provider) or {}
    return provider_cfg if isinstance(provider_cfg, dict) else {"api_key": str(provider_cfg)}


def _standard_api_key(provider: str) -> str:
    env_var = provider_steps._KEY_MAP[provider]
    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        return env_value
    return str(_configured_provider(provider).get("api_key") or "").strip()


def _provider_secret(provider: str, env_var: str, config_key: str) -> str:
    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        return env_value
    return str(_configured_provider(provider).get(config_key) or "").strip()


def _selected(pytestconfig, provider: str) -> bool:
    selected = set(pytestconfig.getoption("--live-provider") or [])
    return not selected or provider in selected


def _explicitly_selected(pytestconfig, provider: str) -> bool:
    return provider in set(pytestconfig.getoption("--live-provider") or [])


def _skip_unselected(pytestconfig, provider: str) -> None:
    if not _selected(pytestconfig, provider):
        pytest.skip(f"live provider {provider!r} not selected")


@pytest.mark.live_provider
@pytest.mark.parametrize("provider", STANDARD_LIVE_PROVIDERS)
def test_live_standard_provider_validation(provider, pytestconfig, monkeypatch):
    _skip_unselected(pytestconfig, provider)
    env_var = provider_steps._KEY_MAP[provider]
    api_key = _standard_api_key(provider)
    if not api_key:
        pytest.skip(f"{env_var} not set and providers.{provider}.api_key missing")

    if provider == "qianfan":
        secret_key = _provider_secret("qianfan", "QIANFAN_SK", "secret_key")
        if not secret_key:
            pytest.skip("QIANFAN_SK not set and providers.qianfan.secret_key missing")
        monkeypatch.setenv("QIANFAN_SK", secret_key)

    result = provider_steps.validate_provider(provider, api_key)

    assert result.ok, f"{provider} live validation failed: {result.error} {result.detail}"


@pytest.mark.live_provider
def test_live_bedrock_validation(pytestconfig):
    provider = "bedrock"
    _skip_unselected(pytestconfig, provider)
    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"missing env vars: {', '.join(missing)}")

    result = provider_steps.validate_provider(provider, os.environ["AWS_ACCESS_KEY_ID"])

    assert result.ok, f"bedrock live validation failed: {result.error} {result.detail}"


@pytest.mark.live_provider
def test_live_vertex_ai_validation(pytestconfig):
    provider = "vertex_ai"
    _skip_unselected(pytestconfig, provider)
    required = ["VERTEXAI_PROJECT", "VERTEXAI_LOCATION"]
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"missing env vars: {', '.join(missing)}")
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
        pytest.skip("GOOGLE_APPLICATION_CREDENTIALS not set")

    result = provider_steps.validate_provider(provider, os.environ["VERTEXAI_PROJECT"])

    assert result.ok, f"vertex_ai live validation failed: {result.error} {result.detail}"


@pytest.mark.live_provider
def test_live_ollama_validation(pytestconfig):
    provider = "ollama"
    _skip_unselected(pytestconfig, provider)

    result = provider_steps.validate_ollama(os.environ.get("OLLAMA_API_BASE"))
    if result.error == "not_running" and not _explicitly_selected(pytestconfig, provider):
        pytest.skip(result.detail)

    assert result.ok, f"ollama live validation failed: {result.error} {result.detail}"
