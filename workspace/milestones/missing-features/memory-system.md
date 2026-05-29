# Memory System — Gaps in Synapse-OSS

## Overview

openclaw has a layered `.md`-file memory system backed by SQLite-vec or LanceDB (via the `qmd` tool), with vector search, full-text search (FTS5), per-session transcript indexing, a sync pipeline, a cache, and a rich provider status API. The system is exposed through a `packages/memory-host-sdk/` package that provides the public interface for extensions and tools. Synapse-OSS has a SQLite-backed memory engine with Qdrant vector storage and FlashRank reranking — a more heavyweight approach that does not index `.md` files and lacks the sync/status/session integration.

---

## What openclaw Has

### 1. Memory Host SDK (`packages/memory-host-sdk/`)

The SDK is the stable public surface for any code that needs to read or write memory. Key exports:

```
engine-foundation.ts  → foundation: agent scope, config load, paths, session transcripts
engine-storage.ts     → storage: chunk markdown, list files, hash text, embeddings
engine-embeddings.ts  → embedding pipeline interface
engine-qmd.ts         → qmd (external binary) integration
runtime.ts            → MemoryHostRuntime: start/stop/sync lifecycle
runtime-cli.ts        → CLI-facing runtime variant
runtime-core.ts       → core provider construction
runtime-files.ts      → file discovery and indexing
secret.ts             → API key resolution for embedding providers
status.ts             → MemoryProviderStatus report
query.ts              → query construction helpers
```

**Package:** `packages/memory-host-sdk/src/`

### 2. MemorySearchManager Interface (`packages/memory-host-sdk/src/host/types.ts`)

```typescript
interface MemorySearchManager {
  search(query, opts?: { maxResults?, minScore?, sessionKey? }): Promise<MemorySearchResult[]>;
  readFile(params: { relPath, from?, lines? }): Promise<{ text, path }>;
  status(): MemoryProviderStatus;
  sync(params?: { reason?, force?, sessionFiles?, progress? }): Promise<void>;
  probeEmbeddingAvailability(): Promise<MemoryEmbeddingProbeResult>;
  probeVectorAvailability(): Promise<boolean>;
  close?(): Promise<void>;
}
```

`MemorySearchResult` carries: `path`, `startLine`, `endLine`, `score`, `snippet`, `source: "memory" | "sessions"`, `citation?`.

**File:** `packages/memory-host-sdk/src/host/types.ts`

### 3. Markdown File Indexing

The memory system indexes `.md` files in:
- The agent's `memory/` directory.
- Configured `extraPaths` (additional directories).
- Session transcripts (as `source: "sessions"`) — separately indexed and toggled per-query via `sessionKey`.

`chunkMarkdown(text, filePath)` — splits markdown into semantic chunks preserving header context.
`buildFileEntry(filePath)` — reads a file, hashes it, builds chunks.
`listMemoryFiles(dir, opts)` — glob-based file discovery with exclusion patterns.
`hashText(content)` — SHA-256 for change detection (skip re-embedding unchanged files).
`remapChunkLines(chunks, originalText)` — line number remapping after chunking.

**File:** `packages/memory-host-sdk/src/host/internal.js`

### 4. Two Backends

#### a. Built-in (SQLite-vec)

- `loadSqliteVecExtension(db)` — loads the `sqlite-vec` native extension for vector operations.
- `ensureMemoryIndexSchema(db)` — creates/migrates the schema (documents, chunks, vec_items tables with FTS5 virtual table).
- `requireNodeSqlite()` — guards against Node.js versions < 22.15 that lack the built-in `node:sqlite` module.
- FTS5 full-text search as fallback when vector search is unavailable.
- `resolveMemoryBackendConfig` — resolves `builtin` vs `qmd` backend from config.

**Files:** `packages/memory-host-sdk/src/host/sqlite-vec.ts`, `memory-schema.ts`, `sqlite.ts`, `backend-config.ts`

#### b. QMD (External Binary)

- `engine-qmd.ts` — integration with the `qmd` CLI tool for vector search.
- Supports `qmd search`, `qmd vsearch` (semantic), `qmd embed` commands.
- `ResolvedQmdConfig` / `ResolvedQmdMcporterConfig` — config shapes for qmd invocation.
- Used for large memory sets where SQLite-vec is insufficient.

**File:** `packages/memory-host-sdk/src/engine-qmd.ts`

### 5. Sync Pipeline

`sync(params)` accepts:
- `reason` — label for logging.
- `force` — re-index all files even if unchanged.
- `sessionFiles` — explicit list of session transcript files to index immediately.
- `progress` callback — `{completed, total, label}` for UI progress reporting.

`runWithConcurrency(tasks, concurrency)` — parallel embedding with configurable concurrency cap to avoid API rate limits.

`MemoryProviderStatus.batch` reports: batch failures, batch limit, wait state, concurrency, poll interval, last error, last provider.

### 6. Embedding Pipeline

- `engine-embeddings.ts` — embedding provider interface.
- `parseEmbedding(raw)` — normalizes embedding vectors from different provider response shapes.
- `buildMultimodalChunkForIndexing(chunk)` — assembles the text to embed (title + content).
- `cosineSimilarity(a, b)` — vector dot product for local scoring fallback.

