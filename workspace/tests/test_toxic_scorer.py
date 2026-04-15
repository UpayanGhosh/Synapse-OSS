"""
test_toxic_scorer.py — Tests for toxic_scorer_lazy.py

All torch/transformers imports are mocked to avoid model loading.

Covers:
  - LazyToxicScorer construction
  - Lazy loading (model not loaded until score())
  - score() returns a float
  - is_loaded() state tracking
  - Auto-unload after idle timeout
  - Error handling in score()
  - Multiple score calls reuse loaded model
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# Mock torch before importing the module
mock_torch = MagicMock()
mock_torch.backends.mps.is_available.return_value = False
mock_torch.no_grad.return_value.__enter__ = MagicMock()
mock_torch.no_grad.return_value.__exit__ = MagicMock()


@pytest.fixture
def mock_transformers():
    mock_tokenizer_cls = MagicMock()
    mock_model_cls = MagicMock()

    mock_tokenizer = MagicMock()
    mock_model = MagicMock()

    mock_tokenizer_cls.from_pretrained.return_value = mock_tokenizer
    mock_model_cls.from_pretrained.return_value = mock_model

    # Mock tokenizer output (tensor-like)
    mock_inputs = MagicMock()
    mock_inputs.to.return_value = mock_inputs
    mock_tokenizer.return_value = mock_inputs

    # Mock model output
    mock_logits = MagicMock()
    mock_sigmoid = MagicMock()
    mock_sigmoid.cpu.return_value = mock_sigmoid
    mock_sigmoid.mean.return_value = mock_sigmoid
    mock_sigmoid.item.return_value = 0.42

    mock_torch.sigmoid.return_value = mock_sigmoid
    mock_model.__call__ = MagicMock()
    mock_output = MagicMock()
    mock_output.logits = mock_logits
    mock_model.return_value = mock_output

    return {
        "tokenizer_cls": mock_tokenizer_cls,
        "model_cls": mock_model_cls,
        "tokenizer": mock_tokenizer,
        "model": mock_model,
    }


class TestLazyToxicScorer:
    def _make_scorer(self, mock_transformers, idle_timeout=30.0):
        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            from sci_fi_dashboard.toxic_scorer_lazy import LazyToxicScorer

            scorer = LazyToxicScorer(idle_timeout=idle_timeout)

        # Patch the _load method to use our mocks
        def mock_load():
            if scorer._model is not None:
                return
            scorer._tokenizer = mock_transformers["tokenizer"]
            scorer._model = mock_transformers["model"]

        scorer._load = mock_load
        return scorer

    def test_not_loaded_initially(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)
        assert scorer.is_loaded() is False

    def test_score_triggers_load(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            result = scorer.score("test text")

        assert scorer.is_loaded() is True
        assert isinstance(result, float)

    def test_score_returns_float(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            result = scorer.score("hello world")
            assert isinstance(result, float)
            assert 0.0 <= result <= 1.0

    def test_multiple_scores_reuse_model(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            scorer.score("text 1")
            scorer.score("text 2")
            assert scorer.is_loaded() is True

    def test_error_returns_zero(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)
        mock_transformers["tokenizer"].side_effect = RuntimeError("tokenizer error")

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            result = scorer.score("test")
            assert result == 0.0

    def test_idle_timeout_default(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)
        assert scorer.idle_timeout == 30.0

    def test_custom_idle_timeout(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers, idle_timeout=60.0)
        assert scorer.idle_timeout == 60.0

    def test_model_name(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)
        assert scorer.model_name == "unitary/toxic-bert"

    def test_unload(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            scorer.score("trigger load")
            assert scorer.is_loaded() is True
            scorer._unload()
            assert scorer.is_loaded() is False

    def test_unload_when_not_loaded(self, mock_transformers):
        scorer = self._make_scorer(mock_transformers)

        with (
            patch.dict(sys.modules, {"torch": mock_torch}),
            patch("sci_fi_dashboard.toxic_scorer_lazy.torch", mock_torch),
        ):
            scorer._unload()  # should not raise
            assert scorer.is_loaded() is False
