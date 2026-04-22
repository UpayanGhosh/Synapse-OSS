"""observability.config -- apply_logging_config entry point.

Reads the `logging` section from SynapseConfig and wires up:
  * JsonFormatter on the root handler (emits structured JSON per line)
  * RunIdFilter on every handler (stamps LogRecord.runId from ContextVar)
  * Per-module levels from cfg['modules']
  * Sensible defaults for third-party loggers (litellm, httpx, uvicorn.access)

Accepts three input shapes:
  1. A plain dict (e.g. SynapseConfig.logging directly)
  2. An object with a `.logging` attribute (the SynapseConfig instance)
  3. None or an object with no `.logging` attr -- applies defaults

Idempotent: safe to call multiple times during test setup.
Called once from api_gateway.lifespan() after SynapseConfig.load().
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from .filters import RunIdFilter
from .formatter import JsonFormatter

_DEFAULT_THIRD_PARTY_LEVELS = {
    "litellm": "WARNING",
    "litellm.proxy": "WARNING",
    "litellm.router": "WARNING",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "urllib3": "WARNING",
    "uvicorn.access": "WARNING",
    "openai._base_client": "WARNING",
    "anthropic._base_client": "WARNING",
    "google.auth": "WARNING",
    "filelock": "WARNING",  # emits lock IDs (large ints) at DEBUG — triggers OBS-02 false positives
}

_OWNED_MARKER = "_synapse_obs_owned"


def _level_value(level: str | int) -> int | None:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        numeric = logging.getLevelName(level.upper())
        if isinstance(numeric, int):
            return numeric
    return None


def _clear_owned_handlers(root: logging.Logger) -> None:
    for h in list(root.handlers):
        if getattr(h, _OWNED_MARKER, False):
            root.removeHandler(h)


def _clear_owned_filters(logger: logging.Logger) -> None:
    for f in list(logger.filters):
        if getattr(f, _OWNED_MARKER, False):
            logger.removeFilter(f)


def apply_logging_config(cfg: Any = None) -> None:
    """Apply synapse.json `logging` config to the root logger.

    Parameters
    ----------
    cfg:
        One of:
          * A plain dict, e.g. {"level": "INFO", "modules": {...}}
          * An object with a `.logging` attribute (SynapseConfig instance
            or any duck-typed equivalent).
          * None -- applies defaults (root=INFO, third-party quieted).
    """
    if cfg is None:
        cfg = {}
    elif not isinstance(cfg, dict):
        cfg = getattr(cfg, "logging", {}) or {}

    root = logging.getLogger()

    _clear_owned_handlers(root)
    _clear_owned_filters(root)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _OWNED_MARKER, True)

    filt = RunIdFilter()
    setattr(filt, _OWNED_MARKER, True)
    handler.addFilter(filt)

    root.addHandler(handler)

    root_level = _level_value(cfg.get("level", "INFO")) or logging.INFO
    root.setLevel(root_level)

    modules: dict[str, Any] = {}
    modules.update(_DEFAULT_THIRD_PARTY_LEVELS)
    operator_modules = cfg.get("modules", {}) or {}
    if isinstance(operator_modules, dict):
        modules.update(operator_modules)

    for name, level in modules.items():
        numeric = _level_value(level)
        if numeric is None:
            root.warning(
                "logging_config_invalid_level",
                extra={"module": name, "value": str(level)},
            )
            continue
        logging.getLogger(name).setLevel(numeric)


__all__ = ["apply_logging_config"]
