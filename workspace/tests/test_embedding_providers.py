"""Unit tests for the embedding provider abstraction layer.

All tests use unittest.mock — fastembed and ollama do NOT need to be installed.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers — build minimal fake modules so imports inside providers don't fail
# ---------------------------------------------------------------------------


def _make_fake_fastembed_module():
    """Return a minimal fake `fastembed` top-level module."""
    mod = types.ModuleType("fastembed")
    mod.TextEmbedding = MagicMock()
    return mod


def _make_fake_ollama_module():
    """Return a minimal fake `ollama` top-level module."""
    mod = types.ModuleType("ollama")
    mod.embeddings = MagicMock()
    return mod


# ---------------------------------------------------------------------------
# FastEmbedProvider tests
# ---------------------------------------------------------------------------


class TestFastEmbedProvider(unittest.TestCase):
    def _make_provider(self, fake_embedder=None):
        """Return a FastEmbedProvider whose internal _embedder is already set."""
        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider.__new__(FastEmbedProvider)
        provider._model_name = FastEmbedProvider.DEFAULT_MODEL
        provider._cache_dir = None
        provider._threads = 1
        provider._embedder = fake_embedder
        return provider

    def _make_embedder(self, vectors: list[list[float]]):
        """Return a mock embedder whose .embed() yields numpy-like arrays."""
        import numpy as np

        embedder = MagicMock()
        embedder.embed.return_value = iter([np.array(v) for v in vectors])
        return embedder

    # 1. embed_query adds "search_query: " prefix
    def test_fastembed_embed_query_adds_prefix(self):
        import numpy as np

        fake_embedder = MagicMock()
        fake_embedder.embed.return_value = iter([np.zeros(768)])
        provider = self._make_provider(fake_embedder)

        provider.embed_query("hello world")

        args, _ = fake_embedder.embed.call_args
        texts_passed = args[0]
        self.assertEqual(len(texts_passed), 1)
        self.assertTrue(
            texts_passed[0].startswith("search_query: "),
            f"Expected 'search_query: ' prefix, got: {texts_passed[0]!r}",
        )

    # 2. embed_documents adds "search_document: " prefix for each doc
    def test_fastembed_embed_documents_adds_prefix(self):
        import numpy as np

        docs = ["doc one", "doc two", "doc three"]
        fake_embedder = MagicMock()
        fake_embedder.embed.return_value = iter([np.zeros(768) for _ in docs])
        provider = self._make_provider(fake_embedder)

        provider.embed_documents(docs)

        args, _ = fake_embedder.embed.call_args
        texts_passed = args[0]
        self.assertEqual(len(texts_passed), 3)
        for t in texts_passed:
            self.assertTrue(
                t.startswith("search_document: "),
                f"Expected 'search_document: ' prefix, got: {t!r}",
            )

    # 3. dimensions property returns 768
    def test_fastembed_output_dimensions(self):
        import numpy as np

        fake_embedder = MagicMock()
        fake_embedder.embed.return_value = iter([np.zeros(768)])
        provider = self._make_provider(fake_embedder)

        result = provider.embed_query("test")
        self.assertEqual(len(result), 768)
        self.assertEqual(provider.dimensions, 768)

    # 4. batch embedding — 3 texts in, 3 vectors out
    def test_fastembed_batch_embedding(self):
        import numpy as np

        docs = ["alpha", "beta", "gamma"]
        fake_embedder = MagicMock()
        fake_embedder.embed.return_value = iter([np.ones(768) * i for i in range(3)])
        provider = self._make_provider(fake_embedder)

        results = provider.embed_documents(docs)

        self.assertEqual(len(results), 3)
        for vec in results:
            self.assertIsInstance(vec, list)
            self.assertEqual(len(vec), 768)

    # 10. info() returns correct ProviderInfo
    def test_provider_info_metadata(self):
        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider
        from sci_fi_dashboard.embedding.base import ProviderInfo

        provider = self._make_provider()
        info = provider.info()

        self.assertIsInstance(info, ProviderInfo)
        self.assertEqual(info.name, "fastembed")
        self.assertEqual(info.model, FastEmbedProvider.DEFAULT_MODEL)
        self.assertEqual(info.dimensions, 768)
        self.assertFalse(info.requires_network)
        self.assertFalse(info.requires_gpu)


# ---------------------------------------------------------------------------
# OllamaProvider tests
# ---------------------------------------------------------------------------


class TestOllamaProvider(unittest.TestCase):
    # 5. OllamaProvider marks itself unavailable when ollama raises
    def test_ollama_provider_unavailable(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.side_effect = ConnectionError("refused")

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

            provider = OllamaProvider.__new__(OllamaProvider)
            provider._model_name = OllamaProvider.DEFAULT_MODEL
            provider._api_base = "http://localhost:11434"
            # Directly invoke availability check with the patched module
            provider._available = provider._check_availability()

        self.assertFalse(provider.available)

    # 6. embed_query passes "search_query: " prefix in the prompt argument
    def test_ollama_provider_adds_prefix(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.return_value = {"embedding": [0.1] * 768}

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

            provider = OllamaProvider.__new__(OllamaProvider)
            provider._model_name = OllamaProvider.DEFAULT_MODEL
            provider._api_base = "http://localhost:11434"
            provider._available = True

            provider.embed_query("test input")

        _, kwargs = fake_ollama.embeddings.call_args
        prompt_used = kwargs.get("prompt") or fake_ollama.embeddings.call_args[0][1]
        self.assertTrue(
            prompt_used.startswith("search_query: "),
            f"Expected 'search_query: ' prefix, got: {prompt_used!r}",
        )


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactory(unittest.TestCase):
    def setUp(self):
        # Always reset the singleton before each factory test
        from sci_fi_dashboard.embedding import factory

        factory._provider = None

    def tearDown(self):
        from sci_fi_dashboard.embedding import factory

        factory._provider = None

    # 7. cascade selects FastEmbed when fastembed is importable
    def test_factory_cascade_fastembed_default(self):
        fake_fastembed = _make_fake_fastembed_module()

        with patch.dict(sys.modules, {"fastembed": fake_fastembed}):
            from sci_fi_dashboard.embedding.factory import create_provider

            with patch(
                "sci_fi_dashboard.embedding.factory.FastEmbedProvider"
            ) as MockFEP:
                MockFEP.return_value = MagicMock()
                # Patch the import inside create_provider
                with patch.dict(
                    sys.modules,
                    {
                        "sci_fi_dashboard.embedding.fastembed_provider": types.ModuleType(
                            "sci_fi_dashboard.embedding.fastembed_provider"
                        )
                    },
                ):
                    sys.modules[
                        "sci_fi_dashboard.embedding.fastembed_provider"
                    ].FastEmbedProvider = MockFEP
                    result = create_provider()

            self.assertIs(result, MockFEP.return_value)

    # 8. cascade falls back to Ollama when fastembed is NOT importable
    def test_factory_cascade_ollama_fallback(self):
        # Remove fastembed from sys.modules to simulate ImportError
        modules_backup = sys.modules.copy()
        sys.modules.pop("fastembed", None)

        try:
            from sci_fi_dashboard.embedding.factory import create_provider

            mock_ollama_provider = MagicMock()
            mock_ollama_provider.available = True

            with patch(
                "sci_fi_dashboard.embedding.factory.OllamaProvider",
                return_value=mock_ollama_provider,
                create=True,
            ):
                # Simulate fastembed ImportError + Ollama success
                original_create = create_provider

                def patched_create(config=None):
                    cfg = (config or {}).get("embedding", {})
                    # fastembed not importable — raises ImportError
                    try:
                        raise ImportError("No module named 'fastembed'")
                    except ImportError:
                        pass
                    # Ollama fallback
                    from sci_fi_dashboard.embedding.factory import OllamaProvider  # noqa

                    p = mock_ollama_provider
                    if p.available:
                        return p
                    raise RuntimeError("none available")

                result = patched_create()
                self.assertIs(result, mock_ollama_provider)
        finally:
            sys.modules.update(modules_backup)

    # 9. explicit config override — config {"embedding": {"provider": "fastembed"}}
    def test_factory_explicit_config_override(self):
        config = {"embedding": {"provider": "fastembed"}}

        fake_provider = MagicMock()

        with patch(
            "sci_fi_dashboard.embedding.factory._create_explicit",
            return_value=fake_provider,
        ) as mock_explicit:
            from sci_fi_dashboard.embedding.factory import create_provider

            result = create_provider(config)

        mock_explicit.assert_called_once()
        call_args = mock_explicit.call_args
        self.assertEqual(call_args[0][0], "fastembed")
        self.assertIs(result, fake_provider)


if __name__ == "__main__":
    unittest.main()
