"""Hemisphere isolation -- fuzz check that a 'safe' query never returns 'spicy' content,
and vice versa. Tier 1 (policy enforcement) -- Tier 2 physical DB split tracked
under PRODUCT_ISSUES.md issue 4.1.

Strategy
--------
The actual hemisphere filter is enforced at the LanceDB layer in
``MemoryEngine.query()``::

    if hemisphere == "spicy":
        hemisphere_filter = "hemisphere_tag IN ('safe', 'spicy')"
    else:
        hemisphere_filter = "hemisphere_tag = 'safe'"
    q_results = self.vector_store.search(query_vec, ..., query_filter=hemisphere_filter)

To fuzz this for real (i.e. not just trust the WHERE clause we built), we use a
**real** ``LanceDBVectorStore`` backed by ``tmp_path`` so the SQL prefilter is
actually evaluated. Heavy/external pieces are mocked:

  - embedding provider returns a deterministic per-doc vector (no network)
  - reranker is mocked to raise immediately so the 'scored_fallback' branch is
    used (fast gate also catches identical-vector queries -- both paths return
    LanceDB-filtered docs verbatim)
  - ``load_affect_for_doc_ids`` returns ``{}`` (no affect overlay needed)
  - we bypass ``add_memory`` entirely and write directly through
    ``vector_store.upsert_facts`` -- this skips the SQLite ``documents`` table
    write while still giving the query path a populated LanceDB to read from.

Deviation from issue example: the parametrized seed governs the RNG that picks
the safe/spicy corpus mix. Safe docs all share one cluster vector and spicy
docs share another, so when we issue the query *embedded at the spicy
cluster* with ``hemisphere="safe"``, the spicy docs are by far the highest
cosine match -- only the hemisphere filter prevents them from leaking. That's
the property we want to fuzz: filter-as-policy under adversarial ranking.

Run with::

    cd workspace && pytest tests/test_hemisphere_isolation.py -v
"""

from __future__ import annotations

import os
import random
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("lancedb", reason="lancedb not installed")

from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore  # noqa: E402

# Markers tagged as a marker for low-cost CI selection
pytestmark = [pytest.mark.unit]


SAFE_MARKER = "SAFE_HEMISPHERE_CONTENT"
SPICY_MARKER = "SPICY_HEMISPHERE_CONTENT"
EMBED_DIM = 8  # tiny vector keeps tests fast; LanceDB still enforces the filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_engine(tmp_path, populate_safe: int, populate_spicy: int):
    """Build a MemoryEngine wired to a real LanceDB at ``tmp_path``.

    Returns ``(engine, store, safe_ids, spicy_ids)``.

    The reranker is forced to raise so the 'scored_fallback' branch executes;
    that branch returns whatever LanceDB gave back, so any leakage proves the
    hemisphere filter let it through (not a reranker artefact).
    """
    # Real LanceDB store on tmp_path (no Docker, no ~/.synapse pollution)
    store = LanceDBVectorStore(
        db_path=str(tmp_path / "lancedb"),
        table_name="hemisphere_test",
        embedding_dimensions=EMBED_DIM,
    )

    # Two clusters: safe docs live near vector A, spicy near vector B.
    safe_vec = [1.0] + [0.0] * (EMBED_DIM - 1)
    spicy_vec = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)

    safe_ids: list[int] = []
    spicy_ids: list[int] = []
    facts: list[dict] = []
    next_id = 1
    for _ in range(populate_safe):
        facts.append(
            {
                "id": next_id,
                "vector": list(safe_vec),
                "metadata": {
                    "text": f"{SAFE_MARKER} doc#{next_id} -- benign daily note",
                    "hemisphere_tag": "safe",
                    "unix_timestamp": 1_700_000_000,
                    "importance": 5,
                },
            }
        )
        safe_ids.append(next_id)
        next_id += 1
    for _ in range(populate_spicy):
        facts.append(
            {
                "id": next_id,
                "vector": list(spicy_vec),
                "metadata": {
                    "text": f"{SPICY_MARKER} doc#{next_id} -- private spicy entry",
                    "hemisphere_tag": "spicy",
                    "unix_timestamp": 1_700_000_000,
                    "importance": 5,
                },
            }
        )
        spicy_ids.append(next_id)
        next_id += 1
    store.upsert_facts(facts)

    # Mock embedding provider: returns the safe-cluster vector by default; tests
    # override per-call via ``engine.get_embedding`` patching when they want to
    # query the spicy side.
    mock_provider = MagicMock()
    mock_provider.info.return_value.name = "test-embedder"
    mock_provider.dimensions = EMBED_DIM
    mock_provider.embed_query.return_value = list(safe_vec)

    with (
        patch(
            "sci_fi_dashboard.memory_engine.LanceDBVectorStore",
            return_value=store,
        ),
        patch(
            "sci_fi_dashboard.memory_engine.get_provider",
            return_value=mock_provider,
        ),
        patch(
            "sci_fi_dashboard.memory_engine._resolve_backup_path",
            return_value=str(tmp_path / "backup.jsonl"),
        ),
    ):
        from sci_fi_dashboard.memory_engine import MemoryEngine

        engine = MemoryEngine()

    # Force the reranker to fail so query() takes the deterministic
    # 'scored_fallback' branch (or fast_gate when scores >= 0.80). Either path
    # returns LanceDB-filtered docs verbatim, which is exactly the surface we
    # want to fuzz.
    def _raise(*_args, **_kwargs):
        raise RuntimeError("reranker disabled for hemisphere isolation test")

    engine._get_ranker = _raise  # type: ignore[assignment]

    # Pin the embedding to an exact tuple so lru_cache is stable per query text.
    engine.get_embedding.cache_clear()

    return engine, store, safe_ids, spicy_ids


