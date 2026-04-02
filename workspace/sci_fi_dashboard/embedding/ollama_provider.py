import logging

from sci_fi_dashboard.embedding.base import EmbeddingProvider, ProviderInfo

logger = logging.getLogger(__name__)


class OllamaProvider(EmbeddingProvider):
    DEFAULT_MODEL = "nomic-embed-text"
    DIMENSIONS = 768

    def __init__(self, model: str | None = None, api_base: str = "http://localhost:11434"):
        self._model_name = model or self.DEFAULT_MODEL
        self._api_base = api_base
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        try:
            import ollama

            ollama.embeddings(model=self._model_name, prompt="ping", keep_alive="0")
            return True
        except Exception as e:
            logger.warning(f"[Ollama] Not available: {e}")
            return False

    def embed_query(self, text: str) -> list[float]:
        import ollama

        result = ollama.embeddings(
            model=self._model_name,
            prompt=f"search_query: {text}",
            keep_alive="5m",
        )
        return result["embedding"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import ollama

        results = []
        for text in texts:
            result = ollama.embeddings(
                model=self._model_name,
                prompt=f"search_document: {text}",
                keep_alive="5m",
            )
            results.append(result["embedding"])
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
