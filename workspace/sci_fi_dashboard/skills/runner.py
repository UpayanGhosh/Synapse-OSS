"""Skill execution runner with exception isolation (SKILL-06).

SkillRunner.execute() is the boundary between the skill system and the main
pipeline. It is the ONLY place where a skill can fail — no exception ever
propagates beyond this function. All failures are converted to user-friendly
error messages that allow the conversation to continue normally.

Usage::

    result = await SkillRunner.execute(
        manifest=matched_skill,
        user_message=user_msg,
        history=request.history,
        llm_router=deps.synapse_llm_router,
    )
    if result.error:
        # Skill failed, but we still have a user-friendly reply in result.text
        ...
    reply = result.text
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sci_fi_dashboard.skills.schema import SkillManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SkillResult:
    """Result of executing a skill.

    Attributes:
        text:          The reply text to send to the user. Always set —
                       even on error, contains a user-friendly message.
        skill_name:    Name of the skill that produced this result.
        error:         True if the skill raised an exception. False on success.
        execution_ms:  Wall-clock time in milliseconds from call to return.
    """

    text: str
    skill_name: str
    error: bool = False
    execution_ms: float = field(default=0.0)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class SkillRunner:
    """Executes a matched skill with full exception isolation.

    A failing skill NEVER crashes the main conversation loop.
    Errors are caught, logged, and returned as a user-friendly message
    inside a ``SkillResult(error=True)``.

    This class has no instance state — all methods are static so callers
    do not need to manage a SkillRunner singleton.
    """

    @staticmethod
    async def execute(
        manifest: SkillManifest,
        user_message: str,
        history: list[dict],
        llm_router,  # SynapseLLMRouter instance — typed loosely to avoid circular import
    ) -> SkillResult:
        """Execute a skill and return the result. NEVER raises.

        Builds the LLM message list from:
          1. A system message using ``manifest.instructions`` (or a default
             built from name + description when instructions is empty).
          2. The conversation ``history`` (user/assistant turns).
          3. The current ``user_message`` as a user turn.

        Determines the LLM role from ``manifest.model_hint`` — falls back to
        ``"casual"`` when hint is absent.

        Wraps the entire LLM call in a try/except block so any exception
        (network error, timeout, provider error, etc.) is caught and
        converted to an error ``SkillResult`` with a human-readable message.

        Args:
            manifest:     Validated SkillManifest for the skill to execute.
            user_message: Raw user input text.
            history:      Conversation history as a list of
                          ``{"role": str, "content": str}`` dicts.
            llm_router:   SynapseLLMRouter instance. Must have a
                          ``call(role, messages, **kwargs)`` coroutine.

        Returns:
            SkillResult with the response text, skill name, error flag,
            and execution time in milliseconds. Never raises.
        """
        # Build message list: system → history → user turn
        system_content = (
            manifest.instructions
            if manifest.instructions
            else (
                f"You are executing the '{manifest.name}' skill. "
                f"{manifest.description}"
            )
        )
        messages: list[dict] = [
            {"role": "system", "content": system_content},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # Determine LLM role
        role = manifest.model_hint if manifest.model_hint else "casual"

        t0 = time.perf_counter()
        try:
            response = await llm_router.call(
                role, messages, temperature=0.7, max_tokens=2000
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[Skills] Executed '%s' in %.0fms via role='%s'",
                manifest.name,
                elapsed_ms,
                role,
            )
            return SkillResult(
                text=response,
                skill_name=manifest.name,
                error=False,
                execution_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = (
                f"I tried to use the '{manifest.name}' skill but it encountered "
                f"an error: {type(exc).__name__}: {str(exc)[:200]}. "
                f"The conversation can continue normally."
            )
            logger.error(
                "[Skills] Skill '%s' failed after %.0fms: %s",
                manifest.name,
                elapsed_ms,
                exc,
                exc_info=True,
            )
            return SkillResult(
                text=error_msg,
                skill_name=manifest.name,
                error=True,
                execution_ms=elapsed_ms,
            )
