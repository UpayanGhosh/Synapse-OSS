"""
config/group_policy.py — Group-level access policy with glob pattern matching.

Evaluates an ordered list of rules (channel_id + glob pattern on group_id)
and caches results for repeated lookups during the same process lifetime.
"""

from __future__ import annotations

import fnmatch

from config.schema import GroupPolicyConfig


class GroupPolicyCache:
    """Evaluate and cache group access decisions.

    Rules are evaluated top-to-bottom; the first matching rule wins.
    If no rule matches, the ``default`` action from the policy is used.
    """

    def __init__(self, config: GroupPolicyConfig) -> None:
        self._config = config
        self._cache: dict[tuple[str, str], bool] = {}

    def should_allow(self, channel_id: str, group_id: str) -> bool:
        """Return ``True`` if the group should be allowed, ``False`` otherwise.

        Parameters
        ----------
        channel_id : str
            The channel identifier (e.g. ``"whatsapp"``, ``"telegram"``).
        group_id : str
            The group/chat identifier to check against policy rules.

        Returns
        -------
        bool
            Whether the group is allowed.
        """
        cache_key = (channel_id, group_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._evaluate(channel_id, group_id)
        self._cache[cache_key] = result
        return result

    def _evaluate(self, channel_id: str, group_id: str) -> bool:
        """Evaluate rules in order — first match wins."""
        for rule in self._config.rules:
            if rule.channel_id != channel_id:
                continue
            if fnmatch.fnmatch(group_id, rule.group_pattern):
                return rule.action == "allow"

        # No rule matched — use default
        return self._config.default == "allow"

    def clear_cache(self) -> None:
        """Clear the decision cache (e.g. after policy reload)."""
        self._cache.clear()
