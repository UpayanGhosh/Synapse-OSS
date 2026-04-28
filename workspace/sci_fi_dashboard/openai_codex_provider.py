"""OpenAI Codex Responses provider (ChatGPT subscription-backed)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

try:
    from litellm import (
        APIConnectionError,
        AuthenticationError,
        BadRequestError,
        RateLimitError,
        ServiceUnavailableError,
    )
except ImportError:  # pragma: no cover - litellm is a hard dependency in prod
    APIConnectionError = AuthenticationError = BadRequestError = Exception  # type: ignore[misc,assignment]
    RateLimitError = ServiceUnavailableError = Exception  # type: ignore[misc,assignment]

from . import openai_codex_oauth

OPENAI_CODEX_MODEL_PREFIXES = ("openai_codex/", "openai-codex/", "codex/")
DEFAULT_OPENAI_CODEX_MODEL = "gpt-5-codex"
OPENAI_CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_TIMEOUT_SEC = 60.0

OPENAI_CODEX_MODEL_ALIASES: dict[str, str] = {
    "gpt-5": "gpt-5-codex",
    "gpt5": "gpt-5-codex",
    "codex": "gpt-5-codex",
    "codex-latest": "gpt-5-codex",
    "gpt-5-codex": "gpt-5-codex",
    "gpt-5-mini": "codex-mini-latest",
    "gpt5-mini": "codex-mini-latest",
    "codex-mini": "codex-mini-latest",
    "codex-mini-latest": "codex-mini-latest",
    "gpt-5-codex-mini": "codex-mini-latest",
}

_QUOTA_HINTS = re.compile(r"quota|rate[\s_-]?limit|too many requests|resource_exhausted", re.I)


@dataclass(frozen=True)
class OpenAICodexResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None


def is_openai_codex_model(model_ref: str | None) -> bool:
    if not model_ref:
        return False
    lowered = str(model_ref).strip().lower()
    return any(lowered.startswith(prefix) for prefix in OPENAI_CODEX_MODEL_PREFIXES)


def _strip_openai_codex_prefix(model_ref: str) -> str:
    lowered = model_ref.lower()
    for prefix in OPENAI_CODEX_MODEL_PREFIXES:
        if lowered.startswith(prefix):
            return model_ref[len(prefix) :]
    return model_ref


def normalize_openai_codex_model(model_ref: str | None) -> str:
    bare = _strip_openai_codex_prefix((model_ref or DEFAULT_OPENAI_CODEX_MODEL).strip())
    if not bare:
        return DEFAULT_OPENAI_CODEX_MODEL
    return OPENAI_CODEX_MODEL_ALIASES.get(bare.lower(), bare)


def _stringify_tool_args(arguments: Any) -> str:
    if arguments is None:
        return "{}"
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _flatten_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in ("text", "input_text", "output_text", None):
                    text = block.get("text") or block.get("content")
                    if text is not None:
                        parts.append(str(text))
                elif "content" in block:
                    parts.append(str(block["content"]))
            elif block is not None:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    return str(content)


def _message_to_input_blocks(
    message: dict[str, Any], *, assistant_content_type: str = "input_text"
) -> list[dict[str, Any]]:
    role = str(message.get("role") or "").lower()
    text_block_type = assistant_content_type if role == "assistant" else "input_text"
    content = message.get("content")
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict):
                btype = str(block.get("type") or "").lower()
                if btype in {"text", "input_text", "output_text", ""}:
                    text = block.get("text") or block.get("content")
                    if text is not None:
                        blocks.append({"type": text_block_type, "text": str(text)})
                elif btype == "image_url":
                    image_url = block.get("image_url")
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url")
                    if isinstance(image_url, str) and image_url.strip():
                        blocks.append({"type": "input_image", "image_url": image_url})
            elif isinstance(block, str) and block.strip():
                blocks.append({"type": text_block_type, "text": block})
        if blocks:
            return blocks

    text = _flatten_message_content(content).strip()
    if not text:
        return []
    return [{"type": text_block_type, "text": text}]


def build_responses_input(
    messages: list[dict[str, Any]], *, assistant_content_type: str = "input_text"
) -> list[dict[str, Any]]:
    """Translate OpenAI chat messages to Responses API `input` items."""
    items: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").lower()

        if role == "tool":
            output = _flatten_message_content(message.get("content")).strip()
            call_id = message.get("tool_call_id") or message.get("id")
            if call_id:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(call_id),
                        "output": output,
                    }
                )
                continue

        if role in {"system", "user", "assistant"}:
            blocks = _message_to_input_blocks(
                message, assistant_content_type=assistant_content_type
            )
            if blocks:
                items.append({"role": role, "content": blocks})

        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            call_id = tool_call.get("id") or tool_call.get("call_id") or f"call_{len(items)+1}"
            items.append(
                {
                    "type": "function_call",
                    "call_id": str(call_id),
                    "name": name,
                    "arguments": _stringify_tool_args(function.get("arguments")),
                }
            )
    return items


def build_responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Translate OpenAI tool schema to Responses API tool schema."""
    if not tools:
        return None

    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        built: dict[str, Any] = {"type": "function", "name": name}
        description = function.get("description")
        if isinstance(description, str) and description.strip():
            built["description"] = description
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            built["parameters"] = parameters
        converted.append(built)
    return converted or None


