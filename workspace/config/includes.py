"""
config/includes.py — Resolve ``$include`` references in configuration dicts.

Supports loading partial config fragments from separate JSON files and merging
them into the main config tree.  Guards against infinite recursion via a
depth limit (default 5).

Usage::

    raw = json.load(open("synapse.json"))
    resolved = resolve_includes(raw, Path("~/.synapse"))
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.merge_patch import merge_patch

logger = logging.getLogger(__name__)

_MAX_INCLUDE_DEPTH = 5


def resolve_includes(
    config_dict: dict[str, Any],
    base_dir: Path,
    depth: int = 0,
) -> dict[str, Any]:
    """Resolve ``$include`` references in *config_dict*.

    An ``$include`` key may appear at any level of the dict.  Its value must
    be a string (relative file path resolved against *base_dir*) or a list of
    such strings.  Each included file is loaded as JSON and merge-patched
    into the surrounding dict (the ``$include`` key itself is removed).

    Parameters
    ----------
    config_dict : dict
        The configuration dict, possibly containing ``$include`` keys.
    base_dir : Path
        Directory against which relative include paths are resolved.
    depth : int
        Current recursion depth (callers should leave at 0).

    Returns
    -------
    dict
        A new dict with all ``$include`` references resolved and merged.

    Raises
    ------
    RecursionError
        If include depth exceeds ``_MAX_INCLUDE_DEPTH``.
    """
    if depth > _MAX_INCLUDE_DEPTH:
        raise RecursionError(
            f"$include depth exceeded maximum of {_MAX_INCLUDE_DEPTH} — "
            "check for circular includes"
        )

    result: dict[str, Any] = {}

    for key, value in config_dict.items():
        if key == "$include":
            # Process include directive — value is a path or list of paths
            paths = [value] if isinstance(value, str) else value
            if not isinstance(paths, list):
                logger.warning("$include value must be a string or list, got %s", type(value))
                continue

            for include_path in paths:
                if not isinstance(include_path, str):
                    logger.warning("$include entry must be a string, got %s", type(include_path))
                    continue

                resolved_path = (base_dir / include_path).resolve()
                if not resolved_path.is_file():
                    logger.warning("$include file not found: %s", resolved_path)
                    continue

                try:
                    with open(resolved_path, encoding="utf-8") as fh:
                        included = json.load(fh)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Failed to load $include file %s: %s", resolved_path, exc)
                    continue

                if not isinstance(included, dict):
                    logger.warning(
                        "$include file %s must contain a JSON object, got %s",
                        resolved_path,
                        type(included).__name__,
                    )
                    continue

                # Recursively resolve includes in the included file
                included = resolve_includes(included, resolved_path.parent, depth + 1)
                result = merge_patch(result, included)
        elif isinstance(value, dict):
            # Recurse into nested dicts to find nested $include directives
            resolved = resolve_includes(value, base_dir, depth)
            existing = result.get(key)
            if isinstance(existing, dict):
                # Deep-merge local keys INTO already-included fragment (local wins on leaves)
                result[key] = merge_patch(existing, resolved)
            else:
                result[key] = resolved
        else:
            result[key] = value

    return result
