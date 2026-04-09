"""
SkillRunner — executes matched skills with full exception isolation (SKILL-06).

A failing skill NEVER crashes the main conversation loop.
All exceptions are caught, logged, and returned as user-friendly messages.

Extension (Plan 05-03): Generic entry_point dispatch via importlib.util.spec_from_file_location().
- No sys.path manipulation
- No hardcoded skill name checks
- Any skill can declare an entry_point in its SKILL.md for pre-processing before the LLM call
- SkillRunner.execute accepts session_context for privacy guard enforcement
"""

from __future__ import annotations

import importlib.util
import logging
import time
from dataclasses import dataclass

from sci_fi_dashboard.skills.schema import SkillManifest

logger = logging.getLogger(__name__)


@dataclass
class SkillResult:
    """Result of executing a skill."""

    text: str
    skill_name: str
    error: bool = False
    execution_ms: float = 0.0


class SkillRunner:
    """Executes a matched skill with full exception isolation.

    A failing skill NEVER crashes the main conversation loop.
    Errors are caught, logged, and returned as a user-friendly message.

    Entry point dispatch (Plan 05-03):
    If a skill declares entry_point in SKILL.md (e.g.
    "scripts/browser_skill.py:run_browser_skill"), SkillRunner loads and calls
    that function before the LLM call using importlib.util.spec_from_file_location().
    This is entirely generic — no hardcoded skill name checks.
    """

    @staticmethod
    async def execute(
        manifest: SkillManifest,
        user_message: str,
        history: list[dict],
        llm_router,
        session_context: dict | None = None,
    ) -> SkillResult:
        """Execute a skill and return the result. NEVER raises.

        Parameters
        ----------
        manifest : SkillManifest
            The matched skill's metadata.
        user_message : str
            The raw user message that triggered the skill.
        history : list[dict]
            Conversation history to include in the LLM context.
        llm_router : SynapseLLMRouter
            LLM router instance for making the final LLM call.
        session_context : dict | None
            Session metadata passed to entry_point functions.
            Should contain 'session_type' for privacy guard enforcement.
            Backward compatible — defaults to None.

        Returns
        -------
        SkillResult
            Always returns a result. Never raises.
        """
        t0 = time.perf_counter()

        # ------------------------------------------------------------------
        # VAULT HEMISPHERE GUARD — block cloud-calling skills in private sessions
        # ------------------------------------------------------------------
        # cloud_safe: True  = safe in any hemisphere (no external calls)
        # cloud_safe: False = calls external cloud APIs; blocked in spicy/Vault hemisphere
        # session_context=None is treated as safe — never blocks
        if (
            not manifest.cloud_safe
            and session_context is not None
            and session_context.get("session_type") == "spicy"
        ):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return SkillResult(
                text=f"The '{manifest.name}' skill isn't available in private mode.",
                skill_name=manifest.name,
                error=False,
                execution_ms=elapsed_ms,
            )

        # ------------------------------------------------------------------
        # GENERIC ENTRY POINT DISPATCH (importlib-based, no sys.path)
        # ------------------------------------------------------------------
        # If the manifest declares an entry_point, load and call it BEFORE
        # the LLM call. This is fully generic — no hardcoded skill name checks.
        pre_result = None
        if manifest.entry_point:
            try:
                pre_result = await SkillRunner._call_entry_point(
                    manifest, user_message, session_context
                )
                # If the entry point returned a hemisphere block, return immediately
                # without calling the LLM (privacy guard takes priority)
                if (
                    pre_result is not None
                    and hasattr(pre_result, "hemisphere_blocked")
                    and pre_result.hemisphere_blocked
                ):
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    return SkillResult(
                        text=getattr(pre_result, "error", "Blocked by privacy guard."),
                        skill_name=manifest.name,
                        error=False,  # Intentional guard, not an error
                        execution_ms=elapsed_ms,
                    )
            except Exception as exc:
                logger.warning(
                    "[Skills] Entry point '%s' failed: %s", manifest.entry_point, exc
                )
                pre_result = None

        # ------------------------------------------------------------------
        # BUILD LLM MESSAGES with optional pre-processed content
        # ------------------------------------------------------------------
        system_content = (
            manifest.instructions
            or f"You are executing the '{manifest.name}' skill. {manifest.description}"
        )

        web_context = ""
        source_urls: list[str] = []

        if pre_result is not None:
            if hasattr(pre_result, "context_block") and pre_result.context_block:
                web_context = pre_result.context_block
                source_urls = getattr(pre_result, "source_urls", [])
            elif hasattr(pre_result, "error") and pre_result.error:
                web_context = f"[Pre-processing note: {pre_result.error}]"

        if web_context:
            system_content += f"\n\n## Web Content\n\n{web_context}"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # Determine LLM role from manifest hint, fallback to "casual"
        role = manifest.model_hint if manifest.model_hint else "casual"

        # ------------------------------------------------------------------
        # LLM CALL (wrapped in try/except — exceptions become user messages)
        # ------------------------------------------------------------------
        try:
            response = await llm_router.call(role, messages, temperature=0.7, max_tokens=2000)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("[Skills] Executed '%s' in %.0fms", manifest.name, elapsed_ms)

            # Append source URLs if web content was used and LLM didn't cite them (BROWSE-05)
            reply_text = response
            if source_urls:
                urls_block = "\n".join(f"- {u}" for u in source_urls)
                # Only append if the LLM didn't already include them
                if not any(u in reply_text for u in source_urls[:2]):
                    reply_text += f"\n\n**Sources:**\n{urls_block}"

            return SkillResult(
                text=reply_text,
                skill_name=manifest.name,
                error=False,
                execution_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = (
                f"I tried to use the '{manifest.name}' skill but it encountered an error: "
                f"{type(exc).__name__}: {str(exc)[:200]}. "
                f"The conversation can continue normally."
            )
            logger.error("[Skills] Skill '%s' failed: %s", manifest.name, exc, exc_info=True)
            return SkillResult(
                text=error_msg,
                skill_name=manifest.name,
                error=True,
                execution_ms=elapsed_ms,
            )

    @staticmethod
    async def _call_entry_point(
        manifest: SkillManifest,
        user_message: str,
        session_context: dict | None,
    ):
        """Load and call a skill's declared entry_point function via importlib.

        entry_point format: "scripts/browser_skill.py:run_browser_skill"
        - Left of ':' is the script path relative to manifest.path
        - Right of ':' is the async function name to call

        Uses importlib.util.spec_from_file_location() — NO sys.path manipulation.
        The function is called with: fn(user_message=str, session_context=dict|None)

        Parameters
        ----------
        manifest : SkillManifest
            The skill manifest with entry_point and path fields.
        user_message : str
            Passed to the entry point function.
        session_context : dict | None
            Passed to the entry point function (used for privacy guard enforcement).

        Returns
        -------
        Any
            Whatever the entry_point function returns (e.g. BrowserSkillResult).

        Raises
        ------
        ValueError
            If entry_point format is invalid (missing ':').
        FileNotFoundError
            If the referenced script does not exist.
        ImportError
            If the module spec cannot be created.
        AttributeError
            If the function name is not found in the loaded module.
        """
        ep = manifest.entry_point
        if ":" not in ep:
            raise ValueError(f"Invalid entry_point format (expected 'path:func'): {ep}")

        script_rel, func_name = ep.rsplit(":", 1)
        script_path = manifest.path / script_rel

        if not script_path.exists():
            raise FileNotFoundError(f"Entry point script not found: {script_path}")

        # Load the module via importlib — no sys.path mutation
        spec = importlib.util.spec_from_file_location(
            f"skill_{manifest.name}.{script_path.stem}",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for: {script_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        fn = getattr(module, func_name, None)
        if fn is None:
            raise AttributeError(f"Function '{func_name}' not found in {script_path}")

        # Call with standardised arguments
        return await fn(
            user_message=user_message,
            session_context=session_context,
        )
