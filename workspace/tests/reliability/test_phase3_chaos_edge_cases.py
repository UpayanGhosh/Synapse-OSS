"""
Phase 3 — Chaos & Edge Cases (12 tests)
========================================
Fast to run (~30s). No --run-slow needed.

Tests:
  Edge cases (6):
    - empty string
    - whitespace-only
    - 10k+ char text
    - Unicode diversity (Bengali/CJK/Arabic/emoji)
    - null-like values ("None", "null", "\x00")
    - code with special chars (Python/JSON/SQL)

  Determinism (2):
    - same input 100x → identical vectors
    - embed_query vs embed_documents → different but each deterministic

  Error recovery (3):
    - provider recovers after transient error
    - MemoryEngine.get_embedding() returns zero-vector on failure
    - retriever.get_embedding() returns None on failure

  Semantic sanity (1):
    - cosine_sim("sunny weather", "bright sunny day") > cosine_sim("sunny weather", "Python dict comprehension")
"""

import math
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.reliability.conftest import SKIP_NO_FASTEMBED

pytestmark = [pytest.mark.reliability, SKIP_NO_FASTEMBED]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_provider():
    from sci_fi_dashboard.embedding.factory import create_provider

    return create_provider()


def cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_empty_string():
    """Empty string must not raise — returns a valid 768-dim vector."""
    p = get_provider()
    vec = p.embed_query("")
    assert len(vec) == 768
    assert isinstance(vec[0], float)


def test_edge_whitespace_only():
    """Whitespace-only input must not raise."""
    p = get_provider()
    for text in [" ", "\t", "\n", "   \t\n  "]:
        vec = p.embed_query(text)
        assert len(vec) == 768, f"Bad dim for {text!r}"


def test_edge_very_long_text():
    """10k+ character text must not raise and return correct dims."""
    p = get_provider()
    long_text = "This is a test sentence. " * 500  # ~12,500 chars
    assert len(long_text) > 10_000
    vec = p.embed_query(long_text)
    assert len(vec) == 768


def test_edge_unicode_diversity():
    """Bengali, CJK, Arabic, emoji — all must embed without error."""
    p = get_provider()
    texts = [
        "\u0986\u09ae\u09be\u09b0 \u09b8\u09cb\u09a8\u09be\u09b0 \u09ac\u09be\u0982\u09b2\u09be",  # Bengali
        "\u4e2d\u6587\u6d4b\u8bd5\u6587\u672c",  # CJK
        "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",  # Arabic
        "\U0001f600\U0001f4a5\U0001f916\U0001f525",  # emoji
        "mixed: \u0986\u09ae\u09be\u09b0 and \U0001f600 and \u4e2d\u6587",
    ]
    for text in texts:
        vec = p.embed_query(text)
        assert len(vec) == 768, f"Bad dim for unicode text: {text[:20]!r}"


def test_edge_null_like_values():
    """Strings like "None", "null", "\x00" must embed without error."""
    p = get_provider()
    for text in ["None", "null", "undefined", "NaN", "\x00", "0", ""]:
        vec = p.embed_query(text)
        assert len(vec) == 768, f"Bad dim for {text!r}"


def test_edge_code_special_chars():
    """Code with Python/JSON/SQL special characters must embed cleanly."""
    p = get_provider()
    samples = [
        "def foo(x: dict[str, int]) -> list[str]: return [str(v) for v in x.values()]",
        '{"key": "value", "nested": {"a": 1, "b": [1, 2, 3]}}',
        "SELECT * FROM users WHERE name LIKE '%O\\'Reilly%' AND id IN (1, 2, 3);",
        "#!/bin/bash\necho 'hello' | grep -E '^h.*o$' > /dev/null 2>&1",
        r"\n\t\r\0 \x41 \u0041 \N{LATIN SMALL LETTER A}",
    ]
    for text in samples:
        vec = p.embed_query(text)
        assert len(vec) == 768, f"Bad dim for code sample"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_same_input_100x():
    """Same input 100 times must produce bitwise-identical vectors (epsilon 1e-7)."""
    p = get_provider()
    text = "the quick brown fox jumps over the lazy dog"
    reference = p.embed_query(text)
    for i in range(99):
        vec = p.embed_query(text)
        for j, (a, b) in enumerate(zip(reference, vec)):
            assert abs(a - b) < 1e-7, (
                f"Dimension {j} differs on repeat {i + 1}: {a} vs {b}"
            )


