"""
conftest.py — Shared fixtures for the full pipeline test suite (phases 1–6).

Design decisions:
- Uses hash-based fake embeddings so tests never require Ollama or FastEmbed.
  Same text always produces the same deterministic 768-dim unit vector.
- Session-scoped LanceDB / SQLiteGraph / MemoryEngine fixtures are built once
  and reused across all six test phases — no redundant ingest overhead.
- Real news articles loaded via RealDatasetLoader (AG News or 20 Newsgroups)
  when available; falls back to 200 synthetic sentences on CI/offline environments.
- sci_fi_dashboard imports: tests run from workspace/ dir. A path-bootstrap
  block at the top also adds the main-branch workspace as a fallback so that
  vector_store/ and embedding/ (which live only there during the refactor branch)
  are always resolvable.
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — ensure sci_fi_dashboard is importable from both the
# linked worktree and the main-branch workspace (vector_store/ and
# embedding/ live there as untracked additions during this refactor branch).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_WORKTREE_WORKSPACE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_MAIN_WORKSPACE = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "..", "workspace")
)
for _p in (_WORKTREE_WORKSPACE, _MAIN_WORKSPACE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Embedding constants
# ---------------------------------------------------------------------------
DIMS = 768


# ---------------------------------------------------------------------------
# Hash-based fake embedding — deterministic, no external service needed
# ---------------------------------------------------------------------------


def _hash_embed(text: str) -> list[float]:
    """Return a deterministic, L2-normalised 768-dim vector for *text*.

    Two calls with the same string always return the same vector.
    This is NOT semantically meaningful — it is only suitable for
    testing DB-layer operations (upsert, search, idempotency, latency).
    """
    rng = np.random.RandomState(abs(hash(text)) % (2**31))
    vec = rng.randn(DIMS).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 1e-9:
        vec /= norm
    return vec.tolist()


# ---------------------------------------------------------------------------
# Fake embedding provider — satisfies the EmbeddingProvider ABC interface
# without loading any model weights.
# ---------------------------------------------------------------------------


class _FakeEmbedProvider:
    """Stub EmbeddingProvider backed by _hash_embed().

    Exposes the minimal surface consumed by MemoryEngine:
      .dimensions, .info(), .embed_query(), .embed_documents()
    """

    dimensions = DIMS

    class _Info:
        name = "fake-hash-embed"

    def info(self) -> _Info:  # type: ignore[override]
        return self._Info()

    def embed_query(self, text: str) -> list[float]:
        return _hash_embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Dataset loader — returns up to n real news sentences (or synthetic fallback)
# ---------------------------------------------------------------------------


def _load_pipeline_facts(n: int = 200) -> list[str]:
    """Return up to *n* non-trivial text strings for ingest fixtures.

    Priority:
    1. AG News via HuggingFace ``datasets`` (cached to ~/.cache after first run).
    2. 20 Newsgroups via scikit-learn (no download needed).
    3. 200 synthetic sentences generated from a simple template (always works).
    """
    try:
        sys.path.insert(0, os.path.join(_HERE, ".."))
        from lancedb_reliability.conftest import RealDatasetLoader

        result = RealDatasetLoader().load(n=n)
        if result:
            texts, _, _ = result
            return [t for t in texts[:n] if t and len(t) > 10]
    except Exception:
        pass

    # Synthetic fallback — guaranteed to work in any environment
    return [
        f"Test fact {i}: topic {i % 10} covering subject area {i % 5} with "
        f"extended context about domain {i % 3} and category {i % 7}"
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Universal mock JSON
# Satisfies BOTH DualCognitionEngine._analyze_present() and _merge_streams()
# parsing so mock_llm_fn works for all dual-cognition tests.
# ---------------------------------------------------------------------------

MOCK_UNIVERSAL_JSON = json.dumps(
    {
        # _analyze_present fields
        "sentiment": "positive",
        "intent": "question",
        "topics": ["career"],
        "claims": [],
        "emotional_state": "calm",
        "conversational_pattern": "single_turn",
        # _merge_streams fields
        "thought": "User seems reflective",
        "tension_level": 0.2,
        "tension_type": "mild_contradiction",
        "response_strategy": "acknowledge",
        "suggested_tone": "warm",
        "inner_monologue": "All clear, respond warmly",
        "contradictions": [],
    }
)


# ---------------------------------------------------------------------------
# Session-scoped: raw fact texts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_facts() -> list[str]:
    """200 real or synthetic fact strings, loaded once per test session."""
    return _load_pipeline_facts(200)


# ---------------------------------------------------------------------------
# Session-scoped: SQLiteGraph populated with topic relations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_graph(tmp_path_factory):
    """SQLiteGraph with ~50 facts and basic topic relations.

    Nodes represent individual facts (fact_0 … fact_49) plus four shared
    topic nodes ("sports", "technology", "business", "world").
    Edges connect each fact to matching topics via ``is_about`` relations.
    """
    import re

    from sci_fi_dashboard.sqlite_graph import SQLiteGraph

    db_path = str(tmp_path_factory.mktemp("graph") / "graph.db")
    graph = SQLiteGraph(db_path=db_path)

    facts = _load_pipeline_facts(50)
    PATTERNS = [
        (r"\b(sports?|sport)\b", "is_about", "sports"),
        (r"\b(tech|software|computer)\b", "is_about", "technology"),
        (r"\b(business|company|market)\b", "is_about", "business"),
        (r"\b(world|international|global)\b", "is_about", "world"),
    ]

    for i, fact in enumerate(facts):
        entity = f"fact_{i}"
        graph.add_node(entity, node_type="fact")
        for pattern, relation, target in PATTERNS:
            if re.search(pattern, fact, re.IGNORECASE):
                graph.add_node(target, node_type="topic")
                graph.add_relation(entity, relation, target)

    yield graph
    graph.close()


# ---------------------------------------------------------------------------
# Session-scoped: LanceDBVectorStore pre-loaded with 200 facts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_lancedb(tmp_path_factory, pipeline_facts):
    """LanceDBVectorStore with 200 upserted facts (hash-embedded, safe hemisphere).

    Shared across all pipeline test phases — only ingested once per session.
    Each fact carries full metadata: text, hemisphere_tag, unix_timestamp,
    importance, source_id, entity, category.
    """
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    db_path = tmp_path_factory.mktemp("lancedb")
    store = LanceDBVectorStore(db_path=str(db_path))

    batch = []
    n = len(pipeline_facts)
    for i, text in enumerate(pipeline_facts):
        batch.append(
            {
                "id": i,
                "vector": _hash_embed(text),
                "metadata": {
                    "text": text,
                    "hemisphere_tag": "safe",
                    "unix_timestamp": int(time.time()) - (n - i) * 3600,
                    "importance": 5,
                    "source_id": i,
                    "entity": "",
                    "category": "news",
                },
            }
        )

    store.upsert_facts(batch)
    yield store
    # LanceDBVectorStore.close() is a no-op but call it for interface completeness
    store.close()


# ---------------------------------------------------------------------------
# Session-scoped: MemoryEngine wired to the pipeline LanceDB + graph
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_memory_engine(pipeline_lancedb, pipeline_graph):
    """MemoryEngine instance with its internals replaced for offline testing.

    Patches:
    - ``get_provider`` → returns _FakeEmbedProvider (no Ollama / FastEmbed).
    - ``engine.vector_store`` → the pre-loaded pipeline_lancedb fixture.
    - ``engine._embed_provider`` → _FakeEmbedProvider instance.
    - ``engine.get_embedding.cache_clear()`` → flush any stale cache entries.

    The engine is safe to use for retrieval tests (query, get_embedding).
    ``add_memory`` is NOT patched — it will attempt real SQLite writes and
    may fail in test environments without a configured DB. Use direct
    ``upsert_facts`` on ``pipeline_lancedb`` for ingest tests instead.
    """
    from unittest.mock import patch

    from sci_fi_dashboard.memory_engine import MemoryEngine

    fake_provider = _FakeEmbedProvider()

    # Patch get_provider to return our fake embedder — prevents any Ollama/FastEmbed
    # network or model-download calls during MemoryEngine.__init__.
    with patch(
        "sci_fi_dashboard.memory_engine.get_provider",
        return_value=fake_provider,
    ):
        # Provide graph_store so graph-context enrichment path is exercised.
        engine = MemoryEngine(graph_store=pipeline_graph)

    # Override the vector store with our pre-seeded LanceDB fixture so that
    # all engine.query() calls hit the same data as the ingest tests.
    engine.qdrant_store = pipeline_lancedb  # type: ignore[attr-defined]
    # Also expose as vector_store for forward-compatibility with the refactored
    # MemoryEngine that uses vector_store instead of qdrant_store.
    engine.vector_store = pipeline_lancedb  # type: ignore[attr-defined]
    engine._embed_provider = fake_provider  # type: ignore[attr-defined]

    # Patch the get_embedding method so it uses _FakeEmbedProvider
    engine.get_embedding.cache_clear()
    # Monkey-patch get_embedding to use our fake provider (bypasses Ollama call)
    import functools

    @functools.lru_cache(maxsize=500)
    def _fake_get_embedding(text: str) -> tuple:
        return tuple(_hash_embed(text))

    engine.get_embedding = _fake_get_embedding  # type: ignore[method-assign]

    yield engine


# ---------------------------------------------------------------------------
# Session-scoped: DualCognitionEngine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pipeline_dual_cognition(pipeline_memory_engine, pipeline_graph):
    """DualCognitionEngine wired to the pipeline MemoryEngine and graph.

    Ready for async think() calls in phase-3 tests.
    """
    from sci_fi_dashboard.dual_cognition import DualCognitionEngine

    return DualCognitionEngine(
        memory_engine=pipeline_memory_engine,
        graph=pipeline_graph,
    )


# ---------------------------------------------------------------------------
# Function-scoped: ProfileManager in a fresh temp directory
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_profile_dir(tmp_path):
    """Isolated per-test directory for ProfileManager state."""
    return tmp_path / "profile"


@pytest.fixture
def pipeline_profile_manager(pipeline_profile_dir):
    """ProfileManager writing to an isolated temp directory.

    Each test gets a clean slate — no cross-test profile pollution.
    """
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager

    return ProfileManager(profile_dir=pipeline_profile_dir)


# ---------------------------------------------------------------------------
# Function-scoped: mock LLM callable (AsyncMock returning universal JSON)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_fn():
    """AsyncMock that returns MOCK_UNIVERSAL_JSON for any input.

    Suitable for feeding into DualCognitionEngine.think() without a live LLM.
    """
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=MOCK_UNIVERSAL_JSON)


# ---------------------------------------------------------------------------
# Function-scoped: mock SynapseLLMRouter
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router():
    """MagicMock standing in for SynapseLLMRouter.

    .call and .call_with_metadata both return a pre-built LLMResult
    with a realistic token count and the text "Sure!".
    """
    from unittest.mock import AsyncMock, MagicMock

    from sci_fi_dashboard.llm_router import LLMResult

    result = LLMResult(
        text="Sure!",
        model="test/mock-model",
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
    )
    mock = MagicMock()
    mock.call = AsyncMock(return_value=result)
    mock.call_with_metadata = AsyncMock(return_value=result)
    return mock
