"""OBS-01: get_child_logger() -- child logger factory returning LoggerAdapter."""

from __future__ import annotations

import logging


def get_child_logger(module: str, **extra) -> logging.LoggerAdapter:
    """Return a LoggerAdapter bound to `module` with sticky extra fields.

    Example:
        log = get_child_logger("channel.whatsapp")
        log.info("DM received", extra={"chat_id": chat_id})
    """
    base = logging.getLogger(module)
    return logging.LoggerAdapter(base, {"module": module, **extra})
