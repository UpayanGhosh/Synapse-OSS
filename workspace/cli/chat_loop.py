from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from cli.chat_client import ChatClient
from cli.chat_types import ChatLaunchOptions, ChatTurn
from cli.gateway_process import GatewayProcessManager
from cli.startup_overview import build_startup_overview, collect_startup_diagnostics

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def run_cli_chat(
    options: ChatLaunchOptions,
    client: ChatClient | None = None,
    gateway_manager: GatewayProcessManager | None = None,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
) -> int:
    manager = gateway_manager
    if manager is None and client is None and options.auto_start_gateway:
        manager = GatewayProcessManager(port=options.port)

    try:
        if manager is not None:
            manager.ensure_running()
        if client is None:
            client = ChatClient(base_url=f"http://127.0.0.1:{options.port}")

        history: list[ChatTurn] = []

        if options.show_startup_greeting:
            _emit(output_fn, _format_status(options, client))

        if options.initial_message:
            if not _send_message(options.initial_message, options, client, history, output_fn):
                return 1
            if options.exit_after_initial:
                return 0

        while True:
            try:
                mode = options.resolved_session_type().upper()
                message = input_fn(f"[{mode}] > ")
            except EOFError:
                return 0
            except KeyboardInterrupt:
                _emit(output_fn, "")
                return 0

            message = message.strip()
            if not message:
                continue

            command = message.lower()
            if command in {"/quit", "/exit"}:
                return 0
            if command == "/safe":
                options = replace(options, session_type="safe")
                _emit(output_fn, "SAFE mode")
                continue
            if command == "/spicy":
                options = replace(options, session_type="spicy")
                _emit(output_fn, "SPICY mode")
                continue
            if command == "/help":
                _emit(output_fn, _format_help())
                continue
            if command == "/status":
                _emit(output_fn, _format_status(options, client))
                continue
            if command == "/model":
                _emit(output_fn, _format_model(options, client))
                continue

            _send_message(message, options, client, history, output_fn)
    finally:
        if manager is not None:
            manager.stop()


def _emit(output_fn: OutputFn, text: str) -> None:
    try:
        output_fn(text)
    except UnicodeEncodeError:
        output_fn(text.encode("ascii", errors="replace").decode("ascii"))


def _format_status(options: ChatLaunchOptions, client: ChatClient) -> str:
    return build_startup_overview(collect_startup_diagnostics(options, client=client))


def _format_help() -> str:
    return "\n".join(
        [
            "Commands:",
            "  /safe    switch to safe chat",
            "  /spicy   switch to spicy chat",
            "  /status  show config, model, gateway, first-run status",
            "  /model   show selected safe-chat model",
            "  /quit    exit",
            "  /exit    exit",
        ]
    )


def _format_model(options: ChatLaunchOptions, client: ChatClient) -> str:
    diagnostics = collect_startup_diagnostics(options, client=client)
    model = diagnostics.safe_chat_model or "not configured"
    return "\n".join(
        [
            f"Safe-chat model: {model}",
            f"Target: {diagnostics.target}",
            f"Config: {diagnostics.config_path}",
        ]
    )


def _send_message(
    message: str,
    options: ChatLaunchOptions,
    client: ChatClient,
    history: list[ChatTurn],
    output_fn: OutputFn,
) -> bool:
    try:
        reply = client.send_turn(message, options=options, history=history)
    except Exception as exc:
        _emit(output_fn, f"Error: {exc}")
        _emit(output_fn, _diagnostic_hint(str(exc)))
        return False
    _emit(output_fn, reply.reply)
    reply_hint = _diagnostic_hint_for_reply(reply)
    if reply_hint:
        _emit(output_fn, reply_hint)
    history.append(ChatTurn(role="user", content=message))
    history.append(ChatTurn(role="assistant", content=reply.reply))
    return True


def _diagnostic_hint(error: str) -> str:
    lowered = error.lower()
    if "unknown model" in lowered:
        return "Diagnostic hint: model route failed. Run /status, then synapse verify."
    return "Diagnostic hint: run /status, then synapse verify."


def _diagnostic_hint_for_reply(reply: object) -> str | None:
    raw = getattr(reply, "raw", None)
    if _total_tokens(raw) == 0:
        return "Diagnostic hint: gateway returned zero tokens. Run /status, then synapse verify."

    text = str(getattr(reply, "reply", "") or "").strip()
    if _total_tokens_from_reply_text(text) == 0:
        return "Diagnostic hint: gateway returned zero tokens. Run /status, then synapse verify."

    lowered = text.lower()
    if not text:
        return "Diagnostic hint: gateway returned an empty reply. Run /status, then synapse verify."
    if "try again" in lowered and any(word in lowered for word in ("error", "failed", "failure")):
        return "Diagnostic hint: generic bot failure. Run /status, then synapse verify."
    return None


_TOKENS_FOOTER_RE = re.compile(
    r"\*\*Tokens:\*\*\s*[\d,]+\s+in\s*/\s*[\d,]+\s+out\s*/\s*([\d,]+)\s+total",
    re.IGNORECASE,
)


def _total_tokens_from_reply_text(text: str) -> int | None:
    match = _TOKENS_FOOTER_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _total_tokens(raw: object) -> int | None:
    if not isinstance(raw, dict):
        return None
    usage = raw.get("usage")
    if isinstance(usage, dict) and "total_tokens" in usage:
        try:
            return int(usage["total_tokens"])
        except (TypeError, ValueError):
            return None
    if "total_tokens" in raw:
        try:
            return int(raw["total_tokens"])
        except (TypeError, ValueError):
            return None
    return None
