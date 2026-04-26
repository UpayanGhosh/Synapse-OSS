"""Prompt-tier policies and markdown filtering for model-sized compilation.

The router can send a turn to anything from a frontier cloud model to a
commodity local model. This module keeps the prompt renderer explicit about
what each class of model can afford.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

PromptTier = Literal["frontier", "mid_open", "small"]

_log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when a model_mappings role has an irreconcilable prompt-tier mismatch."""


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

# ---------------------------------------------------------------------------
# MODEL_TIER_MAP — ordered (regex, tier) rules for cloud + open-weight models.
# Order matters: more-specific patterns MUST come before broader siblings.
# All regexes are matched against the bare model name (provider prefix stripped,
# lower-cased).  First match wins.
# ---------------------------------------------------------------------------
MODEL_TIER_MAP: list[tuple[re.Pattern[str], PromptTier]] = [
    # ── Gemini family ────────────────────────────────────────────────────────
    # flash-lite is smaller than flash; must appear first
    (re.compile(r"gemini-.*-flash-lite"), "small"),  # e.g. gemini-2.5-flash-lite-preview
    # Allow version/date/experiment suffixes: -001, -2024-11-20, -thinking-exp, etc.
    # Uses (-[a-z0-9]+)* to capture any dash-separated suffix segments (e.g.
    # -thinking-exp, -002, -preview).  flash-lite is safe: guarded by the rule above.
    (re.compile(r"gemini-3-flash(-[a-z0-9]+)*$"), "mid_open"),
    (re.compile(r"gemini-.*-flash(-[a-z0-9]+)*$"), "mid_open"),
    (re.compile(r"gemini-3-pro(-[a-z0-9]+)*$"), "frontier"),
    (re.compile(r"gemini-.*-pro(-[a-z0-9]+)*$"), "frontier"),
    (re.compile(r"gemini-.*-ultra"), "frontier"),  # gemini-ultra variants
    # ── Claude family ────────────────────────────────────────────────────────
    # haiku is smaller than sonnet/opus; must appear first
    (re.compile(r"claude-.*-haiku-"), "mid_open"),  # claude-3-haiku-20240307, etc.
    (re.compile(r"claude-.*-(sonnet|opus)-"), "frontier"),  # claude-3/4 sonnet + opus
    (re.compile(r"claude-sonnet|claude-opus"), "frontier"),  # shorthand aliases
    # ── OpenAI GPT family ────────────────────────────────────────────────────
    (re.compile(r"gpt-.*-mini"), "mid_open"),  # gpt-4o-mini, gpt-5-mini — mid not small
    (re.compile(r"gpt-.*-nano"), "small"),  # any hypothetical nano variant
    (re.compile(r"gpt-(4|5)[o]?(-turbo)?$"), "frontier"),  # gpt-4, gpt-4o, gpt-5, gpt-4-turbo
    (re.compile(r"gpt-(4|5)"), "frontier"),  # catch-all for gpt-4* / gpt-5*
    # ── OpenAI o-series reasoning ────────────────────────────────────────────
    # Allow date/version suffixes: o1-2024-12-17, o3-mini-2025-01-31, etc.
    (
        re.compile(r"o[1-4](-mini|-preview|-high|-low)?(-\d{4}-\d{2}-\d{2}|-\d{3,})?$"),
        "frontier",
    ),  # o1, o3, o4, o4-mini, o1-2024-12-17, o3-mini-2025-01-31 — frontier context
    # ── Llama by parameter count ─────────────────────────────────────────────
    (re.compile(r"llama[- _]?3[. _]?[12]?[: _]?(405|70)[b]"), "frontier"),  # 70B / 405B
    (re.compile(r"llama[- _]?3[. _]?[12]?[: _]?(13|34)[b]"), "mid_open"),  # 13B / 34B
    (re.compile(r"llama[- _]?3[. _]?[12]?[: _]?[1-9][b]"), "small"),  # 1B–9B
    (re.compile(r"llama.*70b"), "frontier"),  # llama-guard-70b etc.
    (re.compile(r"llama.*(?<!\d)[1-9]b"), "small"),  # other llama small
    # ── Mistral family ───────────────────────────────────────────────────────
    (re.compile(r"mistral-large"), "frontier"),  # mistral-large-latest
    (re.compile(r"mistral-medium"), "mid_open"),  # mistral-medium
    (re.compile(r"mixtral.*8x2"), "frontier"),  # mixtral-8x22B
    (re.compile(r"mixtral"), "mid_open"),  # mixtral-8x7B
    (re.compile(r"mistral"), "mid_open"),  # mistral-7b, mistral-small
    # ── Qwen family ──────────────────────────────────────────────────────────
    (re.compile(r"qwen.*72b"), "frontier"),  # qwen2.5:72b
    (re.compile(r"qwen.*32b"), "frontier"),  # qwen2.5:32b
    (re.compile(r"qwen.*14b"), "mid_open"),  # qwen2.5:14b
    (re.compile(r"qwen.*7b"), "mid_open"),  # qwen2.5:7b
    (re.compile(r"qwen.*(?<!\d)[1-4]b"), "small"),  # qwen2.5:1.5b / 3b
    # ── Gemma family ─────────────────────────────────────────────────────────
    (re.compile(r"gemma.*27b"), "frontier"),  # gemma2:27b
    (re.compile(r"gemma.*9b"), "mid_open"),  # gemma2:9b
    (re.compile(r"gemma.*(?<!\d)[1-4][b.]"), "small"),  # gemma2:2b, gemma:4b
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    (re.compile(r"deepseek-r[12]"), "frontier"),  # deepseek-r1 / r2 reasoning
    (re.compile(r"deepseek-v3"), "frontier"),  # deepseek-v3
    (re.compile(r"deepseek.*67b"), "frontier"),  # deepseek-coder-33b / 67b
    (re.compile(r"deepseek.*(?<!\d)[1-9]b"), "small"),  # deepseek-coder-6.7b
    # ── Phi / Microsoft small models ─────────────────────────────────────────
    (re.compile(r"phi-?4"), "mid_open"),  # phi-4 (14B class)
    (re.compile(r"phi-?3-medium"), "mid_open"),  # phi-3-medium-14b
    (re.compile(r"phi"), "small"),  # phi-3-mini, phi-3.5-mini
    # ── xAI Grok ─────────────────────────────────────────────────────────────
    (re.compile(r"grok-3$"), "frontier"),  # grok-3
    (re.compile(r"grok-3-mini"), "mid_open"),  # grok-3-mini
    (re.compile(r"grok"), "frontier"),  # grok-2 and other grok variants
    # ── Cohere Command ───────────────────────────────────────────────────────
    (re.compile(r"command-r-plus"), "frontier"),  # command-r-plus
    (re.compile(r"command-r"), "mid_open"),  # command-r
    (re.compile(r"command-light"), "small"),  # command-light
    # ── Groq-hosted (match model name, not provider) ──────────────────────────
    # Groq is an inference provider; tier comes from the underlying model above.
    # ── Generic size catch-alls (lowest priority) ─────────────────────────────
    (re.compile(r":?70b\b"), "frontier"),  # any :70b tag
    # 13–35B mid-weight range — enumerate sizes explicitly to avoid first-digit
    # mismatches (e.g. the digit-greedy pattern would match '2b' inside '22b').
    (re.compile(r":?(13|14|22|27|32|33|34|35)b\b"), "mid_open"),
    # 1B–9B range — (?<!\d) prevents matching the leading digit of multi-digit
    # sizes like 22b or 33b where the catch-all above did not apply.
    (re.compile(r"(?<!\d):?[1-9](\.\d+)?b\b"), "small"),
]

