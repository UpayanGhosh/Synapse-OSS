"""Claude Code CLI provider for Claude Pro/Max subscription access.

This provider deliberately calls the official ``claude`` binary in headless
mode instead of reading Claude credentials or replaying private API requests.
That keeps subscription auth inside Claude Code, matching Anthropic's supported
``claude -p --output-format json`` path.

System prompt > 32k chars triggers ``[WinError 206] The filename or extension
is too long`` on Windows when passed via ``--system-prompt``. OpenClaw's
``cli-runner.spawn.test.ts`` documents the workaround used here: write the
system prompt to a temp file and pass ``--append-system-prompt-file <path>``,
which Claude Code 2.1+ supports per the ``--bare`` help text. The path is
short, the content is unlimited.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

CLAUDE_CLI_PREFIXES = ("claude_cli/", "claude-cli/", "claude_max/")
DEFAULT_CLAUDE_CLI_MODEL = "sonnet"
DEFAULT_CLAUDE_CLI_TIMEOUT_SEC = 180.0
DEFAULT_SYSTEM_PROMPT = "You are a concise chat completion engine."

# OpenClaw clears these so inherited shell config cannot silently route Claude
# Code through API keys, alternate endpoints, Vertex/Bedrock, or telemetry
# bootstrap paths. For Synapse this also matters because the user's goal is to
# use their Claude subscription, not pay-as-you-go API billing.
CLAUDE_CLI_CLEAR_ENV = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY_OLD",
        "ANTHROPIC_API_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_OAUTH_TOKEN",
        "ANTHROPIC_UNIX_SOCKET",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
        "CLAUDE_CODE_OAUTH_SCOPES",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_PLUGIN_CACHE_DIR",
        "CLAUDE_CODE_PLUGIN_SEED_DIR",
        "CLAUDE_CODE_REMOTE",
        "CLAUDE_CODE_USE_COWORK_PLUGINS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_VERTEX",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
        "OTEL_LOGS_EXPORTER",
        "OTEL_METRICS_EXPORTER",
        "OTEL_SDK_DISABLED",
        "OTEL_TRACES_EXPORTER",
    }
)

CLAUDE_CLI_MODEL_ALIASES: dict[str, str] = {
    "opus": "opus",
    "opus-4.7": "opus",
    "opus-4.6": "opus",
    "opus-4.5": "opus",
    "opus-4": "opus",
    "claude-opus-4-7": "opus",
    "claude-opus-4-6": "opus",
    "claude-opus-4-5": "opus",
    "claude-opus-4": "opus",
    "sonnet": "sonnet",
    "sonnet-4.6": "sonnet",
    "sonnet-4.5": "sonnet",
    "sonnet-4.1": "sonnet",
    "sonnet-4.0": "sonnet",
    "claude-sonnet-4-6": "sonnet",
    "claude-sonnet-4-5": "sonnet",
    "claude-sonnet-4-1": "sonnet",
    "claude-sonnet-4-0": "sonnet",
    "haiku": "haiku",
    "haiku-3.5": "haiku",
    "claude-haiku-3-5": "haiku",
}


@dataclass(frozen=True)
class ClaudeCliResponse:
    """Parsed Claude Code headless result."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None
    session_id: str | None = None


def is_claude_cli_model(model_ref: str | None) -> bool:
    """Return True for Claude Code CLI-backed model refs."""
    return bool(model_ref) and any(
        str(model_ref).startswith(prefix) for prefix in CLAUDE_CLI_PREFIXES
    )


def strip_claude_cli_prefix(model_ref: str) -> str:
    """Remove supported Claude CLI provider prefix from a model ref."""
    for prefix in CLAUDE_CLI_PREFIXES:
        if model_ref.startswith(prefix):
            return model_ref[len(prefix) :]
    return model_ref


def normalize_claude_cli_model(model_ref: str | None) -> str:
    """Normalize Synapse/OpenClaw-style model refs to Claude Code CLI aliases."""
    bare = strip_claude_cli_prefix((model_ref or DEFAULT_CLAUDE_CLI_MODEL).strip())
    if not bare:
        return DEFAULT_CLAUDE_CLI_MODEL
    return CLAUDE_CLI_MODEL_ALIASES.get(bare.lower(), bare)


def _flatten_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in ("text", None) and "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(str(block["content"]))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    return str(content)


