# Embedded Vector Database Research: Comprehensive Comparison

**Project:** Synapse-OSS (Personal AI Assistant)
**Researched:** 2026-04-02
**Goal:** Replace Qdrant (Docker-dependent) with a pip-installable, in-process vector DB
**Constraints:** 768-dim vectors (nomic-embed-text), 1M+ scale, 8GB RAM, Windows+Mac+Linux, sub-50ms query, metadata filtering required

---

## Executive Summary & Recommendation

**Winner: LanceDB** -- disk-backed, truly embedded, async-native, sub-10ms query latency at 1M vectors, hybrid search built-in, works on all platforms via `pip install lancedb`.

**Runner-up: sqlite-vec** (already in Synapse's stack) -- worth keeping for small collections, but ANN support is still alpha and brute-force won't hit sub-50ms at 1M x 768-dim.

**Do NOT use: ChromaDB** for this project -- HNSW requires ~4.8GB RAM for 1M x 768-dim vectors, dangerously close to OOM on 8GB machines. Has history of Windows crash bugs with PersistentClient. Milvus Lite is disqualified due to no native Windows support.

---

## 1. LanceDB

### Overview
- **Type:** Disk-backed columnar vector database built on Apache Arrow / Lance format
- **Architecture:** IVF-PQ / IVF-SQ / IVF-RaBitQ indexes, memory-mapped, zero-copy reads
- **Installation:** `pip install lancedb`
- **License:** Apache 2.0
- **Latest version:** 0.30.1 (March 20, 2026)
- **GitHub stars:** ~9,000
- **PyPI downloads:** ~5.9M/month
- **Confidence:** HIGH (verified via official docs, multiple independent sources)

### Performance at 1M Vectors (768-dim)

| Metric | Value | Source |
|--------|-------|--------|
| Query latency (IVF-PQ) | 3-5ms for >0.90 recall, <10ms for >0.95 recall | [LanceDB Benchmarks](https://medium.com/etoai/benchmarking-lancedb-92b01032874a) |
| Index build time (1M x 960-dim) | ~60 seconds | [LanceDB Blog](https://lancedb.com/blog/one-million-iops/) |
| Raw storage (1M x 768 x f32) | ~3 GB | Calculated: 1M * 768 * 4 bytes |
| With IVF-PQ index | ~3.5-4 GB on disk | Estimated with PQ compression |
| With RaBitQ (1-bit/dim) | ~1.5-2 GB on disk | Significant compression for 768-dim |
| RAM usage during query | **Low** -- indexes cached, rows served from disk via mmap | [LanceDB FAQ](https://docs.lancedb.com/faq/faq-oss) |
| recall@10 at 5ms | >0.90 | [LanceDB Benchmarks](https://medium.com/etoai/benchmarking-lancedb-92b01032874a) |

### Key Strengths
- **Disk-first architecture:** Queries work directly from disk via memory-mapped files. Index metadata is cached in RAM but actual vector data does NOT need to be resident in memory. This is the critical differentiator for 8GB RAM machines.
- **Native hybrid search:** Built-in BM25 full-text search + vector search with RRF reranking. This maps directly to Synapse's existing hybrid RAG pattern (vector + FTS + FlashRank rerank). [LanceDB Hybrid Search Docs](https://docs.lancedb.com/search/hybrid-search)
- **Metadata filtering:** Pre-filtering by default (WHERE clause applied before vector search). Supports scalar indexes (BTREE, BITMAP) on metadata columns for acceleration. [LanceDB Filtering Docs](https://docs.lancedb.com/search/filtering)
- **Async Python API:** Native `connect_async` / `AsyncTable` -- fits Synapse's asyncio-throughout architecture. [LanceDB Python SDK](https://lancedb.github.io/lancedb/python/python/)
- **Multiple quantization options:** PQ (128x compression), SQ (4x), RaBitQ (binary, optimized for 768-dim). [LanceDB Quantization Docs](https://docs.lancedb.com/indexing/quantization)
- **Platform support:** OS-independent, PyPI wheels for Windows/Mac/Linux. No reported Windows-specific showstoppers.

### Known Issues / Gotchas
- **Index build can be memory-intensive for very large datasets:** A user running 700M vectors reported index creation failing on 128GB RAM. At 1M vectors this is not a concern. [Source](https://sprytnyk.dev/posts/running-lancedb-in-production/)
- **Storage overhead:** LanceDB can use more disk space than expected due to Lance format versioning and metadata. A LlamaIndex user reported 1.2GB for 500 documents. Manageable but worth monitoring. [GitHub Issue](https://github.com/run-llama/llama_index/issues/13992)
- **Memory leak reported with S3 storage:** Not relevant for local-only use case. [GitHub Issue](https://github.com/lancedb/lancedb/issues/2468)
- **Prefilter logic inversion bug in hybrid search:** Fixed in recent versions but worth testing. [GitHub Issue](https://github.com/lancedb/lancedb/issues/3095)

### Windows Compatibility
- **Status:** Works. PyPI classifies as "OS Independent." Precompiled wheels available for win_amd64.
- **No specific crash reports found** for Windows in 2025-2026 research.
- **Confidence:** MEDIUM (no negative evidence found, but also limited explicit Windows success reports at scale)

---

## 2. ChromaDB

### Overview
- **Type:** In-memory HNSW with disk persistence (Apache Arrow on disk)
- **Architecture:** hnswlib (C++) for ANN, SQLite for metadata, brute-force buffer before HNSW merge
- **Installation:** `pip install chromadb`
- **License:** Apache 2.0
- **Latest version:** 1.5.5 (March 10, 2026)
- **GitHub stars:** ~26,500
- **PyPI downloads:** ~11M/month (most popular by downloads)
- **Confidence:** HIGH (extensively documented, including known issues)

### Performance at 1M Vectors (768-dim)

| Metric | Value | Source |
|--------|-------|--------|
| Query latency | ~12ms vector search + 8ms BM25 = ~20ms e2e | [Chroma Docs](https://docs.trychroma.com/guides/deploy/performance) |
| RAM usage (1M x 768 x f32 + HNSW) | **~4.8 GB** | [Chroma Cookbook Resources](https://cookbook.chromadb.dev/core/resources/) |
| Vector storage formula | 768 dims * 4 bytes = 3,072 bytes/vector | Chroma uses 32-bit floats |
| HNSW graph overhead (M=40) | ~160 bytes/vector (40 links * 4 bytes) | [Zilliz HNSW Memory FAQ](https://zilliz.com/ai-faq/how-much-memory-overhead-is-typically-introduced-by-indexes-like-hnsw-or-ivf-for-a-given-number-of-vectors-and-how-can-this-overhead-be-managed-or-configured) |
| Total per vector | ~3,232 bytes | 3,072 + 160 |
| Total for 1M | ~3.2 GB data + ~1.6 GB overhead = **4.8 GB** | Calculated |
| recall@10 | High (HNSW is naturally high-recall) | General HNSW property |

### CRITICAL ISSUE: RAM Requirements

**This is the disqualifying factor.** ChromaDB's HNSW index MUST reside entirely in RAM.

From [Chroma Docs](https://docs.trychroma.com/deployment/performance):
> "The HNSW algorithm requires that the embedding index reside in system RAM to query or update, and the amount of available system memory defines an upper bound on the size of a Chroma collection. If a collection grows larger than available memory, insert and query latency spike rapidly as the operating system begins swapping memory to disk."

At 4.8 GB for just the vector index, on an 8 GB machine also running Ollama (nomic-embed-text requires ~1-2 GB), Python runtime, FastAPI, and other Synapse services, **OOM is virtually guaranteed**.

### Other Issues
- **Windows PersistentClient crashes:** Multiple reports of crashes when writing to collections on Windows 11. Crash at 99+ records reported. Version 1.0.20 (Sept 2025) had process-killing crash on add/delete. [GitHub #5392](https://github.com/chroma-core/chroma/issues/5392), [GitHub #3058](https://github.com/chroma-core/chroma/issues/3058)
- **Memory leak with PersistentClient:** Each unique persist_directory creates a System singleton that caches HNSW indexes indefinitely in native C++ memory with no API to release. [GitHub #5843](https://github.com/chroma-core/chroma/issues/5843)
- **Async support:** Only via `AsyncHttpClient` (requires client-server mode). Embedded mode is synchronous. This conflicts with Synapse's asyncio architecture.

### Hybrid Search
- **Yes, supported.** BM25 and SPLADE sparse vectors with dense vector fusion via Search() API. [ChromaDB Sparse Vectors](https://www.trychroma.com/project/sparse-vector-search)

### Verdict: REJECTED
- 4.8 GB RAM for 1M vectors is too much for 8GB machines
- Windows stability issues are documented and recent
- No async embedded client (async only in client-server mode)

---

## 3. USearch (by Unum)

### Overview
- **Type:** Lightweight HNSW library with memory-mapped file support
- **Architecture:** Single-file HNSW index, user-defined distance metrics, SIMD-optimized
- **Installation:** `pip install usearch`
- **License:** Apache 2.0
- **Latest version:** 2.24.0 (February 16, 2026)
- **GitHub stars:** ~3,900
- **Confidence:** MEDIUM

### Performance

| Metric | Value | Source |
|--------|-------|--------|
| Speed vs FAISS (HNSW) | Faster at equal recall on Intel Sapphire Rapids | [USearch Benchmarks](https://github.com/unum-cloud/usearch/blob/main/BENCHMARKS.md) |
| Memory-mapped support | Yes, can serve index from external storage | [USearch README](https://github.com/unum-cloud/USearch) |
| Windows support | Yes (prebuilt wheels on PyPI) | [usearch PyPI](https://pypi.org/project/usearch/) |
| Platform support | Linux, macOS, Windows, iOS, Android, WASM | Confirmed |

### CRITICAL ISSUE: No Metadata Filtering

**USearch does not support metadata filtering.** GitHub Issue [#348](https://github.com/unum-cloud/usearch/issues/348) (opened Feb 2024) remains open with no committed timeline. The maintainer acknowledged the C++ layer has predicate function support, but Python/JS bindings do not expose it.

This is a hard requirement for Synapse (filtering by hemisphere_tag = "safe"|"spicy", user_id, etc.).

### Other Concerns
- **Pure vector index, not a database:** USearch stores vectors and integer IDs only. No metadata storage, no document storage, no full-text search. You'd need to build all of that on top.
- **Small community:** 3.9K stars, limited ecosystem integrations compared to LanceDB/ChromaDB.
- **Used by:** DuckDB VSS extension and ClickHouse use USearch as their HNSW backend.

### Verdict: REJECTED
- No metadata filtering (hard requirement)
- Not a database -- just an index library
- Would require significant custom code to integrate

---

## 4. sqlite-vec

### Overview
- **Type:** SQLite extension for vector search (brute-force + experimental ANN)
- **Architecture:** vec0 virtual table, brute-force KNN, metadata columns, partition keys
- **Installation:** `pip install sqlite-vec`
- **License:** MIT / Apache 2.0 dual
- **Latest version:** 0.1.7 (March 17, 2026), pre-release 0.1.8a1 (March 21, 2026)
- **GitHub stars:** ~5,000+ (estimated based on community activity)
- **Creator:** Alex Garcia (Mozilla Builders project)
- **Confidence:** HIGH (Synapse already uses this)

### Performance at 1M Vectors (768-dim)

| Metric | Value | Source |
|--------|-------|--------|
| Build time (1M x 128-dim, brute-force) | 1-4.6 seconds | [sqlite-vec blog](https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html) |
| Query time (1M x 128-dim, brute-force) | 17-35ms | Same source |
| Query time (1M x 768-dim, brute-force) | **Estimated 100-210ms** (scales ~6x with dimension) | Extrapolated from 128-dim numbers |
| Storage (1M x 128-dim + metadata) | 135 MB (binary quantized) | [MarkTechPost](https://www.marktechpost.com/2024/08/04/sqlite-vec-v0-1-0-released/) |
| Storage (1M x 768-dim, f32) | ~3 GB raw | Calculated: 1M * 768 * 4 bytes |

### Key Issue: Brute-Force at 768 Dimensions

**sqlite-vec's vec0 table is brute-force only for stable releases.** At 768 dimensions and 1M vectors, brute-force KNN will take 100-200ms+ per query, which exceeds the 50ms target.

### ANN Status (Alpha)
- **DiskANN and IVF are in alpha** (v0.1.8a1 pre-release). [GitHub #25](https://github.com/asg017/sqlite-vec/issues/25)
- Not production-ready. Known issue: data leaking via un-deleted compressed neighbor vectors in DiskANN, making DELETEs expensive.
- Timeline was December 2024 / January 2025 -- has slipped, still alpha in March 2026.

### Metadata Filtering
- **Yes, supported.** Metadata columns declared in vec0 constructor, filterable via WHERE clause. Partition keys provide 3x query speedup by pre-filtering rows before vector comparison. [sqlite-vec metadata blog](https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/index.html)

### Windows Compatibility
- **Excellent.** Written in pure C with zero dependencies. Runs anywhere SQLite runs, including Windows.

### Hybrid Search
- **No built-in.** Would need to combine with SQLite FTS5 manually (which Synapse already does).

### Verdict: KEEP AS SECONDARY
- Already in Synapse's stack for the SQLite-based memory.db
- Good for small-to-medium collections (under ~200K vectors at 768-dim for sub-50ms)
- Cannot meet sub-50ms at 1M x 768-dim with current stable brute-force
- Watch ANN alpha development -- if DiskANN matures, could become the primary

---

## 5. FAISS (Facebook AI Similarity Search)

### Overview
- **Type:** Vector similarity search library (not a database)
- **Architecture:** Multiple index types (Flat, IVF, HNSW, PQ, SQ, etc.)
- **Installation:** `pip install faiss-cpu` (Windows wheels available since v1.13+)
- **License:** MIT
- **Latest version:** 1.14.1 (March 6, 2025) -- note: 12+ months since last release
- **GitHub stars:** ~39,400 (most popular by far)
- **Confidence:** HIGH (extremely well-documented, industry standard)

### Performance at 1M Vectors (768-dim)

| Metric | Value | Source |
|--------|-------|--------|
| Raw single-query speed | Industry-leading for single queries | [FAISS benchmarks](https://github.com/facebookresearch/faiss/wiki/Vector-codec-benchmarks) |
| Concurrent (10 users) | 652 QPS, 5.8 GB RAM | [Benchmark article](https://python.plainenglish.io/we-need-to-stop-using-faiss-by-default-benchmarking-8-vector-databases-for-real-use-cases-21cf52caf725) |
| RAM (1M x 768, flat) | ~3.1 GB | Calculated: 1M * 768 * 4 |
| RAM (1M x 768, byte-quantized) | ~775 MB | 4x reduction with byte vectors |
| Query latency (200K x 768) | ~30ms on laptop | [Medium article](https://pub.towardsai.net/vector-databases-performance-comparison-chromadb-vs-pinecone-vs-faiss-real-benchmarks-that-will-3eb83027c584) |

### Key Issues

1. **Not a database:** FAISS is a search library. It stores only vectors + integer IDs. No metadata, no persistence (must serialize/deserialize manually), no built-in filtering.

2. **No native metadata filtering:** Must implement post-filtering manually (fetch k*N results, filter, return k). This degrades recall. IDSelector exists but is limited to ID-based filtering. [FAISS Issue #1079](https://github.com/facebookresearch/faiss/issues/1079)

3. **No built-in persistence:** Index must be saved/loaded manually with `faiss.write_index()` / `faiss.read_index()`. No transactions, no WAL, no concurrent writes.

4. **RAM-resident indexes:** FAISS indexes generally need to be in RAM (except IVF with on-disk storage, which is complex to set up).

5. **No concurrency optimization:** As the "Stop Using FAISS by Default" article shows, FAISS drops to middle-of-pack under concurrent load.

6. **No async support:** Entirely synchronous. Would need thread pool wrapper for Synapse's asyncio.

### Windows Compatibility
- **Now works via pip.** Since ~2024, `faiss-cpu` has Windows PyPI wheels. Supports Python 3.10-3.14 on win_amd64. Uses OpenBLAS on Windows. [faiss-cpu PyPI](https://pypi.org/project/faiss-cpu/)

### Verdict: REJECTED
- Too low-level -- would need to build metadata filtering, persistence, hybrid search, async wrapper all from scratch
- RAM-resident index is a concern for 8GB machines
- No metadata filtering is a hard block

---

## 6. Milvus Lite

### Overview
- **Type:** Embedded version of Milvus vector database
- **Installation:** `pip install pymilvus[milvus-lite]`
- **License:** Apache 2.0
- **Latest version:** Available via pymilvus
- **GitHub stars (Milvus overall):** ~35,000+
- **Confidence:** MEDIUM

### CRITICAL ISSUE: No Native Windows Support

**Milvus Lite does NOT support Windows natively.** [GitHub Issue #176](https://github.com/milvus-io/milvus-lite/issues/176)

From official docs: "Milvus Lite currently supports Ubuntu >= 20.04 (x86_64 and arm64) and MacOS >= 11.0."

The documented workaround is WSL (Windows Subsystem for Linux), which adds complexity and defeats the "just pip install" requirement.

### Other Limitations
- **Only FLAT index type:** Milvus Lite ignores specified index types and always uses brute-force FLAT search. This means 1M x 768-dim queries will be slow (similar to sqlite-vec's brute-force problem).
- **No partitions:** Cannot use Milvus partitioning features.
- **No users/roles:** Cannot use access control features.

### Verdict: REJECTED
- No native Windows support (hard requirement)
- FLAT-only index defeats purpose of switching from brute-force sqlite-vec

---

## 7. Turbopuffer

### Overview
- **Type:** Serverless vector database on object storage (S3/Blob)
- **Notable users:** Notion, Linear, Superhuman
- **Confidence:** HIGH

### CRITICAL ISSUE: No Embedded Mode

**Turbopuffer is a cloud-only serverless service.** There is no embedded mode, no local mode, no self-hosted option. It requires internet connectivity and a Turbopuffer account.

This fundamentally conflicts with the requirement for in-process, pip-installable operation.

### Verdict: DISQUALIFIED
- Cloud-only service, no embedded mode exists

---

## 8. DuckDB + VSS Extension

### Overview
- **Type:** Analytical SQL database with HNSW vector search extension
- **Architecture:** Uses USearch as HNSW backend
- **Installation:** `pip install duckdb` + `INSTALL vss; LOAD vss;` in SQL
- **License:** MIT (DuckDB), MIT (VSS extension)
- **Latest version:** DuckDB 1.3.x (active development)
- **Confidence:** MEDIUM

### Key Issues

1. **Experimental extension:** The VSS extension is explicitly experimental. From DuckDB docs: "WAL recovery is not yet properly implemented for custom indexes, meaning crashes during uncommitted changes can cause data loss or corruption."

2. **In-memory HNSW by default:** The HNSW index can only be created in in-memory databases unless `SET hnsw_enable_experimental_persistence = true` is used (behind experimental flag).

3. **No metadata pre-filtering with HNSW:** The HNSW index is only used for top-k queries and cannot be combined with WHERE clauses. This means metadata filtering and vector search cannot be efficiently combined.

4. **Batch-oriented design:** DuckDB is optimized for batch analytics, not point queries. Per-query overhead is noticeable for the single-query pattern Synapse uses.

5. **Deletes not reflected in index:** Deleted records are "marked" but not removed from the HNSW index, causing stale results over time.

### Windows Compatibility
- **Works.** DuckDB has excellent Windows support with prebuilt wheels.

### Verdict: REJECTED
- Experimental persistence with data loss risk
- No metadata filtering with HNSW index
- Batch-oriented, not suited for single-query RAG pattern
- Would add DuckDB as an additional dependency alongside SQLite

---

## 9. Other Emerging Solutions

### Vectorlite (SQLite extension with HNSW)
- **GitHub:** [1yefuwang1/vectorlite](https://github.com/1yefuwang1/vectorlite)
- **Architecture:** hnswlib-based HNSW index as SQLite virtual table
- **Installation:** `pip install vectorlite`
- **Platform:** Windows, macOS, Linux (x64 and ARM)
- **Performance:** 7-30x faster than sqlite-vec for vector queries (varies by dimension)
- **Metadata filtering:** Supports predicate pushdown (requires SQLite >= 3.38)
- **HNSW tuning:** Full control over M, ef_construction, ef parameters
- **SIMD:** Uses Google Highway library for 1.5-3x faster distance computation than hnswlib

**Assessment:** Interesting alternative to sqlite-vec for getting HNSW performance within SQLite. However, small community (~300 stars), unclear maintenance trajectory, and HNSW is RAM-resident like ChromaDB (same 8GB concern at 1M vectors). Version 0.2.0 suggests early maturity.

### sqlite-vector (by SQLite.ai)
- **GitHub:** [sqliteai/sqlite-vector](https://github.com/sqliteai/sqlite-vector)
- **Description:** "Blazing fast and memory efficient vector search extension for SQLite"
- **Status:** New entrant, limited documentation

### hnswlib + SQLite (manual combo)
- Used by some projects (hnsqlite). Essentially what ChromaDB does under the hood. Same RAM concerns as ChromaDB/vectorlite.

---

## Comparison Matrix

| Criterion | LanceDB | ChromaDB | USearch | sqlite-vec | FAISS | Milvus Lite | DuckDB VSS |
|-----------|---------|----------|--------|------------|-------|-------------|------------|
| **pip install** | Yes | Yes | Yes | Yes | Yes | Yes* | Yes |
| **No server required** | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| **Windows** | Yes | Buggy | Yes | Yes | Yes | NO (WSL only) | Yes |
| **Mac** | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| **Linux** | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| **Query <50ms @ 1M** | **3-10ms** | ~20ms | ~5ms | **NO (100-200ms)** | ~10-30ms | NO (flat only) | Varies |
| **RAM @ 1M x 768** | **~200-500MB** | **~4.8GB** | ~3-5GB | ~3GB (brute) | ~3-6GB | N/A | ~3-5GB |
| **Disk-backed queries** | **YES** | No (RAM-resident) | Partial (mmap) | Yes (brute-force) | No | No | Experimental |
| **Metadata filtering** | **Pre-filter** | Post-filter | **NO** | **Yes** | **NO** | Yes | NO with HNSW |
| **Hybrid search (FTS+vec)** | **Yes (BM25+RRF)** | **Yes (BM25/SPLADE)** | No | No | No | Limited | No |
| **Async Python** | **Yes (native)** | HTTP only | No | No | No | Yes | No |
| **8GB safe @ 1M** | **YES** | **RISKY** | Risky | Yes (slow) | Risky | N/A | Risky |
| **GitHub stars** | ~9K | ~26.5K | ~3.9K | ~5K+ | ~39.4K | ~35K | N/A |
| **Last release** | Mar 2026 | Mar 2026 | Feb 2026 | Mar 2026 | Mar 2025 | Active | Active |
| **Quantization** | PQ, SQ, RaBitQ | No | Half/i8 | Binary | PQ, SQ, OPQ | Various | No |

*Milvus Lite: pip install works on Linux/Mac only

---

## RAM Budget Analysis (8GB Machine)

| Component | RAM Usage |
|-----------|-----------|
| OS + system services | ~1.5 GB |
| Python runtime + FastAPI + Synapse | ~300-500 MB |
| Ollama (nomic-embed-text loaded) | ~1-2 GB |
| FlashRank reranker | ~100 MB |
| Toxic-BERT (when loaded) | ~200 MB |
| **Available for vector DB** | **~3.5-4.5 GB** |

| Vector DB | RAM @ 1M vectors | Fits? |
|-----------|-------------------|-------|
| **LanceDB (IVF-PQ)** | **~200-500 MB** | **YES, comfortably** |
| LanceDB (IVF-RaBitQ) | ~100-300 MB | YES, easily |
| ChromaDB (HNSW) | ~4.8 GB | **NO -- exceeds available** |
| FAISS (flat) | ~3.1 GB | Barely, but no headroom |
| FAISS (IVF-PQ) | ~800 MB-1 GB | Possible but tight |
| sqlite-vec (brute-force) | ~3 GB (scan from disk) | RAM OK but query too slow |

---

## Synapse-Specific Integration Analysis

### Current Architecture
```
MemoryEngine.query()
  -> QdrantVectorStore (ANN search via Qdrant Docker container)
  -> SQLite FTS (full-text search via memory.db)
  -> FlashRank rerank (ms-marco-TinyBERT-L-2-v2)
```

### Proposed Architecture with LanceDB
```
MemoryEngine.query()
  -> LanceDB hybrid_search() (vector + BM25 in one call, RRF reranked)
  -> FlashRank rerank (optional second-stage reranking)
```

### Migration Benefits
1. **Eliminates Qdrant Docker dependency** -- single `pip install lancedb`
2. **Simplifies hybrid search** -- LanceDB native BM25+vector replaces manual SQLite FTS + Qdrant ANN combo
3. **Hemisphere filtering** -- Pre-filter `WHERE hemisphere_tag = 'safe'` applied before vector search, no recall degradation
4. **Async compatibility** -- `lancedb.connect_async()` fits Synapse's `asyncio` architecture
5. **Dual SBS support** -- Can use separate LanceDB tables or partition keys for `the_creator` vs `the_partner`
6. **Knowledge graph unaffected** -- `knowledge_graph.db` (SQLiteGraph) remains as-is

### Migration Risks
1. **Storage format change** -- Need migration script from Qdrant + sqlite-vec to LanceDB
2. **FTS quality** -- LanceDB's BM25 may differ from SQLite FTS5 in tokenization/ranking; needs testing
3. **API surface** -- LanceDB uses PyArrow-based API, different from current Qdrant client interface
4. **sqlite-vec coexistence** -- If keeping sqlite-vec for backward compatibility, need clear boundaries on which DB handles what

---

## Disk Storage Estimates at 1M Vectors (768-dim, float32)

| Storage Strategy | Size | Notes |
|------------------|------|-------|
| Raw float32 | 3.0 GB | 1M * 768 * 4 bytes |
| LanceDB IVF-PQ | ~500 MB - 1 GB | PQ compresses to ~24 bytes/vector + overhead |
| LanceDB IVF-RaBitQ | ~200-400 MB | 1 bit/dim + correction scalars |
| LanceDB IVF-SQ | ~1 GB | 4x compression from float32 to int8 |
| FAISS IVF-PQ | ~500 MB - 1 GB | Similar to LanceDB |
| ChromaDB (HNSW on disk) | ~4-5 GB | Includes HNSW graph structure |
| sqlite-vec (binary quantized) | ~135 MB (128-dim reference) | Scales with dimension |

---

## Community & Ecosystem Signals

### LanceDB
- Backed by Y Combinator, raised funding
- Active blog with technical content (Jan/Feb 2026 newsletters)
- Used by OpenClaw as memory layer
- Native support on Hugging Face Hub
- LangChain, LlamaIndex integrations
- ~6M PyPI downloads/month

### ChromaDB
- 10K+ Discord community
- Used in 90K+ open-source repos on GitHub
- Most "getting started" tutorials use ChromaDB
- LangChain, LlamaIndex, Haystack integrations
- ~11M PyPI downloads/month (highest)

### sqlite-vec
- Mozilla Builders project (institutional backing)
- Sponsored by Fly.io, Turso, SQLite Cloud
- Natural fit for SQLite-first architectures
- Growing but smaller community

### FAISS
- Meta/Facebook maintained
- Research-grade, industry standard
- Largest GitHub stars (39K+)
- But: library not database, requires wrappers for production use

---

## ANN-Benchmarks.com Status

Latest benchmarks run April 2025 on AWS r6i.16xlarge with parallelism 31, single-CPU. [Source](https://github.com/erikbern/ann-benchmarks)

Key findings across all datasets:
- **HNSW-based algorithms dominate** at high recall levels
- **FAISS-IVF** competitive at lower recall thresholds
- **Results are for raw library performance** -- do not account for metadata filtering, persistence, or operational concerns

Note: ann-benchmarks tests raw index performance, not database-level operations. For the Synapse use case (metadata filtering + persistence + async + hybrid search), database-level benchmarks are more relevant than raw ANN benchmarks.

---

## Final Recommendation

### Primary: LanceDB

**Use LanceDB as the primary vector store, replacing both Qdrant AND the vector search portion of sqlite-vec.**

Rationale:
1. Only candidate that is disk-backed, sub-10ms at 1M vectors, AND fits in 8GB RAM
2. Native hybrid search eliminates need for separate FTS system
3. Native async Python API matches Synapse's architecture
4. Metadata pre-filtering preserves recall quality
5. Multiple quantization options (RaBitQ ideal for 768-dim nomic-embed-text)
6. Active development (v0.30.1, March 2026)
7. Works on Windows/Mac/Linux via pip

### Secondary: Keep sqlite-vec for small/fast collections

sqlite-vec remains excellent for:
- Small collections (under 100K vectors) where brute-force is fast enough
- The existing memory.db schema if migration is phased
- Metadata-heavy queries where SQLite's query planner shines

### Do Not Use
- **ChromaDB:** RAM requirements too high for 8GB machines, Windows bugs
- **FAISS:** Not a database, no metadata filtering, no persistence, no async
- **USearch:** No metadata filtering, not a database
- **Milvus Lite:** No Windows support, FLAT-only index
- **Turbopuffer:** Cloud-only, no embedded mode
- **DuckDB VSS:** Experimental, no metadata+HNSW combo, data loss risk

---

## Sources

### Official Documentation
- [LanceDB Docs](https://docs.lancedb.com/)
- [LanceDB Hybrid Search](https://docs.lancedb.com/search/hybrid-search)
- [LanceDB Metadata Filtering](https://docs.lancedb.com/search/filtering)
- [LanceDB Quantization](https://docs.lancedb.com/indexing/quantization)
- [LanceDB FAQ](https://docs.lancedb.com/faq/faq-oss)
- [ChromaDB Performance Docs](https://docs.trychroma.com/guides/deploy/performance)
- [ChromaDB Resource Requirements](https://cookbook.chromadb.dev/core/resources/)
- [sqlite-vec Official Site](https://alexgarcia.xyz/sqlite-vec/)
- [USearch README](https://github.com/unum-cloud/USearch)
- [FAISS Installation](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md)
- [DuckDB VSS Docs](https://duckdb.org/docs/1.3/core_extensions/vss)
- [Milvus Lite Docs](https://milvus.io/docs/milvus_lite.md)

### Benchmarks & Comparisons
- [LanceDB Benchmarks](https://medium.com/etoai/benchmarking-lancedb-92b01032874a)
- [Vector Database Comparison 2026 (4xxi)](https://4xxi.com/articles/vector-database-comparison/)
- [Best Vector Databases 2026 (Encore)](https://encore.dev/articles/best-vector-databases)
- [Best Vector Databases 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-vector-databases)
- ["We Need to Stop Using FAISS" (Dec 2025)](https://python.plainenglish.io/we-need-to-stop-using-faiss-by-default-benchmarking-8-vector-databases-for-real-use-cases-21cf52caf725)
- [ANN-Benchmarks](http://ann-benchmarks.com/)
- [VectorDBBench (Zilliz)](https://github.com/zilliztech/VectorDBBench)

### GitHub Issues & Discussions
- [ChromaDB RAM Limitation (Issue #1323)](https://github.com/chroma-core/chroma/issues/1323)
- [ChromaDB Memory Leak (Issue #5843)](https://github.com/chroma-core/chroma/issues/5843)
- [ChromaDB Windows Crash (Issue #5392)](https://github.com/chroma-core/chroma/issues/5392)
- [USearch Filtering Request (Issue #348)](https://github.com/unum-cloud/usearch/issues/348)
- [sqlite-vec ANN Tracking (Issue #25)](https://github.com/asg017/sqlite-vec/issues/25)
- [Milvus Lite Windows (Issue #176)](https://github.com/milvus-io/milvus-lite/issues/176)
- [LanceDB 700M Vectors Production](https://sprytnyk.dev/posts/running-lancedb-in-production/)
- [FAISS Metadata Filtering (Issue #1079)](https://github.com/facebookresearch/faiss/issues/1079)

### PyPI
- [lancedb PyPI](https://pypi.org/project/lancedb/) - v0.30.1
- [chromadb PyPI](https://pypi.org/project/chromadb/) - v1.5.5
- [usearch PyPI](https://pypi.org/project/usearch/) - v2.24.0
- [sqlite-vec PyPI](https://pypi.org/project/sqlite-vec/) - v0.1.7
- [faiss-cpu PyPI](https://pypi.org/project/faiss-cpu/) - v1.13.2
- [vectorlite PyPI](https://pypi.org/project/vectorlite/)
