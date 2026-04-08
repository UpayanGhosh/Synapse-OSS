"""
ConsentProtocol — explain→confirm→execute→snapshot cycle for Zone 2 modifications.

Every Zone 2 modification (skills/, state/agents/) must pass through ConsentProtocol:
  1. explain()              — generate a plain-language description (MOD-01)
  2. confirm_and_execute()  — pre-snapshot, execute, post-snapshot; auto-revert on failure (MOD-03)

Security:
  - T-02-02: PendingConsent is scoped to (session_id, sender_id). Confirmation from a
    different sender or session is rejected.
  - PendingConsent has a 5-minute TTL; expired consents are discarded without execution.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sci_fi_dashboard.sbs.sentinel.manifest import ZONE_2_DESCRIPTIONS
from sci_fi_dashboard.snapshot_engine import SnapshotEngine

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ModificationIntent:
    """A detected intent to modify a Zone 2 path."""

    description: str
    """Human-readable description, e.g. 'Create a medication reminder skill'."""

    change_type: str
    """One of: 'create_skill' | 'create_cron' | 'delete_skill' | 'modify_config'."""

    target_zone2: str
    """Which ZONE_2_PATHS entry is targeted: 'skills' or 'state/agents'."""

    details: dict = field(default_factory=dict)
    """Extra context passed to the executor function."""


@dataclass
class PendingConsent:
    """A consent request waiting for user confirmation.

    Scoped to a single (session_id, sender_id) pair (T-02-02).
    Expires after ``ttl_seconds`` seconds.
    """

    intent: ModificationIntent
    session_id: str
    """Unique session identifier — prevents cross-session hijacking."""

    sender_id: str
    """Who initiated the request — confirmation must come from the same sender."""

    explanation: str
    """The explanation text already shown to the user."""

    created_at: float
    """``time.time()`` at creation."""

    ttl_seconds: float = 300.0
    """How long the pending consent remains valid (default 5 minutes)."""

    @property
    def is_expired(self) -> bool:
        """Return True if the consent window has elapsed."""
        return (time.time() - self.created_at) > self.ttl_seconds


# ---------------------------------------------------------------------------
# ConsentProtocol
# ---------------------------------------------------------------------------


class ConsentProtocol:
    """Orchestrate the explain→confirm→execute→snapshot cycle for Zone 2 mods."""

    def __init__(self, snapshot_engine: SnapshotEngine) -> None:
        self._snapshot_engine = snapshot_engine
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain(self, intent: ModificationIntent) -> str:
        """Generate a plain-language explanation of the proposed change (MOD-01).

        Returns a string suitable for sending directly to the user.
        """
        zone_desc = ZONE_2_DESCRIPTIONS.get(intent.target_zone2, intent.target_zone2)
        return (
            f"I'd like to make a change: {intent.description}\n\n"
            f"This will modify: {zone_desc}\n"
            f"Change type: {intent.change_type}\n\n"
            "Shall I proceed? (yes / no)"
        )

    async def confirm_and_execute(
        self,
        intent: ModificationIntent,
        executor_fn: Callable[..., Awaitable[Any]],
    ) -> dict:
        """Execute a Zone 2 modification with snapshot bracketing.

        Steps (MOD-02, MOD-03):
          1. Create a pre-modification snapshot.
          2. Call ``executor_fn()``.
          3a. On success: create a post-modification snapshot and return status="success".
          3b. On failure: call ``restore(pre_snapshot_id)`` and return status="reverted".

        Args:
            intent: The modification to perform.
            executor_fn: An async callable that performs the actual change.

        Returns:
            dict with keys: ``status`` ("success" | "reverted"),
            ``result`` (on success), ``snapshot_id`` (on success),
            ``error`` (on failure), ``reverted_to`` (on failure).
        """
        # Step 1 — pre-snapshot
        pre_snapshot = self._snapshot_engine.create(
            description=f"pre: {intent.description}",
            change_type="pre_modification",
        )
        self._logger.info("Pre-snapshot created: %s", pre_snapshot.id)

        try:
            # Step 2 — execute
            result = await executor_fn()

            # Step 3a — post-snapshot on success
            post_snapshot = self._snapshot_engine.create(
                description=intent.description,
                change_type=intent.change_type,
            )
            self._logger.info("Post-snapshot created: %s", post_snapshot.id)

            return {
                "status": "success",
                "result": result,
                "snapshot_id": post_snapshot.id,
            }

        except Exception as exc:  # noqa: BLE001
            # Step 3b — auto-revert on failure (MOD-03)
            self._logger.error(
                "Modification failed (%s), reverting to %s",
                exc,
                pre_snapshot.id,
            )
            try:
                self._snapshot_engine.restore(pre_snapshot.id)
            except Exception as restore_exc:  # noqa: BLE001
                self._logger.critical("CRITICAL: Restore also failed: %s", restore_exc)

            return {
                "status": "reverted",
                "error": str(exc),
                "reverted_to": pre_snapshot.id,
            }


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_SKILL_PATTERNS = [
    "create a skill",
    "make a skill",
    "build a skill",
    "add a new skill",
    "create skill",
    "new skill",
]

_CRON_PATTERNS = [
    "remind me",
    "set a reminder",
    "schedule",
    "every day at",
    "every morning",
    "every evening",
    "create a cron",
    "recurring task",
]


async def detect_modification_intent(
    user_msg: str,
    llm_router: Any = None,
) -> ModificationIntent | None:
    """Detect whether a user message implies a Zone 2 modification.

    This is a keyword heuristic. Plan 02-04 may enhance with LLM classification.
    Returns None for normal conversational messages.

    Args:
        user_msg: The raw user message.
        llm_router: Unused by this implementation; reserved for LLM-based upgrade.

    Returns:
        A ``ModificationIntent`` if a modification is detected, else ``None``.
    """
    msg_lower = user_msg.lower()

    for pattern in _SKILL_PATTERNS:
        if pattern in msg_lower:
            return ModificationIntent(
                description=user_msg,
                change_type="create_skill",
                target_zone2="skills",
            )

    for pattern in _CRON_PATTERNS:
        if pattern in msg_lower:
            return ModificationIntent(
                description=user_msg,
                change_type="create_cron",
                target_zone2="state/agents",
            )

    return None


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

_AFFIRMATIVE = frozenset(
    {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "go ahead", "proceed", "do it"}
)
_NEGATIVE = frozenset(
    {"no", "n", "nah", "nope", "cancel", "stop", "don't", "dont", "nevermind"}
)


def is_affirmative(text: str) -> bool:
    """Return True if *text* is a recognised affirmative response."""
    return text.strip().lower() in _AFFIRMATIVE


def is_negative(text: str) -> bool:
    """Return True if *text* is a recognised negative response."""
    return text.strip().lower() in _NEGATIVE