def _query_with_vector(engine, vector: list[float], hemisphere: str, limit: int = 10):
    """Run engine.query() with a forced embedding vector.

    Patches ``MemoryEngine.get_embedding`` so the query embeds exactly to
    ``vector``. We also patch ``load_affect_for_doc_ids`` to return an empty
    map (no affect overlay needed) and ``get_db_connection`` to a MagicMock
    since the affect path opens a real connection.
    """
    mock_conn = MagicMock()
    with (
        patch.object(engine, "get_embedding", return_value=tuple(vector)),
        patch(
            "sci_fi_dashboard.memory_engine.load_affect_for_doc_ids",
            return_value={},
        ),
        patch(
            "sci_fi_dashboard.memory_engine.get_db_connection",
            return_value=mock_conn,
        ),
    ):
        return engine.query(
            "test query about life", limit=limit, hemisphere=hemisphere, with_graph=False
        )


# ---------------------------------------------------------------------------
# Fuzz: safe queries must never surface spicy content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_safe_query_never_returns_spicy(seed, tmp_path):
    """For 50 randomized seedings, a hemisphere='safe' query must not surface
    any document carrying the spicy marker, regardless of corpus mix."""
    rng = random.Random(seed)
    n_safe = rng.randint(3, 12)
    n_spicy = rng.randint(3, 12)

    engine, _store, _safe_ids, _spicy_ids = _build_engine(tmp_path, n_safe, n_spicy)

    # Embed near the SPICY cluster on purpose -- this is the adversarial case:
    # the user's query is semantically closest to spicy docs but the policy
    # must still hide them.
    spicy_cluster = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)
    result = _query_with_vector(engine, spicy_cluster, hemisphere="safe", limit=10)

    assert result.get("tier") != "error", f"query errored: {result.get('error')}"
    contents = [r["content"] for r in result.get("results", [])]
    leaked = [c for c in contents if SPICY_MARKER in c]
    assert leaked == [], (
        f"[HEMISPHERE LEAK] safe query returned spicy docs (seed={seed}, "
        f"n_safe={n_safe}, n_spicy={n_spicy}): {leaked}"
    )