def messages_to_claude_cli_input(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Split chat messages into ``--system-prompt`` text and stdin transcript."""
    system_parts: list[str] = []
    transcript_parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").lower()
        text = _flatten_message_content(msg.get("content")).strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            transcript_parts.append(f"Assistant: {text}")
        elif role == "tool":
            name = msg.get("name") or msg.get("tool_call_id") or "tool"
            transcript_parts.append(f"Tool result ({name}): {text}")
        else:
            transcript_parts.append(f"User: {text}")

    system_prompt = "\n\n".join(system_parts).strip() or DEFAULT_SYSTEM_PROMPT
    prompt = "\n\n".join(transcript_parts).strip()
    return system_prompt, prompt


def _iter_events(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item


def _json_payloads(stdout: str) -> Iterable[Any]:
    stripped = stdout.strip()
    if not stripped:
        return
    try:
        yield json.loads(stripped)
        return
    except json.JSONDecodeError:
        pass

    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _usage_int(usage: dict[str, Any], *names: str) -> int:
    total = 0
    for name in names:
        value = usage.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            total += int(value)
    return total


def parse_claude_cli_output(stdout: str, requested_model: str) -> ClaudeCliResponse:
    """Parse Claude Code ``json``/``stream-json`` output across CLI versions."""
    events: list[dict[str, Any]] = []
    for payload in _json_payloads(stdout):
        events.extend(_iter_events(payload))

    if not events:
        raise RuntimeError("claude CLI returned no parseable JSON")

    assistant_text = ""
    assistant_model: str | None = None
    assistant_usage: dict[str, Any] = {}
    result_event: dict[str, Any] | None = None
    error_event: dict[str, Any] | None = None

    for event in events:
        if event.get("type") == "assistant":
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            assistant_model = message.get("model") or assistant_model
            usage = message.get("usage")
            if isinstance(usage, dict):
                assistant_usage = usage
            content = message.get("content")
            if isinstance(content, list):
                texts = [
                    str(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
                ]
                if texts:
                    assistant_text = "\n".join(texts)
        if event.get("type") == "result":
            if event.get("is_error"):
                error_event = event
            else:
                result_event = event

    if error_event is not None and result_event is None:
        message = (
            error_event.get("result")
            or error_event.get("error")
            or error_event.get("api_error_status")
            or "claude CLI returned an error"
        )
        raise RuntimeError(str(message))

    usage = {}
    text = assistant_text
    finish_reason: str | None = None
    session_id: str | None = None
    if result_event is not None:
        text = str(result_event.get("result") or text)
        usage = result_event.get("usage") if isinstance(result_event.get("usage"), dict) else {}
        finish_reason = result_event.get("stop_reason") or result_event.get("terminal_reason")
        session_id = result_event.get("session_id")
    elif assistant_usage:
        usage = assistant_usage

    if not text:
        raise RuntimeError("claude CLI returned no assistant text")

    prompt_tokens = _usage_int(
        usage,
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    completion_tokens = _usage_int(usage, "output_tokens")
    total_tokens = prompt_tokens + completion_tokens

    model = requested_model
    model_usage = result_event.get("modelUsage") if isinstance(result_event, dict) else None
    if isinstance(model_usage, dict) and model_usage:
        model = next(iter(model_usage.keys()))
    elif assistant_model:
        model = assistant_model

    return ClaudeCliResponse(
        text=text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
        session_id=session_id,
    )


class ClaudeCliClient:
    """Async wrapper around ``claude -p``."""

    def __init__(
        self,
        *,
        command: str = "claude",
        timeout: float = DEFAULT_CLAUDE_CLI_TIMEOUT_SEC,
        cwd: str | None = None,
        extra_args: list[str] | None = None,
        setting_sources: str = "user",
        disable_tools: bool = True,
        disable_slash_commands: bool = True,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self.cwd = cwd
        self.extra_args = list(extra_args or [])
        self.setting_sources = setting_sources
        self.disable_tools = disable_tools
        self.disable_slash_commands = disable_slash_commands

    def _resolve_command(self) -> str:
        if os.path.sep in self.command or (os.path.altsep and os.path.altsep in self.command):
            return self.command
        resolved = shutil.which(self.command)
        if not resolved:
            raise RuntimeError(
                "Claude Code CLI not found. Install it and run `claude` once to log in "
                "with your Claude Pro/Max account."
            )
        return resolved

    def _build_env(self, max_tokens: int | None) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in CLAUDE_CLI_CLEAR_ENV and value is not None
        }
        # Claude Code 2.x enables thinking for Sonnet/Opus and rejects output
        # budgets below 1024. Synapse often asks for tiny smoke-test caps, so
        # only pass the env cap when it is high enough for Claude Code.
        if max_tokens and max_tokens >= 1024:
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        env.setdefault("DISABLE_AUTOUPDATER", "1")
        return env

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ClaudeCliResponse:
        """Run a single non-interactive Claude Code completion.

        Claude Code does not expose temperature in its headless CLI, so the
        argument is accepted for router API compatibility and intentionally
        ignored.
        """
        del temperature
        cli_model = normalize_claude_cli_model(model)
        system_prompt, prompt = messages_to_claude_cli_input(messages)
        cmd = [
            self._resolve_command(),
            "-p",
            "--output-format",
            "json",
            "--model",
            cli_model,
            "--max-turns",
            "1",
            "--no-session-persistence",
            # Move per-machine sections (cwd, env info, memory paths, git
            # status) out of the system prompt and into the first user
            # message — saves ~3-5k tokens and makes the static system
            # prompt prefix-cache friendly across calls.
            "--exclude-dynamic-system-prompt-sections",
            # Empty MCP config skips the plugin scan + MCP server discovery
            # that Claude Code does at startup (~varies, often 5-10k tokens
            # of tool descriptions). Synapse calls Claude only for chat,
            # never for MCP-driven agentic work, so this overhead is dead
            # weight here. ``--bare`` would also strip this but breaks
            # subscription auth, so stay surgical.
            "--mcp-config",
            '{"mcpServers":{}}',
        ]
        if self.setting_sources:
            cmd.extend(["--setting-sources", self.setting_sources])
        if self.disable_slash_commands:
            cmd.append("--disable-slash-commands")
        if self.disable_tools:
            cmd.extend(["--tools", ""])

        # Synapse's compiled persona prompt is ~17k tokens, which trips
        # Windows CreateProcess's ~32k command-line limit when passed via
        # ``--system-prompt``. Mirror OpenClaw: write the system prompt to
        # a NamedTemporaryFile and pass the short path via
        # ``--system-prompt-file`` (NOT the ``--append-...`` variant — that
        # one keeps Claude Code's default "I am Claude Code agent" system
        # prompt active and Synapse's persona just gets appended after,
        # producing terse "AI assistant"-flavoured replies that fight the
        # Bhai persona. ``--system-prompt-file`` REPLACES the default
        # prompt so only Synapse's compiled persona drives the model).
        # Cleanup happens in the finally block regardless of subprocess
        # outcome.
        system_prompt_path: Path | None = None
        if system_prompt:
            tmp = tempfile.NamedTemporaryFile(
                prefix="synapse-claude-system-prompt-",
                suffix=".txt",
                mode="w",
                encoding="utf-8",
                delete=False,
            )
            try:
                tmp.write(system_prompt)
            finally:
                tmp.close()
            system_prompt_path = Path(tmp.name)
            cmd.extend(["--system-prompt-file", str(system_prompt_path)])

        cmd.extend(self.extra_args)

        # Spawn from a fresh empty temp directory so Claude Code's CLAUDE.md
        # auto-discovery walk finds nothing — saves another ~5-10k tokens
        # of project-context that Synapse doesn't want bleeding into chat.
        # ``self.cwd`` (if set) wins to keep test/integration overrides
        # working.
        ephemeral_cwd: Path | None = None
        run_cwd = self.cwd
        if run_cwd is None:
            ephemeral_cwd = Path(tempfile.mkdtemp(prefix="synapse-claude-cwd-"))
            run_cwd = str(ephemeral_cwd)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(max_tokens),
            cwd=run_cwd,
        )
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=self.timeout,
                )
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                raise RuntimeError(f"claude CLI timed out after {self.timeout:g}s") from None
        finally:
            if system_prompt_path is not None:
                with contextlib.suppress(OSError):
                    system_prompt_path.unlink()
            if ephemeral_cwd is not None:
                shutil.rmtree(ephemeral_cwd, ignore_errors=True)

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            detail = stderr_text or stdout_text.strip() or f"exit code {proc.returncode}"
            try:
                parse_claude_cli_output(detail, cli_model)
            except RuntimeError as exc:
                detail = str(exc)
            raise RuntimeError(f"claude CLI failed: {detail[:500]}")

        response = parse_claude_cli_output(stdout_text, cli_model)
        _logger.info(
            "claude_cli_call_done model=%s prompt_tokens=%d completion_tokens=%d",
            response.model,
            response.prompt_tokens,
            response.completion_tokens,
        )
        return response
