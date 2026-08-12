# EMBEDDING REFACTOR PLAN — Synapse-OSS

**Date:** 2026-04-03
**Branch:** `refactor/optimize`
**RFC:** [Discussion #28](https://github.com/UpayanGhosh/Synapse-OSS/discussions/28)
**Status:** Ready for execution
**Goal:** Make Ollama optional for embeddings by introducing a provider abstraction layer with FastEmbed (ONNX) as the zero-dependency default, preserving Ollama and adding Gemini as an optional cloud provider.

---

## Dependency Graph

```
                    +----------------------------+
                    |   PHASE 1 (Foundation)     |
                    | EmbeddingProvider ABC +     |
                    | FastEmbed + Ollama impls   |
                    +----------------------------+
                       /        |          \
                      /         |           \
                     v          v            v
          +------------+  +------------+  +------------+
          |  PHASE 2   |  |  PHASE 3   |  |  PHASE 4   |
          |  Core      |  |  Storage & |  |  Config &  |
          |  Integra-  |  |  Schema    |  |  UX        |
          |  tion      |  |  Evolution |  |            |
          +------------+  +------------+  +------------+
                     \         |           /
                      \        |          /
                       v       v         v
                    +----------------------------+
                    |   PHASE 5 (Finalization)   |
                    | Cloud provider, MCP,       |
                    | cleanup, docs              |
                    +----------------------------+
```

**Execution order:**
- Phase 1: MUST complete first (foundation)
- Phases 2, 3, 4: Can run in parallel after Phase 1
- Phase 5: Runs after Phases 2 + 3 + 4 complete

---

## Complete Blast Radius

**Files that directly call Ollama embeddings or `get_embedding()`:**

| File | Embedding Mechanism | Dimension |
|------|---------------------|-----------|
| `workspace/sci_fi_dashboard/retriever.py` | `ollama.embeddings()` + `SentenceTransformer` fallback | 768 / 384 |
| `workspace/sci_fi_dashboard/memory_engine.py` | `ollama.embeddings()` + `SentenceTransformer` fallback | 768 / 384 |
| `workspace/sci_fi_dashboard/ingest.py` | Calls `retriever.get_embedding()` | inherited |
| `workspace/finish_facts.py` | Direct HTTP to Ollama `/api/embed` | 768 |
| `workspace/scripts/fact_extractor.py` | Direct HTTP to Ollama `/api/embeddings` | 768 |
| `workspace/scripts/nightly_ingest.py` | `ollama.embeddings()` | 768 |
| `workspace/skills/llm_router.py` | `ollama.embeddings()` | 768 |

**Files with hardcoded dimension `768`:**

| File | Location |
|------|----------|
| `workspace/sci_fi_dashboard/db.py` | `embedding float[768]` in `vec_items` |
| `workspace/scripts/v2_migration/qdrant_handler.py` | `size=768` |
| `workspace/scripts/update_memory_schema.py` | `FLOAT[768]` in `atomic_facts_vec` |
| `workspace/finish_facts.py` | `len(emb) == 768` validation |

---

## PHASE 1 — EmbeddingProvider Abstraction Layer

**Goal:** Create a provider abstraction layer (ABC + dataclasses + factory) with FastEmbed and Ollama implementations, plus comprehensive unit tests.

**Owner:** Senior Dev Agent 1

**Dependencies:** None (foundation phase)

### Files to Create

1. `workspace/sci_fi_dashboard/embedding/__init__.py` — Package init, re-exports
2. `workspace/sci_fi_dashboard/embedding/base.py` — ABC + dataclasses
3. `workspace/sci_fi_dashboard/embedding/fastembed_provider.py` — FastEmbed (ONNX) implementation
4. `workspace/sci_fi_dashboard/embedding/ollama_provider.py` — Ollama wrapper
5. `workspace/sci_fi_dashboard/embedding/factory.py` — Provider factory with cascade
6. `workspace/tests/test_embedding_providers.py` — Unit tests

### Implementation Steps

**Step 1: Define the contracts (`base.py`)**

```python
@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimensions: int
    provider: str  # "fastembed" | "ollama" | "gemini" | etc.

@dataclass(frozen=True)
class ProviderInfo:
    name: str
    model: str
    dimensions: int
    requires_network: bool
    requires_gpu: bool

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Adds 'search_query: ' prefix for models that need it."""
    
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents for storage. Adds 'search_document: ' prefix."""
    
    @abstractmethod
    def info(self) -> ProviderInfo:
        """Return provider metadata."""
    
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the output dimension of this provider's model."""
```

Key design decisions:
- `embed_query` vs `embed_documents` distinction enables correct task prefix handling at the abstraction level (LangChain standard)
- All providers handle task prefixes internally — callers never add prefixes
- `EmbeddingResult` is NOT returned from hot path methods (just `list[float]`) to avoid allocation overhead in LRU cache
- `ProviderInfo` is used by health checks and configuration validation

**Step 2: Implement FastEmbedProvider (`fastembed_provider.py`)**

```python
class FastEmbedProvider(EmbeddingProvider):
    DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
    DIMENSIONS = 768
```

Implementation details:
- Lazy-load `TextEmbedding` from `fastembed` on first call (not at import time)
- FastEmbed's `embed()` returns a generator of numpy arrays — must call `list()` and `.tolist()`
- FastEmbed does NOT add task prefixes. Provider must prepend `"search_query: "` in `embed_query()` and `"search_document: "` in `embed_documents()`
- FastEmbed is NOT async — both methods run synchronously (async wrapper is Phase 2's concern)
- Thread count: use `threads` parameter, default to `min(4, os.cpu_count())`
- Cache directory: use `SynapseConfig.data_root / "models" / "fastembed"` or respect `FASTEMBED_CACHE_PATH` env var
- Model download on first use: log informational message before first `TextEmbedding()` instantiation

**Step 3: Implement OllamaProvider (`ollama_provider.py`)**

```python
class OllamaProvider(EmbeddingProvider):
    DEFAULT_MODEL = "nomic-embed-text"
    DIMENSIONS = 768
```

Implementation details:
- Wraps `ollama.embeddings()` calls from existing code
- CRITICAL: Change `keep_alive` from `"0"` to `"5m"` (fixes ~2s cold-start penalty)
- Add `"search_query: "` and `"search_document: "` prefixes (currently missing — 5-15% quality degradation)
- Availability check: try test embed on init, catch `ConnectionError`/`ImportError`, set `self._available = False`
- Must NOT fail hard if Ollama is not running

**Step 4: Implement ProviderFactory (`factory.py`)**

```python
def create_provider(config: dict | None = None) -> EmbeddingProvider:
    """Create an embedding provider using cascade logic."""
```

Priority cascade:
1. If `config` specifies `embedding.provider` explicitly, use that
2. If `fastembed` is importable, use `FastEmbedProvider` (new default)
3. If `ollama` is importable AND running, use `OllamaProvider`
4. Raise `RuntimeError("No embedding provider available. Install fastembed: pip install fastembed")`

Factory must:
- Accept optional `config` dict (Phase 4 defines schema, factory handles `None`)
- Log which provider was selected and why
- Return a singleton via module-level `_provider` with `get_provider()` accessor

**Step 5: Write unit tests (`test_embedding_providers.py`)**

Test cases:
- `test_fastembed_embed_query_adds_prefix` — verify `"search_query: "` is prepended
- `test_fastembed_embed_documents_adds_prefix` — verify `"search_document: "` is prepended
- `test_fastembed_output_dimensions` — verify exactly 768 dimensions
- `test_fastembed_batch_embedding` — multiple documents return correct count
- `test_ollama_provider_unavailable` — mock to raise `ConnectionError`, verify graceful handling
- `test_ollama_provider_adds_prefix` — verify task prefixes added
- `test_factory_cascade_fastembed_default` — fastembed importable → returns `FastEmbedProvider`
- `test_factory_cascade_ollama_fallback` — fastembed NOT importable → returns `OllamaProvider`
- `test_factory_explicit_config_override` — config forces specific provider
- `test_provider_info_metadata` — verify `info()` returns correct metadata

### Acceptance Criteria
- [ ] `from sci_fi_dashboard.embedding import create_provider` works
- [ ] `FastEmbedProvider` produces 768-dim vectors with task prefixes
- [ ] `OllamaProvider` wraps existing calls with task prefixes and `keep_alive="5m"`
- [ ] `create_provider()` returns `FastEmbedProvider` when fastembed is installed
- [ ] All 10 unit tests pass
- [ ] Zero imports of `sentence-transformers` or `torch` in any new file
- [ ] No modification to any existing file (pure additive)

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| FastEmbed first-run download fails (firewall) | Blocks embedding entirely | Cascade falls through to Ollama; clear error message |
| FastEmbed model output not exactly 768-dim | Silent corruption | Unit test validates exact dimension count |
| Prefixes change embedding space vs unprefixed vectors | Quality mismatch with existing data | Phase 3 handles re-embedding; prefixed vectors are strictly better |
| ONNX runtime wheels missing for platform | ImportError | fastembed includes wheels for all major platforms |

---

## PHASE 2 — Core Integration

**Goal:** Rewire all embedding call sites (`retriever.py`, `memory_engine.py`, `ingest.py`) to use the `EmbeddingProvider` abstraction.

**Owner:** Senior Dev Agent 2

**Dependencies:** Phase 1 (the `embedding/` package must exist)

### Files to Modify

1. `workspace/sci_fi_dashboard/retriever.py` — Replace `_init_embedder()` / `get_embedding()` with provider
2. `workspace/sci_fi_dashboard/memory_engine.py` — Replace embedding code with provider
3. `workspace/sci_fi_dashboard/ingest.py` — Use provider for batch embedding

### Files to Create

1. `workspace/tests/test_embedding_integration.py` — Integration tests

### Implementation Steps

**Step 1: Rewire `retriever.py`**

Current: Module-level globals `_embedder`, `_embed_mode` with `_init_embedder()` cascade.

Target:
- Remove `_embedder`, `_embed_mode`, `_init_embedder()`, `EMBEDDING_MODEL_OLLAMA`, `EMBEDDING_MODEL_ST`
- Remove lazy `from sentence_transformers import SentenceTransformer` import
- Add `from sci_fi_dashboard.embedding import get_provider`
- Rewrite `get_embedding()`:
  ```python
  def get_embedding(text: str) -> list[float] | None:
      provider = get_provider()
      if provider is None:
          return None
      return provider.embed_query(text)
  ```
- Function signature unchanged — backward compatible
- `_embed_mode` replaced by `get_provider().info().name`

CRITICAL: `retriever.py` calls `embed_query()` (for search, adds `search_query:` prefix).

**Step 2: Rewire `memory_engine.py`**

Current: `MemoryEngine` has `get_embedding()` with `@lru_cache(maxsize=500)` and `_sentence_transformer_embed()` fallback.

Target:
- Remove `import ollama`, `OLLAMA_AVAILABLE`, `EMBEDDING_MODEL`, `OLLAMA_KEEP_ALIVE` constants
- Remove `_sentence_transformer_embed()` method and `self._st_model`
- Store provider reference: `self._embed_provider = get_provider()`
- Preserve LRU cache:
  ```python
  @lru_cache(maxsize=500)
  def get_embedding(self, text: str) -> tuple:
      try:
          return tuple(self._embed_provider.embed_query(text))
      except Exception as e:
          print(f"[WARN] Embedding generation failed: {e}")
          return tuple([0.0] * self._embed_provider.dimensions)
  ```

**Step 3: Rewire `ingest.py`**

Target:
- Use `embed_documents()` for batch efficiency:
  ```python
  from sci_fi_dashboard.embedding import get_provider
  provider = get_provider()
  texts = [content for _, content, _ in new_items]
  vectors = provider.embed_documents(texts)
  ```
- IMPORTANT: Uses `embed_documents()` (adds `search_document:` prefix)

**Step 4: Integration tests**

- `test_retriever_get_embedding_uses_provider` — mock provider, verify `embed_query()` called
- `test_memory_engine_get_embedding_uses_provider` — mock provider, verify delegation
- `test_memory_engine_lru_cache_works` — verify caching without double provider call
- `test_ingest_uses_embed_documents` — mock provider, verify batch call
- `test_retriever_fallback_to_none` — provider raises → returns None
- `test_memory_engine_zero_vector_on_failure` — provider raises → zero vector

### Acceptance Criteria
- [ ] `retriever.py` has zero `import ollama` or `import sentence_transformers`
- [ ] `memory_engine.py` has zero `import ollama` or `import sentence_transformers`
- [ ] `ingest.py` uses batch `embed_documents()` instead of per-item loop
- [ ] LRU cache in `memory_engine.py` still works
- [ ] All existing tests still pass (or are updated)
- [ ] 6 new integration tests pass

---

## PHASE 3 — Storage & Schema Evolution

**Goal:** Add embedding provenance tracking, dimension validation, and build a re-embedding CLI command.

**Owner:** Senior Dev Agent 3

**Dependencies:** Phase 1 (needs `EmbeddingProvider.dimensions` and `ProviderInfo`)

### Files to Modify

1. `workspace/sci_fi_dashboard/db.py` — Schema migration, dimension validation
2. `workspace/scripts/v2_migration/qdrant_handler.py` — Parameterize dimensions
3. `workspace/scripts/update_memory_schema.py` — Update hardcoded dimensions

### Files to Create

1. `workspace/sci_fi_dashboard/embedding/migrate.py` — Re-embedding engine
2. `workspace/tests/test_schema_migration.py` — Schema migration tests

### Implementation Steps

**Step 1: Schema migration in `db.py`**

Add idempotent migration:
```python
def _ensure_embedding_metadata(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(documents)")
    columns = {row[1] for row in cursor.fetchall()}
    if "embedding_model" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN embedding_model TEXT DEFAULT 'nomic-embed-text'")
        conn.execute("ALTER TABLE documents ADD COLUMN embedding_version TEXT DEFAULT 'ollama-v1'")
    # Same for atomic_facts
```

**Step 2: Parameterize vector dimensions**

Replace hardcoded `float[768]` with `EMBEDDING_DIMENSIONS = 768` constant.

**Step 3: Add dimension validation**

```python
def validate_embedding_dimension(vector: list[float], expected: int = EMBEDDING_DIMENSIONS) -> None:
    if len(vector) != expected:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(vector)}, expected {expected}. "
            f"Run 'synapse re-embed' to fix."
        )
```

This fixes the CRITICAL BUG: 384-dim vectors silently corrupting 768-dim store.

**Step 4: Parameterize Qdrant handler**

Make `size=768` configurable via constructor parameter.

**Step 5: Build `synapse re-embed` CLI**

Idempotent re-embedding command with progress bar. Tracks progress via `embedding_model` column.

**Step 6: Tests**

- `test_migration_adds_columns`, `test_migration_idempotent`
- `test_dimension_validation_correct`, `test_dimension_validation_wrong`
- `test_re_embed_processes_all_rows`, `test_re_embed_idempotent`, `test_re_embed_dry_run`
- `test_qdrant_dimensions_parameterized`

### Acceptance Criteria
- [ ] Existing databases gain `embedding_model` and `embedding_version` columns on first connect
- [ ] New vector inserts validated for dimension correctness
- [ ] `synapse re-embed` works end-to-end
- [ ] `synapse re-embed --dry-run` shows plan without modifying data
- [ ] Qdrant handler accepts configurable dimensions
- [ ] 8 migration/schema tests pass

---

## PHASE 4 — Configuration & UX

**Goal:** Add embedding configuration to `synapse.json`, update startup sequence, add model download progress, update health checks.

**Owner:** Senior Dev Agent 4

**Dependencies:** Phase 1 (needs factory to accept config dict)

### Files to Modify

1. `workspace/synapse_config.py` — Add `embedding` field to `SynapseConfig`
2. `workspace/synapse.json.example` — Add embedding section
3. `workspace/sci_fi_dashboard/api_gateway.py` — Update startup logging
4. `workspace/cli/doctor.py` — Replace sentence-transformers check with provider check

### Files to Create

1. `workspace/tests/test_embedding_config.py` — Config validation tests

### Implementation Steps

**Step 1: Extend `SynapseConfig`**

Add `embedding: dict` field with default `{}`.

**Step 2: Define config schema**

```json
{
  "embedding": {
    "provider": "auto",
    "model": null,
    "cache_dir": null,
    "threads": null
  }
}
```

- `provider`: `"auto"` | `"fastembed"` | `"ollama"` | `"gemini"`
- `model`: Override model name (default: provider's default)
- `cache_dir`: Override cache directory
- `threads`: ONNX thread count

**Step 3: Wire config into factory**

Update `factory.py` to read from `SynapseConfig`.

**Step 4: Update startup sequence**

Separate embedding status from Ollama status in startup banner.

**Step 5: Update doctor checks**

Replace `_check_sentence_transformers()` and `_check_torch()` with `_check_embedding_provider()`.

**Step 6: Tests**

- `test_config_loads_embedding_section`
- `test_config_missing_embedding_section_defaults`
- `test_provider_auto_detection_from_config`
- `test_provider_explicit_from_config`
- `test_doctor_check_embedding_provider`
- `test_startup_logging_shows_provider`

### Acceptance Criteria
- [ ] `synapse.json.example` has `embedding` section
- [ ] `SynapseConfig.load()` returns `embedding` dict
- [ ] `synapse doctor` reports embedding provider status
- [ ] Startup banner shows provider name and model
- [ ] First-run download prints informational message
- [ ] Provider selection respects config
- [ ] 6 config tests pass

---

## PHASE 5 — Cloud Provider, Legacy Cleanup & Documentation

**Goal:** Add Gemini API as optional cloud provider, clean up legacy dependencies, update peripheral scripts, finalize docs.

**Owner:** Senior Dev Agent 5

**Dependencies:** Phases 1 + 2 + 3 + 4 (all must be complete)

### Files to Create

1. `workspace/sci_fi_dashboard/embedding/gemini_provider.py` — Gemini API embeddings
2. `workspace/tests/test_embedding_e2e.py` — End-to-end smoke tests

### Files to Modify

1. `workspace/requirements.txt` — Add `fastembed`
2. `workspace/pyproject.toml` — Add `fastembed` to dependencies
3. `workspace/finish_facts.py` — Use provider instead of direct Ollama HTTP
4. `workspace/scripts/fact_extractor.py` — Use provider
5. `workspace/scripts/nightly_ingest.py` — Use provider
6. `workspace/skills/llm_router.py` — Use provider for `embed()`

### Implementation Steps

**Step 1: Implement GeminiAPIProvider**

```python
class GeminiAPIProvider(EmbeddingProvider):
    DEFAULT_MODEL = "text-embedding-004"
    NATIVE_DIMENSIONS = 768  # 3072 MRL-truncated to 768
```

- Use NEW SDK: `from google import genai` (NOT deprecated `google-generativeai`)
- Task type via API parameter (`RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`), not text prefix
- NEVER auto-selected — explicit config only
- NOT suitable for vault/spicy hemisphere (cloud leakage risk)
- Gemini vectors in DIFFERENT embedding space than nomic — re-embed required on switch

**Step 2: Update peripheral scripts**

Replace direct Ollama calls in `finish_facts.py`, `fact_extractor.py`, `nightly_ingest.py`, `skills/llm_router.py` with provider abstraction.

**Step 3: Update dependencies**

- Add `fastembed>=0.4.0` to `requirements.txt` and `pyproject.toml`
- Comment out `sentence-transformers` from embedding requirements (keep for Toxic-BERT in `requirements-ml.txt`)

**Step 4: E2E tests**

- `test_e2e_embed_and_retrieve` — full embed → store → query cycle
- `test_e2e_provider_health_check`
- `test_e2e_ingest_with_provider`
- `test_e2e_dimension_validation_blocks_mismatch`
- `test_gemini_provider_requires_api_key`
- `test_gemini_provider_not_auto_selected`

### Acceptance Criteria
- [ ] `GeminiAPIProvider` works with API key from synapse.json
- [ ] Gemini is never auto-selected
- [ ] All 4 peripheral scripts use provider abstraction
- [ ] `sentence-transformers` no longer required for embeddings
- [ ] `fastembed` in `requirements.txt` and `pyproject.toml`
- [ ] 6 E2E tests pass
- [ ] Fresh install without Ollama works

---

## Risk Matrix (Top 5)

| # | Risk | Probability | Impact | Phase | Mitigation |
|---|------|-------------|--------|-------|------------|
| 1 | Mixing vectors from different embedding models | HIGH | CRITICAL | 2,3 | Dimension validation blocks wrong-size. `embedding_model` column tracks provenance. Re-embed command. |
| 2 | FastEmbed download fails on firewalled systems | MEDIUM | HIGH | 1,4 | Cascade to Ollama; clear errors; `cache_dir` for pre-download |
| 3 | LRU caches return stale vectors after provider switch | LOW | HIGH | 2 | Cache per-process, cleared on restart. Document restart requirement. |
| 4 | Breaking sentence-transformers removal affects Toxic-BERT | LOW | MEDIUM | 5 | sentence-transformers stays in requirements-ml.txt for Toxic-BERT. |
| 5 | Task prefix changes embedding space vs existing vectors | MEDIUM | MEDIUM | 1,3 | Prefixed vectors objectively better. `synapse re-embed` regenerates all. |

---

## Open Questions Resolution

| Question | Decision | Rationale |
|----------|----------|-----------|
| FastEmbed required or optional? | **Required** — add to `requirements.txt` | Ensures semantic search works for everyone OOTB |
| Gemini for vault/spicy hemisphere? | **No** — violates air-gap principle | Cloud leakage risk for private content |
| Existing 384-dim corrupted vectors? | Dimension validation blocks new ones; `synapse re-embed` fixes existing | Non-destructive migration path |
| Hemisphere-aware providers? | **Not in v1** — all hemispheres use same provider | Future enhancement after v1 stabilizes |
| `keep_alive="0"` fix? | Change to `"5m"` in OllamaProvider | ~500MB RAM trade-off acceptable for ~2s latency improvement |

---

## Performance Comparison

| Provider | Latency (1 text) | Latency (64 batch) | RAM | Model Disk | GPU | Network |
|----------|-----------------|---------------------|-----|------------|-----|---------|
| **FastEmbed** (nomic-v1.5-Q) | ~15ms | ~400ms | ~200MB | ~70MB | No | First download |
| **Ollama** (keep_alive=5m) | ~25ms warm / ~2s cold | ~1.5s | ~500MB | ~274MB | No | No |
| **Ollama** (keep_alive=0) | ~2s always | ~128s | ~0 | ~274MB | No | No |
| **Gemini API** | ~200ms | ~500ms | ~0 | ~0 | No | Always |
| **sentence-transformers** | ~30ms | ~800ms | ~1.2GB | ~2GB | No | First download |

---

## Rollback Strategy

| Phase | Rollback Method | Risk |
|-------|----------------|------|
| Phase 1 | Delete `embedding/` package | Zero — pure additive |
| Phase 2 | Revert 3 modified files | Low — old code paths restored |
| Phase 3 | New columns harmless, can remain | Very low — ALTER TABLE ADD COLUMN is metadata-only |
| Phase 4 | Revert config changes; empty `embedding` dict is ignored | Low |
| Phase 5 | Re-add sentence-transformers; revert peripheral scripts | Low |
| **Full** | Remove `embedding/` + revert 9 files. DB columns harmless. | Low |
