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
                output_fn("")
                return 0

            message = message.strip()
            if not message:
                continue

            command = message.lower()
            if command in {"/quit", "/exit"}:
                return 0
            if command == "/safe":
                options = replace(options, session_type="safe")
                output_fn("SAFE mode")
                continue
            if command == "/spicy":
                options = replace(options, session_type="spicy")
                output_fn("SPICY mode")
                continue
            if command == "/help":
                output_fn("Commands: /safe, /spicy, /quit, /exit")
                continue

            _send_message(message, options, client, history, output_fn)
    finally:
        if manager is not None:
            manager.stop()


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
        output_fn(f"Error: {exc}")
        return False
    output_fn(reply.reply)
    history.append(ChatTurn(role="user", content=message))
    history.append(ChatTurn(role="assistant", content=reply.reply))
    return True
