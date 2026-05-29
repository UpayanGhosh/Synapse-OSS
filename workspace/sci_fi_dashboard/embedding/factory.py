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
    3. GeminiAPIProvider if a Gemini key is available (config or env)
    4. Raise RuntimeError
    """
    root_cfg = config or {}
    cfg = root_cfg.get("embedding", {})
    explicit = cfg.get("provider", "auto")
    model = cfg.get("model")
    cache_dir = cfg.get("cache_dir")
    threads = cfg.get("threads")
    gemini_api_key = _resolve_gemini_api_key(root_cfg, cfg)

    if explicit and explicit != "auto":
        explicit_kwargs: dict = {
            "model": model,
            "cache_dir": cache_dir,
            "threads": threads,
        }
        if explicit == "gemini":
            explicit_kwargs["api_key"] = gemini_api_key
        return _create_explicit(explicit, **explicit_kwargs)

    # Cascade — no external service dependencies
    try:
        import fastembed  # noqa: F401

        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        logger.info("[Embedding] Selected provider: FastEmbed (ONNX, local)")
        return FastEmbedProvider(model=model, cache_dir=cache_dir, threads=threads)
    except ImportError:
        logger.debug("[Embedding] fastembed not installed, trying Gemini API...")

    if gemini_api_key:
        try:
            from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider

            logger.info("[Embedding] Selected provider: Gemini API")
            return GeminiAPIProvider(model=model, api_key=gemini_api_key)
        except Exception:
            pass

    raise RuntimeError("No embedding provider available. Install fastembed: pip install fastembed")


def _create_explicit(name: str, *, model=None, cache_dir=None, threads=None, api_key=None) -> EmbeddingProvider:
    if name == "fastembed":
        from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

        return FastEmbedProvider(model=model, cache_dir=cache_dir, threads=threads)
    elif name == "gemini":
        from sci_fi_dashboard.embedding.gemini_provider import GeminiAPIProvider  # Phase 5

        return GeminiAPIProvider(model=model, api_key=api_key)
    else:
        raise ValueError(f"Unknown embedding provider: {name!r}")


def _resolve_gemini_api_key(config: dict, embedding_cfg: dict) -> str | None:
    embedding_api_key = embedding_cfg.get("api_key")
    if isinstance(embedding_api_key, str) and embedding_api_key:
        return embedding_api_key

    providers_cfg = config.get("providers", {})
    if isinstance(providers_cfg, dict):
        gemini_cfg = providers_cfg.get("gemini")
        if isinstance(gemini_cfg, dict):
            provider_api_key = gemini_cfg.get("api_key")
            if isinstance(provider_api_key, str) and provider_api_key:
                return provider_api_key
        elif isinstance(gemini_cfg, str) and gemini_cfg:
            return gemini_cfg

    import os

    return os.environ.get("GEMINI_API_KEY")


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
