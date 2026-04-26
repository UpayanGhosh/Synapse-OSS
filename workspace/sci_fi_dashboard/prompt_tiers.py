"""Prompt-tier policies and markdown filtering for model-sized compilation.

The router can send a turn to anything from a frontier cloud model to a
commodity local model. This module keeps the prompt renderer explicit about
what each class of model can afford.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

PromptTier = Literal["frontier", "mid_open", "small"]

VALID_PROMPT_TIERS: tuple[PromptTier, ...] = ("frontier", "mid_open", "small")

_TIER_ALIASES: dict[str, PromptTier] = {
    "frontier": "frontier",
    "full": "frontier",
    "cloud": "frontier",
    "large": "frontier",
    "pro": "frontier",
    "mid": "mid_open",
    "mid_open": "mid_open",
    "open_mid": "mid_open",
    "medium": "mid_open",
    "local_7b": "mid_open",
    "small": "small",
    "mini": "small",
    "minimal": "small",
    "local_small": "small",
}


@dataclass(frozen=True)
class PromptTierPolicy:
    """Rendering policy for one prompt capability tier."""

    tier: PromptTier
    token_target: int
    memory_limit: int
    memory_min_score: float | None
    include_graph_context: bool
    include_mcp_context: bool
    history_turns: int
    cognitive_detail: Literal["full", "strategy"]
    native_tool_schemas: bool
    profile_fact_limit: int | None
    profile_fact_chars: int


PROMPT_TIER_POLICIES: dict[PromptTier, PromptTierPolicy] = {
    "frontier": PromptTierPolicy(
        tier="frontier",
        token_target=19_000,
        memory_limit=5,
        memory_min_score=None,
        include_graph_context=True,
        include_mcp_context=True,
        history_turns=6,
        cognitive_detail="full",
        native_tool_schemas=True,
        profile_fact_limit=None,
        profile_fact_chars=700,
    ),
    "mid_open": PromptTierPolicy(
        tier="mid_open",
        token_target=12_000,
        memory_limit=3,
        memory_min_score=None,
        include_graph_context=True,
        include_mcp_context=True,
        history_turns=4,
        cognitive_detail="strategy",
        native_tool_schemas=True,
        profile_fact_limit=5,
        profile_fact_chars=420,
    ),
    "small": PromptTierPolicy(
        tier="small",
        token_target=8_000,
        memory_limit=1,
        memory_min_score=0.85,
        include_graph_context=False,
        include_mcp_context=False,
        history_turns=2,
        cognitive_detail="strategy",
        native_tool_schemas=False,
        profile_fact_limit=3,
        profile_fact_chars=280,
    ),
}

_OPEN_TIER_RE = re.compile(r"^\s*(?:<!--\s*)?<tier:([^>]+)>\s*(?:-->)?\s*$", re.I)
_CLOSE_TIER_RE = re.compile(r"^\s*(?:<!--\s*)?</tier(?::[^>]+)?>\s*(?:-->)?\s*$", re.I)
_SIZE_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*b\b", re.I)


def normalize_prompt_tier(value: Any, default: PromptTier = "frontier") -> PromptTier:
    """Return a canonical tier name, falling back to *default* on unknown input."""

    if value is None:
        return default
    raw = str(value).strip().lower().replace("-", "_")
    return _TIER_ALIASES.get(raw, default)


def get_prompt_tier_policy(tier: Any) -> PromptTierPolicy:
    """Return the policy for *tier* after alias normalization."""

    return PROMPT_TIER_POLICIES[normalize_prompt_tier(tier)]


def prompt_tier_for_role(
    model_mappings: dict[str, Any] | None,
    role: str,
    default: PromptTier = "frontier",
) -> PromptTier:
    """Resolve the prompt tier for a router role.

    Explicit role config wins:
    ``prompt_tier`` > ``capability_tier`` > ``tier``.
    If absent, local Ollama/vLLM roles are inferred from ``num_ctx`` or model
    size. Non-local roles default to frontier for backward compatibility.
    """

    cfg = (model_mappings or {}).get(role) or {}
    explicit = _cfg_get(cfg, "prompt_tier") or _cfg_get(cfg, "capability_tier") or _cfg_get(cfg, "tier")
    if explicit:
        return normalize_prompt_tier(explicit, default)

    model = str(_cfg_get(cfg, "model") or "")
    inferred = infer_prompt_tier_from_model(model, cfg)
    return inferred or default


def infer_prompt_tier_from_model(model: str, role_cfg: Any | None = None) -> PromptTier | None:
    """Infer a tier for local models when the role did not declare one."""

    model_l = (model or "").lower()
    if not model_l:
        return None

    is_local = model_l.startswith(
        (
            "ollama_chat/",
            "hosted_vllm/",
            "vllm/",
            "lm_studio/",
            "local/",
        )
    )
    if not is_local:
        return None

    num_ctx = _ollama_num_ctx(role_cfg)
    if num_ctx is not None:
        if num_ctx <= 8_192:
            return "small"
        if num_ctx <= 16_384:
            return "mid_open"
        return "frontier"

    size_b = _model_size_b(model_l)
    if size_b is not None:
        if size_b <= 4.5:
            return "small"
        if size_b <= 14:
            return "mid_open"
        return "frontier"

    if any(k in model_l for k in ("phi", "mini", "tiny", "3b", "e4b", "4b")):
        return "small"
    if any(k in model_l for k in ("mistral", "qwen", "gemma", "llama")):
        return "mid_open"
    return "small"


def filter_tier_sections(markdown: str, tier: Any) -> str:
    """Strip ``<tier:...>`` markdown sections that do not apply to *tier*.

    Supported markers are line-oriented:

    ``<tier:all>``, ``<tier:frontier>``, ``<tier:mid_open,small>``
    and matching ``</tier:...>`` closers. HTML-comment wrapped forms are also
    accepted, e.g. ``<!-- <tier:small> -->``.
    """

    if not markdown:
        return ""

    active = normalize_prompt_tier(tier)
    include_stack: list[bool] = []
    out: list[str] = []

    for line in markdown.splitlines():
        open_match = _OPEN_TIER_RE.match(line)
        if open_match:
            include_stack.append(_tier_marker_allows(open_match.group(1), active))
            continue

        if _CLOSE_TIER_RE.match(line):
            if include_stack:
                include_stack.pop()
            continue

        if all(include_stack):
            out.append(line)

    return "\n".join(out).strip()


def _cfg_get(cfg: Any, key: str) -> Any:
    if isinstance(cfg, dict):
        return cfg.get(key)
    return getattr(cfg, key, None)


def _ollama_num_ctx(role_cfg: Any | None) -> int | None:
    opts = _cfg_get(role_cfg, "ollama_options") if role_cfg is not None else None
    if not isinstance(opts, dict):
        return None
    raw = opts.get("num_ctx")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _model_size_b(model_l: str) -> float | None:
    match = _SIZE_RE.search(model_l)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _tier_marker_allows(marker_value: str, active: PromptTier) -> bool:
    raw_parts = re.split(r"[,|/\s]+", marker_value.strip().lower().replace("-", "_"))
    parts = {p for p in raw_parts if p}
    if not parts:
        return True
    if "all" in parts or "*" in parts:
        return True
    allowed = {_TIER_ALIASES[p] for p in parts if p in _TIER_ALIASES}
    return active in allowed
