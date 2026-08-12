# Local In-Process Embedding Alternatives for Synapse-OSS

**Researched:** 2026-04-02
**Objective:** Replace mandatory Ollama dependency for embeddings with a zero-config, in-process default while keeping 768-dim nomic-embed-text quality.
**Overall Confidence:** HIGH (multiple sources corroborated, official docs verified)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Solution 1: FastEmbed (Recommended Default)](#solution-1-fastembed-recommended-default)
4. [Solution 2: sentence-transformers (Enhanced)](#solution-2-sentence-transformers-enhanced)
5. [Solution 3: ONNX Runtime Direct](#solution-3-onnx-runtime-direct)
6. [Solution 4: llama-cpp-python](#solution-4-llama-cpp-python)
7. [Solution 5: Model2Vec (Ultra-Lightweight)](#solution-5-model2vec-ultra-lightweight)
8. [Solution 6: EmbeddingGemma-300M (New Contender)](#solution-6-embeddinggemma-300m-new-contender)
9. [Architecture Patterns](#architecture-patterns)
10. [Dimension Compatibility Strategy](#dimension-compatibility-strategy)
11. [Zero-Config Default Design](#zero-config-default-design)
12. [Provider Comparison Matrix](#provider-comparison-matrix)
13. [Recommendation](#recommendation)

---

## Executive Summary

**The answer is FastEmbed as the recommended zero-config default**, with Ollama as an optional power-user backend. FastEmbed delivers the same nomic-embed-text-v1.5 model at 768 dimensions via ONNX Runtime, requires no external process, auto-downloads a ~130MB quantized model on first run, uses ~300MB RAM during inference, and works cross-platform out of the box. It avoids the ~900MB PyTorch dependency entirely.

The fallback chain should be: **Ollama (if running) -> FastEmbed (default) -> sentence-transformers ONNX backend (if already installed) -> FTS-only (last resort)**.

---

## Current State Analysis

### What exists in the codebase today

From `memory_engine.py` (lines 73-83, 156-173):
- **Primary:** `ollama.embeddings(model="nomic-embed-text", prompt=text)` -- HTTP call to localhost:11434
- **Fallback:** `sentence-transformers` with `all-MiniLM-L6-v2` (384-dim) -- **dimension mismatch with 768-dim vec_items table**
- **Vector store:** `vec_items` virtual table created with `embedding float[768]` (db.py line 108)
- **Qdrant:** Also stores 768-dim vectors

From `retriever.py` (lines 39-72):
- Same cascade: Ollama -> sentence-transformers -> FTS-only
- The 384-dim fallback silently produces garbage results against 768-dim stored vectors (cosine similarity on mismatched dimensions is mathematically wrong)

### Core problems

1. **Ollama is mandatory for meaningful semantic search** -- without it, the 384-dim fallback corrupts retrieval quality
2. **Ollama is a separate process** that must be installed, started, and consumes ~500MB+ RAM even idle
3. **Cross-platform friction** -- Ollama install differs on Windows/macOS/Linux, requires admin rights on some systems
4. **The current fallback is broken** -- 384-dim vectors searched against 768-dim index gives nonsense results

---

## Solution 1: FastEmbed (Recommended Default)

**Confidence: HIGH** (verified via PyPI, official docs, HuggingFace model cards)

### Overview

FastEmbed is Qdrant's lightweight embedding library. It uses ONNX Runtime under the hood -- no PyTorch required. It ships quantized model weights and auto-downloads them on first use.

### Key Facts

| Property | Value | Source |
|----------|-------|--------|
| Package | `pip install fastembed` | [PyPI](https://pypi.org/project/fastembed/) |
| Latest version | 0.8.0 (March 2026) | PyPI |
| Python support | 3.10, 3.11, 3.12, 3.13, 3.14 | PyPI |
| Package wheel size | 116.6 KB | PyPI |
| Core dependency | `onnxruntime` (~13-17 MB wheel) | fastembed deps |
| Other deps | `tokenizers`, `huggingface-hub`, `numpy`, `tqdm`, `loguru`, `mmh3` | GitHub |
| **No PyTorch** | Correct -- ONNX Runtime only | Verified |

### nomic-embed-text-v1.5 Support

**YES -- fully supported.** FastEmbed includes `nomic-ai/nomic-embed-text-v1.5` in its model catalog.

| Model variant | Dimensions | Model size | Notes |
|---------------|-----------|------------|-------|
| `nomic-ai/nomic-embed-text-v1.5` | 768 | ~547 MB (FP32 ONNX) | Full precision |
| `nomic-ai/nomic-embed-text-v1.5-Q` | 768 | ~130 MB (quantized) | **Recommended** -- INT8 quantized |

The quantized variant (`-Q` suffix) is the key advantage: 130MB download, ~300MB RAM during inference, minimal quality loss (<1% on MTEB).

**Source:** [FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/), [Qdrant FastEmbed docs](https://qdrant.tech/articles/fastembed/)

### Usage Code

```python
from fastembed import TextEmbedding

# First call downloads ~130MB model to cache (FASTEMBED_CACHE_PATH or temp dir)
model = TextEmbedding("nomic-ai/nomic-embed-text-v1.5-Q")

# Single text
embeddings = list(model.embed(["search_query: What is Synapse?"]))
# -> list of numpy arrays, each 768-dim

# Batch (returns generator)
docs = ["search_document: doc1", "search_document: doc2"]
embeddings = list(model.embed(docs, batch_size=32))
```

**Important:** nomic-embed-text requires task prefixes (`search_query:`, `search_document:`, `clustering:`, `classification:`). This is true across ALL backends (Ollama, FastEmbed, sentence-transformers). The current Synapse code does NOT add these prefixes -- this should be fixed regardless of backend choice.

### Matryoshka Dimension Truncation

FastEmbed supports Matryoshka truncation for nomic-embed-text-v1.5. You can request any dimension from 64 to 768. However, truncation happens post-inference (slice the vector), so inference cost is the same regardless of output dimension.

### Async Compatibility

**FastEmbed is CPU-bound and WILL block the asyncio event loop** if called directly in an async function. This is true for ALL in-process embedding solutions.

**Solution:** Use `asyncio.get_event_loop().run_in_executor(None, ...)` to run embedding in a thread pool:

```python
import asyncio
from functools import partial

async def get_embedding_async(text: str) -> list[float]:
    loop = asyncio.get_event_loop()
    embeddings = await loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        lambda: list(model.embed([f"search_query: {text}"]))[0].tolist()
    )
    return embeddings
```

### Cross-Platform Wheel Availability

| Platform | onnxruntime wheel | Status |
|----------|-------------------|--------|
| Windows x64 | `win_amd64` ~13.2 MB | Available |
| macOS Intel | `macosx_10_15_x86_64` ~17 MB | Available |
| macOS Apple Silicon | `macosx_14_0_arm64` ~17.3 MB | Available (official since ORT 1.16+) |
| Linux x64 | `manylinux_2_27_x86_64` ~17.2 MB | Available |
| Linux ARM64 | `manylinux_2_17_aarch64` ~15.2 MB | Available |

**Source:** [onnxruntime PyPI](https://pypi.org/project/onnxruntime/) (version 1.24.4, March 2026)

All target platforms have prebuilt wheels. No compilation needed.

### Performance Estimates

| Metric | Estimate | Confidence |
|--------|----------|------------|
| Cold start (first use, model cached) | 2-4 seconds | MEDIUM (based on ONNX model load times for ~130MB) |
| First-ever run (download + load) | 30-90 seconds (network dependent) | MEDIUM |
| Warm inference (single text) | 15-40ms on modern CPU | MEDIUM (based on ONNX embedding benchmarks) |
| Batch inference (32 texts) | 200-500ms on modern CPU | MEDIUM |
| RAM during inference | ~300-400 MB | MEDIUM (model size + runtime overhead) |
| RAM idle (model loaded) | ~200-300 MB | MEDIUM |

**Caveat on Apple Silicon performance:** There is an open issue ([#535](https://github.com/qdrant/fastembed/issues/535)) reporting FastEmbed being slower than sentence-transformers on M2 Max. This appears to be related to ONNX Runtime not fully utilizing Apple's Accelerate framework vs PyTorch's MPS backend. For most use cases (single-text embedding in a chat pipeline), this difference is negligible (30ms vs 20ms).

### Quantized Model Variants

FastEmbed ships models with INT8 quantization by default (the `-Q` variants). The quantization is done during model preparation, not at inference time. This provides:
- 4x smaller model files vs FP32
- ~2-3x faster inference on CPU
- <1% accuracy loss on MTEB benchmarks

### Total Install Footprint

| Component | Size |
|-----------|------|
| `fastembed` wheel | 117 KB |
| `onnxruntime` wheel | ~17 MB |
| `tokenizers` wheel | ~7 MB |
| Other deps (numpy, etc.) | ~30 MB (likely already installed) |
| **Total pip install** | **~55 MB** (new deps only) |
| Model download (first run) | **~130 MB** |
| **Grand total** | **~185 MB** |

Compare to sentence-transformers: PyTorch CPU-only (~200 MB) + transformers (~50 MB) + sentence-transformers (~10 MB) + model (~547 MB FP32) = **~800+ MB**.

---

## Solution 2: sentence-transformers (Enhanced)

**Confidence: HIGH** (official docs verified)

### Best 768-dim Models for Retrieval

| Model | MTEB Score | Dims | Params | Notes |
|-------|-----------|------|--------|-------|
| `nomic-ai/nomic-embed-text-v1.5` | 62.28 | 768 | 137M | Matryoshka, 8192 context |
| `nomic-ai/modernbert-embed-base` | ~63 | 768 | 149M | Based on ModernBERT |
| `BAAI/bge-base-en-v1.5` | 63.55 | 768 | 109M | Widely used |
| `nomic-ai/nomic-embed-text-v2-moe` | ~64 | 768 | 305M MoE | Newer, heavier |

**Source:** [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard), [HuggingFace model cards](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)

### Loading nomic-embed-text-v1.5 Directly

**YES, sentence-transformers can load this model directly:**

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
embeddings = model.encode(["search_query: What is Synapse?"])
# -> numpy array, 768-dim
```

**Note:** `trust_remote_code=True` is required because nomic-embed-text uses custom modeling code (rotary embeddings). There is an open discussion about upstreaming this to transformers to remove this requirement.

**Source:** [HuggingFace nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)

### ONNX Backend (since sentence-transformers v3.x)

sentence-transformers v3.2.0+ supports ONNX and OpenVINO backends natively:

```python
from sentence_transformers import SentenceTransformer

# Install: pip install sentence-transformers[onnx]
model = SentenceTransformer(
    "nomic-ai/nomic-embed-text-v1.5",
    backend="onnx",
    trust_remote_code=True,
)
```

Performance improvements with ONNX backend:
- **FP32 ONNX:** ~1.4x speedup over PyTorch on CPU
- **INT8 quantized ONNX:** ~3x speedup over PyTorch on CPU

**Source:** [Sentence Transformers Efficiency Docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)

### Reducing the PyTorch Dependency

| Install method | Total size (approx) |
|---------------|---------------------|
| Default `pip install sentence-transformers` | ~900 MB (PyTorch GPU-capable) |
| `pip install torch --index-url https://download.pytorch.org/whl/cpu` first | ~200 MB (CPU-only PyTorch) |
| `pip install sentence-transformers[onnx]` (uses ONNX instead of PyTorch for inference) | Still needs PyTorch for model loading, but inference is ONNX |
| **Practical minimum** | **~300-400 MB** with CPU-only torch |

**Key issue:** Even with the ONNX backend, sentence-transformers still depends on `torch` and `transformers` for model loading and conversion. You cannot fully eliminate PyTorch from the dependency chain. This is the fundamental disadvantage vs FastEmbed.

**Source:** [sentence-transformers installation](https://sbert.net/docs/installation.html), [Issue #1409](https://github.com/UKPLab/sentence-transformers/issues/1409)

### RAM Footprint

| Model | FP32 RAM | FP16 RAM | INT8 ONNX RAM |
|-------|----------|----------|---------------|
| nomic-embed-text-v1.5 (137M params) | ~550 MB | ~275 MB | ~200 MB |
| all-MiniLM-L6-v2 (33M params) | ~130 MB | ~65 MB | ~50 MB |

**Source:** [HuggingFace automated memory requirements](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15)

### Async Compatibility

Same as FastEmbed -- CPU-bound, must use `run_in_executor`. The `encode()` method is synchronous.

---

## Solution 3: ONNX Runtime Direct

**Confidence: MEDIUM** (verified via HuggingFace discussions, code examples exist but more manual)

### Overview

Run the ONNX model file directly with `onnxruntime` + `tokenizers` -- no wrapper library needed. Most control, least magic, most code to write.

### Minimum Install

```bash
pip install onnxruntime tokenizers numpy huggingface-hub
# Total: ~60 MB of wheels
```

No PyTorch, no sentence-transformers, no FastEmbed.

### ONNX Model Files Available

From the `nomic-ai/nomic-embed-text-v1.5` HuggingFace repo (`onnx/` directory):

| File | Size | Notes |
|------|------|-------|
| `model.onnx` | 547 MB | FP32 |
| `model_fp16.onnx` | 274 MB | FP16 |
| `model_int8.onnx` | 137 MB | INT8 quantized -- **recommended** |
| `model_bnb4.onnx` | 158 MB | 4-bit quantized |

**Source:** [HuggingFace nomic-embed-text-v1.5 onnx directory](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/tree/main/onnx)

### Implementation Complexity

Approximately 60-80 lines of Python to implement:

```python
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from huggingface_hub import hf_hub_download

class ONNXEmbedder:
    def __init__(self, model_id="nomic-ai/nomic-embed-text-v1.5"):
        # Download and cache model
        model_path = hf_hub_download(model_id, "onnx/model_int8.onnx")
        tokenizer_path = hf_hub_download(model_id, "tokenizer.json")
        
        self.session = ort.InferenceSession(model_path)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=8192)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
    
    def embed(self, texts: list[str]) -> np.ndarray:
        encoded = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        
        outputs = self.session.run(
            None,
            {"input_ids": input_ids, "attention_mask": attention_mask}
        )
        
        # Mean pooling
        token_embeddings = outputs[0]  # (batch, seq_len, 768)
        mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.sum(mask_expanded, axis=1)
        embeddings = summed / counts
        
        # L2 normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / norms
```

**Caveat:** This is a simplified example. The actual nomic-embed-text-v1.5 model may require specific handling for the rotary position embeddings and the `bert-base-uncased` tokenizer with `model_max_length=8192`. The tokenizer configuration needs verification. FastEmbed handles all of this automatically.

### Trade-offs

| Pro | Con |
|-----|-----|
| Minimal dependencies | Must handle tokenizer config manually |
| Full control over inference | Must implement mean pooling, normalization |
| Smallest possible install | No model catalog or version management |
| Can pick exact quantization | Must handle model caching yourself (or use huggingface-hub) |

### When to choose this

Only if you need absolute minimum dependency footprint AND are willing to maintain the embedding code yourself. For Synapse-OSS, FastEmbed is a better choice because it handles all the model-specific details automatically.

---

## Solution 4: llama-cpp-python

**Confidence: MEDIUM** (GGUF models exist, but Python API maturity for embeddings is still evolving)

### Overview

Run the SAME model as Ollama (nomic-embed-text GGUF format) in-process via llama-cpp-python, without needing the Ollama server.

### GGUF Model Sizes (nomic-embed-text-v1.5)

| Quantization | File Size | Quality Impact |
|-------------|-----------|---------------|
| Q2_K | 49.4 MB | Significant degradation |
| Q4_K_M | 84.1 MB | Minimal for retrieval |
| Q5_K_M | 99.6 MB | Negligible |
| Q6_K | 113 MB | Near-lossless |
| Q8_0 | 146 MB | Essentially lossless |
| F16 | 274 MB | Full precision |
| F32 | 548 MB | Full precision |

**Source:** [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF)

### Usage Code

```python
from llama_cpp import Llama

# Load model with embedding=True
llm = Llama(
    model_path="nomic-embed-text-v1.5.Q8_0.gguf",
    embedding=True,
    n_ctx=8192,
    verbose=False,
)

# Create embedding
result = llm.create_embedding("search_query: What is Synapse?")
embedding = result["data"][0]["embedding"]  # 768-dim list
```

### Cross-Platform Issues

| Platform | Status | Notes |
|----------|--------|-------|
| Linux x64 | Works | Prebuilt wheels available |
| macOS Apple Silicon | Works | Metal GPU acceleration available |
| macOS Intel | Works | |
| **Windows x64** | **Friction** | Often requires Visual Studio Build Tools for compilation; prebuilt wheels sometimes lag behind |
| Linux ARM64 | Works | |

**This is the major downside of llama-cpp-python:** Windows compilation is unreliable. Users frequently report build failures on Windows. While prebuilt wheels exist, they sometimes don't cover all Python versions or are delayed.

**Source:** [llama-cpp-python GitHub Issues](https://github.com/abetlen/llama-cpp-python/issues/1189), [llama.cpp Discussions](https://github.com/ggml-org/llama.cpp/discussions/7712)

### RAM Usage

For Q8_0 quantization: ~200-250 MB RAM during inference (model + context buffer). This is comparable to FastEmbed.

### Async Compatibility

llama-cpp-python has an async server mode but `create_embedding()` itself is synchronous and CPU-bound. Needs `run_in_executor`.

### Trade-offs

| Pro | Con |
|-----|-----|
| Same model format as Ollama | Windows build issues |
| Very small quantized models (Q4_K_M = 84 MB) | Heavier package (~100 MB+ compiled) |
| GPU acceleration via Metal/CUDA | API maturity for embeddings still evolving |
| Users can share models with Ollama | Model download/management is manual |

### When to choose this

Best for users who already have llama-cpp-python installed for LLM inference and want to reuse the same model format. NOT recommended as the zero-config default due to Windows compilation friction.

---

## Solution 5: Model2Vec (Ultra-Lightweight)

**Confidence: HIGH** (verified via GitHub, HuggingFace, MTEB benchmarks)

### Overview

Model2Vec creates "static embeddings" -- essentially a lookup table approach that runs 50-500x faster than transformer models. The trade-off is lower quality.

### Key Models

| Model | Params | Dims | MTEB Score | Retrieval Score | Model Size |
|-------|--------|------|-----------|----------------|------------|
| `minishlab/potion-base-8M` | 7.6M | 256 | ~46 | ~30 | ~30 MB |
| `minishlab/potion-base-32M` | 32M | 256 | 51.66 | ~33 | ~120 MB |
| `minishlab/potion-retrieval-32M` | 32M | 256 | 49.76 | 36.35 | ~120 MB |

For comparison:
- `all-MiniLM-L6-v2`: MTEB 56.26, retrieval 41.95
- `nomic-embed-text-v1.5`: MTEB 62.28 (no specific retrieval sub-score published, but significantly better)

**potion-retrieval-32M achieves 86.65% of all-MiniLM-L6-v2's retrieval quality** -- and all-MiniLM-L6-v2 already has a significant gap vs nomic-embed-text-v1.5.

**Source:** [Model2Vec Results](https://github.com/MinishLab/model2vec/blob/main/results/README.md), [potion-retrieval-32M HuggingFace](https://huggingface.co/minishlab/potion-retrieval-32M)

### Performance

| Metric | Value |
|--------|-------|
| Install | `pip install model2vec` (~5 MB) |
| Model download | ~30-120 MB |
| RAM usage | ~30-120 MB |
| Inference latency | **<1ms per text** (static lookup) |
| Cold start | <1 second |

### Quality Trade-off for RAG

The 256-dim output and lower retrieval scores make this unsuitable as a primary embedding for Synapse's RAG system. The quality gap is too large for a personal assistant that needs to retrieve specific memories accurately.

**However**, it could serve as a "quick mode" for:
- Low-resource machines (Raspberry Pi, 4GB RAM)
- Initial keyword-level filtering before a heavier model re-ranks
- Real-time typing suggestions where latency matters more than recall

### Dimension Mismatch

256 dims vs 768-dim vector store = **incompatible**. Cannot be mixed with nomic-embed-text vectors. Would need a separate index or re-embedding of all data.

### Verdict

**Not suitable as a default.** Could be a future "lightweight mode" option but adds complexity without solving the primary problem.

---

## Solution 6: EmbeddingGemma-300M (New Contender)

**Confidence: MEDIUM** (released Sept 2025 by Google, still relatively new)

### Overview

Google's EmbeddingGemma-300M is a 308M parameter model derived from Gemma 3, designed for on-device deployment. It outputs 768 dimensions with Matryoshka support (512, 256, 128).

### Key Facts

| Property | Value |
|----------|-------|
| Params | 308M |
| Dimensions | 768 (default), 512, 256, 128 |
| MTEB score | ~65+ (best sub-500M model) |
| Model size | ~600 MB FP32, ~150 MB quantized |
| ONNX available | Yes ([onnx-community/embeddinggemma-300m-ONNX](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX)) |
| GGUF available | Yes ([unsloth/embeddinggemma-300m-GGUF](https://huggingface.co/unsloth/embeddinggemma-300m-GGUF)) |

**Source:** [Google Developers Blog](https://developers.googleblog.com/introducing-embeddinggemma/), [HuggingFace](https://huggingface.co/google/embeddinggemma-300m)

### Why Not Recommended (Yet)

1. **Not in FastEmbed's model catalog** (as of March 2026 -- may change)
2. **Requires special transformers version:** `pip install git+https://github.com/huggingface/transformers@v4.56.0-Embedding-Gemma-preview` -- not stable yet
3. **308M params = ~2x the RAM** of nomic-embed-text-v1.5 (137M params) -- marginal on 8GB machines
4. **New model = less community testing** for edge cases

### Future Consideration

Once EmbeddingGemma lands in a stable transformers release and FastEmbed adds it, it could become the recommended default due to superior MTEB scores. Monitor this.

---

## Architecture Patterns

### How Other Projects Handle Multi-Backend Embeddings

#### ChromaDB Default Embedder
ChromaDB ships `all-MiniLM-L6-v2` running on ONNX Runtime as its default embedding function. No API key required, no external process, auto-downloads on first use. This is exactly the pattern Synapse should follow, but with `nomic-embed-text-v1.5` (768-dim) instead of MiniLM (384-dim).

**Source:** [ChromaDB Embedding Functions](https://docs.trychroma.com/docs/embeddings/embedding-functions)

#### LlamaIndex Embedding Abstraction
LlamaIndex provides `BaseEmbedding` with subclasses like `HuggingFaceEmbedding`, `FastEmbedEmbedding`, `OpenAIEmbedding`. Key design: the base class defines `_get_text_embedding(text)` and `_get_text_embeddings(texts)` as abstract methods. Each provider implements these.

LlamaIndex also supports passing `backend="onnx"` to `HuggingFaceEmbedding` for ONNX acceleration.

**Source:** [LlamaIndex Embeddings](https://developers.llamaindex.ai/python/framework/module_guides/models/embeddings/)

#### LangChain Embedding Abstraction
LangChain's `Embeddings` base class (in `langchain_core`) defines two methods:
- `embed_documents(texts: List[str]) -> List[List[float]]`
- `embed_query(text: str) -> List[float]`

The separation between document and query embedding is important -- nomic-embed-text uses different prefixes for documents vs queries. Synapse's abstraction should mirror this.

**Source:** [LangChain Embeddings](https://python.langchain.com/api_reference/core/embeddings/langchain_core.embeddings.embeddings.Embeddings.html)

### Recommended Abstraction for Synapse

```python
from abc import ABC, abstractmethod
from enum import Enum

class EmbeddingTask(Enum):
    SEARCH_QUERY = "search_query"
    SEARCH_DOCUMENT = "search_document"
    CLUSTERING = "clustering"
    CLASSIFICATION = "classification"

class EmbeddingProvider(ABC):
    """Base class for all embedding providers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
    
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Output embedding dimensions."""
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier for metadata tracking."""
    
    @abstractmethod
    def embed_texts(
        self,
        texts: list[str],
        task: EmbeddingTask = EmbeddingTask.SEARCH_DOCUMENT,
    ) -> list[list[float]]:
        """Embed a batch of texts. Synchronous -- caller wraps in executor."""
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query. Convenience method."""
        return self.embed_texts([text], task=EmbeddingTask.SEARCH_QUERY)[0]
    
    def embed_document(self, text: str) -> list[float]:
        """Embed a single document. Convenience method."""
        return self.embed_texts([text], task=EmbeddingTask.SEARCH_DOCUMENT)[0]

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider can be used (deps installed, model accessible)."""
```

### Provider Implementations (Skeleton)

```python
class FastEmbedProvider(EmbeddingProvider):
    """Recommended default. ONNX-based, no PyTorch needed."""
    name = "fastembed"
    dimensions = 768
    model_name = "nomic-ai/nomic-embed-text-v1.5-Q"
    
    def __init__(self):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(self.model_name)
    
    def embed_texts(self, texts, task=EmbeddingTask.SEARCH_DOCUMENT):
        prefixed = [f"{task.value}: {t}" for t in texts]
        return [e.tolist() for e in self._model.embed(prefixed)]
    
    def is_available(self):
        try:
            import fastembed
            return True
        except ImportError:
            return False


class OllamaProvider(EmbeddingProvider):
    """Uses running Ollama server. Best quality, requires external process."""
    name = "ollama"
    dimensions = 768
    model_name = "nomic-embed-text"
    
    def embed_texts(self, texts, task=EmbeddingTask.SEARCH_DOCUMENT):
        import ollama
        results = []
        for text in texts:
            resp = ollama.embeddings(model=self.model_name, prompt=f"{task.value}: {text}")
            results.append(resp["embedding"])
        return results
    
    def is_available(self):
        try:
            import ollama
            ollama.embeddings(model=self.model_name, prompt="test", keep_alive="0")
            return True
        except Exception:
            return False


class SentenceTransformerProvider(EmbeddingProvider):
    """Falls back to sentence-transformers if already installed."""
    name = "sentence-transformers"
    dimensions = 768
    model_name = "nomic-ai/nomic-embed-text-v1.5"
    
    def embed_texts(self, texts, task=EmbeddingTask.SEARCH_DOCUMENT):
        import torch.nn.functional as F
        prefixed = [f"{task.value}: {t}" for t in texts]
        embeddings = self._model.encode(prefixed, convert_to_tensor=True)
        embeddings = F.layer_norm(embeddings, normalized_shape=(embeddings.shape[1],))
        embeddings = F.normalize(embeddings, p=2, dim=1)
        return embeddings.tolist()
    
    def is_available(self):
        try:
            from sentence_transformers import SentenceTransformer
            return True
        except ImportError:
            return False
```

### Provider Resolution Order

```python
def resolve_embedding_provider(config: dict) -> EmbeddingProvider:
    """
    Resolve the best available embedding provider.
    
    Priority:
    1. User-configured provider (from synapse.json)
    2. Ollama (if running -- best quality, same as existing behavior)
    3. FastEmbed (lightweight default -- ONNX, no PyTorch)
    4. sentence-transformers (if already installed)
    5. None (FTS-only fallback with warning)
    """
    configured = config.get("embedding_provider")
    
    if configured == "ollama":
        provider = OllamaProvider()
        if provider.is_available():
            return provider
        print("[WARN] Ollama configured but not available, falling through...")
    
    if configured == "fastembed" or configured is None:
        provider = FastEmbedProvider()
        if provider.is_available():
            return provider
    
    # Try Ollama if not explicitly configured away
    if configured is None:
        provider = OllamaProvider()
        if provider.is_available():
            return provider
    
    # Fallback
    provider = SentenceTransformerProvider()
    if provider.is_available():
        return provider
    
    print("[WARN] No embedding provider available. Semantic search disabled.")
    return None
```

---

## Dimension Compatibility Strategy

### The Problem

The current vector store (`vec_items`) and Qdrant collection both use 768-dim vectors. If a new provider produces different dimensions, everything breaks.

### Strategy: Standardize on 768

**All providers MUST output 768 dimensions.** This is non-negotiable for compatibility with existing data.

| Provider | Native dims | How to get 768 |
|----------|------------|-----------------|
| Ollama (nomic-embed-text) | 768 | Native |
| FastEmbed (nomic-v1.5-Q) | 768 | Native |
| sentence-transformers (nomic-v1.5) | 768 | Native |
| ONNX direct (nomic-v1.5) | 768 | Native |
| llama-cpp-python (nomic-v1.5 GGUF) | 768 | Native |
| sentence-transformers (all-MiniLM-L6-v2) | 384 | **CANNOT be used** -- zero-padding to 768 produces garbage cosine similarity |
| Model2Vec (potion-*) | 256 | **CANNOT be used** -- too different |

### Why Zero-Padding Does Not Work

Zero-padding a 384-dim vector to 768-dim and computing cosine similarity against a native 768-dim vector will:
1. Artificially reduce the cosine similarity (the zeros contribute nothing to the dot product but inflate the norm)
2. Distort the geometric relationships between vectors
3. Produce systematically lower scores that don't rank correctly against native vectors

**The correct approach is to re-embed all data when switching models, or ensure all providers use the same model family (nomic-embed-text-v1.5).**

### Matryoshka Truncation for Future Flexibility

nomic-embed-text-v1.5 supports Matryoshka dimensions: 768, 512, 256, 128, 64. If storage becomes a concern, all providers could be configured to truncate to 512 or 256 -- but this requires:
1. Re-embedding all existing data
2. Recreating the `vec_items` table with the new dimension
3. Recreating the Qdrant collection

**Recommendation:** Stay at 768 for now. Add a `target_dimensions` config option for future use.

### Model Name Tracking

**YES, the system should store the embedding model name per-vector.** This enables:
- Detecting when stored vectors were embedded with a different model
- Triggering re-embedding during model migration
- Auditing embedding quality

Proposed schema addition:
```sql
ALTER TABLE documents ADD COLUMN embedding_model TEXT DEFAULT 'nomic-embed-text';
```

---

## Zero-Config Default Design

### What Happens: `pip install synapse-oss && synapse start` (No Ollama)

**Recommended flow:**

1. `synapse start` boots the FastAPI gateway
2. Gateway calls `resolve_embedding_provider(config)`
3. Ollama check fails (not running)
4. FastEmbed check succeeds (`fastembed` is a declared dependency)
5. First embedding call triggers model download:
   ```
   [INFO] Downloading nomic-embed-text-v1.5-Q (130 MB)... first time only
   ```
6. Model cached at `~/.synapse/models/fastembed/` (or `FASTEMBED_CACHE_PATH`)
7. Subsequent calls use cached model -- 2-4s cold start, then 15-40ms per text

### First-Run Experience

| Step | Time | Notes |
|------|------|-------|
| `pip install synapse-oss` | ~30s | Includes fastembed + onnxruntime (~55 MB new deps) |
| First `synapse start` | ~5s | Normal boot |
| First embedding (triggers download) | 30-90s | Downloads ~130 MB model, one-time |
| First embedding (model load) | 2-4s | ONNX session initialization |
| Subsequent embeddings | 15-40ms | Warm inference |

### Configuration in synapse.json

```json
{
  "embedding": {
    "provider": "auto",
    "model": "nomic-ai/nomic-embed-text-v1.5-Q",
    "dimensions": 768,
    "cache_dir": null,
    "task_prefixes": true
  }
}
```

Where `"provider": "auto"` means: Ollama if running, else FastEmbed, else sentence-transformers.

Users can override: `"provider": "ollama"` to force Ollama, or `"provider": "fastembed"` to skip the Ollama check.

---

## Provider Comparison Matrix

### Installation

| Provider | pip install | Total wheel size | PyTorch needed | Model auto-download |
|----------|------------|-----------------|----------------|---------------------|
| FastEmbed | `fastembed` | ~55 MB | No | Yes |
| sentence-transformers | `sentence-transformers` | ~300-900 MB | Yes (CPU: ~200 MB) | Yes |
| ONNX Direct | `onnxruntime tokenizers huggingface-hub` | ~60 MB | No | Manual (huggingface-hub helps) |
| llama-cpp-python | `llama-cpp-python` | ~100 MB+ | No | Manual (download GGUF) |
| Model2Vec | `model2vec` | ~5 MB | No | Yes |

### Runtime

| Provider | Model download | Cold start | Warm latency (1 text) | Batch (32 texts) | RAM (loaded) |
|----------|---------------|------------|----------------------|-------------------|--------------|
| FastEmbed (nomic-v1.5-Q) | 130 MB | 2-4s | 15-40ms | 200-500ms | ~300 MB |
| sentence-transformers (nomic-v1.5 FP32) | 547 MB | 5-10s | 20-50ms | 300-800ms | ~550 MB |
| sentence-transformers (nomic-v1.5 ONNX INT8) | ~137 MB | 3-5s | 10-30ms | 150-400ms | ~250 MB |
| ONNX Direct (nomic-v1.5 INT8) | 137 MB | 2-4s | 10-30ms | 150-400ms | ~250 MB |
| llama-cpp-python (nomic-v1.5 Q8_0) | 146 MB | 2-5s | 15-40ms | 200-600ms | ~250 MB |
| Ollama (nomic-embed-text) | ~274 MB | N/A (server) | 5-15ms (HTTP overhead) | 50-200ms | ~500 MB (Ollama process) |
| Model2Vec (potion-32M) | 120 MB | <1s | <1ms | <10ms | ~120 MB |

### Quality

| Provider | MTEB Score | Dimensions | Retrieval Quality | Task Prefixes |
|----------|-----------|------------|-------------------|---------------|
| Any nomic-embed-text-v1.5 backend | 62.28 | 768 | High | Required |
| all-MiniLM-L6-v2 | 56.26 | 384 | Medium | Not needed |
| potion-retrieval-32M | 49.76 | 256 | Low-Medium | Not needed |

### Cross-Platform

| Provider | Win x64 | macOS Intel | macOS Apple Silicon | Linux x64 | Linux ARM64 |
|----------|---------|-------------|--------------------|-----------|----|
| FastEmbed | Yes | Yes | Yes | Yes | Yes |
| sentence-transformers | Yes | Yes | Yes | Yes | Yes |
| ONNX Direct | Yes | Yes | Yes | Yes | Yes |
| llama-cpp-python | Friction | Yes | Yes | Yes | Yes |
| Model2Vec | Yes | Yes | Yes | Yes | Yes |

---

## Recommendation

### Tier 1: Default (ship with synapse-oss)

**FastEmbed with `nomic-ai/nomic-embed-text-v1.5-Q`**

- Declare `fastembed` as a dependency in `pyproject.toml` / `requirements.txt`
- Zero-config: auto-downloads model on first use
- Same 768-dim nomic-embed-text quality as Ollama
- ~185 MB total footprint (deps + model)
- No PyTorch, no external process
- Cross-platform: works everywhere

### Tier 2: Power user (optional)

**Ollama** (current behavior, now optional)

- If Ollama is detected running, prefer it (slightly faster due to persistent model, GPU support)
- Add `"embedding.provider": "ollama"` config option
- This path already exists in the codebase

### Tier 3: Fallback (already-installed deps)

**sentence-transformers with nomic-embed-text-v1.5**

- If `sentence-transformers` is already installed (e.g., user has it for other purposes)
- Use ONNX backend if available: `backend="onnx"`
- **Must use nomic-embed-text-v1.5, NOT all-MiniLM-L6-v2** (dimension mismatch)

### Tier 4: Last resort

**FTS-only** (current behavior for no-embedding case)

- Warn loudly: "Semantic search disabled. Install fastembed for best experience."

### What NOT to Recommend

- **llama-cpp-python as default:** Windows build issues make this a bad zero-config choice
- **Model2Vec as primary:** Quality gap too large for personal memory retrieval
- **ONNX Direct as default:** Too much code to maintain vs FastEmbed wrapper
- **EmbeddingGemma-300M:** Too new, not in FastEmbed yet, 2x the RAM

### Migration Path

1. Add `fastembed` to dependencies
2. Implement `EmbeddingProvider` abstraction with FastEmbed, Ollama, and sentence-transformers backends
3. Update `memory_engine.py` and `retriever.py` to use the new abstraction
4. Add task prefix support (`search_query:` / `search_document:`)
5. Add `embedding_model` column to documents table
6. Fix the broken 384-dim fallback (replace with 768-dim FastEmbed)
7. Add config options to `synapse.json`

---

## Sources

### Official Documentation
- [FastEmbed GitHub](https://github.com/qdrant/fastembed)
- [FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/)
- [FastEmbed PyPI](https://pypi.org/project/fastembed/)
- [Qdrant FastEmbed Article](https://qdrant.tech/articles/fastembed/)
- [Sentence Transformers Efficiency Docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
- [Sentence Transformers Installation](https://sbert.net/docs/installation.html)
- [ONNX Runtime PyPI](https://pypi.org/project/onnxruntime/)
- [ONNX Runtime Threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)

### Model Cards
- [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
- [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF)
- [nomic-ai/nomic-embed-text-v1.5 Memory Requirements](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15)
- [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m)
- [minishlab/potion-retrieval-32M](https://huggingface.co/minishlab/potion-retrieval-32M)
- [Model2Vec GitHub](https://github.com/MinishLab/model2vec)

### Community and Ecosystem
- [ChromaDB Embedding Functions](https://docs.trychroma.com/docs/embeddings/embedding-functions)
- [LlamaIndex Embeddings](https://developers.llamaindex.ai/python/framework/module_guides/models/embeddings/)
- [LangChain Embeddings Base Class](https://python.langchain.com/api_reference/core/embeddings/langchain_core.embeddings.embeddings.Embeddings.html)
- [llama-cpp-python Embedding Support Issue](https://github.com/abetlen/llama-cpp-python/issues/1189)
- [FastEmbed M2 Max Performance Issue](https://github.com/qdrant/fastembed/issues/535)
- [Nomic Matryoshka Blog Post](https://www.nomic.ai/blog/posts/nomic-embed-matryoshka)

### Benchmarks and Comparisons
- [BentoML: Best Open-Source Embedding Models 2026](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [Best Embedding Models for RAG 2026](https://blog.premai.io/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/)
- [FastEmbed vs HF Comparison](https://qdrant.github.io/fastembed/examples/FastEmbed_vs_HF_Comparison/)
- [Google EmbeddingGemma Blog](https://developers.googleblog.com/introducing-embeddinggemma/)
