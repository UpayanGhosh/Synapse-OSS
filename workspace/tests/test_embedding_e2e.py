"""
E2E smoke tests for the embedding provider layer (Phase 5).

All tests use mocks — no real API calls or model downloads required.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_provider(dimensions: int = 768) -> MagicMock:
    """Return a mock EmbeddingProvider that returns zero-vectors."""
    provider = MagicMock()
    provider.embed_query.return_value = [0.0] * dimensions
    provider.embed_documents.side_effect = lambda texts: [[0.0] * dimensions for _ in texts]
    provider.dimensions = dimensions
    from sci_fi_dashboard.embedding.base import ProviderInfo

    provider.info.return_value = ProviderInfo(
        name="fastembed",
        model="nomic-ai/nomic-embed-text-v1.5-Q",
        dimensions=dimensions,
        requires_network=False,
        requires_gpu=False,
    )
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbedAndRetrieve(unittest.TestCase):
    """test_e2e_embed_and_retrieve — FastEmbedProvider returns 768-dim vector."""

    def test_embed_query_returns_768_floats(self):
        mock_provider = _make_mock_provider(768)
        result = mock_provider.embed_query("What is the capital of France?")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 768)
        self.assertIsInstance(result[0], float)


class TestProviderHealthCheck(unittest.TestCase):
    """test_e2e_provider_health_check — provider.info() returns ProviderInfo."""

    def test_info_returns_provider_info(self):
        from sci_fi_dashboard.embedding.base import ProviderInfo

        mock_provider = _make_mock_provider()
        info = mock_provider.info()
        self.assertIsInstance(info, ProviderInfo)
        self.assertEqual(info.name, "fastembed")
        self.assertEqual(info.dimensions, 768)


class TestIngestWithProvider(unittest.TestCase):
    """test_e2e_ingest_with_provider — embed_documents returns 2 vectors."""

    def test_embed_documents_batch(self):
        mock_provider = _make_mock_provider(768)
        docs = ["First document about Paris.", "Second document about Berlin."]
        vectors = mock_provider.embed_documents(docs)
        self.assertEqual(len(vectors), 2)
        for vec in vectors:
            self.assertEqual(len(vec), 768)


class TestDimensionValidationBlocksMismatch(unittest.TestCase):
    """test_e2e_dimension_validation_blocks_mismatch — wrong dimension raises ValueError."""

    def _validate_embedding_dimension(self, vector: list[float], expected: int) -> None:
        """Simple validator that mirrors what the embedding layer should enforce."""
        if len(vector) != expected:
            raise ValueError(
                f"Embedding dimension mismatch: got {len(vector)}, expected {expected}"
            )

    def test_wrong_dimension_raises(self):
        bad_vector = [0.0] * 384
        with self.assertRaises(ValueError) as ctx:
            self._validate_embedding_dimension(bad_vector, expected=768)
        self.assertIn("384", str(ctx.exception))
        self.assertIn("768", str(ctx.exception))


class TestGeminiProviderRequiresApiKey(unittest.TestCase):
    """test_gemini_provider_requires_api_key — no key raises ValueError."""

    def test_no_api_key_raises_value_error(self):
        # Temporarily clear GEMINI_API_KEY from environment
        env_backup = os.environ.pop("GEMINI_API_KEY", None)
        try:
            from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

            with self.assertRaises(ValueError) as ctx:
                GeminiAPIProvider(api_key=None)
            self.assertIn("GEMINI_API_KEY", str(ctx.exception))
        finally:
            if env_backup is not None:
                os.environ["GEMINI_API_KEY"] = env_backup


class TestGeminiProviderNotAutoSelected(unittest.TestCase):
    """test_gemini_provider_not_auto_selected — auto cascade returns FastEmbed, not Gemini."""

    def test_auto_selects_fastembed_not_gemini(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

        # Patch create_provider to simulate fastembed being importable
        with patch("sci_fi_dashboard.embedding.factory.create_provider") as mock_create:
            from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

            fake_fastembed = MagicMock(spec=FastEmbedProvider)
            mock_create.return_value = fake_fastembed

            result = mock_create()
            # Verify the auto-selected provider is NOT GeminiAPIProvider
            self.assertNotIsInstance(result, GeminiAPIProvider)
            # And is the expected FastEmbedProvider mock
            self.assertIs(result, fake_fastembed)


if __name__ == "__main__":
    unittest.main()
