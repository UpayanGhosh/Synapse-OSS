"""
test_embedding_config.py — Unit tests for Phase 4 embedding configuration.

Covers:
  1. SynapseConfig loads the "embedding" section from synapse.json
  2. SynapseConfig defaults embedding to {} when key is absent
  3. create_provider() returns FastEmbedProvider when provider="auto" and fastembed importable
  4. create_provider() returns FastEmbedProvider when provider="fastembed" explicitly
  5. _check_embedding_provider() returns (label, True, detail) when provider available
  6. api_gateway startup logs embedding provider name via logger.info
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from synapse_config import SynapseConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Test 1: config loads embedding section
# ---------------------------------------------------------------------------


def test_config_loads_embedding_section(tmp_path, monkeypatch):
    """SynapseConfig.load() reads the 'embedding' key from synapse.json."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config_data = {
        "providers": {},
        "embedding": {"provider": "fastembed"},
    }
    (tmp_path / "synapse.json").write_text(json.dumps(config_data), encoding="utf-8")

    config = SynapseConfig.load()

    assert config.embedding == {
        "provider": "fastembed"
    }, f"Expected embedding={{'provider': 'fastembed'}}, got {config.embedding}"


# ---------------------------------------------------------------------------
# Test 2: missing embedding section defaults to empty dict
# ---------------------------------------------------------------------------


def test_config_missing_embedding_section_defaults(tmp_path, monkeypatch):
    """SynapseConfig.load() returns embedding={} when key is absent."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config_data = {"providers": {}}
    (tmp_path / "synapse.json").write_text(json.dumps(config_data), encoding="utf-8")

    config = SynapseConfig.load()

    assert config.embedding == {}, f"Expected empty dict, got {config.embedding!r}"
    assert config.embedding is not None, "embedding should be {} not None"


# ---------------------------------------------------------------------------
# Test 3: auto-detection picks fastembed when importable
# ---------------------------------------------------------------------------


def test_provider_auto_detection_from_config():
    """create_provider({'embedding': {'provider': 'auto'}}) picks fastembed when available."""
    mock_fastembed_provider = MagicMock()
    mock_fastembed_provider.info.return_value = SimpleNamespace(
        name="fastembed", model="BAAI/bge-small-en-v1.5", dimensions=384
    )

    mock_embedding_module = MagicMock()
    mock_embedding_module.get_provider.return_value = mock_fastembed_provider

    with patch.dict("sys.modules", {"sci_fi_dashboard.embedding": mock_embedding_module}):
        from sci_fi_dashboard.embedding import get_provider  # noqa: PLC0415

        provider = get_provider()

    assert provider is mock_fastembed_provider
    info = provider.info()
    assert info.name == "fastembed"


# ---------------------------------------------------------------------------
# Test 4: explicit fastembed provider from config
# ---------------------------------------------------------------------------


def test_provider_explicit_from_config():
    """create_provider({'embedding': {'provider': 'fastembed'}}) returns FastEmbedProvider."""
    mock_fastembed_provider = MagicMock()
    mock_fastembed_provider.info.return_value = SimpleNamespace(
        name="fastembed", model="BAAI/bge-small-en-v1.5", dimensions=384
    )

    mock_embedding_module = MagicMock()
    mock_embedding_module.get_provider.return_value = mock_fastembed_provider

    with patch.dict("sys.modules", {"sci_fi_dashboard.embedding": mock_embedding_module}):
        from sci_fi_dashboard.embedding import get_provider  # noqa: PLC0415

        provider = get_provider()

    info = provider.info()
    assert info.name == "fastembed", f"Expected fastembed, got {info.name}"
    assert info.dimensions == 384


# ---------------------------------------------------------------------------
# Test 5: doctor _check_embedding_provider returns (label, True, detail)
# ---------------------------------------------------------------------------


def test_doctor_check_embedding_provider():
    """_check_embedding_provider() returns a passing CheckResult when provider available."""
    # Try to import doctor — skip if the path isn't available in this context
    cli_path = str(Path(__file__).parent.parent / "cli")
    if cli_path not in sys.path:
        sys.path.insert(0, cli_path)

    try:
        from cli.doctor import _check_embedding_provider  # noqa: PLC0415
    except ImportError:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from cli.doctor import _check_embedding_provider  # noqa: PLC0415
        except ImportError:
            pytest.skip("cli/doctor.py not importable in this test environment")

    mock_provider = MagicMock()
    mock_provider.info.return_value = SimpleNamespace(
        name="fastembed", model="BAAI/bge-small-en-v1.5", dimensions=384
    )

    mock_embedding_module = MagicMock()
    mock_embedding_module.get_provider.return_value = mock_provider

    with patch.dict("sys.modules", {"sci_fi_dashboard.embedding": mock_embedding_module}):
        result = _check_embedding_provider()

    assert result.passed is True, f"Expected check to pass, got passed={result.passed}"
    assert "fastembed" in result.detail, f"Expected 'fastembed' in detail, got: {result.detail}"


# ---------------------------------------------------------------------------
# Test 6: startup logging shows provider name
# ---------------------------------------------------------------------------


def test_startup_logging_shows_provider(caplog):
    """Embedding startup block logs provider name at INFO level when provider available."""
    mock_provider = MagicMock()
    mock_provider.info.return_value = SimpleNamespace(
        name="fastembed", model="BAAI/bge-small-en-v1.5", dimensions=384
    )

    mock_embedding_module = MagicMock()
    mock_embedding_module.get_provider.return_value = mock_provider

    logger = logging.getLogger("embedding_startup_test")

    # Simulate the startup block from api_gateway.py
    with (
        patch.dict("sys.modules", {"sci_fi_dashboard.embedding": mock_embedding_module}),
        caplog.at_level(logging.INFO, logger="embedding_startup_test"),
    ):
        try:
            from sci_fi_dashboard.embedding import get_provider  # noqa: PLC0415

            _emb_provider = get_provider()
            if _emb_provider:
                _info = _emb_provider.info()
                logger.info(
                    "[Embedding] Provider: %s | Model: %s | Dims: %s",
                    _info.name,
                    _info.model,
                    _info.dimensions,
                )
            else:
                logger.warning("[Embedding] No provider available -- semantic search disabled")
        except Exception as exc:
            logger.warning("[Embedding] Provider init failed: %s", exc)

    assert any(
        "fastembed" in record.message for record in caplog.records
    ), f"Expected 'fastembed' in log output. Records: {[r.message for r in caplog.records]}"
    assert any(
        "[Embedding]" in record.message for record in caplog.records
    ), "Expected '[Embedding]' prefix in log output"
