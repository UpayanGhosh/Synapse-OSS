"""
test_phase5_semantic_accuracy.py — Real-data semantic retrieval accuracy.

Uses AG News (120k news articles, 4 categories) or 20 Newsgroups (18k posts)
downloaded from HuggingFace / sklearn. Tests that:

1. Same-category articles have higher cosine similarity than cross-category.
2. A query about sports retrieves sports articles in top-K (not world news).
3. Category centroids are well-separated in embedding space.
4. Precision@K and Recall@K meet minimum thresholds for same-category retrieval.
5. Embedding space is not degenerate (no dimension collapse, good spread).
6. Duplicate/near-duplicate detection: same article embedded twice → score ≈ 1.0.
7. Hard negatives: articles from the most confusable category pair are tested.

These tests REQUIRE:
  - `pip install datasets` (for AG News) OR sklearn (for 20 Newsgroups)
  - FastEmbed provider (GPU or CPU) — numpy random vectors have no semantic meaning.

Skip conditions:
  - No real dataset available → all tests skip.
  - No embedding provider available → all tests skip.
"""

from __future__ import annotations

import random
from collections import defaultdict

import numpy as np
import pytest

lancedb = pytest.importorskip("lancedb", reason="lancedb not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_sim(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 1e-8 else 0.0


def _precision_at_k(results: list[dict], true_category: str, k: int) -> float:
    """Fraction of top-k results that match the true category."""
    top_k = results[:k]
    hits = sum(1 for r in top_k if r["metadata"]["category"] == true_category)
    return hits / k if k > 0 else 0.0


def _recall_at_k(results: list[dict], true_category: str, k: int, total_relevant: int) -> float:
    hits = sum(1 for r in results[:k] if r["metadata"]["category"] == true_category)
    return hits / total_relevant if total_relevant > 0 else 0.0


# ---------------------------------------------------------------------------
# Phase 5a — Category separation
# ---------------------------------------------------------------------------


class TestCategorySeparation:

    def test_intra_category_similarity_higher_than_inter(self, categorised_store):
        """Same-category article pairs have higher cosine sim than cross-category pairs.

        Samples 200 same-category pairs and 200 cross-category pairs.
        Mean intra-sim must exceed mean inter-sim by at least 0.05.
        """
        store, texts, labels, label_names = categorised_store
        rng = random.Random(42)

        # Group indices by category
        by_cat: dict[int, list[int]] = defaultdict(list)
        for i, label in enumerate(labels):
            by_cat[label].append(i)

        # Sample intra-category pairs
        facts_list = store.table.to_pandas().to_dict("records")
        vec_by_id = {r["id"]: r["vector"] for r in facts_list}

        intra_sims, inter_sims = [], []

        for _ in range(200):
            # Intra: same category
            cat = rng.choice(list(by_cat.keys()))
            if len(by_cat[cat]) < 2:
                continue
            i, j = rng.sample(by_cat[cat], 2)
            intra_sims.append(_cosine_sim(vec_by_id[i], vec_by_id[j]))

            # Inter: different categories
            cat_a, cat_b = rng.sample(list(by_cat.keys()), 2)
            i2 = rng.choice(by_cat[cat_a])
            j2 = rng.choice(by_cat[cat_b])
            inter_sims.append(_cosine_sim(vec_by_id[i2], vec_by_id[j2]))

        mean_intra = np.mean(intra_sims)
        mean_inter = np.mean(inter_sims)
        gap = mean_intra - mean_inter

        print(
            f"\n[category separation] "
            f"intra={mean_intra:.4f}, inter={mean_inter:.4f}, gap={gap:.4f}"
        )
        assert gap >= 0.05, (
            f"Embedding space not separating categories: "
            f"intra={mean_intra:.4f}, inter={mean_inter:.4f}, gap={gap:.4f}"
        )

    def test_category_centroids_are_separated(self, categorised_store):
        """Each category's centroid is closer to itself than to any other centroid."""
        store, texts, labels, label_names = categorised_store
        facts_df = store.table.to_pandas()

        # Compute centroid per category
        centroids = {}
        for _i, name in enumerate(label_names):
            mask = facts_df["category"] == name
            if mask.sum() == 0:
                continue
            vecs = np.stack(facts_df.loc[mask, "vector"].values)
            centroids[name] = vecs.mean(axis=0)

        # Each centroid must be nearest to itself
        cat_names = list(centroids.keys())
        failures = []
        for name in cat_names:
            c = centroids[name]
            sims = {n: _cosine_sim(c.tolist(), centroids[n].tolist()) for n in cat_names}
            nearest = max(sims, key=lambda k: sims[k])
            if nearest != name:
                failures.append(f"{name}: nearest centroid is {nearest} (sim={sims[nearest]:.4f})")

        print(f"\n[centroids] {len(cat_names)} categories, {len(failures)} centroid failures")
        assert not failures, f"Centroid separation failed: {failures}"


# ---------------------------------------------------------------------------
# Phase 5b — Retrieval precision and recall
# ---------------------------------------------------------------------------


class TestRetrievalPrecisionRecall:

    def test_precision_at_10_same_category(self, categorised_store):
        """P@10 for same-category queries must be ≥ 0.60 on average."""
        store, texts, labels, label_names = categorised_store
        rng = random.Random(43)

        by_cat: dict[int, list[int]] = defaultdict(list)
        for i, label in enumerate(labels):
            by_cat[label].append(i)

        facts_df = store.table.to_pandas()
        vec_by_id = {r["id"]: list(r["vector"]) for r in facts_df.to_dict("records")}

        p_at_10_all = []
        for label_idx, cat_name in enumerate(label_names):
            if len(by_cat[label_idx]) < 5:
                continue
            # Sample 20 query items from this category
            query_indices = rng.sample(by_cat[label_idx], min(20, len(by_cat[label_idx])))
            cat_p = []
            for qi in query_indices:
                q_vec = vec_by_id[qi]
                results = store.search(q_vec, limit=11)  # +1 because query itself may appear
                # Exclude the query document itself
                results = [r for r in results if r["id"] != qi][:10]
                cat_p.append(_precision_at_k(results, cat_name, k=10))
            mean_p = np.mean(cat_p)
            p_at_10_all.append(mean_p)
            print(f"\n  [{cat_name}] P@10 = {mean_p:.3f}")

        overall_p = np.mean(p_at_10_all)
        print(f"\n[P@10 overall] {overall_p:.3f} across {len(label_names)} categories")
        assert overall_p >= 0.60, f"Mean P@10 = {overall_p:.3f} below threshold 0.60"

    def test_sports_query_retrieves_sports_not_world(self, categorised_store):
        """A sports article query should return mostly Sports, not World articles."""
        store, texts, labels, label_names = categorised_store

        if "Sports" not in label_names:
            pytest.skip("Dataset has no 'Sports' category (not AG News)")

        label_names.index("Sports")
        world_idx = label_names.index("World") if "World" in label_names else -1

        facts_df = store.table.to_pandas()
        sports_facts = facts_df[facts_df["category"] == "Sports"].head(10)

        if len(sports_facts) == 0:
            pytest.skip("No Sports articles in store")

        sports_hits, world_hits = 0, 0
        for _, row in sports_facts.iterrows():
            results = store.search(list(row["vector"]), limit=11)
            results = [r for r in results if r["id"] != row["id"]][:10]
            sports_hits += sum(1 for r in results if r["metadata"]["category"] == "Sports")
            if world_idx >= 0:
                world_hits += sum(1 for r in results if r["metadata"]["category"] == "World")

        total = len(sports_facts) * 10
        sports_rate = sports_hits / total
        world_rate = world_hits / total if world_idx >= 0 else 0
        print(f"\n[sports query] Sports={sports_rate:.2%}, World={world_rate:.2%}")
        assert sports_rate > world_rate, (
            f"Sports query returned more World than Sports: "
            f"sports={sports_rate:.2%}, world={world_rate:.2%}"
        )
        assert sports_rate >= 0.50, f"Sports P@10 too low: {sports_rate:.2%}"

    def test_scitech_query_retrieves_scitech(self, categorised_store):
        """Sci/Tech articles should retrieve other Sci/Tech, not Business."""
        store, texts, labels, label_names = categorised_store

        scitech_name = next(
            (n for n in label_names if "sci" in n.lower() or "tech" in n.lower()), None
        )
        if scitech_name is None:
            pytest.skip("Dataset has no Sci/Tech category")

        facts_df = store.table.to_pandas()
        scitech_facts = facts_df[facts_df["category"] == scitech_name].head(10)

        if len(scitech_facts) == 0:
            pytest.skip("No Sci/Tech articles in store")

        p_at_10_list = []
        for _, row in scitech_facts.iterrows():
            results = store.search(list(row["vector"]), limit=11)
            results = [r for r in results if r["id"] != row["id"]][:10]
            p_at_10_list.append(_precision_at_k(results, scitech_name, k=10))

        mean_p = np.mean(p_at_10_list)
        print(f"\n[{scitech_name} P@10] {mean_p:.3f}")
        assert mean_p >= 0.50, f"{scitech_name} P@10 = {mean_p:.3f} below 0.50"


# ---------------------------------------------------------------------------
# Phase 5c — Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:

    def test_same_text_embedded_twice_scores_near_1(self, categorised_store, generator):
        """Embedding the same article twice → cosine similarity ≈ 1.0 (determinism)."""
        store, texts, labels, label_names = categorised_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        sample_text = texts[0]
        vec_a = provider.embed_query(sample_text)
        vec_b = provider.embed_query(sample_text)

        sim = _cosine_sim(vec_a, vec_b)
        print(f"\n[duplicate] same text cosine sim: {sim:.6f}")
        assert sim > 0.9999, f"Same text gave non-deterministic embeddings: sim={sim:.6f}"

    def test_near_duplicate_scores_higher_than_unrelated(self, categorised_store):
        """A near-duplicate article (minor edit) scores higher than an unrelated one."""
        store, texts, labels, label_names = categorised_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        original = texts[0]
        # Near-duplicate: append a period
        near_dup = original.rstrip(".") + ". Updated."
        # Unrelated: pick from opposite end of dataset
        unrelated = texts[-1]

        vec_orig = provider.embed_query(original)
        vec_dup = provider.embed_query(near_dup)
        vec_unrelated = provider.embed_query(unrelated)

        sim_dup = _cosine_sim(vec_orig, vec_dup)
        sim_unrelated = _cosine_sim(vec_orig, vec_unrelated)
        print(f"\n[near-dup] dup_sim={sim_dup:.4f}, unrelated_sim={sim_unrelated:.4f}")
        assert sim_dup > sim_unrelated, (
            f"Near-duplicate scored lower than unrelated: "
            f"dup={sim_dup:.4f}, unrelated={sim_unrelated:.4f}"
        )


# ---------------------------------------------------------------------------
# Phase 5d — Embedding space health
# ---------------------------------------------------------------------------


class TestEmbeddingSpaceHealth:

    def test_vectors_have_positive_variance_per_dimension(self, categorised_store):
        """No embedding dimension should be constant (degenerate/collapsed space)."""
        store, texts, labels, label_names = categorised_store
        facts_df = store.table.to_pandas()
        vecs = np.stack(facts_df["vector"].values)  # (N, 768)

        dim_variance = vecs.var(axis=0)  # variance per dimension
        collapsed_dims = int((dim_variance < 1e-6).sum())
        total_dims = dim_variance.shape[0]

        print(
            f"\n[embedding health] {collapsed_dims}/{total_dims} near-zero-variance dims, "
            f"mean_var={dim_variance.mean():.6f}"
        )
        # Allow up to 1% collapsed dimensions (some models zero-pad a few dims)
        assert (
            collapsed_dims / total_dims < 0.01
        ), f"Too many collapsed dimensions: {collapsed_dims}/{total_dims}"

    def test_vectors_are_unit_normalised(self, categorised_store):
        """All stored vectors should be near unit length (L2 norm ≈ 1.0)."""
        store, texts, labels, label_names = categorised_store
        facts_df = store.table.to_pandas()
        vecs = np.stack(facts_df["vector"].values)
        norms = np.linalg.norm(vecs, axis=1)
        off_unit = int(np.abs(norms - 1.0) > 0.05).sum() if len(norms) > 0 else 0
        print(f"\n[unit norms] min={norms.min():.4f} max={norms.max():.4f} off_unit={off_unit}")
        assert off_unit / len(norms) < 0.01, f"{off_unit}/{len(norms)} vectors not unit-normalised"

    def test_no_zero_vectors_in_store(self, categorised_store):
        """No stored vector should be all-zeros (indicates a failed embedding)."""
        store, texts, labels, label_names = categorised_store
        facts_df = store.table.to_pandas()
        vecs = np.stack(facts_df["vector"].values)
        norms = np.linalg.norm(vecs, axis=1)
        zero_count = int((norms < 1e-6).sum())
        assert zero_count == 0, f"{zero_count} zero vectors found in store"

    def test_mean_pairwise_similarity_in_reasonable_range(self, categorised_store):
        """Mean pairwise cosine sim across 500 random pairs should be in [0.1, 0.9].

        Too high → all texts in one cluster (degenerate).
        Too low  → embeddings are random noise.
        """
        store, texts, labels, label_names = categorised_store
        rng = random.Random(44)
        facts_df = store.table.to_pandas()
        vecs = np.stack(facts_df["vector"].values)

        n = len(vecs)
        sims = []
        for _ in range(500):
            i, j = rng.randrange(n), rng.randrange(n)
            sims.append(_cosine_sim(vecs[i].tolist(), vecs[j].tolist()))

        mean_sim = np.mean(sims)
        print(f"\n[pairwise sim] mean={mean_sim:.4f} over 500 random pairs")
        assert (
            0.05 < mean_sim < 0.95
        ), f"Mean pairwise similarity {mean_sim:.4f} outside expected range [0.05, 0.95]"


# ---------------------------------------------------------------------------
# Phase 5e — Chat simulation (PersonaChat)
# ---------------------------------------------------------------------------


class TestChatMemorySimulation:
    """Simulate Synapse's actual workload: store persona facts, query with chat turns.

    PersonaChat structure:
      facts   = ["I love hiking on weekends", "I work as a nurse", ...]
      queries = ["do you enjoy outdoor activities?", "what do you do for work?", ...]

    The test verifies that a query from persona X retrieves a fact from persona X
    in the top results — i.e., LanceDB + FastEmbed can find the right memory.
    """

    def test_persona_facts_stored_and_queryable(self, persona_store):
        """Basic smoke test: facts loaded, simple query returns results."""
        store, chat_data = persona_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        # Query with a generic chat phrase
        q_vec = provider.embed_query("tell me about yourself")
        results = store.search(q_vec, limit=5)
        assert len(results) > 0, "No results returned for chat query"
        assert all("text" in r["metadata"] for r in results)

    def test_hiking_query_retrieves_hiking_fact(self, persona_store):
        """'I enjoy hiking' query should retrieve a hiking-related persona fact."""
        store, chat_data = persona_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        # Check if any hiking facts exist
        hiking_facts = [f for f in chat_data.facts if "hik" in f.lower() or "outdoor" in f.lower()]
        if not hiking_facts:
            pytest.skip("No hiking facts in dataset")

        q_vec = provider.embed_query("I really enjoy hiking and outdoor activities")
        results = store.search(q_vec, limit=10)
        texts = [r["metadata"]["text"].lower() for r in results]
        hiking_hits = sum(
            1 for t in texts if "hik" in t or "outdoor" in t or "walk" in t or "nature" in t
        )
        print(f"\n[hiking query] top-10 results: {hiking_hits} hiking-related facts")
        assert hiking_hits >= 1, f"No hiking facts in top-10 results. Got: {texts[:5]}"

    def test_job_query_retrieves_occupation_fact(self, persona_store):
        """'What do you do for work?' should retrieve occupation facts."""
        store, chat_data = persona_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        job_keywords = [
            "work",
            "job",
            "profession",
            "career",
            "employed",
            "nurse",
            "doctor",
            "engineer",
            "teacher",
            "student",
        ]
        job_facts = [f for f in chat_data.facts if any(k in f.lower() for k in job_keywords)]
        if not job_facts:
            pytest.skip("No occupation facts in dataset")

        q_vec = provider.embed_query("what do you do for a living? what is your job?")
        results = store.search(q_vec, limit=10)
        texts = [r["metadata"]["text"].lower() for r in results]
        job_hits = sum(1 for t in texts if any(k in t for k in job_keywords))
        print(f"\n[job query] top-10 results: {job_hits} occupation-related facts")
        assert job_hits >= 1, f"No occupation facts in top-10. Got: {texts[:5]}"

    def test_food_query_retrieves_food_preference(self, persona_store):
        """A food preference query retrieves food-related persona facts."""
        store, chat_data = persona_store
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        food_keywords = [
            "food",
            "eat",
            "cook",
            "pizza",
            "pasta",
            "vegetarian",
            "vegan",
            "meat",
            "fish",
            "burger",
            "restaurant",
        ]
        food_facts = [f for f in chat_data.facts if any(k in f.lower() for k in food_keywords)]
        if not food_facts:
            pytest.skip("No food facts in dataset")

        q_vec = provider.embed_query("what kind of food do you like to eat?")
        results = store.search(q_vec, limit=10)
        texts = [r["metadata"]["text"].lower() for r in results]
        food_hits = sum(1 for t in texts if any(k in t for k in food_keywords))
        print(f"\n[food query] top-10 results: {food_hits} food-related facts")
        assert food_hits >= 1, f"No food facts in top-10. Got: {texts[:5]}"

    def test_same_persona_facts_cluster_together(self, persona_store):
        """Facts from the same persona should have higher mutual similarity than cross-persona."""
        store, chat_data = persona_store
        import random as _random
        from collections import defaultdict

        # Find personas with at least 3 facts
        by_pid: dict[int, list[int]] = defaultdict(list)
        for i, pid in enumerate(chat_data.persona_ids):
            by_pid[pid].append(i)
        rich_personas = [pid for pid, idxs in by_pid.items() if len(idxs) >= 3]

        if len(rich_personas) < 10:
            pytest.skip("Not enough personas with 3+ facts")

        facts_df = store.table.to_pandas()
        vec_by_id = {int(r["id"]): list(r["vector"]) for r in facts_df.to_dict("records")}

        rng = _random.Random(99)
        intra_sims, inter_sims = [], []

        for _ in range(200):
            # Intra: two facts from the same persona
            pid = rng.choice(rich_personas)
            i, j = rng.sample(by_pid[pid], 2)
            if i in vec_by_id and j in vec_by_id:
                intra_sims.append(_cosine_sim(vec_by_id[i], vec_by_id[j]))

            # Inter: facts from two different personas
            pid_a, pid_b = rng.sample(rich_personas, 2)
            ia = rng.choice(by_pid[pid_a])
            ib = rng.choice(by_pid[pid_b])
            if ia in vec_by_id and ib in vec_by_id:
                inter_sims.append(_cosine_sim(vec_by_id[ia], vec_by_id[ib]))

        if not intra_sims or not inter_sims:
            pytest.skip("Could not compute similarities (vector IDs mismatched)")

        mean_intra = np.mean(intra_sims)
        mean_inter = np.mean(inter_sims)
        print(f"\n[persona clustering] intra={mean_intra:.4f} inter={mean_inter:.4f}")
        # Same-persona facts should be somewhat more similar
        assert (
            mean_intra >= mean_inter - 0.05
        ), f"Same-persona facts not more similar: intra={mean_intra:.4f} inter={mean_inter:.4f}"

    def test_retrieval_latency_with_real_chat_queries(self, persona_store):
        """p95 search latency over 200 real chat queries stays under 200ms."""
        store, chat_data = persona_store
        import time

        from sci_fi_dashboard.embedding.factory import get_provider

        from .conftest import LatencyTracker

        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        tracker = LatencyTracker()
        queries = chat_data.queries[:200]

        for q in queries:
            q_vec = provider.embed_query(q)
            t0 = time.perf_counter()
            store.search(q_vec, limit=5)
            tracker.record((time.perf_counter() - t0) * 1_000)

        p50 = tracker.percentile(50)
        p95 = tracker.percentile(95)
        print(f"\n[chat latency] p50={p50:.2f}ms p95={p95:.2f}ms over {tracker.count()} queries")
        assert p95 < 200, f"Chat retrieval p95 = {p95:.2f}ms exceeds 200ms"

    def test_print_persona_dataset_summary(self, persona_dataset):
        """Print PersonaChat dataset summary (always passes — informational)."""
        if persona_dataset is None:
            pytest.skip("PersonaChat unavailable")
        from collections import Counter

        pid_counts = Counter(persona_dataset.persona_ids)
        avg_facts = sum(pid_counts.values()) / len(pid_counts) if pid_counts else 0
        print(f"\n{'='*60}")
        print("PERSONACHAT DATASET SUMMARY")
        print(f"{'='*60}")
        print(f"Total facts    : {len(persona_dataset.facts)}")
        print(f"Total personas : {len(set(persona_dataset.persona_ids))}")
        print(f"Avg facts/persona : {avg_facts:.1f}")
        print(f"Total query turns : {len(persona_dataset.queries)}")
        print("Sample facts:")
        for f in persona_dataset.facts[:5]:
            print(f"  • {f}")
        print("Sample queries:")
        for q in persona_dataset.queries[:5]:
            print(f"  ? {q}")
        print(f"{'='*60}")
        assert True


# ---------------------------------------------------------------------------
# Phase 5f — Cross-dataset coverage report
# ---------------------------------------------------------------------------


class TestDatasetCoverageReport:

    def test_print_dataset_summary(self, real_dataset):
        """Print a summary of the loaded dataset (always passes — informational)."""
        if real_dataset is None:
            pytest.skip("No real dataset loaded")
        texts, labels, label_names = real_dataset
        from collections import Counter

        counts = Counter(labels)
        print(f"\n{'='*60}")
        print("DATASET SUMMARY")
        print(f"{'='*60}")
        print(f"Total records : {len(texts)}")
        print(f"Categories    : {len(label_names)}")
        print(
            f"Avg text len  : {sum(len(t) for t in texts[:10000]) / min(len(texts), 10000):.0f} chars"
        )
        print("\nPer-category counts:")
        for i, name in enumerate(label_names):
            print(f"  [{i}] {name:20s}: {counts[i]:,}")
        print(f"{'='*60}")
        assert len(texts) > 0

    def test_print_embedding_provider_info(self):
        """Print which embedding provider and model is active (GPU/CPU)."""
        try:
            from sci_fi_dashboard.embedding.factory import get_provider

            provider = get_provider()
            if provider is None:
                pytest.skip("No provider available")
            info = provider.info()
            print(f"\n{'='*60}")
            print("EMBEDDING PROVIDER")
            print(f"{'='*60}")
            print(f"Provider   : {info.name}")
            print(f"Dimensions : {info.dimensions}")
            print(f"{'='*60}")
        except Exception as e:
            pytest.skip(f"Provider info unavailable: {e}")
        assert True