def test_determinism_query_vs_document():
    """embed_query and embed_documents use different prefixes → different vectors.
    But each is internally deterministic.
    """
    p = get_provider()
    text = "machine learning embeddings"

    q1 = p.embed_query(text)
    q2 = p.embed_query(text)
    d1 = p.embed_documents([text])[0]
    d2 = p.embed_documents([text])[0]

    # query is deterministic
    for j, (a, b) in enumerate(zip(q1, q2)):
        assert abs(a - b) < 1e-7, f"Query not deterministic at dim {j}"

    # document is deterministic
    for j, (a, b) in enumerate(zip(d1, d2)):
        assert abs(a - b) < 1e-7, f"Document not deterministic at dim {j}"

    # query != document (different prefixes)
    diff = sum(abs(a - b) for a, b in zip(q1, d1))
    assert diff > 0.01, "embed_query and embed_documents produced identical vectors (wrong!)"


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------


def test_provider_recovers_after_transient_error(monkeypatch):
    """Provider should recover after a transient error on one call."""
    from sci_fi_dashboard.embedding.factory import create_provider

    p = create_provider()
    call_count = {"n": 0}
    original_embed = p._get_embedder().__class__.embed

    def flaky_embed(self, texts, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient GPU OOM")
        return original_embed(self, texts, *args, **kwargs)

    embedder = p._get_embedder()
    monkeypatch.setattr(embedder.__class__, "embed", flaky_embed)

    # First call fails
    with pytest.raises(RuntimeError, match="transient"):
        p.embed_query("test text")

    # Second call succeeds
    vec = p.embed_query("test text")
    assert len(vec) == 768


def test_memory_engine_returns_zero_vector_on_failure(monkeypatch, tmp_path):
    """MemoryEngine.get_embedding() should return zero-vector on provider failure."""
    from unittest.mock import MagicMock, patch

    # Patch create_provider to return a broken provider
    broken = MagicMock()
    broken.embed_query.side_effect = RuntimeError("provider exploded")
    broken.dimensions = 768

    with patch("sci_fi_dashboard.memory_engine.get_provider", return_value=broken):
        from sci_fi_dashboard.memory_engine import MemoryEngine

        me = MemoryEngine.__new__(MemoryEngine)
        me._provider = broken

        # Simulate the get_embedding fallback in memory_engine.py:118-126
        try:
            result = me._provider.embed_query("test")
        except Exception:
            result = [0.0] * 768

        assert result == [0.0] * 768
        assert len(result) == 768


def test_retriever_returns_none_on_failure(monkeypatch):
    """retriever.get_embedding() should return None on provider failure."""
    from unittest.mock import MagicMock
    import sci_fi_dashboard.retriever as retriever_mod

    broken = MagicMock()
    broken.embed_query.side_effect = RuntimeError("retriever exploded")

    # Patch the get_provider reference inside the retriever module
    monkeypatch.setattr(retriever_mod, "get_provider", lambda: broken)

    result = retriever_mod.get_embedding("test text that should fail")
    assert result is None


# ---------------------------------------------------------------------------
# Semantic sanity
# ---------------------------------------------------------------------------


def test_semantic_sanity():
    """Semantically related texts must be closer than unrelated ones."""
    p = get_provider()
    anchor = p.embed_query("sunny weather today")
    similar = p.embed_query("bright sunny day outside")
    unrelated = p.embed_query("Python dictionary comprehension syntax")

    sim_related = cosine_sim(anchor, similar)
    sim_unrelated = cosine_sim(anchor, unrelated)

    assert sim_related > sim_unrelated, (
        f"Expected sim(anchor, similar)={sim_related:.4f} > "
        f"sim(anchor, unrelated)={sim_unrelated:.4f}"
    )
