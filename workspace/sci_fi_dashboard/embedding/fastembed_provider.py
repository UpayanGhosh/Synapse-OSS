import os
import logging

from sci_fi_dashboard.embedding.base import EmbeddingProvider, ProviderInfo

logger = logging.getLogger(__name__)


class FastEmbedProvider(EmbeddingProvider):
    DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"
    DIMENSIONS = 768

    def __init__(
        self,
        model: str | None = None,
        cache_dir: str | None = None,
        threads: int | None = None,
    ):
        self._model_name = model or self.DEFAULT_MODEL
        self._cache_dir = cache_dir
        self._threads = threads or min(4, os.cpu_count() or 1)
        self._embedder = None  # lazy-loaded

    def _get_embedder(self):
        if self._embedder is None:
            logger.info(
                f"[FastEmbed] First use — downloading model '{self._model_name}' if not cached..."
            )
            from fastembed import TextEmbedding  # lazy import

            kwargs = {"model_name": self._model_name, "threads": self._threads}
            if self._cache_dir:
                kwargs["cache_dir"] = self._cache_dir
            self._embedder = TextEmbedding(**kwargs)
        return self._embedder

    def embed_query(self, text: str) -> list[float]:
        prefixed = f"search_query: {text}"
        embedder = self._get_embedder()
        return list(list(embedder.embed([prefixed]))[0].tolist())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"search_document: {t}" for t in texts]
        embedder = self._get_embedder()
        return [list(v.tolist()) for v in embedder.embed(prefixed)]

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fastembed",
            model=self._model_name,
            dimensions=self.DIMENSIONS,
            requires_network=False,
            requires_gpu=False,
        )
