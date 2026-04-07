import os
import logging
import threading

from sci_fi_dashboard.embedding.base import EmbeddingProvider, ProviderInfo

logger = logging.getLogger(__name__)


def _detect_accelerator() -> str:
    """Detect the best available ONNX execution provider.

    Returns one of: 'cuda', 'coreml', 'cpu'
    Priority: CUDA (Nvidia) > CoreML (Apple Silicon / Mac GPU) > CPU
    """
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return "cuda"
        if "CoreMLExecutionProvider" in available:
            return "coreml"
    except ImportError:
        pass
    return "cpu"


class FastEmbedProvider(EmbeddingProvider):
    # -Q is INT8 quantized — fast on CPU but causes excessive CPU↔GPU memcpy on CUDA.
    # Float32 variant is used when GPU is available.
    DEFAULT_MODEL_CPU = "nomic-ai/nomic-embed-text-v1.5-Q"
    DEFAULT_MODEL_GPU = "nomic-ai/nomic-embed-text-v1.5"
    DIMENSIONS = 768

    def __init__(
        self,
        model: str | None = None,
        cache_dir: str | None = None,
        threads: int | None = None,
        batch_size: int | None = None,
    ):
        FastEmbedProvider._inject_cuda_dlls()  # must run before onnxruntime first imports on Windows
        self._accelerator = _detect_accelerator()  # detect first — needed for model selection
        if model:
            self._model_name = model
        elif self._accelerator in ("cuda", "coreml"):
            self._model_name = self.DEFAULT_MODEL_GPU
        else:
            self._model_name = self.DEFAULT_MODEL_CPU
        self._cache_dir = cache_dir
        self._threads = threads or min(4, os.cpu_count() or 1)
        self._embedder = None  # lazy-loaded
        self._embedder_lock = threading.Lock()
        # ONNX Runtime CUDA sessions are not thread-safe — concurrent session.run()
        # calls on the same session cause an abort. Serialize all inference through
        # this lock. GPU/CoreML is still used; threads simply queue for the accelerator.
        self._inference_lock = threading.Lock()

        # Safe internal batch size passed to fastembed's embed().
        # fastembed default is 256 which overflows VRAM on GPUs with mixed-length texts.
        # GPU: 8 — keeps peak VRAM ~4 GB even for long texts (AG News, 300+ token articles).
        #          64 caused OOM (34 GB arena request) on standard 6-8 GB GPUs.
        # CPU: 64 — no VRAM constraint, higher is fine.
        if batch_size is not None:
            self._batch_size = batch_size
        elif self._accelerator in ("cuda", "coreml"):
            self._batch_size = 8
        else:
            self._batch_size = 64

        mode = {"cuda": "GPU (CUDA)", "coreml": "GPU (CoreML/Apple Silicon)", "cpu": "CPU"}
        logger.info(
            f"[FastEmbed] Execution mode: {mode[self._accelerator]} "
            f"| batch_size={self._batch_size}"
        )

    @staticmethod
    def _inject_cuda_dlls() -> None:
        """Add nvidia pip-package DLL dirs to PATH so onnxruntime-gpu can find them.

        When CUDA is installed via pip (nvidia-cublas-cu12, nvidia-cudnn-cu12, etc.)
        the DLLs land in site-packages/nvidia/*/bin/ which is NOT on PATH by default.
        This is a no-op on Linux/Mac or if the dirs are already present or don't exist.
        """
        if os.name != "nt":
            return  # DLL injection only needed on Windows (pip-installed CUDA)

        import glob, site

        added = []
        for sp in site.getsitepackages():
            pattern = os.path.join(sp, "nvidia", "*", "bin")
            for bin_dir in glob.glob(pattern):
                if bin_dir not in os.environ.get("PATH", ""):
                    os.add_dll_directory(bin_dir)  # Windows DLL search path
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    added.append(bin_dir)
        if added:
            logger.info(f"[FastEmbed] Injected CUDA DLL dirs into PATH: {added}")

    def _get_embedder(self):
        if self._embedder is None:
            with self._embedder_lock:
                if self._embedder is None:
                    if self._accelerator == "cuda":
                        self._inject_cuda_dlls()
                    logger.info(
                        f"[FastEmbed] Loading model '{self._model_name}' "
                        f"(accelerator={self._accelerator})..."
                    )
                    from fastembed import TextEmbedding  # lazy import

                    kwargs = {"model_name": self._model_name, "threads": self._threads}
                    if self._cache_dir:
                        kwargs["cache_dir"] = self._cache_dir
                    if self._accelerator == "cuda":
                        kwargs["cuda"] = True
                    elif self._accelerator == "coreml":
                        kwargs["providers"] = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
                    self._embedder = TextEmbedding(**kwargs)
        return self._embedder

    def embed_query(self, text: str) -> list[float]:
        prefixed = f"search_query: {text}"
        embedder = self._get_embedder()
        with self._inference_lock:
            return list(list(embedder.embed([prefixed], batch_size=1))[0].tolist())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"search_document: {t}" for t in texts]
        embedder = self._get_embedder()
        with self._inference_lock:
            return [list(v.tolist()) for v in embedder.embed(prefixed, batch_size=self._batch_size)]

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fastembed",
            model=self._model_name,
            dimensions=self.DIMENSIONS,
            requires_network=False,
            requires_gpu=self._accelerator != "cpu",
        )