Embedding providers: any configured AI provider key (resolved via `secret.ts` → `resolveMemoryBackendConfig`).

### 7. Cache Layer

`MemoryProviderStatus.cache` reports: `enabled`, `entries`, `maxEntries`. A query cache deduplicates identical queries within the same session to avoid redundant embedding calls.

### 8. Session Transcript Integration

`onSessionTranscriptUpdate(handler)` — event subscription that fires when a session transcript is updated. The memory sync pipeline hooks into this to auto-index new transcript content.

`resolveSessionTranscriptsDirForAgent(agentDir)` — resolves where transcript files are stored for inclusion in the memory index.

**File:** `packages/memory-host-sdk/src/engine-foundation.ts` (re-exports `onSessionTranscriptUpdate`)

### 9. Memory Search Config (`src/agents/memory-search.ts`)

`ResolvedMemorySearchConfig`:
- `enabled: boolean`
- `maxResults: number`
- `minScore: number`
- `maxSnippetChars: number`
- `maxInjectedChars: number`
- `timeoutMs: number`
- `sources: MemorySource[]` — `["memory"]`, `["sessions"]`, or both.
- `citationsMode: MemoryCitationsMode` — how to inject citations into prompt.

**File:** `src/agents/memory-search.ts`

### 10. `readFile` API

Agents can read a specific region of a memory file by `relPath` + optional line range (`from`, `lines`). This is the foundation for the `memory_read` tool exposed to agents.

---

## What Synapse-OSS Has

`workspace/sci_fi_dashboard/memory_engine.py` — `MemoryEngine` class:

- SQLite-backed document storage in `memory.db`.
- Qdrant vector store for semantic search (via `qdrant_client`).
- Ollama embeddings (`nomic-embed-text`) — requires local Ollama server.
- FlashRank reranking (`ms-marco-TinyBERT-L-2-v2`) for result re-ranking.
- Exponential backoff retry for SQLite lock contention.
- `hemisphere_tag` field: `"safe"` / `"spicy"` — dual-hemisphere access control (privacy tiers).
- JSONL backup to `_archived_memories/persistent_log.jsonl`.

`workspace/skills/memory/ingest_memories.py`:
- Gmail memory ingestion script (not a general-purpose indexer).

| Feature | Synapse-OSS | openclaw |
|---|---|---|
| Backend | SQLite + Qdrant (external) | SQLite-vec (built-in) or qmd |
| File indexing (.md) | None (stores strings) | Full markdown chunking |
| Session transcript indexing | None | Full (auto on transcript update) |
| Sync pipeline | None | Full (force, partial, progress cb) |
| FTS5 fallback | None | Yes |
| Embedding concurrency cap | None | Yes |
| Provider status API | None | Full (batch, vector, fts, cache) |
| Query cache | None | Yes |
| Line-range read API | None | Yes |
| Multi-source toggle | None | Yes (memory + sessions) |
| Citations mode | None | Yes |
| SDK package | None (inline class) | Separate versioned package |
| Backend config schema | None (hardcoded) | Zod-validated with QMD config |
| Privacy tiers | hemisphere_tag (custom) | Not built-in (agent-level) |
| Reranking | FlashRank | Not built-in (score only) |
| External dependency | Qdrant + Ollama | sqlite-vec (built-in extension) |

---

## Gap Summary

The major gaps:

1. **No file-based memory indexing** — Synapse-OSS stores raw strings in SQLite, not chunked `.md` files. openclaw's approach enables browsing, editing, and versioning memory as plain Markdown.
2. **No session transcript indexing** — session history is not automatically searchable via the memory system.
3. **No sync pipeline with progress reporting** — there is no incremental re-index, no force-sync, no progress callback.
4. **No built-in vector backend** — requires external Qdrant + Ollama services; openclaw's SQLite-vec runs in-process.
5. **No line-range read API** — agents cannot read a specific section of a memory file.
6. **No provider status API** — no structured diagnostics for the memory backend.
7. **Heavy external dependencies** — Synapse-OSS requires Qdrant and Ollama to be running; openclaw works with zero external services.

---

## Implementation Notes for Porting

1. **File-based indexing** — Add `MemoryFileIndexer` that scans `~/.synapse/memory/*.md`, chunks by heading, hashes each chunk (SHA-256), and only re-embeds changed chunks. Store in SQLite: `(id, path, start_line, end_line, content, embedding BLOB)`.

2. **sqlite-vec** — Load the `sqlite-vec` Python extension (`pip install sqlite-vec`) as the vector backend. Drop Qdrant dependency for the default path.

3. **Session transcript indexing** — Subscribe to session-end events (or poll the transcripts directory). Auto-index new transcript files with `source="sessions"`.

4. **SDK boundary** — Extract `MemoryEngine` into a `memory_host_sdk/` package with a clean `MemorySearchManager` protocol (abstract base class with `search`, `read_file`, `status`, `sync`).

5. **Provider status** — Add a `status()` method that returns a dict with: backend, files count, chunks count, dirty flag, vector availability, FTS availability, last sync time.

6. **Concurrency cap** — Use `asyncio.Semaphore(N)` around embedding API calls. Make `N` configurable.
