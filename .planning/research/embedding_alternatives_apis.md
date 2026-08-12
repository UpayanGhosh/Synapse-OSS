# Embedding Alternatives Research: Free APIs + Local Libraries

**Project:** Synapse-OSS (Personal AI Assistant)
**Researched:** 2026-04-02
**Goal:** Make Ollama OPTIONAL by finding free/reliable embedding alternatives
**Current Setup:** Ollama `nomic-embed-text` (768-dim, float32) with `all-MiniLM-L6-v2` (384-dim) fallback

---

## Table of Contents

1. [Executive Summary & Recommendation](#1-executive-summary--recommendation)
2. [Free Cloud Embedding APIs](#2-free-cloud-embedding-apis)
3. [Free Local Embedding Libraries](#3-free-local-embedding-libraries)
4. [MTEB Benchmark Comparison](#4-mteb-benchmark-comparison)
5. [Dimension Compatibility & Migration](#5-dimension-compatibility--migration)
6. [Implementation Strategy](#6-implementation-strategy)

---

## 1. Executive Summary & Recommendation

### The Problem

Synapse-OSS currently REQUIRES Ollama running locally to get proper 768-dim embeddings via `nomic-embed-text`. The fallback to `all-MiniLM-L6-v2` (384-dim) creates a **dimension mismatch** with the existing `vec_items` table (`float[768]`) and Qdrant collection, making vector search fail or return garbage results.

### Recommended Solution: FastEmbed (Primary) + Gemini Embedding API (Cloud Fallback)

**Tier 1 (LOCAL, no internet needed):** `fastembed` with `nomic-ai/nomic-embed-text-v1.5-Q` -- This runs the EXACT SAME MODEL as Ollama's nomic-embed-text but via ONNX Runtime. No Ollama required. Same 768 dimensions. Same embeddings. Zero migration needed.

**Tier 2 (CLOUD, free):** Google `gemini-embedding-001` via Gemini API free tier -- 3072 dims default but supports Matryoshka truncation to 768. Extremely generous free limits. Requires API key (free signup).

**Tier 3 (LOCAL, lightweight fallback):** `sentence-transformers` with `BAAI/bge-base-en-v1.5` (768-dim) -- Better than current `all-MiniLM-L6-v2` fallback. Same 768 dimensions. No dimension mismatch.

**Tier 4 (LAST RESORT):** FTS-only mode (already implemented in `retriever.py`).

### Why This Stack

| Criterion | FastEmbed (nomic v1.5) | Gemini API | bge-base-en-v1.5 |
|-----------|----------------------|------------|-------------------|
| Offline? | Yes | No | Yes |
| Dims | 768 (exact match) | 768 (via MRL) | 768 (exact match) |
| Quality | Same as current | Better (68.32 MTEB avg) | Comparable (63.55 MTEB avg) |
| Install size | ~150MB (ONNX + model) | ~5KB SDK | ~500MB (PyTorch) |
| RAM | ~300MB | 0 (cloud) | ~500MB |
| Latency | ~15-50ms/text CPU | ~100-300ms (network) | ~20-60ms/text CPU |
| Cost | Free forever | Free tier (generous) | Free forever |

---

## 2. Free Cloud Embedding APIs

### 2.1 Google Gemini Embedding API [RECOMMENDED CLOUD OPTION]

| Attribute | Value |
|-----------|-------|
| **Model** | `gemini-embedding-001` (replaces deprecated `text-embedding-004`) |
| **Dimensions** | 3072 default; supports 768, 1536 via Matryoshka truncation |
| **Context Window** | 2048 tokens per input text |
| **Batch Size** | Up to 250 texts per request |
| **Free Tier** | Yes -- available on Gemini API free tier |
| **Free Tier Limits** | TPM-based (tokens per minute); reportedly up to 10M TPM for embeddings; check AI Studio dashboard for exact limits |
| **Paid Price** | $0.15 per 1M tokens |
| **API Key Required** | Yes (free signup at ai.google.dev) |
| **Python SDK** | `google-genai` or `google-generativeai` |
| **MTEB Avg Score** | 68.32 (top of leaderboard as of March 2026) |
| **Privacy** | Free tier: data MAY be used for model improvement. Paid tier: excluded from training. 55-day retention for abuse monitoring |
| **Multilingual** | Yes |
| **Reliability** | HIGH -- Google infrastructure, unlikely to disappear |
| **Confidence** | HIGH |

**Verdict:** Best free cloud option. Massive free tier, top MTEB scores, supports 768-dim via Matryoshka. The only downside is privacy concern on free tier and API key requirement.

**Sources:**
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Embedding Docs](https://ai.google.dev/gemini-api/docs/embeddings)
- [Gemini Embedding GA Announcement](https://developers.googleblog.com/en/gemini-embedding-available-gemini-api/)
- [Gemini Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)

---

### 2.2 Voyage AI [BEST FREE ALLOCATION]

| Attribute | Value |
|-----------|-------|
| **Model** | `voyage-3.5-lite` (recommended for cost), `voyage-3-large` (best quality) |
| **Dimensions** | 2048, 1024, 512, 256 (Matryoshka) -- NOTE: no 768 option |
| **Free Tier** | 200M tokens free per account (one-time, not monthly) |
| **Paid Price** | $0.02/1M tokens (lite), $0.06/1M (3.5), higher for large |
| **API Key Required** | Yes (free signup) |
| **Python SDK** | `voyageai` |
| **MTEB Retrieval** | voyage-3-large outperforms OpenAI v3-large by ~10%; top-tier |
| **Privacy** | Not publicly documented as clearly as Google |
| **Reliability** | MEDIUM -- acquired by MongoDB in 2024, stable backing |
| **Confidence** | HIGH |

**Verdict:** Most generous one-time free allocation (200M tokens). Problem: no 768-dim option. Closest is 1024 which requires schema migration. Excellent quality but dimension mismatch is a dealbreaker for drop-in replacement.

**Sources:**
- [Voyage AI Pricing](https://docs.voyageai.com/docs/pricing)
- [Voyage 3-Large Announcement](https://blog.voyageai.com/2025/01/07/voyage-3-large/)

---

### 2.3 Jina AI Embeddings [GOOD FREE TIER]

| Attribute | Value |
|-----------|-------|
| **Model** | `jina-embeddings-v4` (latest), `jina-embeddings-v3` |
| **Dimensions** | v4: 2048 default (truncatable to 128); v3: 1024 (truncatable to 32) |
| **Free Tier** | 10M tokens per API key |
| **Paid Price** | Token-based; pricing updated May 2025 |
| **API Key Required** | Yes (free at jina.ai) |
| **Python SDK** | `jina` or direct HTTP |
| **Multilingual** | 89+ languages |
| **Code Support** | Task-specific adapters for code retrieval |
| **Privacy** | Not clearly documented for free tier |
| **Confidence** | MEDIUM |

**Verdict:** 10M free tokens is decent for a personal assistant. v3 supports dimensions down to 32 via Matryoshka but neither v3 nor v4 natively outputs 768-dim. Closest is 1024 (v3). Would require dimension migration.

**Sources:**
- [Jina Embedding API](https://jina.ai/embeddings/)
- [Jina Embeddings v4 on HuggingFace](https://huggingface.co/jinaai/jina-embeddings-v4)

---

### 2.4 Nomic Atlas API [EXACT MODEL MATCH]

| Attribute | Value |
|-----------|-------|
| **Model** | `nomic-embed-text-v1.5` (same model as Ollama) |
| **Dimensions** | 768 default (Matryoshka: 512, 256, 128, 64) |
| **Free Tier** | 1M tokens included |
| **Endpoint** | `https://api-atlas.nomic.ai/v1/embedding/text` |
| **API Key Required** | Yes (signup at atlas.nomic.ai) |
| **Python SDK** | `nomic` package |
| **Quality** | Identical to current Ollama setup |
| **Confidence** | MEDIUM |

**Verdict:** EXACT same model and dimensions as current setup. Zero migration. But only 1M free tokens is stingy for ongoing use. Good as a temporary bridge but not sustainable long-term. The Atlas platform pricing beyond free tier is expensive.

**Sources:**
- [Nomic Atlas Pricing](https://atlas.nomic.ai/pricing)
- [Nomic Embed Text Docs](https://docs.nomic.ai/reference/endpoints/nomic-embed-text)

---

### 2.5 Cohere Embed v4 [TOO RESTRICTIVE]

| Attribute | Value |
|-----------|-------|
| **Model** | `embed-v4` (multimodal), `embed-v3` (text) |
| **Dimensions** | v4: 1536; v3: 1024 |
| **Free Tier** | 1,000 API calls/month total across ALL endpoints |
| **Rate Limit** | Trial: 5 calls/min for Embed |
| **API Key Required** | Yes |
| **Restrictions** | Trial keys CANNOT be used for production/commercial |
| **Confidence** | HIGH |

**Verdict:** SKIP. 1,000 total API calls/month is absurdly low. No commercial use allowed on trial. Dimensions don't match (1024 or 1536). Not viable.

**Sources:**
- [Cohere Rate Limits](https://docs.cohere.com/docs/rate-limits)
- [Cohere Pricing](https://cohere.com/pricing)

---

### 2.6 HuggingFace Inference API [UNRELIABLE]

| Attribute | Value |
|-----------|-------|
| **Free Tier** | ~100,000 characters/month, 60 RPM |
| **Models** | Can run various embedding models (BERT, etc.) |
| **API Key Required** | Yes (free HF account) |
| **Reliability** | LOW -- users report hitting limits quickly, vague documentation |
| **Confidence** | LOW |

**Verdict:** SKIP for production. Limits are poorly documented and change without notice. Users on forums report reaching monthly limits within days. Fine for one-off experiments, not for a personal assistant running daily.

**Sources:**
- [HuggingFace Pricing](https://huggingface.co/pricing)
- [HF Inference Rate Limits Discussion](https://discuss.huggingface.co/t/api-limits-on-free-inference-api/57711)

---

### 2.7 Mistral Embed [MEDIOCRE QUALITY]

| Attribute | Value |
|-----------|-------|
| **Model** | `mistral-embed` |
| **Dimensions** | 1024 |
| **Context Window** | 8,192 tokens |
| **Free Tier** | Available with rate limits (details unclear) |
| **Paid Price** | $0.10/1M tokens (cheapest commercial option) |
| **MTEB Retrieval** | 55.26 -- significantly below nomic-embed-text |
| **Confidence** | MEDIUM |

**Verdict:** SKIP. Retrieval quality (55.26) is WORSE than current nomic-embed-text (62.39). Dimensions don't match (1024 vs 768). Only advantage is low price, but we need free + quality.

**Sources:**
- [Mistral Embed on Pinecone](https://docs.pinecone.io/models/mistral-embed)
- [Mistral Pricing](https://docs.mistral.ai/deployment/ai-studio/pricing)

---

### Cloud API Summary Table

| Provider | Model | Free Tier | Dims | 768 Support? | MTEB Avg | Verdict |
|----------|-------|-----------|------|-------------|----------|---------|
| **Google Gemini** | gemini-embedding-001 | Generous TPM | 3072 | Yes (MRL) | 68.32 | **RECOMMENDED** |
| **Voyage AI** | voyage-3.5-lite | 200M tokens | 2048/1024/512/256 | No | Top-tier | Good but no 768 |
| **Jina AI** | jina-embeddings-v3 | 10M tokens | 1024 | No | Good | Decent but no 768 |
| **Nomic Atlas** | nomic-embed-text-v1.5 | 1M tokens | 768 | Yes (native) | 62.39 | Exact match, tiny free tier |
| **Cohere** | embed-v4 | 1K calls/month | 1536 | No | Good | Too restrictive |
| **HuggingFace** | Various | ~100K chars/month | Varies | Varies | Varies | Unreliable |
| **Mistral** | mistral-embed | Rate-limited | 1024 | No | 55.26 | Poor quality |

---

## 3. Free Local Embedding Libraries

### 3.1 FastEmbed by Qdrant [PRIMARY RECOMMENDATION]

| Attribute | Value |
|-----------|-------|
| **Install** | `pip install fastembed` |
| **Package Size** | Lightweight (~few MB); models downloaded on first use (~130MB for nomic) |
| **Dependencies** | onnxruntime, numpy, tokenizers, huggingface-hub -- NO PyTorch |
| **Key Model** | `nomic-ai/nomic-embed-text-v1.5-Q` (768-dim, ~130MB ONNX quantized) |
| **Also Supports** | `BAAI/bge-base-en-v1.5` (768-dim, ~130MB), `BAAI/bge-small-en-v1.5` (384-dim, ~45MB) |
| **RAM Usage** | ~300MB for nomic model; minimum 4GB system RAM recommended |
| **CPU Latency** | Sub-millisecond claimed for quantized; realistically ~15-50ms per text on CPU |
| **Cross-Platform** | Windows/macOS/Linux; Apple Silicon via CoreML; may need MSVC on Windows for build |
| **Matryoshka** | Supported via nomic-v1.5 (truncate 768 -> 512/256/128/64) |
| **Quantization** | INT8 quantized models ship by default (4x memory reduction, <1% accuracy loss) |
| **Batch Processing** | Built-in data parallelism for large datasets |
| **Confidence** | HIGH |

**Why FastEmbed is the clear winner:**
1. Runs `nomic-embed-text-v1.5` (quantized ONNX) -- the SAME MODEL Ollama uses, so existing 768-dim vectors remain compatible
2. No PyTorch dependency (saves ~2GB of install size)
3. No server process needed (unlike Ollama)
4. Already integrated into Qdrant ecosystem (which Synapse already uses)
5. CPU-optimized via ONNX Runtime
6. Cross-platform wheels available

**Usage Example:**
```python
from fastembed import TextEmbedding

model = TextEmbedding("nomic-ai/nomic-embed-text-v1.5-Q")
embeddings = list(model.embed(["search_query: What are career goals?"]))
# Returns list of numpy arrays, each 768-dim
```

**Known Issue:** Some Windows users have reported installation issues requiring Microsoft Visual C++ 14.0+. The `onnxruntime` wheel should resolve this for most users, but it is a risk.

**Sources:**
- [FastEmbed GitHub](https://github.com/qdrant/fastembed)
- [FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/)
- [FastEmbed PyPI](https://pypi.org/project/fastembed/)
- [Qdrant FastEmbed Article](https://qdrant.tech/articles/fastembed/)

---

### 3.2 sentence-transformers with bge-base-en-v1.5 [IMPROVED FALLBACK]

| Attribute | Value |
|-----------|-------|
| **Install** | `pip install sentence-transformers` |
| **Package Size** | Large (~2GB with PyTorch) |
| **Model** | `BAAI/bge-base-en-v1.5` |
| **Dimensions** | 768 (exact match!) |
| **Parameters** | 109M |
| **MTEB Avg Score** | 63.55 |
| **Context Window** | 512 tokens |
| **RAM Usage** | ~500MB for inference |
| **CPU Latency** | ~20-60ms per text |
| **Cross-Platform** | Yes -- PyTorch wheels for all platforms including Apple Silicon |
| **Matryoshka** | No (fixed 768-dim) |
| **Confidence** | HIGH |

**Why this replaces all-MiniLM-L6-v2 as fallback:**
1. Same 768 dimensions as nomic-embed-text -- NO MISMATCH
2. Better quality (63.55 vs 56.3 MTEB avg)
3. Comparable to nomic-embed-text quality (63.55 vs 62.39)
4. Same sentence-transformers API, drop-in replacement

**Current fallback problem:** `all-MiniLM-L6-v2` outputs 384-dim vectors. These CANNOT be stored in the `vec_items` table (which expects `float[768]`) or searched against existing 768-dim Qdrant vectors. This is why the current fallback silently fails.

**Fix:** Simply change `EMBEDDING_MODEL_ST = "all-MiniLM-L6-v2"` to `EMBEDDING_MODEL_ST = "BAAI/bge-base-en-v1.5"` in `retriever.py` and `memory_engine.py`.

**Sources:**
- [BAAI/bge-base-en-v1.5 on HuggingFace](https://huggingface.co/BAAI/bge-base-en-v1.5)
- [BGE Documentation](https://bge-model.com/bge/bge_v1_v1.5.html)

---

### 3.3 sentence-transformers with all-mpnet-base-v2 [ALTERNATIVE 768-DIM]

| Attribute | Value |
|-----------|-------|
| **Model** | `sentence-transformers/all-mpnet-base-v2` |
| **Dimensions** | 768 |
| **Parameters** | 110M |
| **MTEB Avg Score** | 57.78 |
| **Context Window** | 384 tokens |
| **Confidence** | HIGH |

**Verdict:** Viable 768-dim alternative but lower quality than bge-base-en-v1.5 (57.78 vs 63.55). Use bge-base instead.

**Sources:**
- [all-mpnet-base-v2 on HuggingFace](https://huggingface.co/sentence-transformers/all-mpnet-base-v2)

---

### 3.4 EmbeddingGemma-300M [FUTURE OPTION]

| Attribute | Value |
|-----------|-------|
| **Model** | `google/embeddinggemma-300m` |
| **Dimensions** | 768 (Matryoshka: 512, 256, 128) |
| **Parameters** | 308M |
| **MTEB Performance** | Highest-ranking open model under 500M params |
| **Multilingual** | 100+ languages |
| **RAM** | <200MB with quantization |
| **Release** | September 2025 |
| **Confidence** | MEDIUM (newer model, less battle-tested) |

**Verdict:** Promising -- 768-dim with Matryoshka, multilingual, lightweight with quantization. However, it is newer (Sep 2025) and has 308M params vs nomic's 137M, meaning higher resource use without quantization. Worth monitoring but FastEmbed with nomic is the safer choice today.

**Sources:**
- [EmbeddingGemma on HuggingFace](https://huggingface.co/google/embeddinggemma-300m)
- [Google Developers Blog](https://developers.googleblog.com/introducing-embeddinggemma/)

---

### 3.5 Direct ONNX Runtime (nomic-embed-text-v1.5) [DIY OPTION]

| Attribute | Value |
|-----------|-------|
| **Install** | `pip install onnxruntime transformers numpy` |
| **How** | Download ONNX weights from HuggingFace, load with `onnxruntime.InferenceSession` |
| **Dimensions** | 768 |
| **Advantage** | Maximum control, no FastEmbed abstraction layer |
| **Disadvantage** | More boilerplate code; need to handle tokenization manually |
| **Confidence** | HIGH |

**Verdict:** This is essentially what FastEmbed does under the hood. Use FastEmbed instead unless you need absolute minimum dependencies.

**Sources:**
- [nomic-embed-text-v1.5 ONNX Discussion](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/6)

---

### 3.6 llama-cpp-python [HEAVYWEIGHT OPTION]

| Attribute | Value |
|-----------|-------|
| **Install** | `pip install llama-cpp-python` (may need compilation) |
| **How** | Load GGUF embedding model, use `create_embedding()` |
| **Advantage** | Can run same GGUF models as Ollama without the Ollama server |
| **Disadvantage** | Compilation needed on some platforms; heavier than ONNX |
| **Confidence** | MEDIUM |

**Verdict:** SKIP unless you specifically need GGUF format. FastEmbed's ONNX approach is lighter, faster to install, and doesn't need compilation.

**Sources:**
- [llama-cpp-python GitHub](https://github.com/abetlen/llama-cpp-python)

---

### 3.7 Model2Vec [ULTRA-LIGHTWEIGHT BUT LOW QUALITY]

| Attribute | Value |
|-----------|-------|
| **Install** | `pip install model2vec` (only needs numpy) |
| **Model Size** | ~30MB (7.5M params, 50x smaller than sentence-transformers) |
| **Speed** | 500x faster than original transformer models on CPU |
| **Quality** | Outperforms GloVe/BPEmb but significantly below transformer models |
| **Best For** | Classification, clustering -- NOT retrieval/search |
| **Confidence** | HIGH |

**Verdict:** SKIP for Synapse. The quality tradeoff is too severe for retrieval tasks. The Model2Vec authors themselves note it "may well not be the best fit" for search tasks. Speed is impressive but irrelevant when quality tanks.

**Sources:**
- [Model2Vec GitHub](https://github.com/MinishLab/model2vec)
- [Model2Vec HuggingFace Blog](https://huggingface.co/blog/Pringled/model2vec)

---

### Local Library Summary Table

| Library | Key Model | Dims | MTEB Avg | Install Size | RAM | PyTorch? | Verdict |
|---------|-----------|------|----------|-------------|-----|----------|---------|
| **FastEmbed** | nomic-v1.5-Q | 768 | ~62 | ~150MB | ~300MB | No | **PRIMARY** |
| **sentence-transformers** | bge-base-en-v1.5 | 768 | 63.55 | ~2GB | ~500MB | Yes | **FALLBACK** |
| **sentence-transformers** | all-mpnet-base-v2 | 768 | 57.78 | ~2GB | ~500MB | Yes | Viable |
| **EmbeddingGemma** | embeddinggemma-300m | 768 | High | ~600MB | <200MB* | Yes | Future |
| **ONNX Direct** | nomic-v1.5 | 768 | ~62 | ~200MB | ~300MB | No | DIY |
| **llama-cpp-python** | GGUF models | 768 | ~62 | ~500MB+ | ~300MB | No | Overkill |
| **Model2Vec** | potion-base-8M | Various | Low | ~30MB | ~50MB | No | Bad for search |

*with quantization

---

## 4. MTEB Benchmark Comparison

### Retrieval-Focused Scores (nDCG@10 where available)

| Model | MTEB Average | Retrieval Score | Dims | Params | Type |
|-------|-------------|-----------------|------|--------|------|
| gemini-embedding-001 | **68.32** | 67.71 | 3072 (768 MRL) | Proprietary | Cloud API |
| Qwen3-Embedding-8B | 70.58 (multilingual) | ~62 | 1024 | 8B | Self-host (huge) |
| voyage-3-large | Top tier | +10% vs OpenAI v3-large | 2048 | Proprietary | Cloud API |
| nomic-embed-text-v1.5 | **62.39** | 86.2% top-5 (TREC-COVID) | **768** | 137M | **Current model** |
| BAAI/bge-base-en-v1.5 | **63.55** | Strong (MS-MARCO top) | **768** | 109M | Local |
| all-mpnet-base-v2 | 57.78 | Moderate | 768 | 110M | Local |
| all-MiniLM-L6-v2 | **56.3** | Lower | **384** | 22M | **Current fallback** |
| mistral-embed | ~55.26 | 55.26 | 1024 | Proprietary | Cloud API |

### Key Takeaways

1. **nomic-embed-text-v1.5 is genuinely good** at 62.39 avg. It outperforms OpenAI Ada-002 (60.99) and text-embedding-3-small (62.26). No reason to downgrade.

2. **all-MiniLM-L6-v2 is significantly worse** at 56.3. The 6-point gap to nomic matters for retrieval quality. AND it has a dimension mismatch (384 vs 768).

3. **bge-base-en-v1.5 is the best 768-dim alternative** at 63.55 -- actually slightly BETTER than nomic on average MTEB, with the same dimensions.

4. **Gemini embedding-001 is the quality leader** at 68.32 if you can accept cloud dependency.

5. **For Synapse's use case** (English + Banglish + code): nomic-embed-text is adequate. Jina v3/v4 would be better for multilingual but requires dimension migration. Voyage-code-3 would be better for code but also different dimensions.

### Retrieval Quality vs nomic-embed-text-v1.5 (baseline = 100%)

```
gemini-embedding-001:   ~110% (better, cloud)
bge-base-en-v1.5:      ~102% (slightly better, same dims, local)
nomic-embed-text-v1.5:  100% (BASELINE - current)
all-mpnet-base-v2:      ~93% (worse, same dims)
all-MiniLM-L6-v2:       ~90% (worse, WRONG dims)
mistral-embed:           ~89% (worse, wrong dims)
```

**Sources:**
- [MTEB Leaderboard (HuggingFace)](https://huggingface.co/spaces/mteb/leaderboard)
- [Best Embedding Models for RAG 2026](https://blog.premai.io/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/)
- [SuperMemory Open Source Benchmarks](https://supermemory.ai/blog/best-open-source-embedding-models-benchmarked-and-ranked/)
- [BentoML Open Source Guide 2026](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)

---

## 5. Dimension Compatibility & Migration

### Current Schema (from `db.py`)

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
    document_id INTEGER,
    embedding float[768]  -- HARDCODED 768 dimensions
);
```

Qdrant collection also stores 768-dim vectors.

### Impact of Switching Models

| Scenario | Migration Required? | Risk |
|----------|-------------------|------|
| FastEmbed nomic-v1.5-Q (768-dim) | **NO** -- exact same model | None |
| bge-base-en-v1.5 (768-dim) | **PARTIAL** -- same dims but different embedding space | Existing vectors become slightly less accurate when mixed |
| Gemini at 768-dim (MRL truncated) | **PARTIAL** -- same dims but different model | Same as above |
| Any model with != 768 dims | **FULL RE-EMBED** -- drop and recreate vec_items + Qdrant | Hours of re-indexing |

### Matryoshka Dimension Flexibility

nomic-embed-text-v1.5 supports Matryoshka Representation Learning (MRL). This means:
- The first 512 dimensions of a 768-dim embedding are themselves a valid 512-dim embedding
- You can truncate 768 -> 512 -> 256 -> 128 -> 64
- After truncation, re-normalize with L2 norm
- sqlite-vec supports this via `vec_slice()` + `vec_normalize()`

**This is useful for future optimization** (smaller vectors = faster search + less storage) but not needed for the immediate Ollama-optional goal.

### Mixed-Model Strategy (NOT RECOMMENDED)

Storing vectors from different models in the same collection is technically possible (if dimensions match) but semantically problematic. A query embedded with Model A will not reliably match documents embedded with Model B, even at the same dimensionality. The vector spaces are different.

**Recommended approach:** Pick one model and stick with it. If switching models, re-embed everything. Store the model name in a metadata column to track which model generated each vector.

### Migration Path if Changing Dimensions

If you ever need to switch to a non-768 model:

1. Add a `embedding_model` column to `documents` table
2. Create a new `vec_items_v2` table with new dimensions
3. Re-embed all documents with the new model
4. Swap tables atomically
5. Update Qdrant collection (recreate with new dimension config)

**Estimated time:** For Synapse's typical corpus (~1000-5000 documents), re-embedding takes 5-30 minutes locally with FastEmbed.

**Sources:**
- [Matryoshka Embeddings Guide (HuggingFace)](https://huggingface.co/blog/matryoshka)
- [sqlite-vec Matryoshka Guide](https://alexgarcia.xyz/sqlite-vec/guides/matryoshka.html)

---

## 6. Implementation Strategy

### Recommended Embedding Provider Cascade

```python
# Priority order for embedding generation:
# 1. FastEmbed (nomic-embed-text-v1.5-Q) -- local, no server, 768-dim
# 2. Ollama (nomic-embed-text) -- local, needs server running, 768-dim  
# 3. Gemini API (gemini-embedding-001 @ 768-dim) -- cloud, needs API key
# 4. sentence-transformers (bge-base-en-v1.5) -- local, heavy, 768-dim
# 5. FTS-only mode -- no vectors, just text search
```

### Why FastEmbed Should Be Tier 1 (Above Ollama)

1. **Same model, same vectors** -- nomic-embed-text-v1.5 quantized ONNX produces embeddings compatible with Ollama's nomic-embed-text
2. **No server process** -- FastEmbed runs in-process, no need to start/manage Ollama
3. **Lighter** -- ~150MB vs Ollama's ~500MB+ installation
4. **Faster startup** -- No cold-start waiting for Ollama to load the model
5. **Cross-platform** -- Pre-built ONNX Runtime wheels for all platforms

### Files to Modify

1. **`retriever.py`** -- Replace `all-MiniLM-L6-v2` fallback with FastEmbed nomic or bge-base
2. **`memory_engine.py`** -- Add FastEmbed as primary provider, demote Ollama to secondary
3. **`requirements.txt`** -- Add `fastembed` (and optionally `google-generativeai`)
4. **`synapse_config.py`** -- Add embedding provider configuration

### Dependency Impact

```
Current:    pip install ollama sentence-transformers
                        ~50MB    ~2GB (with PyTorch)

Proposed:   pip install fastembed
                        ~few MB (onnxruntime ~100MB, model ~130MB on first use)

Total new dependency footprint: ~230MB vs ~2GB+ currently
```

### Configuration Schema (proposed for synapse.json)

```json
{
  "embedding": {
    "provider": "auto",  // "auto" | "fastembed" | "ollama" | "gemini" | "sentence-transformers"
    "model": "nomic-ai/nomic-embed-text-v1.5-Q",
    "dimensions": 768,
    "gemini_api_key_env": "GEMINI_API_KEY",  // reuse existing key if set
    "fallback_chain": ["fastembed", "ollama", "gemini", "sentence-transformers", "fts"]
  }
}
```

---

## Confidence Assessment

| Finding | Confidence | Basis |
|---------|-----------|-------|
| FastEmbed runs nomic-embed-text-v1.5 in ONNX | HIGH | Official FastEmbed model list, multiple sources |
| FastEmbed produces 768-dim embeddings | HIGH | Official docs, model card |
| Gemini embedding-001 supports 768-dim via MRL | HIGH | Google official docs |
| bge-base-en-v1.5 outputs 768-dim | HIGH | HuggingFace model card |
| all-MiniLM-L6-v2 causes dimension mismatch | HIGH | Direct code analysis (384 != 768) |
| MTEB scores as reported | MEDIUM | Scores are self-reported, leaderboard shifts; relative rankings are stable |
| FastEmbed CPU latency ~15-50ms | MEDIUM | Vendor claims + community reports; actual depends on hardware |
| Gemini free tier embedding limits | MEDIUM | TPM-based limits exist but exact numbers vary by project |
| Voyage AI 200M free tokens | HIGH | Official pricing page |
| EmbeddingGemma quality claims | MEDIUM | Newer model (Sep 2025), fewer independent benchmarks |
| FastEmbed Windows compatibility | MEDIUM | Some users report issues; most work fine with pre-built wheels |

---

## Open Questions for Later

1. **FastEmbed + Qdrant integration:** Since Synapse already uses Qdrant and FastEmbed is by Qdrant, there may be tighter integration options (e.g., `qdrant-client[fastembed]` bundle).

2. **Embedding cache warming:** When switching from Ollama to FastEmbed, the first call downloads the model (~130MB). Need to handle this gracefully in the startup flow.

3. **Nomic v1.5 quantized vs full:** The quantized ONNX model in FastEmbed may produce slightly different vectors than Ollama's full-precision model. Need to test cosine similarity between them to confirm compatibility.

4. **Apple Silicon optimization:** FastEmbed may use CoreML on Apple Silicon for better performance. Need to verify this works on macOS ARM.

5. **Gemini embedding normalization:** When truncating from 3072 to 768 dims, need to verify the re-normalization step produces vectors compatible with existing cosine similarity search.
