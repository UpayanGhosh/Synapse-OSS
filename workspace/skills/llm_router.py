"""
LLMRouter — sync wrapper around SynapseLLMRouter (litellm backend).

Preserves the existing public interface:
    llm = LLMRouter()
    text = llm.generate(prompt, system_prompt, force_kimi)
    vecs = llm.embed(text)

Dispatches through SynapseLLMRouter.call() from sync context via a thread-pool executor
(avoids RuntimeError: This event loop is already running when called from async
contexts such as FastAPI request handlers).

If SynapseLLMRouter is unavailable (no synapse.json, missing litellm),
returns an error message.
"""

import asyncio
import concurrent.futures
import logging
import os
import re
import sys

# Ensure workspace root is on the path so synapse_config and sci_fi_dashboard
# are importable regardless of how this module is invoked.
_DIR = os.path.abspath(os.path.dirname(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLMRouter")


# ---------------------------------------------------------------------------
# Async helper — runs a coroutine from sync *or* async contexts safely.
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine from any context without blocking the event loop.

    - Sync context (e.g. db/tools.py): no running loop → asyncio.run() works.
    - Async context (e.g. FastAPI handler): running loop present → spawn a
      ThreadPoolExecutor and run asyncio.run() on the worker thread (which has
      its own fresh event loop).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We are inside an async context; can't call asyncio.run() here.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# LLMRouter
# ---------------------------------------------------------------------------


class LLMRouter:
    """Sync LLM router backed by SynapseLLMRouter (litellm).

    Public interface (unchanged from original):
        generate(prompt, system_prompt, force_kimi) -> str
        embed(text, model) -> list[float]
        kimi_model  # backward-compat attribute
    """

    def __init__(self, cloud_models=None, backup_model="llama3.2:3b"):
        self.cloud_models = cloud_models or ["casual"]
        self.backup_model = backup_model
        # Backward-compatible attribute used by db/server.py status payload.
        self.kimi_model = self.cloud_models[0]

        try:
            from synapse_config import SynapseConfig  # noqa: PLC0415

            self._synapse_config = SynapseConfig.load()
            from sci_fi_dashboard.llm_router import SynapseLLMRouter  # noqa: PLC0415

            self._synapse_router = SynapseLLMRouter(self._synapse_config)
            logger.info("LLMRouter: SynapseLLMRouter initialized (litellm backend)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLMRouter: SynapseLLMRouter unavailable (%s)", exc)
            self._synapse_config = None
            self._synapse_router = None

    def generate(
        self,
        prompt,
        system_prompt="You are a helpful assistant.",
        force_kimi=False,  # noqa: ARG002 — preserved for backward compat, ignored
    ) -> str:
        """Route prompt through SynapseLLMRouter (litellm).

        force_kimi is preserved in the signature for backward compatibility but
        is intentionally ignored — role-based routing replaces the old Kimi path.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Determine role from cloud_models (first entry) or default to "casual".
        # If cloud_models[0] is a synapse role name (present in model_mappings),
        # use it directly; otherwise fall back to the "casual" role.
        role = "casual"
        if self._synapse_router is not None and self.cloud_models:
            candidate = self.cloud_models[0]
            cfg = self._synapse_config.model_mappings if self._synapse_config is not None else {}
            if candidate in cfg:
                role = candidate

        if self._synapse_router is not None:
            try:
                text = _run_async(self._synapse_router.call(role, messages, max_tokens=1024))
                if text:
                    return self._sanitize(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SynapseLLMRouter failed for role '%s': %s", role, exc)

        return "Error: LLM router unavailable — configure synapse.json with valid providers."

    def _sanitize(self, text: str) -> str:
        """Strip internal reasoning blocks before returning to caller."""
        if not text:
            return ""
        # 1. Remove <think> blocks completely
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # 2. Extract content from <final> tags if they exist
        text = re.sub(r"<final>(.*?)</final>", r"\1", text, flags=re.DOTALL | re.IGNORECASE)
        # 3. Clean up generic thought headers
        text = re.sub(r"^Thought for\b.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
        # 4. Clean up any leftover thinking content (non-greedy)
        text = re.sub(r"\n+Thinking\n+.*?\n+", "\n\n", text, flags=re.IGNORECASE)
        return text.strip()

    def embed(self, text, model="text-embedding-004") -> list:  # noqa: ARG002
        """Return embedding vector for text using the configured embedding provider."""
        try:
            from sci_fi_dashboard.embedding import get_provider

            provider = get_provider()
            if provider is not None:
                return provider.embed_query(text)
        except Exception:  # noqa: BLE001
            pass
        return []


# Module-level singleton — all callers use `from skills.llm_router import llm`
llm = LLMRouter()
