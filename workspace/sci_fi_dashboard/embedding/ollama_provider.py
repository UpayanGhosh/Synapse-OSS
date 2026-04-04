import logging

from sci_fi_dashboard.embedding.base import EmbeddingProvider, ProviderInfo

logger = logging.getLogger(__name__)


class OllamaProvider(EmbeddingProvider):
    DEFAULT_MODEL = "nomic-embed-text"
    DIMENSIONS = 768

    def __init__(self, model: str | None = None, api_base: str = "http://localhost:11434"):
        self._model_name = model or self.DEFAULT_MODEL
        self._api_base = api_base
        self._client = None  # lazy — avoids import at module load
        self._available = self._check_availability()

    def _get_client(self):
        """Return a stable ollama.Client bound to api_base (ignores OLLAMA_HOST env)."""
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self._api_base)
        return self._client

    def _check_availability(self) -> bool:
        try:
            client = self._get_client()
            client.embeddings(model=self._model_name, prompt="ping", keep_alive="0")
            return True
        except Exception as e:
            logger.warning(f"[Ollama] Not available at {self._api_base}: {e}")
            return False

    def embed_query(self, text: str) -> list[float]:
        result = self._get_client().embeddings(
            model=self._model_name,
            prompt=f"search_query: {text}",
            keep_alive="5m",
        )
        return list(result.embedding)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        results = []
        for text in texts:
            result = client.embeddings(
                model=self._model_name,
                prompt=f"search_document: {text}",
                keep_alive="5m",
            )
            results.append(list(result.embedding))
        return results

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="ollama",
            model=self._model_name,
            dimensions=self.DIMENSIONS,
            requires_network=False,
            requires_gpu=False,
        )

    @property
    def available(self) -> bool:
        return self._available
