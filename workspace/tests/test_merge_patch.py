"""
test_merge_patch.py — Unit tests for config/merge_patch.py (RFC 7396).

Covers:
  - Null removes key
  - Nested dicts merge recursively
  - Proto-pollution keys silently rejected
  - Empty patch returns target unchanged
  - Non-dict patch replaces target
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.merge_patch import BLOCKED_KEYS, merge_patch

# ---------------------------------------------------------------------------
# Null removes key
# ---------------------------------------------------------------------------


class TestNullRemoval:
    def test_null_removes_existing_key(self):
        target = {"a": 1, "b": 2}
        result = merge_patch(target, {"b": None})
        assert result == {"a": 1}
        assert "b" not in result

    def test_null_on_nonexistent_key_is_noop(self):
        target = {"a": 1}
        result = merge_patch(target, {"zzz": None})
        assert result == {"a": 1}

    def test_null_removes_nested_key(self):
        target = {"a": {"b": 1, "c": 2}}
        result = merge_patch(target, {"a": {"c": None}})
        assert result == {"a": {"b": 1}}

    def test_null_removes_entire_subtree(self):
        target = {"a": {"b": {"c": 3}}, "d": 4}
        result = merge_patch(target, {"a": None})
        assert result == {"d": 4}


# ---------------------------------------------------------------------------
# Nested dicts merge recursively
# ---------------------------------------------------------------------------


class TestNestedMerge:
    def test_deep_merge(self):
        target = {"a": {"b": 1, "c": 2}, "d": 3}
        patch = {"a": {"c": 99, "e": 5}}
        result = merge_patch(target, patch)
        assert result == {"a": {"b": 1, "c": 99, "e": 5}, "d": 3}

    def test_three_level_deep_merge(self):
        target = {"a": {"b": {"c": 1, "d": 2}}}
        patch = {"a": {"b": {"d": 99, "e": 3}}}
        result = merge_patch(target, patch)
        assert result == {"a": {"b": {"c": 1, "d": 99, "e": 3}}}

    def test_new_nested_key(self):
        target = {"a": 1}
        patch = {"b": {"c": 2}}
        result = merge_patch(target, patch)
        assert result == {"a": 1, "b": {"c": 2}}

    def test_patch_dict_over_non_dict(self):
        """Patching a dict value onto a non-dict key should replace it."""
        target = {"a": "string-value"}
        patch = {"a": {"nested": True}}
        result = merge_patch(target, patch)
        assert result == {"a": {"nested": True}}

    def test_patch_non_dict_over_dict(self):
        """Patching a non-dict value onto a dict key should replace it."""
        target = {"a": {"nested": True}}
        patch = {"a": "flat-value"}
        result = merge_patch(target, patch)
        assert result == {"a": "flat-value"}


# ---------------------------------------------------------------------------
# Proto-pollution keys silently rejected
# ---------------------------------------------------------------------------


class TestProtoPollution:
    def test_proto_key_rejected(self):
        target = {"a": 1}
        result = merge_patch(target, {"__proto__": {"bad": True}})
        assert result == {"a": 1}
        assert "__proto__" not in result

    def test_constructor_key_rejected(self):
        target = {"a": 1}
        result = merge_patch(target, {"constructor": "evil"})
        assert result == {"a": 1}
        assert "constructor" not in result

    def test_prototype_key_rejected(self):
        target = {"a": 1}
        result = merge_patch(target, {"prototype": {"pwned": True}})
        assert result == {"a": 1}
        assert "prototype" not in result

    def test_blocked_keys_with_valid_keys(self):
        """Proto-pollution keys should be silently dropped; valid keys should apply."""
        target = {"a": 1}
        result = merge_patch(target, {"__proto__": {}, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_blocked_keys_set_complete(self):
        """Verify all three expected blocked keys are in the set."""
        assert {"__proto__", "constructor", "prototype"} == BLOCKED_KEYS

    def test_nested_proto_pollution(self):
        """Proto-pollution keys nested inside valid dicts should also be rejected."""
        target = {"a": {"x": 1}}
        result = merge_patch(target, {"a": {"__proto__": {"evil": True}, "y": 2}})
        assert result == {"a": {"x": 1, "y": 2}}
        assert "__proto__" not in result["a"]


# ---------------------------------------------------------------------------
# Empty patch returns target unchanged
# ---------------------------------------------------------------------------


class TestEmptyPatch:
    def test_empty_dict_patch(self):
        target = {"a": 1, "b": {"c": 2}}
        result = merge_patch(target, {})
        assert result == target

    def test_empty_target_with_patch(self):
        result = merge_patch({}, {"a": 1})
        assert result == {"a": 1}

    def test_both_empty(self):
        result = merge_patch({}, {})
        assert result == {}


# ---------------------------------------------------------------------------
# Non-dict patch replaces target
# ---------------------------------------------------------------------------


class TestNonDictPatch:
    def test_string_replaces_target(self):
        target = {"a": 1, "b": 2}
        result = merge_patch(target, "replaced")
        assert result == "replaced"

    def test_int_replaces_target(self):
        target = {"a": 1}
        result = merge_patch(target, 42)
        assert result == 42

    def test_list_replaces_target(self):
        target = {"a": 1}
        result = merge_patch(target, [1, 2, 3])
        assert result == [1, 2, 3]

    def test_bool_replaces_target(self):
        target = {"a": 1}
        result = merge_patch(target, True)
        assert result is True

    def test_none_replaces_target(self):
        """A None patch at the top level replaces the entire target."""
        target = {"a": 1}
        result = merge_patch(target, None)
        assert result is None


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_target_not_mutated(self):
        """merge_patch should not mutate the original target."""
        target = {"a": 1, "b": {"c": 2}}
        original_target = {"a": 1, "b": {"c": 2}}
        merge_patch(target, {"b": {"c": 99}})
        assert target == original_target

    def test_patch_not_mutated(self):
        """merge_patch should not mutate the patch."""
        patch = {"a": {"b": 1}}
        original_patch = {"a": {"b": 1}}
        merge_patch({"x": 1}, patch)
        assert patch == original_patch
