from __future__ import annotations

import ast
import os
from pathlib import Path

SOURCE = Path(
    os.environ.get(
        "SYNAPSE_GATEWAY_SOURCE",
        Path(__file__).resolve().parents[2] / "workspace" / "sci_fi_dashboard" / "api_gateway.py",
    )
)


def _start_call_lines(tree: ast.Module, service_name: str) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not isinstance(func, ast.Attribute) or func.attr != "start":
            continue
        receiver = func.value
        if isinstance(receiver, ast.Attribute) and receiver.attr == service_name:
            lines.append(node.lineno)
    return lines


def test_lifespan_restores_cron_source_validator_before_starting_outbox_and_worker() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    lifespan = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )
    cron_start = _start_call_lines(ast.Module(body=lifespan.body, type_ignores=[]), "cron_service")
    outbox_start = _start_call_lines(ast.Module(body=lifespan.body, type_ignores=[]), "retry_queue")
    worker_start = _start_call_lines(ast.Module(body=lifespan.body, type_ignores=[]), "worker")

    assert cron_start and outbox_start and worker_start
    assert cron_start[0] < outbox_start[0] < worker_start[0], (
        "CronStore must restore source jobs and install the stale-send validator "
        "before outbox dispatch and inbound worker startup"
    )
