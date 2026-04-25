"""
antigravity_provider.py — Google Antigravity / Gemini CLI inference client.

Posts to ``cloudcode-pa.googleapis.com/v1internal:generateContent`` (the
CodeAssist endpoint, same one the official ``gemini`` CLI hits) using the
OAuth bearer token captured by ``google_oauth.py``. Wraps the Gemini request
in the CodeAssist envelope ``{model, project, user_prompt_id, request: {...}}``
required by ``v1internal:generateContent`` — bare-body shapes targeted at
``generativelanguage.googleapis.com`` will not work for OAuth identities.

Translates OpenAI-format messages and tools into the inner Gemini request
(contents, systemInstruction?, tools?, toolConfig?, generationConfig?,
session_id), then translates the response back into Synapse's ``LLMResult`` /
``LLMToolResult`` shape so the rest of the chat pipeline doesn't care what
provider it came from.

Pro reasoning level is selected by suffix: ``gemini-3-pro-low`` →
``thinkingConfig.thinkingLevel = "LOW"``, ``gemini-3-pro-high`` → ``"HIGH"``.
Both resolve to the same API model ID (``gemini-3.1-pro-preview``).

Auto-refreshes the access token on 401/403 with a single retry. Maps quota
errors to ``litellm.RateLimitError`` so the existing ``InferenceLoop`` retry
+ fallback logic catches them naturally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

try:
    from litellm import (
        APIConnectionError,
        AuthenticationError,
        BadRequestError,
        RateLimitError,
        ServiceUnavailableError,
    )
except ImportError:  # pragma: no cover — litellm is a hard dep
    APIConnectionError = AuthenticationError = BadRequestError = Exception  # type: ignore[misc,assignment]
    RateLimitError = ServiceUnavailableError = Exception  # type: ignore[misc,assignment]

from sci_fi_dashboard import google_oauth
from sci_fi_dashboard.google_oauth import (
    CODE_ASSIST_ENDPOINT_PROD,
    GoogleAntigravityCredentials,
)

_logger = logging.getLogger(__name__)

# API model IDs that the CodeAssist v1internal endpoint actually accepts.
# Verified live (2026-04-26): only the ``-preview``-suffixed IDs return 200;
# bare ``gemini-3-pro``, ``gemini-3.1-pro``, and ``gemini-3.1-flash-preview``
# return 404 NOT_FOUND. Reasoning level for Pro is controlled by
# ``generationConfig.thinkingConfig.thinkingLevel`` (LOW / HIGH), not by the
# model id, so ``-low``/``-high`` suffixes never reach the wire.
_PRO_API_MODEL = "gemini-3.1-pro-preview"
_FLASH_API_MODEL = "gemini-3-flash-preview"

_PRO_USER_IDS = frozenset(
    {
        "gemini-3-pro",
        "gemini-3.1-pro",
        "gemini-3-1-pro",
        "gemini-3-pro-low",
        "gemini-3.1-pro-low",
        "gemini-3-1-pro-low",
        "gemini-3-pro-high",
        "gemini-3.1-pro-high",
        "gemini-3-1-pro-high",
        "gemini-3-pro-preview",
        "gemini-3.1-pro-preview",
    }
)
_FLASH_USER_IDS = frozenset(
    {
        "gemini-3-flash",
        "gemini-3.1-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-preview",
        "gemini-3-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-lite-preview",
        "gemini-3.1-flash-lite-preview",
    }
)

USER_AGENT = "google-api-nodejs-client/9.15.1"
GOOG_API_CLIENT = "gl-node/22.0.0"
CLIENT_METADATA = {
    "ideType": "IDE_UNSPECIFIED",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
}

# Credit types that route the request through the user's paid tier (Google
# One AI Pro / Antigravity Pro). Without this field the CodeAssist API bills
# against standard-tier quotas regardless of paidTier eligibility — which is
# why "free" Pro accounts hit Flash 429s after ~10-20 RPM.
# Reference: @google/gemini-cli code_assist/server.js — `G1_CREDIT_TYPE`
# and ``enabled_credit_types`` field passed to ``toGenerateContentRequest``.
G1_CREDIT_TYPE = "GOOGLE_ONE_AI"

# Models that are eligible to consume G1 (Google One AI Pro) credits — i.e.
# requests with these model IDs may carry ``enabled_credit_types: [GOOGLE_ONE_AI]``
# to use the user's Pro entitlement. Mirrors ``OVERAGE_ELIGIBLE_MODELS`` in
# the Gemini CLI bundle.
_G1_OVERAGE_MODELS = frozenset(
    {
        _PRO_API_MODEL,           # gemini-3.1-pro-preview
        _FLASH_API_MODEL,          # gemini-3-flash-preview
        "gemini-3-pro-preview",    # legacy alias the CLI still recognises
    }
)
DEFAULT_TIMEOUT_SEC = 60.0


@dataclass
class AntigravityResponse:
    """Parsed response from a single CodeAssist :generateContent call."""

    text: str
    tool_calls: list[dict[str, Any]]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None


# ---------------------------------------------------------------------------
# Model id normalization
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelResolution:
    """API model id + optional reasoning level for a user-facing model name.

    Attributes:
        api_model:       The model id sent on the wire (e.g. ``gemini-3.1-pro-preview``).
        thinking_level:  ``"LOW"`` / ``"HIGH"`` / ``"MEDIUM"`` / ``"MINIMAL"`` or
                         ``None`` to let the server decide. Applied as
                         ``generationConfig.thinkingConfig.thinkingLevel`` on
                         Pro models.
    """

    api_model: str
    thinking_level: str | None


def resolve_model_with_thinking(prefixed: str) -> ModelResolution:
    """Translate a user-facing antigravity model name into (api_model, level).

    Both Pro reasoning levels collapse to the same wire model
    (``gemini-3.1-pro-preview``); the difference is communicated via
    ``thinkingConfig.thinkingLevel`` in ``generationConfig``. All Flash
    variants currently route to ``gemini-3-flash-preview`` since the API does
    not expose a separate flash-lite model id.
    """
    bare = prefixed.split("/", 1)[1] if "/" in prefixed else prefixed
    lower = bare.lower()

    if lower in _PRO_USER_IDS:
        if lower.endswith("-low"):
            return ModelResolution(_PRO_API_MODEL, "LOW")
        if lower.endswith("-high"):
            return ModelResolution(_PRO_API_MODEL, "HIGH")
        return ModelResolution(_PRO_API_MODEL, None)

    if lower in _FLASH_USER_IDS:
        if "flash-lite" in lower:
            return ModelResolution(_FLASH_API_MODEL, "LOW")
        return ModelResolution(_FLASH_API_MODEL, None)

    # Unknown id — pass through verbatim, no thinking config.
    return ModelResolution(bare, None)


def resolve_inference_model_id(prefixed: str) -> str:
    """Backward-compatible helper that returns just the API model id."""
    return resolve_model_with_thinking(prefixed).api_model


# ---------------------------------------------------------------------------
# Message translation: OpenAI format -> Gemini contents
# ---------------------------------------------------------------------------


def _flatten_message_content(content: Any) -> str:
    """Collapse OpenAI multipart content blocks into a single text string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            if isinstance(chunk, dict):
                if chunk.get("type") in ("text", None) and "text" in chunk:
                    parts.append(str(chunk["text"]))
                elif "content" in chunk:
                    parts.append(str(chunk["content"]))
            elif isinstance(chunk, str):
                parts.append(chunk)
        return "\n".join(p for p in parts if p)
    return str(content)


