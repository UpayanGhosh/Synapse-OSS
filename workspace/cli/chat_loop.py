from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from cli.chat_client import ChatClient
from cli.chat_types import ChatLaunchOptions, ChatTurn
from cli.gateway_process import GatewayProcessManager


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

        if options.show_startup_greeting and not options.initial_message:
            _emit(output_fn, _format_startup_greeting(options, client))

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
                _emit(output_fn, "Commands: /safe, /spicy, /quit, /exit")
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


def _format_startup_greeting(options: ChatLaunchOptions, client: ChatClient) -> str:
    model = "not configured"
    config_status = "missing"
    try:
        from synapse_config import SynapseConfig  # noqa: PLC0415

        cfg = SynapseConfig.load()
        config_status = "valid"
        mappings = cfg.model_mappings or {}
        role_cfg = mappings.get("casual") or next(iter(mappings.values()), {})
        if isinstance(role_cfg, dict):
            model = str(role_cfg.get("model") or model)
            try:
                from sci_fi_dashboard.openai_codex_provider import (  # noqa: PLC0415
                    is_openai_codex_model,
                    normalize_openai_codex_model,
                )

                if is_openai_codex_model(model):
                    model = f"openai_codex/{normalize_openai_codex_model(model)}"
            except Exception:
                pass
    except Exception:
        config_status = "unavailable"

    gateway_url = f"http://127.0.0.1:{options.port}"
    reachable = False
    detail = "not probed"
    probe = getattr(client, "probe_health", None)
    if callable(probe):
        reachable, detail = probe()

    gateway_line = (
        f"Gateway: reachable at {gateway_url} ({detail})."
        if reachable
        else f"Gateway: not reachable at {gateway_url}; first probe said {detail}."
    )

    return "\n".join(
        [
            "## Hi, I'm Synapse.",
            "",
            "- Start here when setup, model routing, Gateway, or local chat feels off.",
            f"- Using: {model} for safe chat.",
            f"- Config: {config_status}. Persona: {options.target}.",
            f"- {gateway_line}",
            "",
            "Send a message, or use `/help` for local commands.",
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
        return False
    _emit(output_fn, reply.reply)
    history.append(ChatTurn(role="user", content=message))
    history.append(ChatTurn(role="assistant", content=reply.reply))
    return True