def build_responses_request(
    *,
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stop: list[str] | str | None = None,
) -> dict[str, Any]:
    normalized_model = normalize_openai_codex_model(model)
    requires_stream = _requires_stream_protocol(normalized_model)
    assistant_content_type = "output_text" if requires_stream else "input_text"
    payload: dict[str, Any] = {
        "model": normalized_model,
        "input": build_responses_input(messages, assistant_content_type=assistant_content_type),
    }
    if requires_stream:
        # ChatGPT-account "gpt-5.4" path requires stream protocol and explicit store flag.
        payload["store"] = False
        payload["stream"] = True
        payload["instructions"] = _extract_instructions(messages)
        # Default to "medium thinking" for natural conversation quality.
        payload["reasoning"] = {"effort": "medium"}
        payload["text"] = {"format": {"type": "text"}, "verbosity": "medium"}
    codex_tools = build_responses_tools(tools)
    if codex_tools:
        payload["tools"] = codex_tools
    if temperature is not None and not requires_stream:
        payload["temperature"] = temperature
    if top_p is not None and not requires_stream:
        payload["top_p"] = top_p
    if max_tokens is not None and not requires_stream:
        payload["max_output_tokens"] = int(max_tokens)
    if stop is not None:
        payload["stop"] = [stop] if isinstance(stop, str) else list(stop)
    return payload


def _requires_stream_protocol(model_name: str) -> bool:
    """Return True when this model requires ChatGPT streaming request shape."""
    lowered = str(model_name or "").strip().lower()
    return lowered.startswith("gpt-5.4")


def _extract_instructions(messages: list[dict[str, Any]]) -> str:
    """Build top-level instructions from system messages for stream-mode requests."""
    if not messages:
        return "You are a helpful assistant."
    chunks: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() != "system":
            continue
        text = _flatten_message_content(message.get("content")).strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks) if chunks else "You are a helpful assistant."


