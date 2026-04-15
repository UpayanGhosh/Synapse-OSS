"""
test_includes.py — Unit tests for config/includes.py ($include resolution).

Covers:
  - Basic $include from a JSON file
  - Nested $include (include within include)
  - Deep-merge: local nested dict merges into included defaults (P1 bug fix)
  - Depth limit triggers RecursionError
  - Missing / invalid include files skipped gracefully
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.includes import resolve_includes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic $include
# ---------------------------------------------------------------------------


class TestBasicInclude:
    def test_single_include(self, tmp_path):
        """A single $include should merge the included file into the result."""
        _write_json(tmp_path / "defaults.json", {"a": 1, "b": 2})
        config = {"$include": "defaults.json", "c": 3}

        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_include_list(self, tmp_path):
        """$include as a list should merge all files in order."""
        _write_json(tmp_path / "first.json", {"a": 1})
        _write_json(tmp_path / "second.json", {"b": 2})
        config = {"$include": ["first.json", "second.json"], "c": 3}

        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_local_value_overrides_included(self, tmp_path):
        """Local scalar values should override included ones."""
        _write_json(tmp_path / "defaults.json", {"a": 1, "b": "old"})
        config = {"$include": "defaults.json", "b": "new"}

        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1, "b": "new"}


# ---------------------------------------------------------------------------
# Deep-merge: the P1 bug fix
# ---------------------------------------------------------------------------


class TestDeepMergeWithIncludes:
    def test_local_nested_dict_merges_into_included(self, tmp_path):
        """When an included file defines a nested dict (e.g. providers.openai.base_url)
        and the main file also has that same key with different nested keys
        (e.g. providers.openai.api_key), the result must contain BOTH keys.

        This is the exact scenario from the P1 bug report.
        """
        _write_json(
            tmp_path / "provider_defaults.json",
            {"providers": {"openai": {"base_url": "https://api.openai.com"}}},
        )
        config = {
            "$include": "provider_defaults.json",
            "providers": {"openai": {"api_key": "sk-test-123"}},
        }

        result = resolve_includes(config, tmp_path)

        # Both the included base_url AND the local api_key must be present
        assert result["providers"]["openai"]["base_url"] == "https://api.openai.com"
        assert result["providers"]["openai"]["api_key"] == "sk-test-123"

    def test_local_leaf_wins_on_conflict(self, tmp_path):
        """When both included and local define the same leaf key, local wins."""
        _write_json(
            tmp_path / "defaults.json",
            {"providers": {"openai": {"base_url": "https://default.com", "timeout": 30}}},
        )
        config = {
            "$include": "defaults.json",
            "providers": {"openai": {"base_url": "https://custom.com"}},
        }

        result = resolve_includes(config, tmp_path)
        assert result["providers"]["openai"]["base_url"] == "https://custom.com"
        assert result["providers"]["openai"]["timeout"] == 30

    def test_three_level_deep_merge(self, tmp_path):
        """Deep-merge should work at arbitrary nesting depth."""
        _write_json(
            tmp_path / "defaults.json",
            {"a": {"b": {"c": 1, "d": 2}}},
        )
        config = {
            "$include": "defaults.json",
            "a": {"b": {"d": 99, "e": 3}},
        }

        result = resolve_includes(config, tmp_path)
        assert result == {"a": {"b": {"c": 1, "d": 99, "e": 3}}}

    def test_multiple_top_level_keys_merge_independently(self, tmp_path):
        """Each top-level dict key should merge independently with included data."""
        _write_json(
            tmp_path / "defaults.json",
            {
                "providers": {"openai": {"base_url": "https://api.openai.com"}},
                "channels": {"whatsapp": {"enabled": True}},
            },
        )
        config = {
            "$include": "defaults.json",
            "providers": {"openai": {"api_key": "sk-123"}},
            "channels": {"telegram": {"enabled": True}},
        }

        result = resolve_includes(config, tmp_path)
        assert result["providers"]["openai"]["base_url"] == "https://api.openai.com"
        assert result["providers"]["openai"]["api_key"] == "sk-123"
        assert result["channels"]["whatsapp"]["enabled"] is True
        assert result["channels"]["telegram"]["enabled"] is True


# ---------------------------------------------------------------------------
# Nested $include (include within include)
# ---------------------------------------------------------------------------


class TestNestedIncludes:
    def test_include_within_include(self, tmp_path):
        """An included file can itself contain $include directives."""
        _write_json(tmp_path / "base.json", {"x": 10})
        _write_json(tmp_path / "mid.json", {"$include": "base.json", "y": 20})
        config = {"$include": "mid.json", "z": 30}

        result = resolve_includes(config, tmp_path)
        assert result == {"x": 10, "y": 20, "z": 30}


# ---------------------------------------------------------------------------
# Depth limit
# ---------------------------------------------------------------------------


class TestDepthLimit:
    def test_recursive_include_raises(self, tmp_path):
        """Circular includes should raise RecursionError."""
        # a.json includes b.json which includes a.json
        _write_json(tmp_path / "a.json", {"$include": "b.json"})
        _write_json(tmp_path / "b.json", {"$include": "a.json"})

        with pytest.raises(RecursionError, match="depth exceeded"):
            resolve_includes({"$include": "a.json"}, tmp_path)


# ---------------------------------------------------------------------------
# Graceful handling of bad includes
# ---------------------------------------------------------------------------


class TestBadIncludes:
    def test_missing_file_skipped(self, tmp_path):
        """A missing include file should be skipped with a warning."""
        config = {"$include": "nonexistent.json", "a": 1}
        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1}

    def test_invalid_json_skipped(self, tmp_path):
        """An include file with invalid JSON should be skipped."""
        (tmp_path / "bad.json").write_text("not valid json", encoding="utf-8")
        config = {"$include": "bad.json", "a": 1}
        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1}

    def test_non_dict_include_skipped(self, tmp_path):
        """An include file that contains a non-dict (e.g. a list) should be skipped."""
        _write_json(tmp_path / "list.json", [1, 2, 3])  # type: ignore[arg-type]
        config = {"$include": "list.json", "a": 1}
        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1}

    def test_non_string_include_value_skipped(self, tmp_path):
        """$include with a non-string, non-list value should be skipped."""
        config = {"$include": 42, "a": 1}
        result = resolve_includes(config, tmp_path)
        assert result == {"a": 1}
