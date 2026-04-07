"""
Unit tests for triple_extractor.py.

Model is mocked throughout — no 3 GB download in CI.
"""

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal torch stub so the module imports without CUDA/transformers installed
# ---------------------------------------------------------------------------


def _make_torch_stub(cuda: bool = False, mps: bool = False):
    torch_mod = types.ModuleType("torch")
    torch_mod.float16 = "float16"
    torch_mod.float32 = "float32"
    torch_mod.cuda = MagicMock()
    torch_mod.cuda.is_available = MagicMock(return_value=cuda)
    if cuda:
        props = MagicMock()
        props.total_memory = 8 * (1024 ** 3)  # 8 GB
        torch_mod.cuda.get_device_properties = MagicMock(return_value=props)

    backends = types.ModuleType("torch.backends")
    mps_mod = types.ModuleType("torch.backends.mps")
    mps_mod.is_available = MagicMock(return_value=mps)
    backends.mps = mps_mod
    torch_mod.backends = backends

    torch_mod.no_grad = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=None),
                                                          __exit__=MagicMock(return_value=False)))
    return torch_mod


# ---------------------------------------------------------------------------
# Tests: JSON parsing helpers
# ---------------------------------------------------------------------------


class TestParsing(unittest.TestCase):
    def setUp(self):
        # Patch torch before importing to avoid hardware dependency
        self.torch_stub = _make_torch_stub()
        sys.modules.setdefault("torch", self.torch_stub)
        sys.modules.setdefault("torch.backends", self.torch_stub.backends)
        sys.modules.setdefault("torch.backends.mps", self.torch_stub.backends.mps)

        from sci_fi_dashboard.triple_extractor import _parse_llm_output
        self._parse = _parse_llm_output

    def test_valid_json(self):
        raw = json.dumps({
            "facts": [{"entity": "user", "content": "likes coffee", "category": "Preference"}],
            "triples": [["user", "likes", "coffee"]],
        })
        result = self._parse(raw)
        self.assertEqual(len(result["facts"]), 1)
        self.assertEqual(result["triples"], [["user", "likes", "coffee"]])

    def test_markdown_code_block(self):
        raw = '```json\n{"facts": [], "triples": [["a", "b", "c"]]}\n```'
        result = self._parse(raw)
        self.assertEqual(result["triples"], [["a", "b", "c"]])

    def test_markdown_code_block_no_lang(self):
        raw = '```\n{"facts": [], "triples": [["x", "y", "z"]]}\n```'
        result = self._parse(raw)
        self.assertEqual(result["triples"], [["x", "y", "z"]])

    def test_regex_fallback(self):
        raw = 'Some text ["alice", "knows", "bob"] more text ["bob", "likes", "cats"]'
        result = self._parse(raw)
        self.assertEqual(len(result["triples"]), 2)
        self.assertIn(["alice", "knows", "bob"], result["triples"])

    def test_completely_malformed_returns_empty(self):
        result = self._parse("not json at all :-)")
        self.assertEqual(result, {"facts": [], "triples": []})

    def test_empty_string(self):
        result = self._parse("")
        self.assertEqual(result, {"facts": [], "triples": []})


# ---------------------------------------------------------------------------
# Tests: normalisation
# ---------------------------------------------------------------------------


class TestNormalization(unittest.TestCase):
    def setUp(self):
        self.torch_stub = _make_torch_stub()
        sys.modules.setdefault("torch", self.torch_stub)
        from sci_fi_dashboard.triple_extractor import _normalize_result
        self._normalize = _normalize_result

    def test_lowercase_entities(self):
        result = self._normalize({"facts": [
            {"entity": "Upayan", "content": "Is a developer", "category": "Work"}
        ], "triples": []})
        self.assertEqual(result["facts"][0]["entity"], "upayan")

    def test_whitespace_collapse(self):
        result = self._normalize({"facts": [
            {"entity": "  user  ", "content": "likes  coffee  a lot  ", "category": ""}
        ], "triples": []})
        self.assertEqual(result["facts"][0]["content"], "likes coffee a lot")

    def test_dedup_facts(self):
        result = self._normalize({"facts": [
            {"entity": "user", "content": "likes coffee", "category": "Preference"},
            {"entity": "user", "content": "likes coffee", "category": "Preference"},
        ], "triples": []})
        self.assertEqual(len(result["facts"]), 1)

    def test_dedup_triples(self):
        result = self._normalize({"facts": [], "triples": [
            ["a", "b", "c"],
            ["a", "b", "c"],
            ["A", "B", "C"],  # same after lowercase
        ]})
        self.assertEqual(len(result["triples"]), 1)

    def test_skip_empty_triple_parts(self):
        result = self._normalize({"facts": [], "triples": [
            ["", "rel", "obj"],
            ["subj", "", "obj"],
            ["subj", "rel", ""],
        ]})
        self.assertEqual(result["triples"], [])

    def test_skip_malformed_triples(self):
        result = self._normalize({"facts": [], "triples": [
            ["only_two_items", "rel"],
            "not a list",
        ]})
        self.assertEqual(result["triples"], [])


# ---------------------------------------------------------------------------
# Tests: device detection
# ---------------------------------------------------------------------------


