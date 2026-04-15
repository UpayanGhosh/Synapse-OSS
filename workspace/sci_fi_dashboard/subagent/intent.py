"""Spawn intent detection — conservative keyword gate for sub-agent delegation.

This module detects whether a user message is a request to delegate a task
to a background sub-agent.  The detection is intentionally conservative:
false negatives are acceptable (the user can rephrase), false positives are
not (a normal question mistakenly spawned would be jarring).

No LLM calls are made here — pure string matching only.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword / prefix definitions
# ---------------------------------------------------------------------------

# Full trigger phrases that, when found at the START of a message, indicate
# a spawn intent.  Lowercase only — input is lowercased before comparison.
SPAWN_PREFIXES: tuple[str, ...] = (
    "can you research",
    "go research",
    "please research",
    "research and summarize",
    "look up and summarize",
    "find out about",
    "investigate and report",
)

# Single keywords / short phrases that trigger detection when they appear at
# the START of a message (i.e. the message *begins* with this word/phrase
# followed by a space and then the topic).
SPAWN_KEYWORDS: frozenset[str] = frozenset(
    {
        "research",
        "look up",
        "look into",
        "find out",
        "investigate",
        "dig into",
        "analyze in background",
        "summarize for me",
        "compile a list",
        "gather information",
    }
)

# Inline markers — if these phrases appear anywhere in the message the entire
# message (cleaned) is treated as a spawn intent.
_BACKGROUND_MARKERS: tuple[str, ...] = (
    "in the background",
    "in background",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_spawn_intent(message: str) -> tuple[bool, str]:
    """Detect whether *message* is a request to spawn a background sub-agent.

    Parameters
    ----------
    message:
        Raw user message string (any casing).

    Returns
    -------
    (is_spawn, task_description)
        ``is_spawn`` is ``True`` if the message matches a spawn pattern.
        ``task_description`` is the cleaned-up task description to pass to the
        agent.  Returns ``(False, "")`` when no spawn intent is detected.

    Detection priority
    ------------------
    1. SPAWN_PREFIXES — multi-word prefix match (highest specificity).
    2. Background-marker phrases ("in the background") — presence anywhere.
    3. SPAWN_KEYWORDS — single-word / short-phrase prefix match.
    """
    clean = message.strip()
    lower = clean.lower()

    # 1. Multi-word prefix match (most specific — check first).
    for prefix in SPAWN_PREFIXES:
        if lower.startswith(prefix):
            remainder = clean[len(prefix) :].strip()
            logger.debug("detect_spawn_intent: prefix=%r matched, task=%r", prefix, remainder)
            return (True, remainder) if remainder else (False, "")

    # 2. Background-marker phrase anywhere in the message.
    for marker in _BACKGROUND_MARKERS:
        if marker in lower:
            # Strip the marker and surrounding whitespace from the message.
            task_desc = lower.replace(marker, "").strip(" ,.")
            # Use original casing from the cleaned input for the task description.
            clean.lower().replace(marker, "").strip(" ,.")
            # Preserve original case by removing the marker from the original string.
            task_desc = clean
            for m in _BACKGROUND_MARKERS:
                task_desc = task_desc.replace(m, "").replace(m.title(), "")
            task_desc = task_desc.strip(" ,.")
            logger.debug(
                "detect_spawn_intent: background marker=%r matched, task=%r",
                marker,
                task_desc,
            )
            return (True, task_desc) if task_desc else (False, "")

    # 3. Single keyword / short-phrase prefix match.
    for keyword in SPAWN_KEYWORDS:
        if lower.startswith(keyword + " "):
            remainder = clean[len(keyword) :].strip()
            logger.debug("detect_spawn_intent: keyword=%r matched, task=%r", keyword, remainder)
            return (True, remainder) if remainder else (False, "")

    logger.debug("detect_spawn_intent: no spawn intent in %r", message[:60])
    return (False, "")
