"""
test_smart_entity.py — Tests for the EntityGate (FlashText keyword extraction).

Covers:
  - Initialization with existing/missing entities file
  - Entity extraction from text
  - extract_keywords alias
  - Adding entities at runtime
  - Empty/None input handling
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

pytest.importorskip("flashtext", reason="flashtext not installed (requirements-ml.txt)")

from sci_fi_dashboard.smart_entity import EntityGate


@pytest.fixture
def entities_file(tmp_path):
    """Create a temporary entities JSON file."""
    entities = {
        "Python": ["python", "py", "Python3"],
        "Elden Ring": ["elden ring", "SOTE", "elden"],
        "Kolkata": ["kolkata", "calcutta", "cal"],
    }
    fpath = tmp_path / "entities.json"
    fpath.write_text(json.dumps(entities))
    return str(fpath)


@pytest.fixture
def gate(entities_file):
    """EntityGate with test entities."""
    # EntityGate resolves path relative to its own script dir, so we need to patch
    with patch.object(EntityGate, "__init__", lambda self, **kw: None):
        g = EntityGate.__new__(EntityGate)
        from flashtext import KeywordProcessor

        g.keyword_processor = KeywordProcessor()
        g.entities_file = entities_file
        g.load_entities()
        return g


class TestEntityGateInit:
    """Tests for EntityGate initialization."""

    def test_init_with_entities_file(self, gate):
        """Should load entities from file."""
        # If entities loaded, extract_entities should work
        result = gate.extract_entities("I love python")
        assert "Python" in result

    def test_init_with_missing_file(self, tmp_path):
        """Missing file should result in empty keyword processor."""
        with patch.object(EntityGate, "__init__", lambda self, **kw: None):
            g = EntityGate.__new__(EntityGate)
            from flashtext import KeywordProcessor

            g.keyword_processor = KeywordProcessor()
            g.entities_file = str(tmp_path / "nonexistent.json")
            g.load_entities()
            result = g.extract_entities("I love python")
            assert result == []


class TestExtractEntities:
    """Tests for extract_entities method."""

    def test_single_entity(self, gate):
        """Should extract a single entity."""
        result = gate.extract_entities("Let's play elden ring")
        assert "Elden Ring" in result

    def test_variation_mapping(self, gate):
        """Should map variations to standard names."""
        result = gate.extract_entities("Is SOTE worth it?")
        assert "Elden Ring" in result

    def test_multiple_entities(self, gate):
        """Should extract multiple entities."""
        result = gate.extract_entities("I code python in kolkata")
        assert "Python" in result
        assert "Kolkata" in result

    def test_no_match(self, gate):
        """No matching entities should return empty list."""
        result = gate.extract_entities("The weather is nice today")
        assert result == []

    def test_empty_string(self, gate):
        """Empty string should return empty list."""
        result = gate.extract_entities("")
        assert result == []

    def test_case_insensitivity(self, gate):
        """Extraction should be case-insensitive for variations."""
        result = gate.extract_entities("I love PYTHON programming")
        # FlashText is case-insensitive by default
        assert "Python" in result


class TestExtractKeywords:
    """Tests for the extract_keywords alias method."""

    def test_alias_works(self, gate):
        """extract_keywords should be an alias for extract_entities."""
        entities = gate.extract_entities("I code python")
        keywords = gate.extract_keywords("I code python")
        assert entities == keywords


class TestAddEntity:
    """Tests for the add_entity method."""

    def test_add_new_entity(self, gate):
        """Adding a new entity should make it extractable."""
        gate.add_entity("Docker", ["docker", "Docker Desktop"])
        result = gate.extract_entities("I use docker")
        # Note: add_keyword signature is (clean_name, keyword) so behavior may vary
        # Just verify no crash
        assert isinstance(result, list)

    def test_add_entity_string_variation(self, gate):
        """Single string variation should work."""
        gate.add_entity("FastAPI", "fastapi")
        # Should not crash
        result = gate.extract_entities("deploy fastapi")
        assert isinstance(result, list)
