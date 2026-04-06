"""
Offline knowledge-graph triple extractor using local Qwen2.5 LLM.

Follows LazyToxicScorer pattern: model loaded on first extract() call,
unloaded after idle_timeout seconds to free VRAM/RAM.

Tiered model selection (auto-detected, override via SYNAPSE_KG_MODEL):
  CUDA >= 6 GB VRAM  → Qwen2.5-1.5B-Instruct (FP16)
  CUDA <  6 GB VRAM  → Qwen2.5-0.5B-Instruct  (FP16)
  MPS  >= 16 GB RAM  → Qwen2.5-1.5B-Instruct  (FP16)
  MPS  <  16 GB RAM  → Qwen2.5-0.5B-Instruct  (FP16)
  CPU  (fallback)    → Qwen2.5-0.5B-Instruct  (FP32)

Both models are Apache 2.0. Downloaded once to ~/.cache/huggingface/.
"""

import gc
import json
import logging
import os
import re
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract key atomic facts and knowledge graph triples from the following text.
Return ONLY valid JSON with this structure:
{{
  "facts": [
    {{"entity": "main subject", "content": "atomic fact", "category": "Work|Relationship|Plan|Preference|Health|Location"}}
  ],
  "triples": [
    ["subject", "relation", "object"]
  ]
}}

