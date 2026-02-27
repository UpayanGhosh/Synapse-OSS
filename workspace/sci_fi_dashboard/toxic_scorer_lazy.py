import gc
import threading
import time

import torch


class LazyToxicScorer:
    """
    Drop-in replacement for ToxicScorer.
    Loads model on first score() call, unloads after idle_timeout seconds.
    """

    def __init__(self, idle_timeout: float = 30.0):
        self.model_name = "unitary/toxic-bert"
        self.idle_timeout = idle_timeout
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._cleanup_timer = None

    def _load(self):
        if self._model is not None:
            return

        print("🧪 Loading Toxic-BERT (lazy)...")
        start = time.time()
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)

        # Use MPS if available (Apple Silicon GPU)
        if torch.backends.mps.is_available():
            self._model = self._model.to("mps")

        self._model.eval()
        print(f"🧪 Toxic-BERT loaded in {time.time() - start:.1f}s")

    def _unload(self):
        with self._lock:
            if self._model is None:
                return
            print("[CLEAN] Unloading Toxic-BERT (saving ~600MB)...")
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            gc.collect()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()

    def _schedule_cleanup(self):
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        self._cleanup_timer = threading.Timer(self.idle_timeout, self._unload)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def score(self, text: str) -> float:
        with self._lock:
            self._load()
            self._last_used = time.time()

        try:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            ).to(device)

            with torch.no_grad():
                logits = self._model(**inputs).logits

            # Model outputs 6 toxicity scores (one per class)
            # Get the mean across all toxicity classes for overall toxicity
            scores = torch.sigmoid(logits).cpu()
            score = scores.mean().item()
            self._schedule_cleanup()
            return score

        except Exception as e:
            print(f"[WARN] Toxic score error: {e}")
            return 0.0

    def is_loaded(self) -> bool:
        return self._model is not None
