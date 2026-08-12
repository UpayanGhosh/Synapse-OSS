# Hybrid Vector Search Architectures for Synapse-OSS

**Domain:** Local-first RAG memory for a Python personal AI assistant
**Researched:** 2026-04-02
**Overall Confidence:** MEDIUM-HIGH (most findings verified across multiple sources)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture Analysis](#current-architecture-analysis)
3. [Pattern 1: SQLite-vec + HNSW Library Combo](#pattern-1-sqlite-vec--hnsw-library-combo)
4. [Pattern 2: LanceDB as Single Source of Truth](#pattern-2-lancedb-as-single-source-of-truth)
5. [Pattern 3: DuckDB + VSS Extension](#pattern-3-duckdb--vss-extension)
6. [Pattern 4: FAISS + SQLite Metadata](#pattern-4-faiss--sqlite-metadata)
7. [Pattern 5: Custom HNSW on Top of SQLite](#pattern-5-custom-hnsw-on-top-of-sqlite)
8. [Pattern 6: Tantivy/MeiliSearch-style Hybrid](#pattern-6-tantivymeilisearch-style-hybrid)
9. [Pattern 7: Brute-Force with Quantization](#pattern-7-brute-force-with-quantization)
10. [RAG Without Vector Database Trends](#rag-without-vector-database-trends)
11. [BM25 + Reranker vs Vector Search](#bm25--reranker-vs-vector-search)
12. [Hybrid Search Implementations](#hybrid-search-implementations)
13. [Framework Recommendations (LlamaIndex/LangChain)](#framework-recommendations)
14. [Novel Approaches](#novel-approaches)
15. [Real-World Case Studies](#real-world-case-studies)
16. [Recommendation for Synapse-OSS](#recommendation-for-synapse-oss)
17. [Decision Matrix](#decision-matrix)

---

## Executive Summary

Synapse-OSS currently uses a **dual-store architecture**: SQLite + sqlite-vec for metadata/FTS/brute-force vector search, and Qdrant via Docker for ANN vector search. The goal is to **eliminate the Docker dependency** (Qdrant) while maintaining or improving retrieval quality.

**Bottom line recommendation:** Use **sqlite-vec with binary quantization** for the immediate term (it already works, handles the project's likely <50K vector scale, and the binary quantization trick gets 768-dim brute-force search down to ~23ms for 1M vectors). For the medium term, add **hnswlib as a sidecar index** alongside SQLite for ANN search, using the `hnsqlite` or `vectorlite` pattern. This keeps SQLite as the single source of truth for metadata/FTS while getting O(log n) search via HNSW.

Additionally, implement **Reciprocal Rank Fusion (RRF)** to properly combine FTS5 and vector results -- Alex Garcia has published the exact SQL pattern for this, and Blake Crosley has proven it works at 50K chunks with ~23ms total latency.

Do NOT migrate to LanceDB, DuckDB, or ChromaDB. The migration cost is high, the project already has deep SQLite integration (schema, FTS5, hemisphere tagging, WAL mode, sessions table), and none of these alternatives offer a compelling enough advantage to justify rewriting the data layer.

---

## Current Architecture Analysis

### What Synapse has today

| Component | Technology | Role |
|-----------|-----------|------|
| Metadata + FTS | SQLite + FTS5 | Documents table, hemisphere tagging, importance scores |
| Brute-force vectors | sqlite-vec (float[768]) | `vec_items` virtual table, cosine distance |
| ANN vectors | Qdrant (Docker, port 6333) | Fast approximate search, hemisphere filtering |
| Reranker | FlashRank (ms-marco-TinyBERT-L-2-v2) | Post-retrieval reranking |
| Embeddings | Ollama nomic-embed-text (768-dim) | Embedding generation |
| Knowledge Graph | SQLiteGraph (separate .db) | Subject-predicate-object triples |

### What needs replacing

Only **Qdrant** needs to go. Everything else stays. The replacement must:
1. Support ANN search (not just brute-force) for future scaling
2. Support hemisphere filtering (safe/spicy partition)
3. Support incremental adds (no full index rebuilds)
4. Be in-process (no Docker, no server, no ports)
5. Work on Windows, macOS, and Linux
6. Handle 768-dimensional float32 vectors
7. Be pip-installable

### Scale context

A personal AI assistant will realistically accumulate:
- **Year 1:** 5K-20K documents/memories
- **Year 3:** 20K-100K documents
- **Year 5+:** 100K-500K documents (heavy usage)

This is critical for technology choice. Many patterns are overkill for this scale.

---

## Pattern 1: SQLite-vec + HNSW Library Combo

**Concept:** Keep SQLite for metadata + FTS. Add a standalone HNSW library (hnswlib, usearch) as a sidecar index for fast ANN search.

### Real-world implementations

**vectorlite** (340+ GitHub stars)
- SQLite extension wrapping hnswlib with SQL API
- `pip install vectorlite-py`
- 3x-100x faster than sqlite-vec for search, 10x faster than sqlite-vss for insertion
- Full HNSW parameter control (M, ef_construction, ef_search)
- Supports predicate pushdown for metadata filtering via rowid
- Supports index serialization: save to file and reload, plus cross-compatibility with raw hnswlib indexes
- **Status: Beta.** Has known issues on Apple Silicon (SVE instructions)
- Source: https://github.com/1yefuwang1/vectorlite

**hnsqlite** (Python library)
- Integrates hnswlib + SQLite for persistent text embedding search
- `pip install hnsqlite`
- Stores text + vectors + metadata in SQLite, HNSW index as sidecar file
- Supports metadata filtering at search time via filter dictionaries
- Delete functionality: remove items by filters, doc IDs, or entire collections
- Good for <10M embeddings
- Source: https://github.com/jiggy-ai/hnsqlite

**DocArray HnswDocumentIndex**
- From Jina AI, stores vectors in hnswlib, metadata in SQLite
- Part of the docarray library
- Source: https://docs.docarray.org/user_guide/storing/index_hnswlib/

### Complexity

**Low-Medium.** The pattern is: SQLite owns all data, hnswlib owns the ANN index file. On add: write to SQLite + add to hnswlib index. On search: query hnswlib for approximate neighbors, join with SQLite for metadata filtering and FTS augmentation. On startup: load the hnswlib index from disk.

### Failure modes

- **Index corruption:** hnswlib saves a single binary file. If the process crashes mid-save, the index can be corrupted. Mitigation: save to temp file, then atomic rename. hnswlib supports pickling as a backup persistence path.
- **Index/metadata desync:** If SQLite write succeeds but hnswlib add fails, they desync. Mitigation: add to hnswlib first (in-memory), then persist to SQLite, or use a reconciliation pass on startup.
- **Index rebuilds:** If the hnswlib index is lost/corrupted, you can rebuild from SQLite (which has all vectors in vec_items). This is a clean recovery path.

### Incremental updates

**Excellent.** hnswlib natively supports `add_items()` for incremental adds. It also supports element deletion by marking (with optional replace). No full rebuild needed.

### Verdict for Synapse

**STRONG CANDIDATE.** This is the lightest-weight path. Synapse already stores vectors in `vec_items` (SQLite), so hnswlib just needs to maintain a parallel HNSW index. Recovery is simple: rebuild from SQLite data. The `hnsqlite` library proves this pattern works.

**Confidence: HIGH** (multiple production implementations, well-understood technology)

---

## Pattern 2: LanceDB as Single Source of Truth

**Concept:** Replace SQLite entirely with LanceDB, which stores vectors + metadata + FTS in a single Lance-format file.

### Capabilities

- Embedded, in-process, no server
- Built on Lance columnar format (Apache Arrow-based)
- Vector search (IVF_PQ index, brute-force, DiskANN upcoming)
- Full-text search via Tantivy (BM25-based)
- Hybrid search with RRF reranking built in
- Zero-copy operations via Apache Arrow
- Rust core -- 4x faster writes/queries after 2025 rewrite
- Source: https://github.com/lancedb/lancedb

### FTS capabilities

LanceDB has two FTS implementations:
1. **Legacy:** Tantivy-based, Python sync only, no incremental indexing, no object storage support
2. **New:** lance-index based, under active development

Hybrid search example:
```python
table.search("query text", query_type="hybrid",
             vector_column_name="vector", fts_columns="text")
     .rerank(RRFReranker())
     .limit(10)
     .to_pandas()
```

Multi-column FTS indexing:
```python
table.create_fts_index(["title", "content"], use_tantivy=True, replace=True)
```

### Performance (130K records, Wine Reviews benchmark)

| Metric | LanceDB | Elasticsearch |
|--------|---------|--------------|
| FTS QPS (direct) | ~1,534 | ~5,949 |
| FTS P50 latency | 10.18ms | 2.59ms |
| Vector QPS | ~97 | ~98 |

Source: https://thedataquarry.com/blog/embedded-db-3/

### Production experience: 700M vectors at scale

Vladyslav Krylasov documented running LanceDB with 700M vectors in production. Key takeaways:
- Works but requires careful tuning
- Version file management is critical (every write produces a new version)
- Cleanup cron jobs are mandatory -- no automatic version pruning
- Source: https://sprytnyk.dev/posts/running-lancedb-in-production/

### Limitations (critical for Synapse)

1. **Tantivy FTS is sync-only in Python** -- Synapse's gateway is fully async (asyncio throughout)
2. **No incremental FTS indexing** with the legacy Tantivy path
3. **No phrase queries** in FTS (Tantivy limitation in LanceDB integration)
4. **FTS only supports local filesystem** (not a problem for Synapse, but worth noting)
5. **Migration cost is VERY HIGH** -- Synapse has deep SQLite integration: sessions table, hemisphere tagging, WAL mode, FTS5 content tables, vec_items virtual table, knowledge_graph.db (separate SQLiteGraph). Ripping all of that out is a multi-week effort.
6. **Schema differs fundamentally** -- Lance format is columnar/append-optimized, not transactional like SQLite. Different mental model for updates.
7. **Concurrency control is manual** -- no centralized concurrency control; multi-process writes need application-level coordination. Too many concurrent writers cause failing writes.
8. **Version file sprawl** -- every write creates a new version file; data directory grows continuously. No background cleanup service, so it's the application's responsibility.
9. **v0.x maturity** -- project is currently at v0.x with breaking API changes (async API broke at 0.30.0). Version pins need attention.
10. **Python multiprocessing issues** -- Lance is multi-threaded internally; fork + multi-threaded Python do not work well together.

### Incremental updates

LanceDB supports incremental vector adds but FTS index must be rebuilt. The Lance format is append-optimized, so adds are fast. Deletes and updates are tombstone-based with compaction.

### Verdict for Synapse

**NOT RECOMMENDED.** The migration cost vastly outweighs the benefits. Synapse's SQLite integration is deep and well-tested. LanceDB's FTS is sync-only (incompatible with asyncio gateway), lacks incremental FTS indexing, and the Lance format is a fundamentally different data model. The v0.x maturity and operational complexity (version file cleanup, concurrency management) add risk. If starting from scratch, LanceDB would be worth considering. For Synapse's existing architecture, it's a rewrite.

**Confidence: HIGH** (well-documented limitations, verified against official docs and production reports)

---

## Pattern 3: DuckDB + VSS Extension

**Concept:** Replace SQLite with DuckDB which has built-in HNSW via the vss extension, plus excellent analytical queries.

### Capabilities

- HNSW index via usearch library
- Supports cosine, L2, inner product distance metrics
- Full SQL support with analytical superpowers
- In-process, single file
- VSS extension included by default since v0.10.2
- Source: https://duckdb.org/2024/05/03/vector-similarity-search-vss

### Critical limitations

1. **HNSW persistence is experimental** -- requires `SET hnsw_enable_experimental_persistence = true`
2. **No incremental HNSW updates** -- every checkpoint serializes the ENTIRE index to disk, overwriting previous blocks
3. **Deletes are not reflected in the index** -- only "marked" as deleted. Must manually compact via `PRAGMA hnsw_compact_index('<name>')` or rebuild.
4. **Index deserialization on restart** -- the entire HNSW index loads into memory on first table access. For large indexes, this can be slow.
5. **DuckDB is OLAP-optimized** -- designed for batch analytics, not the transactional CRUD pattern Synapse uses (individual message inserts, per-message reads)
6. **No FTS5 equivalent** -- DuckDB has `fts` extension but it's less mature than SQLite FTS5
7. **WAL recovery not implemented** -- if a crash occurs with uncommitted changes to an HNSW-indexed table, you get data loss or index corruption
8. **Index must fit in RAM** -- the HNSW index is not buffer-managed
9. **Only float vectors supported** -- no int8 or binary quantization in the VSS extension

Source: https://duckdb.org/docs/1.3/core_extensions/vss, https://github.com/duckdb/duckdb-vss

### Verdict for Synapse

**NOT RECOMMENDED.** DuckDB is an analytical engine, not a transactional one. Synapse does individual row inserts (add_memory) and point queries (search), which is SQLite's sweet spot and DuckDB's weakness. The VSS extension's lack of incremental updates, experimental persistence, and missing WAL recovery are dealbreakers. The migration cost is also very high.

**Confidence: HIGH** (limitations verified against official DuckDB docs and VSS extension source)

---

## Pattern 4: FAISS + SQLite Metadata

**Concept:** Keep SQLite for metadata + FTS. Use FAISS as a separate in-process vector index.

### Real-world implementations

**faissqlite** (GitHub library)
- Combines FAISS + SQLite for persistent vector search
- `pip install faissqlite`
- Stores vectors in FAISS, metadata in SQLite
- Supports hybrid search, CLI, REST API
- save_index/load_index for persistence
- Source: https://github.com/praveencs87/faissqlite

**sqlite-vss** (now deprecated)
- Was a SQLite extension based on FAISS
- Deprecated in favor of sqlite-vec by the same author (asg017)
- Source: https://github.com/asg017/sqlite-vss

**LangChain FAISS integration**
- LangChain's FAISS vector store persists embeddings + metadata to disk
- Without `save_local()`, index is purely in-memory and lost on restart
- Source: https://docs.langchain.com/oss/python/integrations/vectorstores/faiss

### FAISS index types for Synapse's scale

| Index | Best for | Recall | Speed | Incremental adds |
|-------|----------|--------|-------|-------------------|
| IndexFlatL2 | <50K vectors | 100% | Brute force | Yes (add_with_ids) |
| IndexHNSW | 50K-10M | ~95% | Very fast | Yes (add) |
| IndexIVF | 50K-1M | ~95% | Fast | Yes (after initial train) |
| IndexIVF_PQ | >1M | ~90% | Very fast, compressed | Yes (after train) |

Source: https://github.com/facebookresearch/faiss/wiki/Indexing-1M-vectors

### FAISS incremental update details

- **Flat indexes:** `add_with_ids()` for adds, `remove_ids()` for deletes
- **IVF indexes:** Train once on representative sample, then add incrementally without retraining. Retrain only if data distribution drifts significantly.
- **HNSW index (in FAISS):** Supports adds natively, but does NOT support removal (unlike hnswlib which does)
- **Index sync hazard:** Pairing FAISS vectors with SQLite can silently cause sync issues when chunks change but vector IDs don't update. Recommended: generate content hash as integer ID, store in both FAISS and SQLite, update both when content changes.

Source: https://github.com/facebookresearch/faiss/issues/183, https://github.com/facebookresearch/faiss/issues/163

### Complexity

**Medium.** FAISS indexes are in-memory and must be explicitly serialized to disk with `faiss.write_index()` / `faiss.read_index()`. You need to manage:
- ID mapping between FAISS internal IDs and SQLite document IDs (use IndexIDMap)
- Periodic saves to disk
- Recovery from crashes (reload from disk, reconcile with SQLite)
- FAISS uses C++ under the hood, so it has binary dependencies (pip-installable via `faiss-cpu`)

### Failure modes

- **Index loss on crash:** If the process crashes before `faiss.write_index()`, recent additions are lost. Mitigation: periodic saves + rebuild from SQLite's vec_items.
- **Memory usage:** FAISS keeps the entire index in RAM. For 100K 768-dim float32 vectors: ~300MB. Manageable for a personal assistant.
- **Dependency weight:** `faiss-cpu` is a ~30MB package with numpy dependency. Heavier than hnswlib (~2MB).

### Verdict for Synapse

**VIABLE BUT HEAVIER THAN NEEDED.** FAISS is industrial-strength and overkill for Synapse's scale. The `faiss-cpu` package is larger than hnswlib, and FAISS's HNSW doesn't support deletion (hnswlib does). For <500K vectors, hnswlib is simpler. FAISS becomes the right choice only at million+ scale.

**Confidence: HIGH** (FAISS is extremely well-documented and battle-tested)

---

## Pattern 5: Custom HNSW on Top of SQLite

**Concept:** Build a thin wrapper that stores vectors in SQLite but maintains a separate HNSW index file for fast search.

### Existing implementations

**vectorlite** (already covered in Pattern 1)
- The most mature implementation of this exact pattern
- SQLite extension with hnswlib backend
- Source: https://github.com/1yefuwang1/vectorlite

**The DIY approach (~100 lines):**
```python
import hnswlib
import sqlite3
import struct
import os

class HnswSidecar:
    """HNSW index that sits alongside SQLite as the source of truth."""
    
    def __init__(self, db_path, index_path, dim=768):
        self.conn = sqlite3.connect(db_path)
        self.dim = dim
        self.index_path = index_path
        
        # Initialize or load HNSW index
        self.index = hnswlib.Index(space='cosine', dim=dim)
        if os.path.exists(index_path):
            self.index.load_index(index_path)
        else:
            self.index.init_index(max_elements=100000, ef_construction=200, M=16)
        self.index.set_ef(50)  # search-time parameter
    
    def add(self, doc_id, vector, metadata):
        # Write to SQLite (source of truth)
        vec_blob = struct.pack(f'{len(vector)}f', *vector)
        self.conn.execute(
            "INSERT INTO vec_items (document_id, embedding) VALUES (?, ?)",
            (doc_id, vec_blob)
        )
        # Add to HNSW index
        self.index.add_items([vector], [doc_id])
    
    def search(self, query_vector, k=10, hemisphere=None):
        # Fast ANN search via HNSW -- overfetch for post-filtering
        fetch_k = k * 3 if hemisphere else k
        labels, distances = self.index.knn_query([query_vector], k=fetch_k)
        doc_ids = labels[0].tolist()
        
        # Fetch metadata from SQLite + hemisphere filter
        if hemisphere:
            placeholders = ','.join('?' * len(doc_ids))
            rows = self.conn.execute(
                f"SELECT document_id, hemisphere_tag FROM documents "
                f"WHERE document_id IN ({placeholders}) AND hemisphere_tag = ?",
                doc_ids + [hemisphere]
            ).fetchall()
            return [(r[0], d) for r, d in zip(rows, distances[0]) if r][:k]
        return list(zip(doc_ids, distances[0].tolist()))
    
    def save(self):
        # Atomic save: write to temp, then rename
        tmp_path = self.index_path + '.tmp'
        self.index.save_index(tmp_path)
        os.replace(tmp_path, self.index_path)
    
    def rebuild_from_sqlite(self):
        """Recovery: rebuild HNSW index from SQLite data"""
        rows = self.conn.execute(
            "SELECT document_id, embedding FROM vec_items"
        ).fetchall()
        self.index = hnswlib.Index(space='cosine', dim=self.dim)
        self.index.init_index(max_elements=max(len(rows) * 2, 1000),
                              ef_construction=200, M=16)
        for doc_id, blob in rows:
            vec = list(struct.unpack(f'{self.dim}f', blob))
            self.index.add_items([vec], [doc_id])
        self.save()
```

### Key parameters for hnswlib

| Parameter | Recommended | Effect |
|-----------|-------------|--------|
| M | 16 | Connections per node. Higher = better recall, more memory |
| ef_construction | 200 | Build quality. Higher = better index, slower build |
| ef | 50-200 | Search quality. Higher = better recall, slower search |
| max_elements | 2x expected count | Pre-allocate space. Can resize with `resize_index()` |

Source: https://opensearch.org/blog/a-practical-guide-to-selecting-hnsw-hyperparameters/

### USearch as alternative to hnswlib

USearch (from Unum) is a more modern single-file HNSW implementation:
- Fewer dependencies than hnswlib
- User-defined metrics (custom distance functions)
- Can serve indexes from external memory (mmap) -- indexes don't have to fully load into RAM
- SIMD-optimized for multiple architectures
- Claims 10x faster than FAISS in some benchmarks
- `pip install usearch`
- Source: https://github.com/unum-cloud/USearch

However, hnswlib is more battle-tested (4K+ GitHub stars) and widely used. For Synapse, hnswlib is the safer choice. Consider USearch if memory-mapped index serving becomes important (e.g., if the index grows larger than available RAM).

### Verdict for Synapse

**RECOMMENDED APPROACH (medium-term).** This is the exact pattern Synapse should adopt. SQLite remains the source of truth. hnswlib provides O(log n) ANN search. The `rebuild_from_sqlite()` recovery path makes corruption a non-issue. The code is ~100 lines.

**Confidence: HIGH** (well-understood pattern, hnswlib has 4K+ GitHub stars, battle-tested)

---

## Pattern 6: Tantivy/MeiliSearch-style Hybrid

**Concept:** Use a single engine that does both vector AND keyword search.

### Tantivy (via tantivy-py)

- Full-text search engine written in Rust, Python bindings available
- BM25 ranking built in
- **Does NOT have native vector search** (as of 2026, planned for 0.22+)
- Used by LanceDB internally for FTS
- Industry adoption reportedly surged 300% in 2025-2026 for RAG systems (per Stack Overflow Developer Survey 2026)
- 15-20x faster indexing than pure Python alternatives like Whoosh
- `pip install tantivy`
- Source: https://github.com/quickwit-oss/tantivy-py

### MeiliSearch

- Excellent search engine but runs as a separate server (Rust binary)
- Has hybrid search (vector + keyword)
- But introduces the same problem as Qdrant: external dependency
- NOT a good fit for Synapse's zero-dependency goal

### What actually works for Python hybrid search

There is no single Python library that does both vector AND keyword search well in-process. The practical pattern is:

1. **SQLite FTS5** for keyword/BM25 search (already in Synapse)
2. **hnswlib / sqlite-vec** for vector search
3. **Reciprocal Rank Fusion (RRF)** to merge results
4. **FlashRank** for final reranking (already in Synapse)

This is essentially what Synapse already has, minus the Qdrant piece.

### Verdict for Synapse

**NOT APPLICABLE as a single-engine solution.** No Python library does both well in-process. Synapse's existing FTS5 + vector search + FlashRank reranker IS the hybrid search architecture. Just replace the Qdrant vector piece.

**Confidence: HIGH** (verified that Tantivy lacks vector search, MeiliSearch requires server)

---

## Pattern 7: Brute-Force with Quantization ("Just Use sqlite-vec Better")

**Concept:** Instead of adding another library, optimize sqlite-vec's brute-force search with quantization tricks to push its viable range from ~50K to 500K+ vectors.

### Binary quantization in sqlite-vec

sqlite-vec has built-in support for binary quantization via `vec_quantize_binary()`:

```sql
-- Create binary quantized virtual table
CREATE VIRTUAL TABLE vec_items_binary USING vec0(
    document_id INTEGER,
    embedding bit[768]
);

-- Insert binary-quantized vector
INSERT INTO vec_items_binary (document_id, embedding)
SELECT document_id, vec_quantize_binary(embedding)
FROM vec_items;

-- Search using Hamming distance (hardware-accelerated via POPCNT)
SELECT document_id, distance
FROM vec_items_binary
WHERE embedding MATCH vec_quantize_binary(?)
ORDER BY distance
LIMIT 20;
```

### Performance numbers (768-dim vectors)

| Vectors | float32 latency | Binary quantized latency | Speedup |
|---------|----------------|-------------------------|---------|
| 10K | ~7ms | <1ms | ~10x |
| 50K | ~35ms | ~2ms | ~17x |
| 100K | ~75ms | ~4ms | ~17x |
| 500K | ~350ms | ~17ms | ~20x |
| 1M | ~700ms+ | ~23ms | ~30x |

Source: https://alexgarcia.xyz/sqlite-vec/guides/binary-quant.html, https://ikyle.me/blog/2025/binary-quantized-embeddings

### How it works

1. Each float32 dimension becomes 1 bit (positive = 1, negative = 0)
2. 768-dim float32 vector (3,072 bytes) becomes 96 bytes (32x compression)
3. Distance computed via Hamming (XOR + POPCNT) -- hardware-accelerated
4. Achieves >95% recall vs float32 cosine similarity for most embedding models
5. **Brute-force on 1M binary vectors at 768-dim: ~23ms** -- fast enough!

### Two-pass search pattern

For maximum quality with minimum latency:
```
Pass 1: Binary quantized brute-force (fast, ~95% recall) -> top 100 candidates
Pass 2: Float32 reranking of top 100 candidates (exact) -> top 10 results
```

This gives you 99%+ recall at 2-5ms total for 100K vectors.

### Int8 (scalar) quantization alternative

sqlite-vec also supports int8 quantization via `vec_quantize_i8()`:
- 4x compression (768 float32 -> 768 int8: 3,072 bytes -> 768 bytes)
- Less aggressive than binary, better recall (~99%)
- ~4-5x speedup over float32
- Source: https://alexgarcia.xyz/sqlite-vec/guides/scalar-quant.html

### sqlite-vec ANN roadmap

Alex Garcia has confirmed ANN indexes are on the roadmap for sqlite-vec (tracking issue #25). A custom ANN index optimized for SQLite storage could reach "low millions" or "tens of millions" of vectors. IVF + HNSW are both being considered. However, no concrete timeline has been published as of April 2026.

Source: https://github.com/asg017/sqlite-vec/issues/25

### Verdict for Synapse

**STRONGLY RECOMMENDED (immediate term).** This is the zero-dependency path. Synapse already has sqlite-vec. Adding binary quantization is a schema change + a few SQL queries, no new pip packages. At Synapse's scale (<100K vectors for years), binary-quantized brute force is sub-5ms. This buys time before any HNSW sidecar is needed.

**Confidence: HIGH** (verified against sqlite-vec official docs, benchmarked by multiple sources)

---

## RAG Without Vector Database Trends (2025-2026)

### Industry direction

The 2025-2026 landscape shows a clear shift:

1. **Hybrid search is now table stakes.** Every production RAG system combines BM25 + vector search. Source: https://docs.bswen.com/blog/2026-02-25-hybrid-search-vs-reranker/

2. **Three-stage pipeline is the standard:** BM25 captures exact keyword matches, dense retrieval finds semantic similarities, and reranking optimizes the final ordering. Source: https://blog.premai.io/hybrid-search-for-rag-bm25-splade-and-vector-search-combined/

3. **"Fix recall before precision"** is the mantra. Hybrid search improves recall by 22% over vector-only. Reranking then improves precision but cannot recover missed documents. Only add a reranker after recall@50 is solid (>90%). Source: https://docs.bswen.com/blog/2026-02-25-hybrid-search-vs-reranker/

4. **Graph RAG is moving from experimental to essential** (2026 trend). Synapse already has this with SQLiteGraph. Source: https://community.netapp.com/t5/Tech-ONTAP-Blogs/Hybrid-RAG-in-the-Real-World-Graphs-BM25-and-the-End-of-Black-Box-Retrieval/ba-p/464834

5. **Local-first is winning.** OpenClaw and similar projects prove that SQLite + FTS5 + sqlite-vec is a functional RAG stack in a single binary. Users should not need Docker. Source: https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/

6. **BM25's renaissance.** BM25 is nearly thirty years old, but RAG has revitalized this classic technology. It delivers millisecond responses at millions of documents without GPU infrastructure. Source: https://ragaboutit.com/hybrid-retrieval-for-enterprise-rag-when-to-use-bm25-vectors-or-both/

### Benchmark: Hybrid search vs reranker

From a 2026 comparison study:

| Approach | Recall@50 | Precision@10 | Latency |
|----------|-----------|--------------|---------|
| Vector search only | 72% | 48% | 80ms |
| Hybrid (BM25 + vector) | 94% | 61% | 95ms |
| Hybrid + reranker | 94% | 78% | 285ms |

**Synapse already has the optimal architecture:** hybrid search (FTS5 + vector) with FlashRank reranking. The only gap is that the vector search piece (Qdrant) needs to be replaced with something in-process.

### FlashRank performance context

FlashRank specifically improves mean NDCG@10 by up to 5.4%, enhances generation accuracy by 6-8%, and reduces context tokens by 35%. Executes in under 60ms for 100 candidates (parallelized), making it suitable for real-time systems.

Source: https://arxiv.org/html/2601.03258v1

---

## BM25 + Reranker vs Vector Search

### Can BM25 + reranker replace vector search entirely?

**No, but it covers more cases than you'd think.** For queries with specific keywords, names, or technical terms, BM25 + reranker outperforms vector search because:
- BM25 catches exact keyword matches that embeddings can miss
- The reranker (FlashRank) adds semantic understanding on top
- BM25-only is sufficient when queries are exact-match dominated: product catalogs with SKUs, legal case numbers, financial identifiers

For queries that require semantic understanding ("how did I feel about the project last month"), vector search is essential because BM25 can't match semantically similar but lexically different text.

### When to use which

| Query type | BM25 | Vector | Hybrid |
|-----------|------|--------|--------|
| Exact name/keyword | Best | Weak | Good |
| Semantic similarity | Weak | Best | Good |
| Mixed ("tell me about the X project") | Okay | Good | Best |
| Recall-critical | Good | Good | Best (+22%) |

### Practical recommendation for Synapse

Keep both. The current architecture (vector + FTS5 + FlashRank) is the industry-standard pattern. Don't try to drop vector search entirely.

### bm25s library (alternative to FTS5)

If SQLite FTS5's BM25 becomes insufficient, `bm25s` is a fast pure-Python BM25 implementation:
- 500x faster than Rank-BM25
- Comparable speed to Elasticsearch on single node
- Uses scipy sparse matrices
- `pip install bm25s`
- Source: https://github.com/xhluca/bm25s

For Synapse, SQLite FTS5's built-in BM25 is sufficient. No need for bm25s unless FTS5 becomes a bottleneck.

---

## Hybrid Search Implementations (Lightweight Python)

### The RRF pattern -- Alex Garcia's SQL implementation (recommended for Synapse)

Alex Garcia published the complete SQL pattern for combining FTS5 + sqlite-vec via RRF:

```sql
WITH vec_matches AS (
    SELECT article_id,
        row_number() OVER (ORDER BY distance) AS rank_number
    FROM vec_articles
    WHERE headline_embedding MATCH lembed(:query) AND k = :k
),
fts_matches AS (
    SELECT rowid,
        row_number() OVER (ORDER BY rank) AS rank_number
    FROM fts_articles
    WHERE headline MATCH :query
    LIMIT :k
),
final AS (
    SELECT articles.id, articles.headline,
        (COALESCE(1.0 / (:rrf_k + fts_matches.rank_number), 0.0) * :weight_fts +
         COALESCE(1.0 / (:rrf_k + vec_matches.rank_number), 0.0) * :weight_vec
        ) AS combined_rank
    FROM fts_matches
    FULL OUTER JOIN vec_matches
        ON vec_matches.article_id = fts_matches.rowid
    JOIN articles ON articles.rowid =
        COALESCE(fts_matches.rowid, vec_matches.article_id)
    ORDER BY combined_rank DESC
)
SELECT * FROM final;
```

Parameters: `:rrf_k = 60` (standard), `:weight_fts = 1.0`, `:weight_vec = 1.0` (adjust to tune blend).

Source: https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html

### Three hybrid approaches Alex Garcia documents

1. **Keyword-First:** Returns all FTS5 matches before vector results using `UNION ALL`, prioritizing exact matches. Best for inbox/search UIs.
2. **RRF:** Combines results using reciprocal rank fusion with configurable weights. Best for RAG systems.
3. **Re-rank by Semantics:** FTS5 search first, then reorder by vector similarity using `vec_distance_cosine()`. Best for duplicate detection.

### Python RRF implementation (framework-free)

```python
def reciprocal_rank_fusion(results_lists, k=60):
    """Merge results from multiple search methods using RRF."""
    scores = {}
    for results in results_lists:
        for rank, (doc_id, _) in enumerate(results):
            if doc_id not in scores:
                scores[doc_id] = 0
            scores[doc_id] += 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

# Usage in Synapse:
vector_results = search_vectors(query_embedding, k=20)  # from hnswlib/sqlite-vec
fts_results = search_fts(query_text, k=20)              # from SQLite FTS5
merged = reciprocal_rank_fusion([vector_results, fts_results])
final = flashrank_rerank(query_text, merged[:20])        # FlashRank top 20
```

This is ~20 lines of code. No library needed for the fusion step.

### sqlite-rag project (reference implementation)

The sqliteai team has built `sqlite-rag`, a complete hybrid search engine on SQLite:
- Combines vector embeddings + FTS5 using RRF
- All search logic stays within SQLite (embeddings via sqlite-ai, vectors via sqlite-vector)
- Production deployment: 182 documentation files, ~640 words each
- Build time: GitHub Action embeds on doc change (~25 minutes for full re-embed)
- Runtime: lightweight server (4 vCPUs, ~100MB RAM), full query-response cycle ~370ms average
- `pip install sqlite-rag`
- Source: https://github.com/sqliteai/sqlite-rag

### Existing frameworks (context only -- not recommended for Synapse)

| Framework | Hybrid search support | Weight | Notes |
|-----------|----------------------|--------|-------|
| LlamaIndex | Yes (via retrievers) | Heavy (~100+ deps) | Overkill for Synapse |
| LangChain | Yes (EnsembleRetriever) | Heavy (~80+ deps) | Overkill for Synapse |
| Haystack | Yes (hybrid pipeline) | Heavy | Overkill for Synapse |
| bm25s + hnswlib + RRF | Manual but simple | Light (~3 deps) | Recommended |

Synapse should NOT add LlamaIndex or LangChain just for hybrid search. The manual RRF implementation is trivial and keeps the dependency footprint minimal.

---

## Framework Recommendations

### What LlamaIndex recommends for local/embedded (2025-2026)

LlamaIndex's default `SimpleVectorStore` stores embeddings in memory and persists to disk. For production, they recommend ChromaDB or FAISS. Source: https://docs.llamaindex.ai/en/stable/module_guides/storing/vector_stores/

### What LangChain recommends

LangChain commonly uses ChromaDB (embedded mode with SQLite + HNSW backend). Pinned around `langchain-chroma 1.1.0` as of late 2025. Source: various LangChain docs

### ChromaDB assessment

ChromaDB is embedded, uses SQLite + HNSW internally:
- In-process, no server needed
- 2025 Rust-core rewrite eliminates GIL bottlenecks, 4x faster writes/queries
- Three-tier storage: brute force buffer -> HNSW cache -> Arrow format on disk
- Single VPS with 4-8 GB RAM handles millions of embeddings
- `pip install chromadb`
- **Limitation: No built-in BM25/FTS** -- must use separately
- **Limitation: SQLite concurrency issues under high concurrent writes** (file-level locking)
- **Limitation: Introduces a SECOND SQLite database** alongside Synapse's existing one
- Source: https://www.trychroma.com/

### Verdict

ChromaDB would work as a Qdrant replacement, but it introduces its own SQLite database alongside Synapse's existing one. This creates a dual-SQLite problem and doesn't leverage Synapse's existing schema. The hnswlib sidecar pattern is cleaner.

---

## Novel Approaches

### Binary quantization + brute force (MOST PROMISING for Synapse)

Already covered in Pattern 7. The key insight: at 768 dimensions, binary-quantized brute-force search over 1M vectors takes ~23ms with hardware-accelerated Hamming distance. For Synapse's <100K scale, this is <5ms. No ANN index needed.

### Matryoshka embeddings + dimension reduction

Matryoshka embedding models (like nomic-embed-text v1.5) support truncating dimensions without retraining:
- 768-dim -> 256-dim: minor quality loss, 3x storage reduction, 3x search speedup
- sqlite-vec supports this via `vec_slice()` + `vec_normalize()`
- Combine with binary quantization for dramatic compression

### Product Quantization (PQ)

Compresses 768-dim float32 vectors by 97% with ~90% recall:
- Decomposes vector space into Cartesian product of lower-dimensional subspaces
- Learns multiple smaller codebooks, one per subspace
- FAISS supports this natively (IndexIVF_PQ)
- Too complex for Synapse's scale -- only relevant at millions of vectors
- Source: https://www.pinecone.io/learn/series/faiss/product-quantization/

### LSH (Locality-Sensitive Hashing)

Maps high-dimensional vectors to binary codes via random projections:
- The intuition: project high-dimensional data to lower dimensions, grouping similar vectors into same buckets
- Python implementations exist in FAISS and scikit-learn
- Recent research (March 2025) proposes trainable hash functions (LearnedHasher) via PyTorch
- Not recommended -- binary quantization with sqlite-vec is simpler and nearly as effective
- Source: https://www.pinecone.io/learn/series/faiss/locality-sensitive-hashing-random-projection/

### SPLADE (Sparse Learned Embeddings)

Emerging alternative to BM25 for sparse retrieval:
- Creates sparse vectors that capture both semantic and lexical features
- Requires a SPLADE model (~500MB)
- Interesting for future research but adds complexity with marginal benefit over BM25 + dense vectors
- Source: https://blog.premai.io/hybrid-search-for-rag-bm25-splade-and-vector-search-combined/

### Model2Vec (lightweight embeddings)

Used in the Obsidian hybrid retriever case study:
- minishlab/potion-base-8M: 7.6M params, 256 dims, ~30MB model size
- 50-500x faster than transformer-based models (no sequential computation)
- Trade-off: lower quality than full transformer embeddings
- Interesting as a complementary fast embedding for real-time use cases
- Not recommended to replace nomic-embed-text for primary embeddings

---

## Real-World Case Studies

### Case Study 1: Blake Crosley's Obsidian Hybrid Retriever (March 2026)

**The most relevant production example for Synapse.**

Architecture: FTS5 BM25 + Model2Vec vector search, fused via RRF. Everything runs locally in ONE SQLite database.

| Metric | Value |
|--------|-------|
| Files indexed | 16,894 |
| Chunks | 49,746 |
| Database size | 83 MB |
| Total query latency | ~23ms (M3 Pro) |
| BM25 search | ~12ms |
| Vector search | ~8ms |
| RRF fusion | ~3ms |
| Full reindex | 4 minutes |
| Incremental update | <10 seconds |

Stack: Python 3, Model2Vec (30MB model), sqlite-vec. No GPU, no Docker, no external services.

RRF configuration: k=60, equal weights. Formula uses only rank positions, not raw scores, so you never need to calibrate BM25 scores against cosine distances.

**Failure modes discovered:** Well-tagged shallow content can outrank poorly-structured deep content because BM25 rewards keyword density, not depth. BM25 catches exact identifiers and function names; vector search catches semantic matches across different terminology.

**Integration:** Hooks into Claude Code, giving the agent vault knowledge without loading files into context.

Source: https://blakecrosley.com/blog/hybrid-retriever-obsidian

### Case Study 2: sqlite-rag Production Deployment

Built by the SQLite AI team, demonstrates a complete RAG system on pure SQLite:
- 182 files, ~640 words average
- Build-time: GitHub Action for embedding generation (~25 min)
- Runtime: 4 vCPUs, ~100MB RAM
- Average query-response cycle: ~370ms
- Source: https://blog.sqlite.ai/building-a-rag-on-sqlite

### Case Study 3: OpenClaw Local-First RAG

Demonstrates SQLite + FTS5 + sqlite-vec as a functional RAG stack for AI agent memory:
- Zero external dependencies approach
- Validates that the sqlite-vec + FTS5 combination is production-ready
- Source: https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/

---

## Recommendation for Synapse-OSS

### Phased approach

#### Phase 1 (Immediate): Binary Quantization + sqlite-vec + RRF

**Zero new dependencies. Schema change only.**

1. Add a binary-quantized `vec_items_binary` virtual table alongside existing `vec_items`
2. On add_memory: insert into both `vec_items` (float32) and `vec_items_binary` (binary)
3. Search path: binary quantized brute-force -> top 100 candidates -> float32 rerank from `vec_items` -> FlashRank rerank -> top K results
4. Implement RRF fusion between FTS5 and vector search results (Alex Garcia's SQL pattern, ~20 lines Python)
5. Remove Qdrant dependency entirely

**Expected performance at 100K vectors:**
- Binary search: ~4ms
- Float32 rerank of top 100: ~1ms
- FTS5 search: ~12ms (based on Obsidian case study scaling)
- RRF fusion: ~3ms
- FlashRank rerank: ~10ms
- **Total: ~30ms** (well within interactive latency budget)

**Migration effort:** ~1-2 days. Change `memory_engine.py` to query `vec_items_binary` instead of Qdrant. Add binary table creation to `db.py`. Add RRF fusion function. Remove all `qdrant_client` imports.

#### Phase 2 (When >100K vectors): hnswlib Sidecar

**One new dependency: `hnswlib` (~2MB).**

1. Add hnswlib HNSW index as a sidecar file (`~/.synapse/workspace/db/vectors.hnsw`)
2. On add_memory: insert into SQLite (source of truth) + add to hnswlib index
3. Search path: hnswlib ANN -> top 100 -> float32 rerank -> FlashRank -> top K
4. On startup: load hnswlib index from disk (or rebuild from SQLite if corrupted)
5. Periodic save: save hnswlib index to disk after N inserts or on graceful shutdown
6. Atomic saves: write to `.tmp` then `os.replace()` to prevent corruption

**HNSW parameters for Synapse:**
- M=16 (standard for 768-dim)
- ef_construction=200 (quality build)
- ef=50 (fast search, tune up if recall drops)
- max_elements=2x current count

**Migration effort:** ~2-3 days. New `HnswSidecar` class (~100 lines), integrate into `memory_engine.py`.

#### Phase 3 (Optional, if needed): Advanced Hybrid Search

1. Tune RRF weights (`:weight_fts` vs `:weight_vec`) based on query analysis
2. Implement query classification to route keyword-heavy queries to FTS-first
3. Consider Matryoshka dimension reduction if embeddings grow
4. May improve recall by ~20% based on industry benchmarks

**Migration effort:** ~1 day. Tuning and query routing logic.

### What NOT to do

- **Do NOT migrate to LanceDB/DuckDB/ChromaDB.** The migration cost is huge and the benefit is marginal. LanceDB's FTS is sync-only. DuckDB's VSS is experimental. ChromaDB creates a second SQLite.
- **Do NOT add FAISS.** Overkill for this scale. hnswlib is simpler and lighter (~2MB vs ~30MB). FAISS's HNSW doesn't support deletion.
- **Do NOT add LlamaIndex/LangChain just for vector storage.** Massive dependency bloat for a problem solvable in 20-100 lines.
- **Do NOT try to make a single engine do everything.** SQLite for metadata/FTS + hnswlib for ANN is the right separation of concerns.
- **Do NOT wait for sqlite-vec ANN support.** It's on the roadmap but has no timeline. Binary quantization + hnswlib sidecar covers all foreseeable needs.

---

## Decision Matrix

| Pattern | Migration Cost | New Deps | Performance | Scales To | Incremental Adds | Recovery | Overall |
|---------|---------------|----------|-------------|-----------|------------------|----------|---------|
| **sqlite-vec binary quant** | Minimal | 0 | Great (<100K) | ~500K | Yes | Trivial (rebuild from float32) | **BEST for Phase 1** |
| **hnswlib sidecar** | Low | 1 (hnswlib) | Excellent | 10M+ | Yes | Rebuild from SQLite | **BEST for Phase 2** |
| vectorlite | Low | 1 (vectorlite-py) | Excellent | 10M+ | Yes | Rebuild from SQLite | Good alternative to hnswlib |
| hnsqlite | Low | 1 (hnsqlite) | Excellent | 10M | Yes | Rebuild | Good if you want a pre-built wrapper |
| FAISS + SQLite | Medium | 1 (faiss-cpu, ~30MB) | Excellent | Billions | Partial (index-dependent) | Rebuild from SQLite | Overkill |
| LanceDB | Very High | Many | Good | Petabytes | Partial (FTS rebuild) | Complex | NOT recommended |
| DuckDB VSS | Very High | Many | Experimental | Unknown | No | Complex | NOT recommended |
| ChromaDB | High | Many | Good | ~1M | Yes | Internal | Redundant with existing SQLite |

### Brute-force viability by scale

| Vector count | sqlite-vec float32 | sqlite-vec binary | hnswlib HNSW | Verdict |
|-------------|--------------------|--------------------|-------------|---------|
| <10K | <7ms | <1ms | <1ms | Any works. Binary quant is free. |
| 10K-50K | ~35ms | ~2ms | <1ms | Binary quant is fine. |
| 50K-100K | ~75ms | ~4ms | <1ms | Binary quant still great. |
| 100K-500K | ~350ms | ~17ms | <1ms | Binary quant works. HNSW nice to have. |
| 500K-1M | ~700ms+ | ~23ms | <1ms | HNSW recommended. Binary is backup. |
| >1M | Too slow | ~23ms+ | <1ms | HNSW required. |

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| sqlite-vec binary quant | HIGH | Official docs + multiple independent benchmarks |
| hnswlib sidecar pattern | HIGH | 4K+ star library, multiple production wrappers (hnsqlite, vectorlite, DocArray) |
| RRF hybrid search | HIGH | Alex Garcia's implementation + Blake Crosley's 50K-chunk production proof |
| LanceDB NOT recommended | HIGH | Well-documented sync-only FTS, v0.x maturity, migration cost analysis |
| DuckDB NOT recommended | HIGH | Official docs document experimental persistence and no incremental updates |
| FAISS overkill | HIGH | Well-understood, but hnswlib is lighter for this scale |
| Performance numbers | MEDIUM | Numbers from various benchmarks, may vary on Synapse's specific hardware |
| Scale projections | MEDIUM | Personal assistant scale is estimated, not measured |

---

## Sources

### Official Documentation
- sqlite-vec binary quantization: https://alexgarcia.xyz/sqlite-vec/guides/binary-quant.html
- sqlite-vec scalar quantization: https://alexgarcia.xyz/sqlite-vec/guides/scalar-quant.html
- sqlite-vec v0.1.0 release: https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html
- sqlite-vec ANN tracking issue: https://github.com/asg017/sqlite-vec/issues/25
- sqlite-vec hybrid search (Alex Garcia): https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html
- DuckDB VSS official docs: https://duckdb.org/docs/1.3/core_extensions/vss
- DuckDB VSS intro: https://duckdb.org/2024/05/03/vector-similarity-search-vss
- DuckDB VSS updates: https://duckdb.org/2024/10/23/whats-new-in-the-vss-extension
- LanceDB FTS docs: https://docs.lancedb.com/search/full-text-search
- LanceDB FTS Tantivy guide: https://lancedb.com/documentation/guides/search/full-text-search-tantivy/
- LanceDB FAQ: https://docs.lancedb.com/faq/faq-oss
- hnswlib README: https://github.com/nmslib/hnswlib
- FAISS wiki: https://github.com/facebookresearch/faiss/wiki/Indexing-1M-vectors
- FAISS incremental adds: https://github.com/facebookresearch/faiss/issues/183
- LlamaIndex vector stores: https://docs.llamaindex.ai/en/stable/module_guides/storing/vector_stores/
- HNSW parameter guide: https://opensearch.org/blog/a-practical-guide-to-selecting-hnsw-hyperparameters/

### Libraries and Tools
- vectorlite: https://github.com/1yefuwang1/vectorlite
- hnsqlite: https://github.com/jiggy-ai/hnsqlite
- faissqlite: https://github.com/praveencs87/faissqlite
- USearch: https://github.com/unum-cloud/USearch
- bm25s: https://github.com/xhluca/bm25s
- tantivy-py: https://github.com/quickwit-oss/tantivy-py
- ChromaDB: https://github.com/chroma-core/chroma
- LanceDB: https://github.com/lancedb/lancedb
- sqlite-rag: https://github.com/sqliteai/sqlite-rag

### Blog Posts and Case Studies
- Blake Crosley Obsidian hybrid retriever: https://blakecrosley.com/blog/hybrid-retriever-obsidian
- Simon Willison on hybrid search: https://simonwillison.net/2024/Oct/4/hybrid-full-text-search-and-vector-search-with-sqlite/
- Building a RAG on SQLite: https://blog.sqlite.ai/building-a-rag-on-sqlite
- Local-first RAG with OpenClaw: https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/
- LanceDB 700M vectors in production: https://sprytnyk.dev/posts/running-lancedb-in-production/
- Binary quantized embeddings: https://ikyle.me/blog/2025/binary-quantized-embeddings
- State of vector search in SQLite: https://marcobambini.substack.com/p/the-state-of-vector-search-in-sqlite
- LanceDB selection guide: https://yage.ai/share/lancedb-selection-guide-en-20260327.html

### Research and Benchmarks
- FlashRank reranking study: https://arxiv.org/html/2601.03258v1
- Hybrid search vs reranker: https://docs.bswen.com/blog/2026-02-25-hybrid-search-vs-reranker/
- Hybrid search for RAG (BM25+SPLADE+vectors): https://blog.premai.io/hybrid-search-for-rag-bm25-splade-and-vector-search-combined/
- Hybrid RAG in the real world: https://community.netapp.com/t5/Tech-ONTAP-Blogs/Hybrid-RAG-in-the-Real-World-Graphs-BM25-and-the-End-of-Black-Box-Retrieval/ba-p/464834
- VectorDBBench: https://github.com/zilliztech/VectorDBBench
- Superlinked hybrid search guide: https://superlinked.com/vectorhub/articles/optimizing-rag-with-hybrid-search-reranking
- Product quantization (Pinecone): https://www.pinecone.io/learn/series/faiss/product-quantization/
- LSH random projection (Pinecone): https://www.pinecone.io/learn/series/faiss/locality-sensitive-hashing-random-projection/
- Reranker guide 2026: https://www.zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025
- FAISS vs HNSWlib: https://zilliz.com/blog/faiss-vs-hnswlib-choosing-the-right-tool-for-vector-search
- Vector database comparison 2026: https://4xxi.com/articles/vector-database-comparison/
- Cosine similarity optimization: https://ashvardanian.com/posts/python-c-assembly-comparison/
