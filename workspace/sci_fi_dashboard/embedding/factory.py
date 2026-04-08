import logging
import threading

from sci_fi_dashboard.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)
_provider: EmbeddingProvider | None = None
_provider_lock = threading.Lock()


def create_provider(config: dict | None = None) -> EmbeddingProvider:
    """Create an embedding provider using cascade logic.

    Priority:
    1. config['embedding']['provider'] if explicitly set (not 'auto')
    2. FastEmbedProvider if fastembed is importable (primary — zero external services)
    3. GeminiAPIProvider if GEMINI_API_KEY is set
    4. Raise RuntimeError
    """
    cfg = (config or {}).get("embedding", {})
    explicit = cfg.get("provider", "auto")
    model = cfg.get("model")
    cache_dir = cfg.get("cache_dir")
    threads = cfg.get("threads")

    if explicit and explicit != "auto":
        return _create_explicit(explicit, model=model, cache_dir=cache_dir, threads=threads)

    # Cascade — no external service dependencies
    try:
        import fastembed  # noqa: F401

        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        logger.info("[Embedding] Selected provider: FastEmbed (ONNX, local)")
        return FastEmbedProvider(model=model, cache_dir=cache_dir, threads=threads)
    except ImportError:
        logger.debug("[Embedding] fastembed not installed, trying Gemini API...")

    import os
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

            logger.info("[Embedding] Selected provider: Gemini API")
            return GeminiAPIProvider(model=model)
        except Exception:
            pass

    raise RuntimeError(
        "No embedding provider available. Install fastembed: pip install fastembed"
    )


def _create_explicit(
    name: str, *, model=None, cache_dir=None, threads=None
) -> EmbeddingProvider:
    if name == "fastembed":
        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        return FastEmbedProvider(model=model, cache_dir=cache_dir, threads=threads)
    elif name == "gemini":
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider  # Phase 5

        return GeminiAPIProvider(model=model)
    else:
        raise ValueError(f"Unknown embedding provider: {name!r}")


def get_provider(config: dict | None = None) -> EmbeddingProvider | None:
    """Return singleton provider, creating it on first call (thread-safe)."""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                try:
                    _provider = create_provider(config)
                except RuntimeError as e:
                    logger.error(f"[Embedding] {e}")
                    return None
    return _provider


def reset_provider() -> None:
    """Reset singleton — used in tests (thread-safe)."""
    global _provider
    with _provider_lock:
        _provider = None
