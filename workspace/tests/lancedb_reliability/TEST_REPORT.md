# LanceDB Reliability Test Report

**Date:** 2026-04-05
**Suite:** `workspace/tests/lancedb_reliability/`
**Runner:** `.venv/Scripts/python -m pytest tests/lancedb_reliability/ -v --tb=short`
**Duration:** 5m 40s (340.52s)

---

## Summary

| Status   | Count |
|----------|-------|
| Passed   | 87    |
| Failed   | 5     |
| Skipped  | 36    |
| **Total**| **128** |

---

## Failed Tests

### Phase 1 — Ingestion

#### `TestIngestionMemory::test_memory_growth_bounded_10k`
- **File:** `test_phase1_ingestion.py`
- **Error:** `AssertionError: Memory grew 280.2 MB — possible leak. assert 280.25 < 200`
- **Description:** RSS memory delta for a 10k-row upsert exceeded the 200 MB budget by ~80 MB. Indicates a possible memory leak in `lancedb_store.py` during batch ingestion.

---

### Phase 2 — Retrieval

#### `TestHemisphereFiltering::test_spicy_filter_includes_both_hemispheres`
- **File:** `test_phase2_retrieval.py`
- **Error:** `AssertionError: No spicy results in spicy+safe query. assert 'spicy' in {'safe'}`
- **Description:** A query using the `spicy` hemisphere filter returned only `safe` records. The filter logic is expected to include both hemispheres when `spicy` is requested, but it is behaving as a strict `safe`-only filter.

#### `TestResultFormat::test_result_has_all_required_keys`
- **File:** `test_phase2_retrieval.py`
- **Error:** `assert 0 > 0` — search returned an empty list when at least 1 result was expected.
- **Description:** A valid vector query against a populated store returned 0 results. Likely related to the hemisphere filtering bug above causing over-filtering.

#### `TestSearchAccuracy::test_planted_vector_is_top1`
- **File:** `test_phase2_retrieval.py`
- **Error:** `AssertionError: Expected id=999999 as top-1, got id=0`
- **Description:** A vector planted as an exact match for a query was not returned as the top-1 result. The ANN index appears to favour `id=0` regardless. Possible issue with large ID values or index ordering.

---

### Phase 3 — Concurrency

#### `TestSingletonStoreSafety::test_concurrent_lazy_init_no_race`
- **File:** `test_phase3_concurrency.py`
- **Error:** `AssertionError: Concurrent init errors: ["Table 'memories' already exists" × 8]`
- **Description:** 8 threads simultaneously instantiating `LanceDBVectorStore` against the same path all raised `"Table 'memories' already exists"`. The table-creation path in `__init__` is not guarded by a mutex, causing a race condition on concurrent initialisation.

---

## Skipped Tests (36)

Skipped tests fall into two categories:

| Reason | Count |
|--------|-------|
| `--run-slow` flag not set (100k-scale tests) | ~20 |
| `fastembed` embedding provider not installed | ~16 |

To run slow tests: `pytest tests/lancedb_reliability/ --run-slow`
To run fastembed tests: install `fastembed` in the venv, then re-run.

---

## Warnings

`lancedb_store.py:78` calls the deprecated `table_names()` API. Replace with `list_tables()`.

```python
# Current (deprecated)
existing = self._db.table_names()

# Fix
existing = self._db.list_tables()
```

This warning appears 172 times across the suite.

---

## Action Items

| Priority | Issue | Location |
|----------|-------|----------|
| High | Add mutex around table creation to fix race condition | `lancedb_store.py` `__init__` |
| High | Fix hemisphere filter — `spicy` should include `safe` docs | `lancedb_store.py` search/filter logic |
| Medium | Investigate memory growth during batch upsert | `lancedb_store.py` `upsert_facts()` |
| Medium | Investigate ANN accuracy for large ID values | `lancedb_store.py` / index config |
| Low | Replace deprecated `table_names()` with `list_tables()` | `lancedb_store.py:78` |