def _usage_int(usage: dict[str, Any], *names: str) -> int:
    """Return the first present numeric usage field from a priority list."""
    for name in names:
        value = usage.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def parse_responses_payload(payload: dict[str, Any], *, requested_model: str) -> OpenAICodexResponse:
    text_chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    if isinstance(payload.get("output"), list):
        for item in payload["output"]:
            if not isinstance(item, dict):
                continue
            itype = str(item.get("type") or "").lower()
            if itype == "message":
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = str(block.get("type") or "").lower()
                        if btype in {"output_text", "text", "input_text", ""}:
                            text = block.get("text") or block.get("content")
                            if text is not None:
                                text_chunks.append(str(text))
                elif isinstance(content, str):
                    text_chunks.append(content)
            elif itype in {"function_call", "tool_call"}:
                raw_name = item.get("name") or item.get("function_name")
                if isinstance(raw_name, str) and raw_name.strip():
                    tool_calls.append(
                        {
                            "id": str(item.get("call_id") or item.get("id") or ""),
                            "name": raw_name,
                            "arguments": _stringify_tool_args(
                                item.get("arguments") or item.get("input") or "{}"
                            ),
                        }
                    )

    output_text = payload.get("output_text")
    if not text_chunks and isinstance(output_text, str) and output_text:
        text_chunks.append(output_text)

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    completion_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_int(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    model = payload.get("model")
    finish_reason = payload.get("finish_reason") or payload.get("status")
    return OpenAICodexResponse(
        text="".join(text_chunks),
        tool_calls=tool_calls,
        model=str(model or requested_model),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=str(finish_reason) if finish_reason is not None else None,
    )


def parse_responses_stream_payload(raw_body: str, *, requested_model: str) -> OpenAICodexResponse:
    """Parse SSE stream body from ChatGPT responses transport into OpenAICodexResponse."""
    text_chunks: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    model = requested_model

    for line in (raw_body or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        raw_json = stripped[5:].strip()
        if not raw_json:
            continue
        try:
            event = json.loads(raw_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type") or "").lower()
        if etype == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                text_chunks.append(delta)
        elif etype == "response.output_text.done":
            if not text_chunks:
                done_text = event.get("text")
                if isinstance(done_text, str):
                    text_chunks.append(done_text)
        elif etype == "response.completed":
            response_obj = event.get("response")
            if isinstance(response_obj, dict):
                usage_obj = response_obj.get("usage")
                if isinstance(usage_obj, dict):
                    usage = usage_obj
                model = str(response_obj.get("model") or model)
                finish_reason = str(response_obj.get("status") or "") or finish_reason

    prompt_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    completion_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_int(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    return OpenAICodexResponse(
        text="".join(text_chunks),
        tool_calls=[],
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
    )


def _error_detail(resp: httpx.Response) -> str:
    with_exception = f"HTTP {resp.status_code}"
    try:
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    text = resp.text.strip()
    return text[:512] if text else with_exception


def _raise_for_status(resp: httpx.Response, *, model: str) -> None:
    if resp.status_code < 400:
        return
    detail = _error_detail(resp)
    if resp.status_code in (401, 403):
        raise AuthenticationError(
            message=f"OpenAI Codex auth failed for {model}: {detail}",
            llm_provider="openai_codex",
            model=model,
        )
    if resp.status_code == 429 or _QUOTA_HINTS.search(detail):
        raise RateLimitError(
            message=f"OpenAI Codex rate limited for {model}: {detail}",
            llm_provider="openai_codex",
            model=model,
        )
    if resp.status_code == 400:
        raise BadRequestError(
            message=f"OpenAI Codex bad request for {model}: {detail}",
            llm_provider="openai_codex",
            model=model,
        )
    if resp.status_code >= 500:
        raise ServiceUnavailableError(
            message=f"OpenAI Codex backend unavailable for {model}: {detail}",
            llm_provider="openai_codex",
            model=model,
        )
    raise APIConnectionError(
        message=f"OpenAI Codex HTTP {resp.status_code} for {model}: {detail}",
        llm_provider="openai_codex",
        model=model,
    )


class OpenAICodexClient:
    """Async client for OpenAI Codex Responses transport."""

    def __init__(
        self,
        *,
        endpoint: str = OPENAI_CODEX_RESPONSES_URL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        http_client: httpx.AsyncClient | Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout_sec = timeout_sec
        self._http_owner = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_sec)
        self._creds: openai_codex_oauth.OpenAICodexCredentials | None = None
        self._refresh_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._http_owner and hasattr(self._http, "aclose"):
            await self._http.aclose()

    def _ensure_creds_loaded(self) -> openai_codex_oauth.OpenAICodexCredentials:
        if self._creds is None:
            creds = openai_codex_oauth.load_credentials()
            if creds is None:
                raise AuthenticationError(
                    message=(
                        "No OpenAI Codex credentials found. Run device-code login "
                        "to initialize openai-codex-oauth.json."
                    ),
                    llm_provider="openai_codex",
                    model="<unknown>",
                )
            self._creds = creds
        return self._creds

    async def _refresh_if_needed(self) -> openai_codex_oauth.OpenAICodexCredentials:
        creds = self._ensure_creds_loaded()
        if not creds.is_expired():
            return creds
        async with self._refresh_lock:
            creds = self._ensure_creds_loaded()
            if not creds.is_expired():
                return creds
            try:
                new_creds = await asyncio.to_thread(openai_codex_oauth.refresh_access_token, creds)
            except Exception as exc:
                access_token = str(getattr(creds, "access_token", "") or "").strip()
                if access_token and time.time() < float(getattr(creds, "expires_at", 0.0) or 0.0):
                    return creds
                if isinstance(exc, AuthenticationError):
                    raise
                raise AuthenticationError(
                    message=f"OpenAI Codex token refresh failed: {exc}",
                    llm_provider="openai_codex",
                    model="<unknown>",
                ) from exc
            await asyncio.to_thread(openai_codex_oauth.save_credentials, new_creds)
            self._creds = new_creds
            return new_creds

    async def _force_refresh(self) -> openai_codex_oauth.OpenAICodexCredentials:
        creds = self._ensure_creds_loaded()
        async with self._refresh_lock:
            new_creds = await asyncio.to_thread(openai_codex_oauth.refresh_access_token, creds)
            await asyncio.to_thread(openai_codex_oauth.save_credentials, new_creds)
            self._creds = new_creds
            return new_creds

    async def _post_responses(
        self,
        *,
        payload: dict[str, Any],
        access_token: str,
    ) -> httpx.Response:
        return await self._http.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_sec,
        )

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
    ) -> OpenAICodexResponse:
        creds = await self._refresh_if_needed()
        normalized_model = normalize_openai_codex_model(model)
        payload = build_responses_request(
            messages=messages,
            model=normalized_model,
            tools=tools,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )

        for attempt in (1, 2):
            try:
                resp = await self._post_responses(payload=payload, access_token=creds.access_token)
            except httpx.HTTPError as exc:
                raise APIConnectionError(
                    message=f"OpenAI Codex transport error: {exc}",
                    llm_provider="openai_codex",
                    model=normalized_model,
                ) from exc

            if resp.status_code in (401, 403) and attempt == 1:
                try:
                    creds = await self._force_refresh()
                except Exception as exc:
                    if isinstance(exc, AuthenticationError):
                        raise
                    raise AuthenticationError(
                        message=f"OpenAI Codex token refresh failed: {exc}",
                        llm_provider="openai_codex",
                        model=normalized_model,
                    ) from exc
                continue

            _raise_for_status(resp, model=normalized_model)
            if payload.get("stream") is True:
                return parse_responses_stream_payload(resp.text, requested_model=normalized_model)

            try:
                body = resp.json()
            except ValueError as exc:
                raise APIConnectionError(
                    message=f"OpenAI Codex response was not JSON: {resp.text[:200]}",
                    llm_provider="openai_codex",
                    model=normalized_model,
                ) from exc
            if not isinstance(body, dict):
                raise APIConnectionError(
                    message="OpenAI Codex response payload must be a JSON object",
                    llm_provider="openai_codex",
                    model=normalized_model,
                )
            return parse_responses_payload(body, requested_model=normalized_model)

        raise AuthenticationError(
            message=f"OpenAI Codex auth failed after retry for {normalized_model}",
            llm_provider="openai_codex",
            model=normalized_model,
        )


_singleton_lock = asyncio.Lock()
_singleton: OpenAICodexClient | None = None


async def get_default_client() -> OpenAICodexClient:
    global _singleton
    if _singleton is not None:
        return _singleton
    async with _singleton_lock:
        if _singleton is None:
            _singleton = OpenAICodexClient()
        return _singleton


async def shutdown_default_client() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.aclose()
        _singleton = None
