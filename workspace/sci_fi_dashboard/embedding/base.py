from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimensions: int
    provider: str  # "fastembed" | "ollama" | "gemini"


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
