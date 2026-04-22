"""OBS-01 + OBS-03: JSON formatter + child logger + ContextVar tests. Wave 0 scaffold."""

from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from sci_fi_dashboard.observability.context import (
    get_run_id,
    mint_run_id,
)
from sci_fi_dashboard.observability.formatter import JsonFormatter
from sci_fi_dashboard.observability.logger_factory import get_child_logger


def _capture(logger: logging.Logger, formatter: logging.Formatter) -> io.StringIO:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(formatter)
    logger.addHandler(h)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return buf


@pytest.mark.unit
def test_json_formatter_fields():
    """OBS-03: Output line contains module / runId / level fields as JSON."""
    mint_run_id()
    logger = logging.getLogger("test.fmt.fields")
    buf = _capture(logger, JsonFormatter())
    logger.info("hello")
    line = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert "module" in payload
    assert "runId" in payload
    assert payload["runId"] is not None
    assert payload["level"] == "INFO"
    assert payload["msg"] == "hello"


@pytest.mark.unit
def test_formatter_ascii_safe():
    """OBS-03: Non-ASCII content (emoji) round-trips as \\uXXXX — no UnicodeEncodeError."""
    logger = logging.getLogger("test.fmt.ascii")
    buf = _capture(logger, JsonFormatter())
    logger.info("hello \N{GRINNING FACE}")  # emoji
    line = buf.getvalue().strip().splitlines()[-1]
    # Must be pure ASCII bytes (json.dumps with ensure_ascii=True)
    line.encode("ascii")  # would raise UnicodeEncodeError if non-ASCII present
    assert "\\u" in line  # escape sequence present when emoji logged (ensure_ascii=True)


@pytest.mark.unit
def test_child_logger_extras():
    """OBS-01: get_child_logger('channel.whatsapp') returns adapter with module in extras."""
    log = get_child_logger("channel.whatsapp")
    assert isinstance(log, logging.LoggerAdapter)
    assert log.extra.get("module") == "channel.whatsapp"


@pytest.mark.asyncio
async def test_contextvar_across_tasks():
    """OBS-01: run_id ContextVar propagates across asyncio.create_task() (py311+ behavior)."""
    rid = mint_run_id()

    async def child():
        return get_run_id()

    got = await asyncio.create_task(child())
    assert got == rid, f"ContextVar did not propagate into create_task: parent={rid} child={got}"
