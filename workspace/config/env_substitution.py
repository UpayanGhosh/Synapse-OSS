"""
config/env_substitution.py — Expand ``${VAR_NAME}`` references in config values.

Only string values are examined.  Missing env vars are left as-is (the
``${VAR}`` literal remains in the output) to avoid silent data loss.
"""
from __future__ import annotations

import os
import re
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _replace_match(m: re.Match[str]) -> str:
    """Return the env var value if set, otherwise leave the placeholder intact."""
    var_name = m.group(1)
    return os.environ.get(var_name, m.group(0))


def substitute_env_vars(data: Any) -> Any:
    """Deep-walk *data* and expand ``${VAR_NAME}`` in all string values.

    Parameters
    ----------
    data : Any
        Typically the raw config dict loaded from JSON.

    Returns
    -------
    Any
        A new structure with env vars expanded (original not mutated).
    """
    if isinstance(data, dict):
        return {k: substitute_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [substitute_env_vars(item) for item in data]
    if isinstance(data, str):
        return _ENV_PATTERN.sub(_replace_match, data)
    return data