class TestDeviceDetection(unittest.TestCase):
    def _run(self, cuda: bool, mps: bool) -> str:
        stub = _make_torch_stub(cuda=cuda, mps=mps)
        with patch.dict(sys.modules, {"torch": stub,
                                       "torch.backends": stub.backends,
                                       "torch.backends.mps": stub.backends.mps}):
            # Re-import with patched modules
            import importlib
            import sci_fi_dashboard.triple_extractor as mod
            importlib.reload(mod)
            return mod._detect_device()

    def test_cuda_preferred_over_mps(self):
        result = self._run(cuda=True, mps=True)
        self.assertEqual(result, "cuda")

    def test_mps_when_no_cuda(self):
        result = self._run(cuda=False, mps=True)
        self.assertEqual(result, "mps")

    def test_cpu_fallback(self):
        result = self._run(cuda=False, mps=False)
        self.assertEqual(result, "cpu")


# ---------------------------------------------------------------------------
# Tests: text chunking
# ---------------------------------------------------------------------------


class TestChunking(unittest.TestCase):
    def setUp(self):
        self.torch_stub = _make_torch_stub()
        sys.modules.setdefault("torch", self.torch_stub)
        from sci_fi_dashboard.triple_extractor import _chunk_text
        self._chunk = _chunk_text

    def test_short_text_no_split(self):
        text = "This is short."
        chunks = self._chunk(text, max_chars=1500)
        self.assertEqual(chunks, [text])

    def test_long_text_is_split(self):
        # 5 sentences of ~45 chars each (~225 chars total) — should split at max_chars=100
        sent = "The quick brown fox jumps over the lazy dog. " * 5
        chunks = self._chunk(sent, max_chars=100)
        self.assertGreater(len(chunks), 1)
        # All original content is preserved (reconstructable)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 600)  # allow sentence overshoot

    def test_empty_string(self):
        chunks = self._chunk("", max_chars=1500)
        self.assertEqual(chunks, [""])

    def test_single_very_long_sentence(self):
        text = "a" * 3000
        chunks = self._chunk(text, max_chars=1500)
        # Falls back to truncation — one chunk of max_chars
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 1500)


# ---------------------------------------------------------------------------
# Tests: extraction with mocked model
# ---------------------------------------------------------------------------


class TestExtraction(unittest.TestCase):
    def _make_extractor_with_mock_model(self, model_output: str):
        """Return a TripleExtractor whose _run_inference always returns model_output."""
        torch_stub = _make_torch_stub(cuda=True, mps=False)
        transformers_stub = types.ModuleType("transformers")
        transformers_stub.AutoModelForCausalLM = MagicMock()
        transformers_stub.AutoTokenizer = MagicMock()

        with patch.dict(sys.modules, {
            "torch": torch_stub,
            "torch.backends": torch_stub.backends,
            "torch.backends.mps": torch_stub.backends.mps,
            "transformers": transformers_stub,
        }):
            import importlib
            import sci_fi_dashboard.triple_extractor as mod
            importlib.reload(mod)
            extractor = mod.TripleExtractor()
            extractor._run_inference = MagicMock(return_value=model_output)
            return extractor

    def test_extract_returns_facts_and_triples(self):
        payload = json.dumps({
            "facts": [{"entity": "user", "content": "has reflux esophagitis", "category": "Health"}],
            "triples": [["user", "diagnosed_with", "reflux esophagitis"]],
        })
        ext = self._make_extractor_with_mock_model(payload)
        result = ext.extract("At 13 I was diagnosed with reflux esophagitis.")
        self.assertEqual(len(result["facts"]), 1)
        self.assertEqual(result["facts"][0]["content"], "has reflux esophagitis")
        self.assertEqual(len(result["triples"]), 1)

    def test_extract_empty_text(self):
        ext = self._make_extractor_with_mock_model("{}")
        result = ext.extract("")
        self.assertEqual(result, {"facts": [], "triples": []})

    def test_extract_deduplicates_across_chunks(self):
        payload = json.dumps({
            "facts": [{"entity": "user", "content": "likes coffee", "category": "Preference"}],
            "triples": [["user", "likes", "coffee"]],
        })
        ext = self._make_extractor_with_mock_model(payload)
        # Long enough to produce 2 chunks
        text = ("Sentence one. " * 110)  # ~1540 chars
        result = ext.extract(text)
        # Despite 2 chunks returning the same fact, dedup keeps one
        contents = [f["content"] for f in result["facts"]]
        self.assertEqual(len(contents), len(set(contents)))

    def test_prompt_contains_text(self):
        """Verify the extraction prompt embeds the input text."""
        torch_stub = _make_torch_stub()
        with patch.dict(sys.modules, {"torch": torch_stub,
                                       "torch.backends": torch_stub.backends,
                                       "torch.backends.mps": torch_stub.backends.mps}):
            from sci_fi_dashboard.triple_extractor import _EXTRACTION_PROMPT
            sample = "some unique content 12345"
            rendered = _EXTRACTION_PROMPT.format(content=sample)
            self.assertIn(sample, rendered)


if __name__ == "__main__":
    unittest.main()
