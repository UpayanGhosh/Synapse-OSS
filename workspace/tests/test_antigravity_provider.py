import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard import antigravity_provider as ag
from sci_fi_dashboard.google_oauth import GoogleAntigravityCredentials


@pytest.mark.parametrize(
    ("model", "api_model", "thinking_level"),
    [
        ("google_antigravity/gemini-3-pro", "gemini-3.1-pro-preview", "LOW"),
        ("google_antigravity/gemini-3.1-pro", "gemini-3.1-pro-preview", "LOW"),
        ("google_antigravity/gemini-3-pro-low", "gemini-3.1-pro-preview", "LOW"),
        ("google_antigravity/gemini-3-pro-high", "gemini-3.1-pro-preview", "HIGH"),
        ("google_antigravity/gemini-3-flash", "gemini-3-flash-preview", None),
        ("google_antigravity/gemini-3-flash-lite", "gemini-3-flash-preview", "LOW"),
    ],
)
def test_resolve_model_with_thinking(model, api_model, thinking_level):
    resolution = ag.resolve_model_with_thinking(model)

    assert resolution.api_model == api_model
    assert resolution.thinking_level == thinking_level


def test_clean_tool_schema_for_gemini_matches_cloud_code_assist_limits():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "definitions": {"unused": {"type": "string"}},
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 20,
                "pattern": "^[a-z]+$",
                "format": "hostname",
                "default": "synapse",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "multipleOf": 1,
            },
            "tags": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "uniqueItems": True,
                "items": {"type": "string", "examples": ["a"]},
            },
            "nested": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 2,
                "$defs": {"bad": {"type": "string"}},
                "properties": {"name": {"type": "string", "$ref": "#/$defs/bad"}},
            },
        },
        "required": ["query"],
    }

    cleaned = ag.clean_tool_schema_for_gemini(schema)

    assert cleaned["type"] == "object"
    assert cleaned["required"] == ["query"]
    assert schema["additionalProperties"] is False

    serialized = json.dumps(cleaned)
    for unsupported_key in [
        "additionalProperties",
        "definitions",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "default",
        "minimum",
        "maximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "$defs",
        "$ref",
        "examples",
    ]:
        assert f'"{unsupported_key}"' not in serialized


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, *, headers, content):
        self.calls.append({"url": url, "headers": headers, "content": content})
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_chat_completion_uses_codeassist_envelope_g1_credits_and_refresh_retry(
    monkeypatch,
):
    old_creds = GoogleAntigravityCredentials(
        access_token="old-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        project_id="old-project",
        email="user@example.com",
        tier="standard-tier",
    )
    new_creds = GoogleAntigravityCredentials(
        access_token="new-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        project_id="new-project",
        email="user@example.com",
        tier="standard-tier",
    )
    saved = []

    monkeypatch.setattr(ag.google_oauth, "load_credentials", lambda: old_creds)
    monkeypatch.setattr(ag.google_oauth, "refresh_access_token", lambda creds: new_creds)
    monkeypatch.setattr(ag.google_oauth, "save_credentials", lambda creds: saved.append(creds))

    fake_http = _FakeAsyncClient(
        [
            httpx.Response(401, json={"error": {"message": "expired"}}),
            httpx.Response(
                200,
                json={
                    "response": {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": "ok"},
                                        {
                                            "functionCall": {
                                                "name": "lookup",
                                                "args": {"q": "synapse"},
                                            }
                                        },
                                    ]
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 3,
                            "candidatesTokenCount": 4,
                            "totalTokenCount": 7,
                        },
                    }
                },
            ),
        ]
    )
    client = ag.AntigravityClient(http_client=fake_http)

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Use lookup."},
        ],
        model="google_antigravity/gemini-3-pro",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"q": {"type": "string", "minLength": 1}},
                    },
                },
            }
        ],
        temperature=0,
        top_p=0.5,
        max_tokens=256,
        stop=["END"],
    )

    assert result.text == "ok"
    assert result.model == "gemini-3.1-pro-preview"
    assert result.finish_reason == "stop"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 4
    assert result.total_tokens == 7
    assert result.tool_calls[0]["name"] == "lookup"
    assert json.loads(result.tool_calls[0]["arguments"]) == {"q": "synapse"}

    assert saved == [new_creds]
    assert len(fake_http.calls) == 2
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer old-token"
    assert fake_http.calls[1]["headers"]["Authorization"] == "Bearer new-token"
    assert fake_http.calls[0]["headers"]["User-Agent"] == ag.USER_AGENT
    assert fake_http.calls[0]["url"].endswith("/v1internal:generateContent")

    first_payload = json.loads(fake_http.calls[0]["content"])
    second_payload = json.loads(fake_http.calls[1]["content"])
    assert first_payload["model"] == "gemini-3.1-pro-preview"
    assert first_payload["project"] == "old-project"
    assert second_payload["project"] == "new-project"
    assert first_payload["enabled_credit_types"] == [ag.G1_CREDIT_TYPE]
    assert first_payload["request"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW"
    }
    assert first_payload["request"]["generationConfig"]["maxOutputTokens"] == 256
    assert first_payload["request"]["generationConfig"]["stopSequences"] == ["END"]
    assert first_payload["request"]["systemInstruction"]["parts"][0]["text"] == "Be terse."

    parameters = first_payload["request"]["tools"][0]["functionDeclarations"][0]["parameters"]
    serialized_parameters = json.dumps(parameters)
    assert '"additionalProperties"' not in serialized_parameters
    assert '"minLength"' not in serialized_parameters
