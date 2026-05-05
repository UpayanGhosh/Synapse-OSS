"""Contract tests for Synapse LLM provider onboarding.

These tests do not call provider networks. They verify that every provider listed in
the onboarding UI has a coherent validation/auth contract, so production failures are
caught before a real user enters a key.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from cli import provider_steps


SPECIAL_PROVIDER_KEYS = {
    "ollama",
    "vllm",
    "bedrock",
    "vertex_ai",
    "github_copilot",
    "openai_codex",
    "google_antigravity",
    "claude_cli",
}


def test_provider_inventory_is_unique_and_accounted_for():
    grouped = [
        provider["key"]
        for group in provider_steps.PROVIDER_GROUPS
        for provider in group["providers"]
    ]

    assert provider_steps.PROVIDER_LIST == grouped
    assert len(grouped) == len(set(grouped))
    assert len(grouped) == 25

    accounted = (
        set(provider_steps.VALIDATION_MODELS)
        | set(provider_steps._KEY_MAP)
        | SPECIAL_PROVIDER_KEYS
    )
    assert set(provider_steps.PROVIDER_LIST) <= accounted


def test_every_api_key_provider_has_validation_model():
    missing = set(provider_steps._KEY_MAP) - set(provider_steps.VALIDATION_MODELS)
    assert not missing


def test_every_standard_validation_provider_has_key_mapping():
    standard_validation = set(provider_steps.VALIDATION_MODELS) - {"bedrock", "vertex_ai"}
    missing = standard_validation - set(provider_steps._KEY_MAP)
    assert not missing


@pytest.mark.parametrize(
    "provider",
    sorted(set(provider_steps.VALIDATION_MODELS) - {"bedrock", "vertex_ai"}),
)
def test_validate_provider_sets_expected_env_and_litellm_contract(provider, monkeypatch):
    env_var = provider_steps._KEY_MAP[provider]
    monkeypatch.delenv(env_var, raising=False)
    captured_env = {}

    async def fake_acompletion(**kwargs):
        captured_env[env_var] = os.environ.get(env_var)
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch("litellm.acompletion", new=AsyncMock(side_effect=fake_acompletion)) as mocked:
        result = provider_steps.validate_provider(provider, "test-key")

    assert result.ok is True
    assert captured_env[env_var] == "test-key"
    assert os.environ.get(env_var) is None

    call = mocked.await_args.kwargs
    assert call["model"] == provider_steps.VALIDATION_MODELS[provider]
    assert call["messages"] == [{"role": "user", "content": "Hi"}]
    assert call["max_tokens"] == 1
    assert call["timeout"] == 5.0
    assert call["num_retries"] == 0


@pytest.mark.parametrize("provider", ["bedrock", "vertex_ai"])
def test_validate_provider_supports_multi_field_auth_providers(provider):
    with patch("litellm.acompletion", new=AsyncMock(return_value={})):
        result = provider_steps.validate_provider(provider, "ignored-by-contract")

    assert result.ok is True


def test_validate_provider_restores_preexisting_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "original")

    with patch("litellm.acompletion", new=AsyncMock(return_value={})):
        result = provider_steps.validate_provider("openai", "temporary")

    assert result.ok is True
    assert os.environ["OPENAI_API_KEY"] == "original"


def test_router_key_injection_covers_onboarding_provider_shapes(monkeypatch):
    from sci_fi_dashboard.llm_router import _inject_provider_keys

    env_names = set(provider_steps._KEY_MAP.values()) | {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION_NAME",
        "VERTEXAI_PROJECT",
        "VERTEXAI_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "QIANFAN_AK",
        "QIANFAN_SK",
    }
    for env_name in env_names:
        monkeypatch.delenv(env_name, raising=False)

    providers = {
        provider: {"api_key": f"{provider}-key"}
        for provider in provider_steps._KEY_MAP
        if provider != "qianfan"
    }
    providers["qianfan"] = {
        "api_key": "qianfan-ak",
        "access_key": "qianfan-ak",
        "secret_key": "qianfan-sk",
    }
    providers["bedrock"] = {
        "aws_access_key_id": "aws-ak",
        "aws_secret_access_key": "aws-sk",
        "aws_region_name": "us-east-1",
    }
    providers["vertex_ai"] = {
        "project_id": "gcp-project",
        "location": "us-central1",
        "credentials_path": "/tmp/service-account.json",
    }

    _inject_provider_keys(providers)

    for provider, env_name in provider_steps._KEY_MAP.items():
        expected = "qianfan-ak" if provider == "qianfan" else f"{provider}-key"
        assert os.environ[env_name] == expected
    assert os.environ["QIANFAN_SK"] == "qianfan-sk"
    assert os.environ["AWS_ACCESS_KEY_ID"] == "aws-ak"
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "aws-sk"
    assert os.environ["AWS_REGION_NAME"] == "us-east-1"
    assert os.environ["VERTEXAI_PROJECT"] == "gcp-project"
    assert os.environ["VERTEXAI_LOCATION"] == "us-central1"
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/tmp/service-account.json"