Text:
{content}"""

_CHUNK_SIZE = 1500  # chars — well within Qwen's 32K token window for best quality


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _detect_device() -> str:
    """Return the best available compute device string (cuda / mps / cpu)."""
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _select_model() -> tuple[str, object]:
    """Pick (model_id, torch_dtype) based on available hardware."""
    env_override = os.environ.get("SYNAPSE_KG_MODEL")
    try:
        import torch  # noqa: PLC0415

        if env_override:
            dtype = torch.float32 if _detect_device() == "cpu" else torch.float16
            return env_override, dtype

        device = _detect_device()

        if device == "cuda":
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb >= 6:
                return "Qwen/Qwen2.5-1.5B-Instruct", torch.float16
            return "Qwen/Qwen2.5-0.5B-Instruct", torch.float16

        if device == "mps":
            import psutil  # noqa: PLC0415

            total_gb = psutil.virtual_memory().total / (1024 ** 3)
            if total_gb >= 16:
                return "Qwen/Qwen2.5-1.5B-Instruct", torch.float16
            return "Qwen/Qwen2.5-0.5B-Instruct", torch.float16

        # CPU fallback — always use smaller model, FP32 (no half support on CPU)
        return "Qwen/Qwen2.5-0.5B-Instruct", torch.float32
    except ImportError:
        if env_override:
            return env_override, None
        return "Qwen/Qwen2.5-0.5B-Instruct", None


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def _chunk_text(text: str, max_chars: int = _CHUNK_SIZE) -> list[str]:
    """Split text at sentence boundaries, keeping chunks under max_chars."""
    if len(text) <= max_chars:
        return [text]

    # Split on sentence-ending punctuation including Bengali/Devanagari danda
    sentences = re.split(r"(?<=[.!?।\n])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        if len(sent) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.append(sent[:max_chars])
            continue
        if current and current_len + len(sent) > max_chars:
            chunks.append(" ".join(current))
            current = [sent]
            current_len = len(sent)
        else:
            current.append(sent)
            current_len += len(sent)

    if current:
        chunks.append(" ".join(current))

    return chunks if chunks else [text[:max_chars]]


# ---------------------------------------------------------------------------
# JSON parsing (3-tier fallback)
# ---------------------------------------------------------------------------


def _parse_llm_output(raw: str) -> dict:
    """
    Parse LLM output into {"facts": [...], "triples": [...]}.

    Tier 1: direct json.loads
    Tier 2: extract JSON from markdown code block
    Tier 3: regex-extract triple patterns
    Returns empty result (never raises) if all tiers fail.
    """
    raw = raw.strip()

    # Tier 1
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Tier 2
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 3 — extract triple patterns
    triples = re.findall(
        r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]', raw
    )
    if triples:
        logger.warning("[KG] LLM output not valid JSON — regex fallback used")
        return {"facts": [], "triples": [[s, r, o] for s, r, o in triples]}

    logger.warning("[KG] Could not parse LLM output — returning empty result")
    return {"facts": [], "triples": []}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalize_result(result: dict) -> dict:
    """Lowercase entities, collapse whitespace, deduplicate facts and triples."""
    facts: list[dict] = []
    seen_facts: set[str] = set()
    for f in result.get("facts", []):
        entity = re.sub(r"\s+", " ", (f.get("entity") or "").lower().strip())
        content = re.sub(r"\s+", " ", (f.get("content") or "").strip())
        if content and content not in seen_facts:
            seen_facts.add(content)
            facts.append({
                "entity": entity,
                "content": content,
                "category": f.get("category", ""),
            })

    triples: list[list[str]] = []
    seen_triples: set[tuple] = set()
    for t in result.get("triples", []):
        if not isinstance(t, (list, tuple)) or len(t) < 3:
            continue
        subj = re.sub(r"\s+", " ", str(t[0]).lower().strip())
        rel = re.sub(r"\s+", " ", str(t[1]).lower().strip())
        obj = re.sub(r"\s+", " ", str(t[2]).lower().strip())
        if subj and rel and obj:
            key = (subj, rel, obj)
            if key not in seen_triples:
                seen_triples.add(key)
                triples.append([subj, rel, obj])

    return {"facts": facts, "triples": triples}


# ---------------------------------------------------------------------------
# TripleExtractor
# ---------------------------------------------------------------------------


class TripleExtractor:
    """
    Lazy-loaded local LLM triple extractor (Qwen2.5-0.5B or 1.5B).

    Usage::

        extractor = TripleExtractor()
        result = extractor.extract("Some text about a person...")
        # {"facts": [...], "triples": [...]}

    The model is loaded on the first extract() call and unloaded after
    idle_timeout seconds of inactivity (default 120 s).
    """

    def __init__(self, idle_timeout: float = 120.0):
        self.idle_timeout = idle_timeout
        self._model = None
        self._tokenizer = None
        self._device: Optional[str] = None
        self._model_name: Optional[str] = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._cleanup_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Load / unload
    # ------------------------------------------------------------------

    def _load(self):
        """Load model + tokenizer. Caller must hold self._lock."""
        if self._model is not None:
            return

        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

        self._device = _detect_device()
        self._model_name, dtype = _select_model()
        size_label = "1.5B" if "1.5B" in self._model_name else "0.5B"
        approx_gb = 3 if size_label == "1.5B" else 1

        print(
            f"[KG] Loading Qwen2.5-{size_label} on {self._device}"
            f" (first download: ~{approx_gb} GB, cached after) ..."
        )
        start = time.time()

        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        load_kwargs: dict = {"dtype": dtype} if dtype is not None else {}
        if self._device == "cuda":
            load_kwargs["device_map"] = {"": 0}  # force all layers to GPU 0
        self._model = AutoModelForCausalLM.from_pretrained(self._model_name, **load_kwargs)
        if self._device != "cuda":
            self._model = self._model.to(self._device)
        self._model.eval()

        print(f"[KG] Loaded {self._model_name} on {self._device} in {time.time() - start:.1f}s")

    def _unload(self):
        """Unload model and free VRAM/RAM."""
        with self._lock:
            if self._model is None:
                return
            print(f"[KG] Unloading {self._model_name} (idle {self.idle_timeout}s reached)...")
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            gc.collect()
            try:
                import torch  # noqa: PLC0415

                if self._device == "cuda":
                    torch.cuda.empty_cache()
                elif self._device == "mps":
                    torch.mps.empty_cache()
            except Exception:
                pass

    def _schedule_cleanup(self):
        """Restart the idle-unload timer."""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        self._cleanup_timer = threading.Timer(self.idle_timeout, self._unload)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _run_inference(self, text: str) -> str:
        """Run one LLM pass and return the raw decoded output."""
        with self._lock:
            self._load()
            self._last_used = time.time()
            model = self._model
            tokenizer = self._tokenizer
            device = self._device

        import torch  # noqa: PLC0415

        prompt = _EXTRACTION_PROMPT.format(content=text)
        messages = [{"role": "user", "content": prompt}]
        try:
            input_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            input_text = prompt

        inputs = tokenizer(input_text, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,  # greedy decoding — temperature must not be set
                pad_token_id=tokenizer.eos_token_id,
            )

        new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, text: str) -> dict:
        """
        Extract facts and triples from text.

        Long text is chunked at ~1500 chars; results are merged and
        deduplicated across chunks.

        Returns::

            {
                "facts": [{"entity": str, "content": str, "category": str}, ...],
                "triples": [["subject", "relation", "object"], ...],
            }
        """
        if not text or not text.strip():
            return {"facts": [], "triples": []}

        chunks = _chunk_text(text)
        merged_facts: list[dict] = []
        merged_triples: list[list[str]] = []
        seen_facts: set[str] = set()
        seen_triples: set[tuple] = set()

        for chunk in chunks:
            try:
                raw = self._run_inference(chunk)
                result = _normalize_result(_parse_llm_output(raw))

                for f in result["facts"]:
                    if f["content"] not in seen_facts:
                        seen_facts.add(f["content"])
                        merged_facts.append(f)

                for t in result["triples"]:
                    key = tuple(t)
                    if key not in seen_triples:
                        seen_triples.add(key)
                        merged_triples.append(t)

            except Exception as e:
                logger.warning(f"[KG] Chunk extraction failed ({type(e).__name__}): {e}")

        self._schedule_cleanup()
        return {"facts": merged_facts, "triples": merged_triples}

    def extract_batch(
        self,
        texts: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> list[dict]:
        """
        Extract from multiple texts sequentially.

        progress_callback(done, total) is called after each document.
        """
        results = []
        total = len(texts)
        for i, text in enumerate(texts):
            results.append(self.extract(text))
            if progress_callback:
                progress_callback(i + 1, total)
        return results

    def is_loaded(self) -> bool:
        """Return True if the model is currently in memory."""
        return self._model is not None
