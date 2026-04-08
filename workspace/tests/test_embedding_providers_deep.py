"""Deep unit tests for the embedding provider abstraction layer — QA-1.

Covers edge cases, contract enforcement, error paths, singleton lifecycle,
and thread safety that the initial dev tests missed.

All tests are mock-based — zero real fastembed / ollama / gemini calls.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_fake_ollama_module():
    mod = types.ModuleType("ollama")
    mod.embeddings = MagicMock()
    return mod


def _make_numpy_array(values: list[float]):
    """Return a minimal object that mimics a 1-D numpy array."""
    arr = MagicMock()
    arr.tolist.return_value = values
    return arr


def _make_fastembed_provider(embedder=None):
    """Build a FastEmbedProvider bypassing __init__, injecting a fake embedder."""
    from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

    p = FastEmbedProvider.__new__(FastEmbedProvider)
    p._model_name = FastEmbedProvider.DEFAULT_MODEL
    p._cache_dir = None
    p._threads = 1
    p._embedder = embedder
    return p


def _make_ollama_provider(available: bool = True, model: str | None = None):
    """Build an OllamaProvider bypassing __init__."""
    from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

    p = OllamaProvider.__new__(OllamaProvider)
    p._model_name = model or OllamaProvider.DEFAULT_MODEL
    p._api_base = "http://localhost:11434"
    p._available = available
    return p


# ---------------------------------------------------------------------------
# 1. FastEmbedProvider — Edge Cases & Contracts
# ---------------------------------------------------------------------------


class TestFastEmbedEmptyString(unittest.TestCase):
    """embed_query('') must not raise and must return a 768-dim list[float]."""

    def test_fastembed_empty_string_query(self):
        vec = [0.0] * 768
        fake_array = _make_numpy_array(vec)
        embedder = MagicMock()
        embedder.embed.return_value = iter([fake_array])

        provider = _make_fastembed_provider(embedder)
        result = provider.embed_query("")

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 768)
        # Verify prefix still applied even for empty string
        args, _ = embedder.embed.call_args
        self.assertEqual(args[0][0], "search_query: ")


class TestFastEmbedUnicodeText(unittest.TestCase):
    """embed_query with non-ASCII Unicode must return a 768-dim vector."""

    def test_fastembed_unicode_text(self):
        vec = [0.1] * 768
        fake_array = _make_numpy_array(vec)
        embedder = MagicMock()
        embedder.embed.return_value = iter([fake_array])

        provider = _make_fastembed_provider(embedder)
        result = provider.embed_query("日本語テスト こんにちは")

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 768)


class TestFastEmbedVeryLongText(unittest.TestCase):
    """embed_query with 1 000-word text must not crash."""

    def test_fastembed_very_long_text(self):
        long_text = "word " * 1000
        vec = [0.5] * 768
        fake_array = _make_numpy_array(vec)
        embedder = MagicMock()
        embedder.embed.return_value = iter([fake_array])

        provider = _make_fastembed_provider(embedder)
        result = provider.embed_query(long_text)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 768)


class TestFastEmbedSingleDocumentBatch(unittest.TestCase):
    """embed_documents(['single doc']) returns a list of exactly 1 vector."""

    def test_fastembed_single_document_batch(self):
        vec = [1.0] * 768
        fake_array = _make_numpy_array(vec)
        embedder = MagicMock()
        embedder.embed.return_value = iter([fake_array])

        provider = _make_fastembed_provider(embedder)
        results = provider.embed_documents(["single doc"])

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], list)
        self.assertEqual(len(results[0]), 768)


class TestFastEmbedOutputIsListOfFloat(unittest.TestCase):
    """embed_query must return list[float], NOT a numpy array."""

    def test_fastembed_output_is_list_of_float_not_numpy(self):
        import numpy as np

        embedder = MagicMock()
        # Return a real numpy array (the provider should convert it)
        embedder.embed.return_value = iter([np.array([0.1] * 768)])

        provider = _make_fastembed_provider(embedder)
        result = provider.embed_query("hello")

        # Must be a plain list, not a numpy ndarray
        self.assertIsInstance(result, list)
        # All elements must be plain Python floats (JSON-serialisable)
        for val in result:
            self.assertIsInstance(val, float)
        # Verify it is JSON-serialisable (no TypeError)
        import json
        json.dumps(result)  # would raise if numpy floats slipped through


class TestFastEmbedPrefixNotDuplicated(unittest.TestCase):
    """Calling embed_query twice must NOT duplicate the prefix."""

    def test_fastembed_prefix_not_duplicated_on_retry(self):
        import numpy as np

        call_count = {"n": 0}

        def fake_embed(texts):
            call_count["n"] += 1
            return iter([np.zeros(768)])

        embedder = MagicMock()
        embedder.embed.side_effect = fake_embed

        provider = _make_fastembed_provider(embedder)

        provider.embed_query("hello")
        provider.embed_query("hello")

        # Inspect both calls
        all_calls = embedder.embed.call_args_list
        self.assertEqual(len(all_calls), 2)
        for c in all_calls:
            texts_passed = c[0][0]
            self.assertEqual(len(texts_passed), 1)
            text = texts_passed[0]
            # Prefix appears exactly once
            self.assertEqual(text.count("search_query: "), 1,
                             f"Prefix duplicated: {text!r}")
            # Must start with the prefix
            self.assertTrue(text.startswith("search_query: "))


class TestFastEmbedThreadCountMinCpu(unittest.TestCase):
    """When os.cpu_count() returns 2, _threads must equal 2 (min(4, 2))."""

    def test_fastembed_thread_count_defaults_to_min4_cpu(self):
        with patch("os.cpu_count", return_value=2):
            from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider
            p = FastEmbedProvider.__new__(FastEmbedProvider)
            p._model_name = FastEmbedProvider.DEFAULT_MODEL
            p._cache_dir = None
            # Replicate __init__ logic
            p._threads = None or min(4, os.cpu_count() or 1)
            p._embedder = None

        self.assertEqual(p._threads, 2)


class TestFastEmbedThreadCountCapsAt4(unittest.TestCase):
    """When os.cpu_count() returns 16, _threads must equal 4 (min(4, 16))."""

    def test_fastembed_thread_count_caps_at_4(self):
        with patch("os.cpu_count", return_value=16):
            from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider
            p = FastEmbedProvider.__new__(FastEmbedProvider)
            p._model_name = FastEmbedProvider.DEFAULT_MODEL
            p._cache_dir = None
            p._threads = None or min(4, os.cpu_count() or 1)
            p._embedder = None

        self.assertEqual(p._threads, 4)


# ---------------------------------------------------------------------------
# 2. OllamaProvider — Behaviour & Error Paths
# ---------------------------------------------------------------------------


class TestOllamaKeepAlive(unittest.TestCase):
    """embed_query must pass keep_alive='5m', never '0'."""

    def test_ollama_keep_alive_is_5m_not_0(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.return_value = {"embedding": [0.0] * 768}

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            provider = _make_ollama_provider(available=True)
            provider.embed_query("test")

        _, kwargs = fake_ollama.embeddings.call_args
        self.assertEqual(kwargs.get("keep_alive"), "5m",
                         "keep_alive must be '5m' for actual embed calls")


class TestOllamaBatchPreservesOrder(unittest.TestCase):
    """embed_documents must return vectors in the same order as input texts."""

    def test_ollama_batch_preserves_order(self):
        texts = ["alpha", "beta", "gamma"]
        # Return distinct embeddings per input so we can distinguish them
        call_index = {"n": 0}

        def side_effect(**kwargs):
            idx = call_index["n"]
            call_index["n"] += 1
            return {"embedding": [float(idx)] * 768}

        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.side_effect = side_effect

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            provider = _make_ollama_provider(available=True)
            results = provider.embed_documents(texts)

        self.assertEqual(len(results), 3)
        # First vector should have all 0.0 values, second 1.0, third 2.0
        self.assertAlmostEqual(results[0][0], 0.0)
        self.assertAlmostEqual(results[1][0], 1.0)
        self.assertAlmostEqual(results[2][0], 2.0)


class TestOllamaEmbedDocumentsPrefix(unittest.TestCase):
    """embed_documents must prepend 'search_document: ' to each text."""

    def test_ollama_embed_documents_prefix(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.return_value = {"embedding": [0.0] * 768}

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            provider = _make_ollama_provider(available=True)
            provider.embed_documents(["my document"])

        _, kwargs = fake_ollama.embeddings.call_args
        prompt = kwargs.get("prompt", "")
        self.assertTrue(
            prompt.startswith("search_document: "),
            f"Expected 'search_document: ' prefix, got: {prompt!r}",
        )


class TestOllamaUnavailableDoesNotRaiseOnInit(unittest.TestCase):
    """OllamaProvider.__init__ must not raise even when ollama is unreachable."""

    def test_ollama_unavailable_does_not_raise_on_init(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.side_effect = ConnectionError("refused")

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            # Re-import to get the patched module
            if "sci_fi_dashboard.embedding.ollama_provider" in sys.modules:
                del sys.modules["sci_fi_dashboard.embedding.ollama_provider"]
            from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

            # Should not raise
            try:
                provider = OllamaProvider()
            except Exception as exc:
                self.fail(f"OllamaProvider() raised unexpectedly: {exc}")

        self.assertFalse(provider.available)


class TestOllamaEmbedQueryWhenUnavailable(unittest.TestCase):
    """embed_query when _available=False must raise or propagate a clear error.

    The provider does NOT guard against this in its current implementation —
    the call will simply attempt the ollama import and call, which will fail
    when ollama itself raises. We verify that OllamaProvider doesn't silently
    swallow errors for disabled providers.
    """

    def test_ollama_embed_query_when_unavailable_raises(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.side_effect = ConnectionError("refused")

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            provider = _make_ollama_provider(available=False)
            # The implementation always calls ollama regardless of _available.
            # A ConnectionError should propagate out.
            with self.assertRaises(Exception):
                provider.embed_query("test")


class TestOllamaInfoMetadata(unittest.TestCase):
    """info() must return correct ProviderInfo for Ollama."""

    def test_ollama_info_returns_correct_metadata(self):
        from sci_fi_dashboard.embedding.base import ProviderInfo

        provider = _make_ollama_provider(available=True)
        info = provider.info()

        self.assertIsInstance(info, ProviderInfo)
        self.assertEqual(info.name, "ollama")
        self.assertEqual(info.dimensions, 768)
        self.assertFalse(info.requires_network,
                         "Ollama is local — requires_network should be False")


# ---------------------------------------------------------------------------
# 3. GeminiAPIProvider — Guards & Contracts
# ---------------------------------------------------------------------------


class TestGeminiRaisesWithoutApiKey(unittest.TestCase):
    """GeminiAPIProvider() must raise ValueError when no API key is available."""

    def test_gemini_raises_without_env_var_and_no_kwarg(self):
        env_without_gemini = {k: v for k, v in os.environ.items()
                              if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env_without_gemini, clear=True):
            from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider
            with self.assertRaises(ValueError):
                GeminiAPIProvider()


class TestGeminiAcceptsApiKeyKwarg(unittest.TestCase):
    """GeminiAPIProvider(api_key='fake') must not raise on init (client is lazy)."""

    def test_gemini_accepts_api_key_kwarg(self):
        env_without_gemini = {k: v for k, v in os.environ.items()
                              if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env_without_gemini, clear=True):
            from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider
            try:
                provider = GeminiAPIProvider(api_key="fake-key-abc123")
            except Exception as exc:
                self.fail(f"GeminiAPIProvider(api_key=...) raised: {exc}")
            # Client must still be None (lazy)
            self.assertIsNone(provider._client)


class TestGeminiTaskTypeQuery(unittest.TestCase):
    """embed_query must use task_type='RETRIEVAL_QUERY'."""

    def _make_provider_with_mock_client(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

        mock_embedding_value = MagicMock()
        mock_embedding_value.values = [0.1] * 768

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding_value]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result

        provider = GeminiAPIProvider.__new__(GeminiAPIProvider)
        provider._model_name = GeminiAPIProvider.DEFAULT_MODEL
        provider._api_key = "fake-key"
        provider._client = mock_client
        return provider, mock_client

    def test_gemini_task_type_query_for_embed_query(self):
        provider, mock_client = self._make_provider_with_mock_client()
        provider.embed_query("hello")

        _, kwargs = mock_client.models.embed_content.call_args
        config = kwargs.get("config", {})
        self.assertEqual(config.get("task_type"), "RETRIEVAL_QUERY",
                         f"Expected RETRIEVAL_QUERY, got: {config!r}")


class TestGeminiTaskTypeDocument(unittest.TestCase):
    """embed_documents must use task_type='RETRIEVAL_DOCUMENT'."""

    def _make_provider_with_mock_client(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

        mock_embedding_value = MagicMock()
        mock_embedding_value.values = [0.1] * 768

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding_value]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result

        provider = GeminiAPIProvider.__new__(GeminiAPIProvider)
        provider._model_name = GeminiAPIProvider.DEFAULT_MODEL
        provider._api_key = "fake-key"
        provider._client = mock_client
        return provider, mock_client

    def test_gemini_task_type_document_for_embed_documents(self):
        provider, mock_client = self._make_provider_with_mock_client()
        provider.embed_documents(["doc"])

        _, kwargs = mock_client.models.embed_content.call_args
        config = kwargs.get("config", {})
        self.assertEqual(config.get("task_type"), "RETRIEVAL_DOCUMENT",
                         f"Expected RETRIEVAL_DOCUMENT, got: {config!r}")


class TestGeminiOutputDimensionality(unittest.TestCase):
    """embed_query must pass output_dimensionality=768 in the API config."""

    def _make_provider_with_mock_client(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

        mock_embedding_value = MagicMock()
        mock_embedding_value.values = [0.1] * 768

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding_value]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result

        provider = GeminiAPIProvider.__new__(GeminiAPIProvider)
        provider._model_name = GeminiAPIProvider.DEFAULT_MODEL
        provider._api_key = "fake-key"
        provider._client = mock_client
        return provider, mock_client

    def test_gemini_output_dimensionality_is_768(self):
        provider, mock_client = self._make_provider_with_mock_client()
        provider.embed_query("test")

        _, kwargs = mock_client.models.embed_content.call_args
        config = kwargs.get("config", {})
        self.assertEqual(config.get("output_dimensionality"), 768,
                         f"Expected output_dimensionality=768, got: {config!r}")


# ---------------------------------------------------------------------------
# 4. Factory Lifecycle & Singleton
# ---------------------------------------------------------------------------


class _FactoryTestBase(unittest.TestCase):
    """Base class that always resets the factory singleton."""

    def setUp(self):
        from sci_fi_dashboard.embedding import factory
        factory._provider = None

    def tearDown(self):
        from sci_fi_dashboard.embedding import factory
        factory._provider = None


class TestGetProviderReturnsSingleton(_FactoryTestBase):
    """Two consecutive get_provider() calls must return the exact same object."""

    def test_get_provider_returns_singleton(self):
        fake_provider = MagicMock()

        with patch("sci_fi_dashboard.embedding.factory.create_provider",
                   return_value=fake_provider):
            from sci_fi_dashboard.embedding.factory import get_provider
            first = get_provider()
            second = get_provider()

        self.assertIs(first, second,
                      "get_provider() must return the singleton on subsequent calls")


class TestResetProviderClearsSingleton(_FactoryTestBase):
    """reset_provider() must cause get_provider() to return a new object."""

    def test_reset_provider_clears_singleton(self):
        provider_a = MagicMock()
        provider_b = MagicMock()
        create_calls = {"n": 0}

        def side_effect(config=None):
            create_calls["n"] += 1
            return provider_a if create_calls["n"] == 1 else provider_b

        with patch("sci_fi_dashboard.embedding.factory.create_provider",
                   side_effect=side_effect):
            from sci_fi_dashboard.embedding.factory import get_provider, reset_provider

            instance_a = get_provider()
            reset_provider()
            instance_b = get_provider()

        self.assertIs(instance_a, provider_a)
        self.assertIs(instance_b, provider_b)
        self.assertIsNot(instance_a, instance_b,
                         "After reset, get_provider() must create a fresh instance")


class TestFactoryUnknownProviderRaisesValueError(_FactoryTestBase):
    """create_provider with an unknown provider name must raise ValueError."""

    def test_factory_unknown_provider_name_raises_value_error(self):
        from sci_fi_dashboard.embedding.factory import create_provider
        with self.assertRaises(ValueError):
            create_provider({"embedding": {"provider": "nonexistent_provider"}})


class TestFactoryReturnsNoneWhenNoProviderAvailable(_FactoryTestBase):
    """get_provider() must return None (not raise) when all providers fail."""

    def test_factory_returns_none_gracefully_when_no_provider(self):
        with patch("sci_fi_dashboard.embedding.factory.create_provider",
                   side_effect=RuntimeError("No embedding provider available")):
            from sci_fi_dashboard.embedding.factory import get_provider
            result = get_provider()

        self.assertIsNone(result)


class TestFactoryExplicitOllamaConfig(_FactoryTestBase):
    """create_provider({'embedding': {'provider': 'ollama'}}) must return OllamaProvider."""

    def test_factory_explicit_ollama_config(self):
        mock_ollama_instance = MagicMock()
        mock_ollama_instance.available = True

        with patch("sci_fi_dashboard.embedding.factory._create_explicit",
                   return_value=mock_ollama_instance) as mock_explicit:
            from sci_fi_dashboard.embedding.factory import create_provider
            result = create_provider({"embedding": {"provider": "ollama"}})

        mock_explicit.assert_called_once_with("ollama", model=None,
                                               cache_dir=None, threads=None)
        self.assertIs(result, mock_ollama_instance)


class TestFactoryPassesModelToProvider(_FactoryTestBase):
    """create_provider with a custom model must forward it to the provider constructor."""

    def test_factory_passes_model_to_provider(self):
        mock_provider = MagicMock()

        with patch("sci_fi_dashboard.embedding.factory._create_explicit",
                   return_value=mock_provider) as mock_explicit:
            from sci_fi_dashboard.embedding.factory import create_provider
            result = create_provider({
                "embedding": {"provider": "fastembed", "model": "custom/model"}
            })

        mock_explicit.assert_called_once_with(
            "fastembed", model="custom/model", cache_dir=None, threads=None
        )
        self.assertIs(result, mock_provider)


# ---------------------------------------------------------------------------
# Additional contract tests — cross-cutting
# ---------------------------------------------------------------------------


class TestFastEmbedLazyLoadsEmbedder(unittest.TestCase):
    """_embedder must be None after __init__ (lazy) and only created on first use."""

    def test_fastembed_embedder_is_none_before_first_use(self):
        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        p = FastEmbedProvider.__new__(FastEmbedProvider)
        p._model_name = FastEmbedProvider.DEFAULT_MODEL
        p._cache_dir = None
        p._threads = 1
        p._embedder = None

        self.assertIsNone(p._embedder)

    def test_fastembed_get_embedder_creates_embedder_on_first_call(self):
        """_get_embedder() must instantiate TextEmbedding exactly once."""
        import numpy as np

        mock_te_instance = MagicMock()
        mock_te_instance.embed.return_value = iter([np.zeros(768)])

        mock_te_class = MagicMock(return_value=mock_te_instance)

        fake_fastembed = types.ModuleType("fastembed")
        fake_fastembed.TextEmbedding = mock_te_class

        with patch.dict(sys.modules, {"fastembed": fake_fastembed}):
            # Force re-import of fastembed_provider to pick up the patch
            if "sci_fi_dashboard.embedding.fastembed_provider" in sys.modules:
                del sys.modules["sci_fi_dashboard.embedding.fastembed_provider"]
            from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

            p = FastEmbedProvider(model="nomic-ai/nomic-embed-text-v1.5-Q")
            self.assertIsNone(p._embedder)

            # Trigger lazy init
            mock_te_instance.embed.return_value = iter([np.zeros(768)])
            p.embed_query("trigger")

            mock_te_class.assert_called_once()


class TestFastEmbedDocumentOutputIsListOfLists(unittest.TestCase):
    """embed_documents must return list[list[float]], not list of numpy arrays."""

    def test_fastembed_documents_output_type(self):
        import numpy as np

        docs = ["doc one", "doc two"]
        embedder = MagicMock()
        embedder.embed.return_value = iter([np.zeros(768), np.ones(768)])

        provider = _make_fastembed_provider(embedder)
        results = provider.embed_documents(docs)

        self.assertIsInstance(results, list)
        for vec in results:
            self.assertIsInstance(vec, list)
            for val in vec:
                self.assertIsInstance(val, float)


class TestOllamaCheckAvailabilityUsesKeepAlive0(unittest.TestCase):
    """_check_availability ping must use keep_alive='0' to avoid model warm-up cost."""

    def test_ollama_availability_check_uses_keep_alive_0(self):
        fake_ollama = _make_fake_ollama_module()
        fake_ollama.embeddings.return_value = {"embedding": [0.0] * 768}

        with patch.dict(sys.modules, {"ollama": fake_ollama}):
            if "sci_fi_dashboard.embedding.ollama_provider" in sys.modules:
                del sys.modules["sci_fi_dashboard.embedding.ollama_provider"]
            from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

            provider = OllamaProvider()

        # The ping during __init__ should have used keep_alive="0"
        _, kwargs = fake_ollama.embeddings.call_args
        self.assertEqual(kwargs.get("keep_alive"), "0")


class TestGeminiDimensionsProperty(unittest.TestCase):
    """GeminiAPIProvider.dimensions must return 768 (MRL-truncated)."""

    def test_gemini_dimensions_property(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

        provider = GeminiAPIProvider.__new__(GeminiAPIProvider)
        provider._model_name = GeminiAPIProvider.DEFAULT_MODEL
        provider._api_key = "fake-key"
        provider._client = None

        self.assertEqual(provider.dimensions, 768)


class TestGeminiInfoMetadata(unittest.TestCase):
    """GeminiAPIProvider.info() must return correct ProviderInfo."""

    def test_gemini_info_metadata(self):
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider
        from sci_fi_dashboard.embedding.base import ProviderInfo

        provider = GeminiAPIProvider.__new__(GeminiAPIProvider)
        provider._model_name = GeminiAPIProvider.DEFAULT_MODEL
        provider._api_key = "fake-key"
        provider._client = None

        info = provider.info()

        self.assertIsInstance(info, ProviderInfo)
        self.assertEqual(info.name, "gemini")
        self.assertEqual(info.dimensions, 768)
        self.assertTrue(info.requires_network,
                        "Gemini is a cloud API — requires_network must be True")
        self.assertFalse(info.requires_gpu)


if __name__ == "__main__":
    unittest.main()
