"""Test-only, file-mediated router for agent-driven GPT-6 Luna simulation.

This is deliberately not a production provider. A separate test operator reads
each request packet, obtains one fresh Luna inference, and writes its response
packet. No credentials, network calls, or arbitrary tool execution live here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sci_fi_dashboard.llm_router import LLMResult, LLMToolResult, ToolCall


class RelayProtocolError(ValueError):
    """An inference response does not match the outstanding request contract."""


class RelayLimitError(RuntimeError):
    """The configured cap on test-only model requests has been reached."""


class FileRelayRouter:
    """Router-compatible async handoff through isolated request/response files."""

    model = "gpt-6-luna"

    def __init__(
        self,
        run_dir: str | Path,
        *,
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 0.05,
        max_requests: int = 40,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0 or max_requests <= 0:
            raise ValueError("relay timeout, poll interval, and request cap must be positive")
        self.run_dir = Path(run_dir).resolve()
        self.request_dir = self.run_dir / "requests"
        self.response_dir = self.run_dir / "responses"
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_requests = max_requests
        self._request_count = 0
        self._request_lock = asyncio.Lock()

    async def call(
        self,
        role: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **_kwargs: Any,
    ) -> str:
        response = await self._exchange(
            kind="text",
            role=role,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response["text"]

    async def call_with_metadata(
        self,
        role: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **_kwargs: Any,
    ) -> LLMResult:
        response = await self._exchange(
            kind="text",
            role=role,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResult(
            text=response["text"],
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason=response.get("finish_reason"),
        )

    async def call_with_tools(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        tool_choice: str | dict[str, Any] = "auto",
        **_kwargs: Any,
    ) -> LLMToolResult:
        response = await self._exchange(
            kind="tools",
            role=role,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        allowed_names = {
            tool.get("function", {}).get("name")
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        calls: list[ToolCall] = []
        seen_ids: set[str] = set()
        for raw in response.get("tool_calls", []):
            if not isinstance(raw, dict):
                raise RelayProtocolError("tool_calls entries must be objects")
            call_id, name, arguments = raw.get("id"), raw.get("name"), raw.get("arguments")
            if not isinstance(call_id, str) or not call_id.strip() or call_id in seen_ids:
                raise RelayProtocolError("tool call ids must be nonempty and unique")
            if not isinstance(name, str) or name not in allowed_names:
                raise RelayProtocolError(f"tool {name!r} is not declared in the current request")
            if not isinstance(arguments, dict):
                raise RelayProtocolError("tool call arguments must be a JSON object")
            seen_ids.add(call_id)
            calls.append(ToolCall(call_id, name, json.dumps(arguments, sort_keys=True)))
        return LLMToolResult(
            text=response["text"],
            tool_calls=calls,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason=response.get("finish_reason"),
        )

    async def _exchange(self, *, kind: str, role: str, messages: list[dict[str, Any]], **kwargs):
        async with self._request_lock:
            if self._request_count >= self.max_requests:
                raise RelayLimitError(f"Luna simulation reached max_requests={self.max_requests}")
            self._request_count += 1
            request_id = uuid4().hex
            self.request_dir.mkdir(parents=True, exist_ok=True)
            self.response_dir.mkdir(parents=True, exist_ok=True)
            packet = {
                "schema_version": 1,
                "request_id": request_id,
                "request_number": self._request_count,
                "model": self.model,
                "kind": kind,
                "role": role,
                "messages": messages,
                **kwargs,
            }
            _atomic_json(self.request_dir / f"{request_id}.json", packet)
            response_path = self.response_dir / f"{request_id}.json"
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                if response_path.exists():
                    response = _load_json_object(response_path)
                    if response.get("request_id") != request_id:
                        raise RelayProtocolError("response request_id does not match outstanding request")
                    unknown = set(response) - {"request_id", "text", "tool_calls", "finish_reason"}
                    if unknown:
                        raise RelayProtocolError(f"response has unsupported fields: {sorted(unknown)}")
                    if not isinstance(response.get("text"), str):
                        raise RelayProtocolError("response text must be a string")
                    tool_calls = response.get("tool_calls", [])
                    if kind == "text" and tool_calls:
                        raise RelayProtocolError("text-only request cannot return tool calls")
                    if not isinstance(tool_calls, list):
                        raise RelayProtocolError("tool_calls must be a list")
                    return response
                await asyncio.sleep(self.poll_interval_seconds)
            raise TimeoutError(f"Timed out waiting for {self.model} response {request_id}")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(f".json.{uuid4().hex}.tmp")
    try:
        with tmp_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RelayProtocolError(f"invalid relay response file: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise RelayProtocolError("relay response must be a JSON object")
    return value
