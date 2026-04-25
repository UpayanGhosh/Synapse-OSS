"""
antigravity_provider.py — Google Antigravity / Gemini CLI inference client.

Posts to ``cloudcode-pa.googleapis.com/v1internal:generateContent`` using the
OAuth bearer token captured by ``google_oauth.py``. Translates OpenAI-format
messages and tools into Gemini contents + envelope, then translates the
response back into Synapse's ``LLMResult`` / ``LLMToolResult`` shape so the
rest of the chat pipeline doesn't care what provider it came from.

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

# Models published by Google Antigravity / Gemini CLI free tier.
# When a user lists a "bare" pro id (without -low/-high), default to -low so
# we don't burn through their high-reasoning quota.
_ANTIGRAVITY_BARE_PRO_IDS = frozenset({"gemini-3-pro", "gemini-3.1-pro", "gemini-3-1-pro"})

# CodeAssist requires "preview"-suffixed model IDs for the public Gemini 3
# generations; bare aliases are treated as forward-compat hints.
_PREVIEW_REWRITES: dict[str, str] = {
    "gemini-3-pro": "gemini-3-pro-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini-3-flash-lite": "gemini-3-flash-lite-preview",
    "gemini-3.1-flash-lite": "gemini-3.1-flash-lite-preview",
}

USER_AGENT = "synapse-oss-antigravity/1.0"
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


def normalize_antigravity_model_id(model_id: str) -> str:
    """Mirror OpenClaw: bare gemini-3 pro IDs default to ``-low`` reasoning."""
    if model_id in _ANTIGRAVITY_BARE_PRO_IDS:
        return f"{model_id}-low"
    return model_id


def normalize_google_model_id(model_id: str) -> str:
    """Mirror OpenClaw: rewrite known bare aliases to their preview model IDs."""
    return _PREVIEW_REWRITES.get(model_id, model_id)


def resolve_inference_model_id(prefixed: str) -> str:
    """Strip the ``google_antigravity/`` prefix and apply both normalizations."""
    bare = prefixed.split("/", 1)[1] if "/" in prefixed else prefixed
    bare = normalize_antigravity_model_id(bare)
    return normalize_google_model_id(bare)


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
            decl["parameters"] = params
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
    if isinstance(finish_reason, str):
        finish_reason = finish_reason.lower()
    else:
        finish_reason = None

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

    def _build_envelope(
        self,
        *,
        model_id: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
        generation_config: dict[str, Any] | None,
        project_id: str,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"contents": contents}
        if system_instruction:
            request["systemInstruction"] = system_instruction
        if tools:
            request["tools"] = tools
        if generation_config:
            request["generationConfig"] = generation_config
        return {"model": model_id, "project": project_id, "request": request}

    async def _post_generate(
        self,
        *,
        envelope: dict[str, Any],
        access_token: str,
        model_id: str,
    ) -> httpx.Response:
        url = f"{self._endpoint}/v1internal:generateContent"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
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
        model_id = resolve_inference_model_id(model)

        contents, system_instruction = translate_messages_to_gemini(messages)
        gemini_tools = translate_tools_to_gemini(tools)
        gen_config = build_generation_config(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=stop,
        )

        envelope = self._build_envelope(
            model_id=model_id,
            contents=contents,
            system_instruction=system_instruction,
            tools=gemini_tools,
            generation_config=gen_config,
            project_id=creds.project_id,
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
                    model_id=model_id,
                )
            except httpx.HTTPError as exc:
                raise APIConnectionError(
                    message=f"Antigravity request transport error: {exc}",
                    llm_provider="google_antigravity",
                    model=model_id,
                ) from exc
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _logger.info(
                "antigravity.call",
                extra={
                    "model": model_id,
                    "status": resp.status_code,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "attempt": attempts,
                },
            )
            last_resp = resp

            if resp.status_code in (401, 403) and attempts == 1:
                # Token may have been revoked or rotated server-side. Try once.
                try:
                    creds = await self._force_refresh()
                except RuntimeError as exc:
                    raise AuthenticationError(
                        message=f"Antigravity refresh failed: {exc}",
                        llm_provider="google_antigravity",
                        model=model_id,
                    ) from exc
                continue
            break

        assert last_resp is not None
        _raise_for_status(last_resp, model=model_id)

        try:
            payload = last_resp.json()
        except ValueError as exc:
            raise APIConnectionError(
                message=f"Antigravity response was not JSON: {last_resp.text[:200]}",
                llm_provider="google_antigravity",
                model=model_id,
            ) from exc
        return parse_response_payload(payload, requested_model=model_id)


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
