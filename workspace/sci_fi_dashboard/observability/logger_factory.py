"""OBS-01: get_child_logger() -- child logger factory returning LoggerAdapter."""

from __future__ import annotations

import logging


class _SynapseAdapter(logging.LoggerAdapter):
    """LoggerAdapter that moves 'module' → '_obs_module' at emit time.

    Python's LogRecord already has a 'module' attribute (the Python module
    filename). Passing 'module' in extra raises KeyError in makeRecord on
    Python 3.x.  We keep 'module' in self.extra (so callers can inspect it)
    but rename it to '_obs_module' before it reaches makeRecord.  JsonFormatter
    reads '_obs_module' preferentially over record.name.
    """

    def process(self, msg, kwargs):
        extra = {**self.extra, **kwargs.get("extra", {})}
        if "module" in extra:
            extra["_obs_module"] = extra.pop("module")
        kwargs["extra"] = extra
        return msg, kwargs


def get_child_logger(module: str, **extra) -> _SynapseAdapter:
    """Return a LoggerAdapter bound to `module` with sticky extra fields.

    Example:
        log = get_child_logger("channel.whatsapp")
        log.info("DM received", extra={"chat_id": chat_id})
    """
    base = logging.getLogger(module)
    return _SynapseAdapter(base, {"module": module, **extra})