# ---------------------------------------------------------------------------
# Fuzz: spicy queries are allowed to see both, but never *only* leak the
# inverse (i.e. should still surface spicy content when it exists). We split
# this into the policy-critical assertion: "spicy cannot be hidden behind a
# safe query" -- which is the same as the previous test from the other angle.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_spicy_query_can_see_both_but_safe_cannot_see_spicy(seed, tmp_path):
    """Symmetric check: a spicy session sees both hemispheres (per policy:
    'Spicy sessions see both safe + spicy; safe sessions see only safe').

    The asymmetry is the actual security invariant -- so we assert:

    1. spicy query can return spicy docs (policy: spicy is allowed to see them)
    2. safe query, even with the SAME vector, returns ZERO spicy docs.
    """
    rng = random.Random(seed + 1000)  # disjoint from previous parametrize
    n_safe = rng.randint(3, 12)
    n_spicy = rng.randint(3, 12)

    engine, _store, _safe_ids, _spicy_ids = _build_engine(tmp_path, n_safe, n_spicy)

    spicy_cluster = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)

    spicy_result = _query_with_vector(engine, spicy_cluster, hemisphere="spicy", limit=10)
    safe_result = _query_with_vector(engine, spicy_cluster, hemisphere="safe", limit=10)

    assert spicy_result.get("tier") != "error", spicy_result.get("error")
    assert safe_result.get("tier") != "error", safe_result.get("error")

    spicy_contents = [r["content"] for r in spicy_result.get("results", [])]
    safe_contents = [r["content"] for r in safe_result.get("results", [])]

    spicy_seen_in_spicy = [c for c in spicy_contents if SPICY_MARKER in c]
    spicy_seen_in_safe = [c for c in safe_contents if SPICY_MARKER in c]

    # Spicy session: with n_spicy >= 3 docs in the spicy cluster and an embedding
    # pointed at that cluster, at least one spicy doc must surface. If this
    # ever flakes, it indicates the spicy hemisphere is silently empty -- which
    # is itself a hemisphere bug worth surfacing.
    assert spicy_seen_in_spicy, (
        f"spicy session saw zero spicy docs (seed={seed}, n_spicy={n_spicy}): "
        f"{spicy_contents}"
    )

    # Safe session: must NEVER see any spicy doc, regardless of how close the
    # query embedding is to the spicy cluster.
    assert spicy_seen_in_safe == [], (
        f"[HEMISPHERE LEAK] safe query returned spicy docs (seed={seed}): "
        f"{spicy_seen_in_safe}"
    )


# ---------------------------------------------------------------------------
# Behavioural pin: unknown hemisphere value falls back to 'safe'
# ---------------------------------------------------------------------------


def test_unknown_hemisphere_falls_back_to_safe(tmp_path):
    """Pin current behavior: any value other than 'spicy' is treated as 'safe'
    by ``MemoryEngine.query()``.

    See ``MemoryEngine.query`` lines 270-273::

        if hemisphere == "spicy":
            hemisphere_filter = "hemisphere_tag IN ('safe', 'spicy')"
        else:
            hemisphere_filter = "hemisphere_tag = 'safe'"

    This is a defense-in-depth property: a typo or unrecognized hemisphere
    value MUST default to the locked-down hemisphere, never the open one.
    """
    engine, _store, _safe_ids, _spicy_ids = _build_engine(tmp_path, 5, 5)

    spicy_cluster = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)

    for bogus in ("other", "", "SAFE", "SPICY", "vault", "private", "unknown_xyz"):
        result = _query_with_vector(engine, spicy_cluster, hemisphere=bogus, limit=10)
        assert result.get("tier") != "error", f"hemisphere={bogus!r} errored: {result.get('error')}"
        leaked = [r["content"] for r in result.get("results", []) if SPICY_MARKER in r["content"]]
        assert leaked == [], (
            f"[HEMISPHERE LEAK] hemisphere={bogus!r} surfaced spicy docs (must default to safe): "
            f"{leaked}"
        )


# ---------------------------------------------------------------------------
# Sanity: empty corpus on either side does not crash hemisphere filtering
# ---------------------------------------------------------------------------


def test_safe_query_with_no_safe_docs_returns_empty(tmp_path):
    """A safe query against a corpus that contains ONLY spicy docs must return
    zero results -- never fall back to spicy as a 'helpful' default."""
    engine, _store, _safe_ids, _spicy_ids = _build_engine(tmp_path, 0, 6)

    spicy_cluster = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)
    result = _query_with_vector(engine, spicy_cluster, hemisphere="safe", limit=10)

    assert result.get("tier") != "error", result.get("error")
    contents = [r["content"] for r in result.get("results", [])]
    assert contents == [], (
        f"safe query against spicy-only corpus must return empty, got: {contents}"
    )
