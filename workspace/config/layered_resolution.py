"""
config/layered_resolution.py — 5-layer config resolution for Synapse-OSS.

Layer priority (highest to lowest):
  1. CLI overrides (per-invocation)
  2. Runtime overrides (applied via API at runtime)
  3. Session overrides (per-session JSON file)
  4. Agent-level config (from SynapseConfigSchema.model_mappings)
  5. Gateway defaults (hardcoded fallbacks)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.merge_patch import merge_patch
from config.schema import AgentModelConfig, SynapseConfigSchema

logger = logging.getLogger(__name__)

# Gateway defaults — the absolute fallback for model resolution.
_GATEWAY_DEFAULTS: dict[str, Any] = {
    "model": "gemini/gemini-2.0-flash-exp",
    "fallback": None,
    "fallbacks": [],
    "thinking": None,
}


class ConfigResolver:
    """5-layer config resolution: CLI > runtime > session > agent > gateway defaults."""

    def __init__(self, base_config: SynapseConfigSchema, data_root: Path) -> None:
        self._base = base_config
        self._data_root = data_root
        self._runtime_overrides: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Layer 2: runtime overrides
    # ------------------------------------------------------------------

    def apply_runtime_override(self, patch: dict[str, Any]) -> None:
        """Merge *patch* into the runtime override layer (in-memory only)."""
        self._runtime_overrides = merge_patch(self._runtime_overrides, patch)

    # ------------------------------------------------------------------
    # Session file I/O
    # ------------------------------------------------------------------

    def _session_dir(self, session_key: str) -> Path:
        return self._data_root / "sessions" / session_key

    def _read_session_overrides(self, session_key: str) -> dict[str, Any]:
        """Read session-level overrides from disk.  Returns {} if absent."""
        config_file = self._session_dir(session_key) / "config.json"
        if not config_file.exists():
            return {}
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read session config %s: %s", config_file, exc)
            return {}

    def write_session_override(self, session_key: str, patch: dict[str, Any]) -> None:
        """Write (merge) a session-level override to disk."""
        existing = self._read_session_overrides(session_key)
        merged = merge_patch(existing, patch)
        out_dir = self._session_dir(session_key)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "config.json").write_text(
            json.dumps(merged, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_model_for_session(
        self,
        session_key: str,
        agent_id: str | None = None,
        cli_overrides: dict[str, Any] | None = None,
    ) -> AgentModelConfig:
        """Resolve the effective model config for a given session.

        Parameters
        ----------
        session_key : str
            Unique session identifier.
        agent_id : str | None
            Role key in ``model_mappings`` (e.g. ``"casual"``, ``"code"``).
        cli_overrides : dict | None
            Highest-priority overrides from CLI flags.

        Returns
        -------
        AgentModelConfig
            The fully-resolved model configuration.
        """
        # Layer 5: gateway defaults
        result = dict(_GATEWAY_DEFAULTS)

        # Layer 4: agent-level config from base schema
        if agent_id and agent_id in self._base.model_mappings:
            agent_cfg = self._base.model_mappings[agent_id].model_dump(
                exclude_none=True
            )
            result = merge_patch(result, agent_cfg)

        # Layer 3: session overrides
        session_cfg = self._read_session_overrides(session_key)
        if session_cfg:
            result = merge_patch(result, session_cfg)

        # Layer 2: runtime overrides
        if self._runtime_overrides:
            result = merge_patch(result, self._runtime_overrides)

        # Layer 1: CLI overrides (highest priority)
        if cli_overrides:
            result = merge_patch(result, cli_overrides)

        return AgentModelConfig(**result)