def _coerce_function_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def translate_messages_to_gemini(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Translate OpenAI-format messages into (contents, systemInstruction).

    System messages are concatenated into a single systemInstruction; user and
    assistant messages map to ``role = "user"`` / ``"model"``. Tool calls become
    ``functionCall`` parts on assistant turns; tool results become
    ``functionResponse`` parts on user turns.
    """
    contents: list[dict[str, Any]] = []
    system_chunks: list[str] = []

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            text = _flatten_message_content(msg.get("content"))
            if text:
                system_chunks.append(text)
            continue

        if role == "user":
            text = _flatten_message_content(msg.get("content"))
            contents.append({"role": "user", "parts": [{"text": text or ""}]})
            continue

        if role == "assistant":
            text = _flatten_message_content(msg.get("content"))
            tool_calls = msg.get("tool_calls") or []
            parts: list[dict[str, Any]] = []
            if text:
                parts.append({"text": text})
            for tc in tool_calls:
                fn = tc.get("function") or {}
                parts.append(
                    {
                        "functionCall": {
                            "name": fn.get("name", ""),
                            "args": _coerce_function_args(fn.get("arguments", "")),
                        }
                    }
                )
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            name = msg.get("name") or msg.get("tool_name") or ""
            raw_payload = msg.get("content")
            if isinstance(raw_payload, str):
                try:
                    response_payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    response_payload = {"output": raw_payload}
            elif isinstance(raw_payload, dict):
                response_payload = raw_payload
            else:
                response_payload = {"output": _flatten_message_content(raw_payload)}
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": name,
                                "response": response_payload,
                            }
                        }
                    ],
                }
            )
            continue

    system_instruction: dict[str, Any] | None = None
    if system_chunks:
        system_instruction = {"parts": [{"text": "\n\n".join(system_chunks)}]}
    return contents, system_instruction


_GEMINI_UNSUPPORTED_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "additionalProperties",
        "$ref",
        "patternProperties",
        "pattern",
        "format",
        "$schema",
        "$id",
        "examples",
        "default",
        "$defs",
    }
)


def clean_tool_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively strip JSON Schema keys that the Gemini API rejects.

    Returns a new deep-cleaned dict — the input is never mutated.
    Handles nested ``properties`` dicts and ``items`` arrays/dicts.
    """
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                prop_name: clean_tool_schema_for_gemini(prop_schema)
                if isinstance(prop_schema, dict)
                else prop_schema
                for prop_name, prop_schema in value.items()
            }
        elif key == "items":
            if isinstance(value, dict):
                cleaned[key] = clean_tool_schema_for_gemini(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    clean_tool_schema_for_gemini(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                cleaned[key] = value
        elif isinstance(value, dict):
            cleaned[key] = clean_tool_schema_for_gemini(value)
        else:
            cleaned[key] = value
    return cleaned


def translate_tools_to_gemini(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Convert OpenAI tool definitions into a Gemini ``tools`` array."""
    if not tools:
        return None
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        decl: dict[str, Any] = {"name": name}
        if "description" in fn:
            decl["description"] = fn["description"]
        params = fn.get("parameters")
        if isinstance(params, dict):
            decl["parameters"] = clean_tool_schema_for_gemini(params)
        declarations.append(decl)
    if not declarations:
        return None
    return [{"functionDeclarations": declarations}]


def build_generation_config(
    *,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    stop: list[str] | str | None,
) -> dict[str, Any] | None:
    """Build the optional generationConfig block for a CodeAssist request."""
    config: dict[str, Any] = {}
    if temperature is not None:
        config["temperature"] = float(temperature)
    if top_p is not None:
        config["topP"] = float(top_p)
    if max_tokens is not None:
        config["maxOutputTokens"] = int(max_tokens)
    if stop:
        if isinstance(stop, str):
            config["stopSequences"] = [stop]
        else:
            config["stopSequences"] = list(stop)
    return config or None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_response_payload(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> AntigravityResponse:
    """Parse a CodeAssist generateContent JSON payload into AntigravityResponse."""
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        # Some endpoints return the response shape inline instead of nested
        response = payload if isinstance(payload, dict) else {}

    candidates = response.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []

    text_chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if "text" in part and isinstance(part["text"], str):
            text_chunks.append(part["text"])
        elif "functionCall" in part and isinstance(part["functionCall"], dict):
            fc = part["functionCall"]
            name = str(fc.get("name", ""))
            args = fc.get("args", {})
            arguments = json.dumps(args) if isinstance(args, (dict, list)) else str(args)
            tool_calls.append(
                {
                    "id": f"call_{uuid4().hex[:8]}",
                    "name": name,
                    "arguments": arguments,
                }
            )

    finish_reason = candidate.get("finishReason")
    finish_reason = finish_reason.lower() if isinstance(finish_reason, str) else None

    usage = response.get("usageMetadata") or {}
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    completion_tokens = int(
        usage.get("candidatesTokenCount") or usage.get("outputTokenCount") or 0
    )
    total_tokens = int(usage.get("totalTokenCount") or (prompt_tokens + completion_tokens))

    return AntigravityResponse(
        text="".join(text_chunks),
        tool_calls=tool_calls,
        model=requested_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
    )


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


_QUOTA_HINTS = re.compile(r"quota|rate limit|too many requests|resource_exhausted", re.I)


def _raise_for_status(resp: httpx.Response, *, model: str) -> None:
    if resp.status_code < 400:
        return

    body = resp.text
    snippet = body[:512] if body else f"HTTP {resp.status_code}"

    if resp.status_code in (401, 403):
        raise AuthenticationError(
            message=f"Antigravity auth failed for {model}: {snippet}",
            llm_provider="google_antigravity",
            model=model,
        )
    if resp.status_code == 429 or _QUOTA_HINTS.search(body or ""):
        raise RateLimitError(
            message=f"Antigravity quota exceeded for {model}: {snippet}",
            llm_provider="google_antigravity",
            model=model,
        )
    if resp.status_code == 400:
        raise BadRequestError(
            message=f"Antigravity bad request for {model}: {snippet}",
            llm_provider="google_antigravity",
            model=model,
        )
    if resp.status_code >= 500:
        raise ServiceUnavailableError(
            message=f"Antigravity backend error for {model}: {snippet}",
            llm_provider="google_antigravity",
            model=model,
        )
    raise APIConnectionError(
        message=f"Antigravity unexpected status {resp.status_code} for {model}: {snippet}",
        llm_provider="google_antigravity",
        model=model,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AntigravityClient:
    """Async client for the Google Antigravity / CodeAssist generateContent API.

    Lazy-loads credentials from ``~/.synapse/state/google-oauth.json`` on first
    call, refreshes the access token when it's near expiry or after a 401/403,
    and exposes a single ``chat_completion`` entrypoint.
    """

    def __init__(
        self,
        *,
        endpoint: str = CODE_ASSIST_ENDPOINT_PROD,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout_sec = timeout_sec
        self._http_owner = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_sec)
        self._creds: GoogleAntigravityCredentials | None = None
        self._refresh_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._http_owner:
            await self._http.aclose()

    # -- credential plumbing -----------------------------------------------

    def _ensure_creds_loaded(self) -> GoogleAntigravityCredentials:
        if self._creds is None:
            creds = google_oauth.load_credentials()
            if creds is None:
                raise AuthenticationError(
                    message=(
                        "No Google Antigravity credentials found. Run "
                        "`python workspace/synapse_cli.py onboard` and choose "
                        "Google Antigravity, or set up via the wizard."
                    ),
                    llm_provider="google_antigravity",
                    model="<unknown>",
                )
            self._creds = creds
        return self._creds

    async def _refresh_if_needed(self) -> GoogleAntigravityCredentials:
        creds = self._ensure_creds_loaded()
        if not creds.is_expired():
            return creds
        async with self._refresh_lock:
            creds = self._ensure_creds_loaded()
            if not creds.is_expired():
                return creds
            new_creds = await asyncio.to_thread(google_oauth.refresh_access_token, creds)
            await asyncio.to_thread(google_oauth.save_credentials, new_creds)
            self._creds = new_creds
            return new_creds

    async def _force_refresh(self) -> GoogleAntigravityCredentials:
        creds = self._ensure_creds_loaded()
        async with self._refresh_lock:
            new_creds = await asyncio.to_thread(google_oauth.refresh_access_token, creds)
            await asyncio.to_thread(google_oauth.save_credentials, new_creds)
            self._creds = new_creds
            return new_creds

    # -- request building --------------------------------------------------

    def _build_inner_request(
        self,
        *,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
        generation_config: dict[str, Any] | None,
        session_id: str,
    ) -> dict[str, Any]:
        """Inner Gemini request — what goes inside the CodeAssist envelope."""
        inner: dict[str, Any] = {"contents": contents, "session_id": session_id}
        if system_instruction:
            inner["systemInstruction"] = system_instruction
        if tools:
            inner["tools"] = tools
        if generation_config:
            inner["generationConfig"] = generation_config
        return inner

    def _build_envelope(
        self,
        *,
        api_model: str,
        project_id: str,
        user_prompt_id: str,
        inner_request: dict[str, Any],
    ) -> dict[str, Any]:
        """CodeAssist v1internal envelope around the inner Gemini request.

        For Pro users (``g1-pro-tier``), eligible models carry
        ``enabled_credit_types: ["GOOGLE_ONE_AI"]`` so the request bills against
        the paid Pro quota rather than the much smaller standard-tier RPM cap.
        """
        envelope: dict[str, Any] = {
            "model": api_model,
            "project": project_id,
            "user_prompt_id": user_prompt_id,
            "request": inner_request,
        }
        if api_model in _G1_OVERAGE_MODELS:
            envelope["enabled_credit_types"] = [G1_CREDIT_TYPE]
        return envelope

    async def _post_generate(
        self,
        *,
        envelope: dict[str, Any],
        access_token: str,
        api_model: str,
    ) -> httpx.Response:
        url = f"{self._endpoint}/v1internal:generateContent"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Goog-Api-Client": GOOG_API_CLIENT,
            "Client-Metadata": json.dumps(CLIENT_METADATA),
        }
        return await self._http.post(url, headers=headers, content=json.dumps(envelope))

    # -- public entrypoint -------------------------------------------------

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | str | None = None,
    ) -> AntigravityResponse:
        """Run a single non-streaming generateContent call.

        Args:
            messages:    OpenAI-format messages list.
            model:       Either ``google_antigravity/<id>`` or a bare ``<id>``.
            tools:       Optional OpenAI-format tool definitions.
            temperature, top_p, max_tokens, stop: Standard sampling controls.

        Returns:
            An ``AntigravityResponse`` carrying text, tool calls, and usage metadata.
        """
        creds = await self._refresh_if_needed()
        resolution = resolve_model_with_thinking(model)
        api_model = resolution.api_model

        contents, system_instruction = translate_messages_to_gemini(messages)
        gemini_tools = translate_tools_to_gemini(tools)
        gen_config = build_generation_config(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )
        if resolution.thinking_level:
            gen_config = dict(gen_config or {})
            gen_config["thinkingConfig"] = {"thinkingLevel": resolution.thinking_level}

        inner = self._build_inner_request(
            contents=contents,
            system_instruction=system_instruction,
            tools=gemini_tools,
            generation_config=gen_config,
            session_id=str(uuid4()),
        )
        envelope = self._build_envelope(
            api_model=api_model,
            project_id=creds.project_id,
            user_prompt_id=str(uuid4()),
            inner_request=inner,
        )

        attempts = 0
        last_resp: httpx.Response | None = None
        while attempts < 2:
            attempts += 1
            t0 = time.perf_counter()
            try:
                resp = await self._post_generate(
                    envelope=envelope,
                    access_token=creds.access_token,
                    api_model=api_model,
                )
            except httpx.HTTPError as exc:
                raise APIConnectionError(
                    message=f"Antigravity request transport error: {exc}",
                    llm_provider="google_antigravity",
                    model=api_model,
                ) from exc
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _logger.info(
                "antigravity.call",
                extra={
                    "model": api_model,
                    "thinking_level": resolution.thinking_level,
                    "status": resp.status_code,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "attempt": attempts,
                },
            )
            last_resp = resp

            if resp.status_code in (401, 403) and attempts == 1:
                try:
                    creds = await self._force_refresh()
                    envelope["project"] = creds.project_id
                except RuntimeError as exc:
                    raise AuthenticationError(
                        message=f"Antigravity refresh failed: {exc}",
                        llm_provider="google_antigravity",
                        model=api_model,
                    ) from exc
                continue
            break

        assert last_resp is not None
        _raise_for_status(last_resp, model=api_model)

        try:
            payload = last_resp.json()
        except ValueError as exc:
            raise APIConnectionError(
                message=f"Antigravity response was not JSON: {last_resp.text[:200]}",
                llm_provider="google_antigravity",
                model=api_model,
            ) from exc
        return parse_response_payload(payload, requested_model=api_model)


# ---------------------------------------------------------------------------
# Module-level singleton (matches existing _deps style)
# ---------------------------------------------------------------------------


_singleton_lock = asyncio.Lock()
_singleton: AntigravityClient | None = None


async def get_default_client() -> AntigravityClient:
    """Return a process-wide singleton ``AntigravityClient``.

    Most call sites should use this instead of constructing their own client,
    so the refresh lock is shared and the underlying httpx connection pool is
    reused.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    async with _singleton_lock:
        if _singleton is None:
            _singleton = AntigravityClient()
        return _singleton


async def shutdown_default_client() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.aclose()
        _singleton = None
