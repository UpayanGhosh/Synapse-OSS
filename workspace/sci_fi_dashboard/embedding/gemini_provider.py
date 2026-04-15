"""
Gemini API embedding provider for Synapse-OSS.

NEVER auto-selected — only used when explicitly configured:
    {"embedding": {"provider": "gemini"}}

NOT suitable for vault/spicy hemisphere (cloud leakage risk).
DIFFERENT embedding space from nomic — requires re-embed when switching.
"""

from __future__ import annotations

import logging

from sci_fi_dashboard.embedding.base import EmbeddingProvider, ProviderInfo

logger = logging.getLogger(__name__)


class GeminiAPIProvider(EmbeddingProvider):
    DEFAULT_MODEL = "text-embedding-004"
    NATIVE_DIMENSIONS = 3072
    OUTPUT_DIMENSIONS = 768  # MRL-truncated to match nomic

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self._model_name = model or self.DEFAULT_MODEL
        self._api_key = api_key or self._load_api_key()
        if not self._api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY env var or add to synapse.json"
                " providers.gemini"
            )
        self._client = None  # lazy

    def _load_api_key(self) -> str | None:
        import os

        return os.environ.get("GEMINI_API_KEY")

    def _get_client(self):
        if self._client is None:
            from google import genai  # NEW SDK — not google-generativeai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def embed_query(self, text: str) -> list[float]:
        client = self._get_client()
        result = client.models.embed_content(
            model=self._model_name,
            content=text,
            config={
                "task_type": "RETRIEVAL_QUERY",
                "output_dimensionality": self.OUTPUT_DIMENSIONS,
            },
        )
        return result.embeddings[0].values

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        results = []
        for text in texts:
            result = client.models.embed_content(
                model=self._model_name,
                content=text,
                config={
                    "task_type": "RETRIEVAL_DOCUMENT",
                    "output_dimensionality": self.OUTPUT_DIMENSIONS,
                },
            )
            results.append(result.embeddings[0].values)
        return results

    @property
    def dimensions(self) -> int:
        return self.OUTPUT_DIMENSIONS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="gemini",
            model=self._model_name,
            dimensions=self.OUTPUT_DIMENSIONS,
            requires_network=True,
            requires_gpu=False,
        )
