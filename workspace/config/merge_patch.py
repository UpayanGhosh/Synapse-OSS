"""
config/merge_patch.py — RFC 7396 JSON Merge Patch implementation.

Rules:
- If patch is not a dict, it replaces the target entirely.
- If a patch value is None (null), the key is removed from the target.
- Nested dicts merge recursively.
- Proto-pollution keys (__proto__, constructor, prototype) are silently rejected.
"""
from __future__ import annotations

from typing import Any

# Keys that must never be merged — proto-pollution guard.
BLOCKED_KEYS: frozenset[str] = frozenset({"__proto__", "constructor", "prototype"})


def merge_patch(target: dict[str, Any], patch: Any) -> dict[str, Any]:
    """Apply an RFC 7396 merge-patch to *target* and return the result.

    *target* is not mutated — a new dict is returned.

    Parameters
    ----------
    target : dict
        The base configuration dict.
    patch : Any
        The patch to apply.  If not a dict, it replaces *target* entirely
        (caller must handle the type change).

    Returns
    -------
    dict
        The merged result.
    """
    if not isinstance(patch, dict):
        # Non-dict patch replaces target wholesale.
        return patch  # type: ignore[return-value]

    result = dict(target)  # shallow copy of top level

    for key, value in patch.items():
        if key in BLOCKED_KEYS:
            continue  # silently reject proto-pollution keys

        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            existing = result.get(key)
            if isinstance(existing, dict):
                result[key] = merge_patch(existing, value)
            else:
                result[key] = merge_patch({}, value)
        else:
            result[key] = value

    return result
