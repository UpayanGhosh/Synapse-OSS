"""
models_catalog.py — ModelsCatalog artifact system.

Provides:
  - ModelChoice dataclass for representing available LLM models
  - ContextWindowGuard for validating context window sizes
  - OllamaDiscovery for auto-discovering locally running Ollama models
  - ensure_models_catalog() for atomic catalog file persistence

The catalog is written to ~/.synapse/models_catalog.json alongside synapse.json
and follows the same atomic-write pattern (tempfile + os.replace + chmod 0o600).
"""

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# --- Constants ---

CONTEXT_WINDOW_HARD_MIN = 16_000
CONTEXT_WINDOW_WARN_BELOW = 32_000


# --- Dataclasses ---


@dataclass
class ModelChoice:
    """A single model available for routing."""

    id: str
    name: str
    provider: str
    context_window: int = 0
    reasoning: bool = False


@dataclass
class ContextWindowGuardResult:
    """Result of a context-window safety check."""

    tokens: int
    source: str = "default"  # "model" | "config" | "default"
    should_warn: bool = False  # tokens > 0 and tokens < CONTEXT_WINDOW_WARN_BELOW
    should_block: bool = False  # tokens > 0 and tokens < CONTEXT_WINDOW_HARD_MIN


# --- Context Window Guard ---


def check_context_window(
    tokens: int, source: str = "default"
) -> ContextWindowGuardResult:
    """Check whether a context window size is safe for operation.

    Args:
        tokens: The context window size in tokens.
        source: Where the value came from ("model", "config", or "default").

    Returns:
        ContextWindowGuardResult with should_warn / should_block flags set.
    """
    return ContextWindowGuardResult(
        tokens=tokens,
        source=source,
        should_warn=0 < tokens < CONTEXT_WINDOW_WARN_BELOW,
        should_block=0 < tokens < CONTEXT_WINDOW_HARD_MIN,
    )


# --- Ollama Discovery ---


async def discover_ollama_models(
    base_url: str = "http://127.0.0.1:11434",
) -> list[ModelChoice]:
    """Discover locally running Ollama models via the Ollama HTTP API.

    Calls GET /api/tags to list models, then POST /api/show for each model
    (up to 200, 8 concurrent) to extract context_window metadata.

    Returns an empty list on any error (connection refused, timeout, etc.).
    Never raises exceptions.
    """
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        logger.debug("httpx not installed — Ollama discovery unavailable")
        return []

    timeout = httpx.Timeout(5.0, connect=5.0)
    models: list[ModelChoice] = []

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: GET /api/tags to list all models
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            model_entries = data.get("models", [])

            # Cap at 200 models
            model_entries = model_entries[:200]
            if not model_entries:
                return []

            # Step 2: GET /api/show for each model (8 concurrent)
            semaphore = asyncio.Semaphore(8)

            async def _fetch_model_info(entry: dict) -> ModelChoice | None:
                name = entry.get("name", "")
                if not name:
                    return None
                async with semaphore:
                    try:
                        show_resp = await client.post(
                            f"{base_url}/api/show",
                            json={"name": name},
                        )
                        show_resp.raise_for_status()
                        show_data = show_resp.json()

                        # Extract context_window from model_info or parameters
                        context_window = 0
                        model_info = show_data.get("model_info", {})
                        if isinstance(model_info, dict):
                            # Try common keys for context length
                            for key in model_info:
                                if "context_length" in key.lower():
                                    val = model_info[key]
                                    if isinstance(val, (int, float)):
                                        context_window = int(val)
                                        break

                        # Fallback: check parameters string
                        if context_window == 0:
                            params = show_data.get("parameters", "")
                            if isinstance(params, str) and "num_ctx" in params:
                                for line in params.splitlines():
                                    if "num_ctx" in line:
                                        parts = line.strip().split()
                                        if len(parts) >= 2:
                                            with contextlib.suppress(ValueError):
                                                context_window = int(parts[-1])
                                        break

                        return ModelChoice(
                            id=f"ollama_chat/{name}",
                            name=name,
                            provider="ollama",
                            context_window=context_window,
                            reasoning=False,
                        )
                    except Exception:
                        # Individual model fetch failure is non-fatal
                        logger.debug("Failed to fetch info for Ollama model %s", name)
                        return ModelChoice(
                            id=f"ollama_chat/{name}",
                            name=name,
                            provider="ollama",
                            context_window=0,
                            reasoning=False,
                        )

            tasks = [_fetch_model_info(entry) for entry in model_entries]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, ModelChoice):
                    models.append(result)

    except Exception as exc:
        logger.debug("Ollama discovery failed: %s", exc)
        return []

    return models


# --- Catalog Persistence ---


def ensure_models_catalog(config) -> tuple[Path, Literal["skip", "noop", "write"]]:
    """Atomically write ~/.synapse/models_catalog.json.

    Builds a catalog from config.providers and config.model_mappings, then:
      - Returns ("skip") if no providers are configured.
      - Returns ("noop") if the existing file is identical.
      - Returns ("write") after an atomic write (tempfile + os.replace + chmod 0o600).

    Follows the same atomic-write pattern as synapse_config.write_config().

    Args:
        config: A SynapseConfig instance.

    Returns:
        Tuple of (path_to_catalog, action_taken).
    """
    catalog_path: Path = config.data_root / "models_catalog.json"

    # Build the catalog payload
    providers = config.providers or {}
    model_mappings = config.model_mappings or {}

    if not providers and not model_mappings:
        logger.debug("No providers or model_mappings configured — skipping catalog write")
        return catalog_path, "skip"

    # Build provider entries for the catalog
    catalog_providers: dict = {}
    for provider_name, provider_cfg in providers.items():
        if isinstance(provider_cfg, dict):
            # Include non-secret fields only (api_base, enabled, etc.)
            entry: dict = {}
            for k, v in provider_cfg.items():
                if "key" not in k.lower() and "secret" not in k.lower():
                    entry[k] = v
            if entry:
                catalog_providers[provider_name] = entry
        elif isinstance(provider_cfg, str):
            # String value is likely just an API key — don't include
            catalog_providers[provider_name] = {"configured": True}

    # Build model entries
    catalog_models: dict = {}
    for role, mapping in model_mappings.items():
        if isinstance(mapping, dict):
            catalog_models[role] = {
                "model": mapping.get("model", ""),
                "fallback": mapping.get("fallback"),
            }

    catalog_data = {
        "providers": catalog_providers,
        "models": catalog_models,
    }

    # Serialize to compare
    new_content = json.dumps(catalog_data, indent=2, sort_keys=True)

    # Compare with existing file
    if catalog_path.exists():
        try:
            existing_content = catalog_path.read_text(encoding="utf-8")
            if existing_content.strip() == new_content.strip():
                logger.debug("models_catalog.json unchanged — noop")
                return catalog_path, "noop"
        except (OSError, ValueError):
            pass  # File unreadable or corrupt — overwrite it

    # Atomic write: tempfile + os.replace + chmod 0o600
    config.data_root.mkdir(parents=True, exist_ok=True)
    tmp = catalog_path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp))
        raise

    os.replace(str(tmp), str(catalog_path))
    # Re-enforce permissions after replace (umask drift guard)
    with contextlib.suppress(OSError):
        os.chmod(str(catalog_path), 0o600)

    logger.info("Wrote models_catalog.json (%d bytes)", len(new_content))
    return catalog_path, "write"