# Ordered tier names for two-tier gap detection
_TIER_ORDER: dict[PromptTier, int] = {"frontier": 0, "mid_open": 1, "small": 2}

# Provider prefixes to strip before model-name matching
_PROVIDER_PREFIXES = (
    "gemini/",
    "anthropic/",
    "openai/",
    "google_antigravity/",
    "ollama_chat/",
    "hosted_vllm/",
    "vllm/",
    "lm_studio/",
    "local/",
    "groq/",
    "openrouter/",
    "claude_cli/",
    "togetherai/",
    "xai/",
    "cohere/",
    "deepseek/",
    "mistral/",
    "vertex_ai/",
    "bedrock/",
    "huggingface/",
    "nvidia_nim/",
    "moonshot/",
    "minimax/",
)

_LOCAL_PREFIXES = (
    "ollama_chat/",
    "hosted_vllm/",
    "vllm/",
    "lm_studio/",
    "local/",
)


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
    explicit = (
        _cfg_get(cfg, "prompt_tier") or _cfg_get(cfg, "capability_tier") or _cfg_get(cfg, "tier")
    )
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


def infer_tier_from_any_model(model: str) -> PromptTier | None:
    """Infer a prompt tier from any model string, cloud or local.

    Steps:
    1. Strip known provider prefix (e.g. ``gemini/``, ``google_antigravity/``).
    2. Walk ``MODEL_TIER_MAP`` regex-by-regex; return first match.
    3. If no regex match AND the model was local-prefixed, fall back to the
       size/context heuristic in ``infer_prompt_tier_from_model``.
    4. Otherwise return ``None`` (unknown model — caller decides).
    """
    if not model:
        return None

    model_l = model.strip().lower()

    # Detect whether the original string had a local prefix before stripping
    is_local = model_l.startswith(_LOCAL_PREFIXES)

    # Strip any known provider prefix
    bare = model_l
    for prefix in _PROVIDER_PREFIXES:
        if bare.startswith(prefix):
            bare = bare[len(prefix) :]
            break

    # Walk MODEL_TIER_MAP — first match wins
    for pattern, tier in MODEL_TIER_MAP:
        if pattern.search(bare):
            return tier

    # No regex hit — fall back to local size heuristic if applicable
    if is_local:
        return infer_prompt_tier_from_model(model_l)

    return None


def validate_role_tier(role: str, cfg: dict, *, strict: bool = False) -> None:
    """Validate that a role's explicit prompt_tier agrees with the inferred tier.

    Severity rules:
    - ``match``     — silent.
    - ``upgrade``   — INFO  (e.g. frontier model with small config — cost shedding).
    - ``downgrade`` — WARNING (e.g. frontier config on a small model — silent truncation risk).
    - ``unknown``   — DEBUG (unrecognised model string — no inference possible).

    When ``strict=True`` AND the mismatch is a *downgrade* of **two or more tiers**
    (e.g. ``frontier`` configured, ``small`` inferred) a ``ConfigError`` is raised.
    An off-by-one downgrade (``frontier``→``mid_open``) only warns in strict mode.

    Parameters
    ----------
    role:
        Role name from ``model_mappings`` (e.g. ``"casual"``).
    cfg:
        The raw dict for this role from ``model_mappings``.
    strict:
        When ``True``, two-tier downgrades raise ``ConfigError`` instead of warning.
    """
    model = str(_cfg_get(cfg, "model") or "")

    # Explicit tier from config (any of the three accepted keys)
    explicit_raw = (
        _cfg_get(cfg, "prompt_tier") or _cfg_get(cfg, "capability_tier") or _cfg_get(cfg, "tier")
    )
    if not explicit_raw:
        # No explicit tier — nothing to validate against
        return

    configured: PromptTier = normalize_prompt_tier(explicit_raw, "frontier")
    inferred: PromptTier | None = infer_tier_from_any_model(model)

    if inferred is None:
        _log.debug(
            "prompt_tier validation: role=%r model=%r — tier unknown, skipping validation",
            role,
            model,
        )
        return

    cfg_rank = _TIER_ORDER[configured]
    inf_rank = _TIER_ORDER[inferred]

    if cfg_rank == inf_rank:
        return  # match — silent

    if cfg_rank < inf_rank:
        # configured is "higher" (frontier=0) than inferred (small=2) → downgrade risk
        gap = inf_rank - cfg_rank
        _log.warning(
            "prompt_tier mismatch for role=%r: configured=%r but model %r infers as %r. "
            "Silent truncation likely — set prompt_tier=%r on this role, "
            "OR switch to a %s-tier model (e.g. gemini-3-pro, claude-sonnet-4, gpt-4o).",
            role,
            configured,
            model,
            inferred,
            inferred,
            configured,
        )
        if strict and gap >= 2:
            raise ConfigError(
                f"[strict] role={role!r}: configured prompt_tier={configured!r} is "
                f"two or more tiers above inferred tier={inferred!r} for model {model!r}. "
                "Set tier_strict_mode=false to warn-only, or fix the model/tier mismatch."
            )
    else:
        # configured is "lower" than inferred → upgrade (deliberate cost/speed shedding)
        _log.info(
            "prompt_tier for role=%r: configured=%r, model %r infers as %r "
            "(deliberate cost/speed shedding — OK).",
            role,
            configured,
            model,
            inferred,
        )


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
