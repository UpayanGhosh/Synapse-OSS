"""Skill creator — generates new skill directories from conversation (SKILL-04).

SkillCreator.create() is the filesystem primitive: takes a name/description and
writes a valid skill directory with SKILL.md + optional subdirectories.

SkillCreator.generate_from_conversation() is the LLM layer: extracts skill
parameters from natural language, then calls create().

Security mitigations:
- T-01-16: _normalize_name strips everything except a-z, 0-9, hyphens; path
  traversal is impossible since the sanitized name is path-joined to skills_dir.
- T-01-17: LLM JSON output is parsed with error handling; invalid JSON returns
  a failure dict, never triggering arbitrary filesystem writes.
- T-01-18: Existence check prevents overwriting; requires explicit ValueError
  resolution before a second write can succeed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sci_fi_dashboard.skills.loader import SkillLoader
from sci_fi_dashboard.skills.schema import OPTIONAL_SUBDIRS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML frontmatter delimiter
# ---------------------------------------------------------------------------

_YAML_DELIM = "---"

# ---------------------------------------------------------------------------
# Extraction prompt — instructs the LLM to return JSON skill parameters
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are a skill parameter extractor. The user wants to create a new Synapse skill.
Extract the skill parameters from their request and return ONLY a valid JSON object.

JSON format (all fields required):
{
  "name": "<lowercase-hyphenated 2-5 words>",
  "description": "<one sentence describing what the skill does>",
  "instructions": "<detailed instructions for the skill>",
  "triggers": ["<trigger phrase 1>", "<trigger phrase 2>"],
  "model_hint": "<one of: casual, code, analysis, review>"
}

Rules for name:
- Lowercase letters, numbers, and hyphens only
- 2 to 5 words joined by hyphens
- Descriptive and unique (e.g. "weather-checker", "code-reviewer", "joke-teller")

Rules for description:
- One clear sentence, under 100 characters

Rules for model_hint:
- casual: conversational tasks
- code: anything involving programming
- analysis: research, data, deep reasoning
- review: evaluation, feedback, critique

Return ONLY the JSON object — no prose, no markdown fences, no extra explanation.
"""


# ---------------------------------------------------------------------------
# SKILL.md builder
# ---------------------------------------------------------------------------


def _build_skill_md(
    name: str,
    description: str,
    instructions: str,
    triggers: list[str],
    model_hint: str,
) -> str:
    """Build SKILL.md content with valid YAML frontmatter + instructions body."""
    display_name = name.replace("-", " ").title()
    triggers_yaml = json.dumps(triggers)  # produces valid YAML-compatible inline list

    lines = [
        _YAML_DELIM,
        f"name: {name}",
        f'description: "{description}"',
        'version: "1.0.0"',
        'author: "synapse-skill-creator"',
        f"triggers: {triggers_yaml}",
        f'model_hint: "{model_hint}"',
        "permissions: []",
        _YAML_DELIM,
        "",
        f"# {display_name}",
        "",
        instructions,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SkillCreator
# ---------------------------------------------------------------------------


class SkillCreator:
    """Creates new skill directories from user conversation requests.

    Primary entry points:
        create()                  — filesystem primitive (sync)
        generate_from_conversation() — LLM extraction layer (async)
    """

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Convert a name to lowercase-hyphenated format.

        - Strips whitespace
        - Lowercases everything
        - Removes characters that are not a-z, 0-9, space, or hyphen
        - Collapses consecutive spaces/hyphens into a single hyphen
        - Strips leading/trailing hyphens
        """
        name = name.strip().lower()
        name = re.sub(r"[^a-z0-9\s-]", "", name)
        name = re.sub(r"[\s-]+", "-", name)
        return name.strip("-")

    @staticmethod
    def create(
        name: str,
        description: str,
        skills_dir: Path,
        instructions: str = "",
        triggers: list[str] | None = None,
        model_hint: str = "casual",
    ) -> Path:
        """Create a new skill directory with SKILL.md and all OPTIONAL_SUBDIRS.

        Args:
            name:         Skill name — will be normalized to lowercase-hyphenated.
            description:  Human-readable description.
            skills_dir:   Parent directory where the new skill directory is created.
            instructions: Markdown body for SKILL.md; defaults to a generic message.
            triggers:     Trigger phrases for the skill; defaults to empty list.
            model_hint:   LLM role hint; defaults to "casual".

        Returns:
            Path to the created skill directory.

        Raises:
            ValueError: If a skill with the same name already exists.
        """
        # Normalize name — T-01-16: only a-z, 0-9, hyphen survive
        name = SkillCreator._normalize_name(name)

        skill_dir = skills_dir / name
        if skill_dir.exists():
            raise ValueError(f"Skill '{name}' already exists at {skill_dir}")

        # Create skill directory + all OPTIONAL_SUBDIRS (per SKILL-01)
        skill_dir.mkdir(parents=True, exist_ok=False)
        for subdir in OPTIONAL_SUBDIRS:
            (skill_dir / subdir).mkdir()

        # Build default instructions if none provided
        if not instructions:
            instructions = f"Execute the '{name}' skill. {description}"

        # Build and write SKILL.md
        skill_md_content = _build_skill_md(
            name=name,
            description=description,
            instructions=instructions,
            triggers=triggers or [],
            model_hint=model_hint,
        )
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

        # Validate the generated skill — T-01-17: catch any issues immediately
        try:
            SkillLoader.load_skill(skill_dir)
        except Exception as exc:
            logger.error(
                "[SkillCreator] Generated skill at %s failed SkillLoader validation: %s",
                skill_dir,
                exc,
            )
            # Don't delete — caller can inspect or clean up
            raise

        logger.info("[SkillCreator] Created skill '%s' at %s", name, skill_dir)
        return skill_dir

    @classmethod
    async def generate_from_conversation(
        cls,
        user_message: str,
        skills_dir: Path,
        llm_router,
    ) -> dict:
        """Use the LLM to extract skill parameters from a user message, then create.

        Makes one LLM call using the "analysis" role with EXTRACTION_PROMPT as
        the system message and the user's message as the user turn.  Parses
        the response as JSON (also handles JSON embedded in markdown code blocks).

        Args:
            user_message: Natural language request ("create a skill that checks weather").
            skills_dir:   Target directory for the new skill.
            llm_router:   SynapseLLMRouter instance (or compatible mock).

        Returns:
            Success dict:  {"skill_name": str, "skill_path": str, "message": str}
            Failure dict:  {"message": str, "error": str}
        """
        try:
            messages = [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": user_message},
            ]
            raw_response = await llm_router.call(
                "analysis", messages, temperature=0.3, max_tokens=800
            )

            # T-01-17: parse JSON; handle bare JSON or markdown code block
            params = cls._parse_json_response(raw_response)

            # Validate minimum required keys
            name = params.get("name", "").strip()
            description = params.get("description", "").strip()
            if not name or not description:
                return {
                    "message": (
                        "I couldn't extract a skill name or description from the response. "
                        "Please try describing the skill more clearly."
                    ),
                    "error": "missing_fields",
                }

            skill_dir = cls.create(
                name=name,
                description=description,
                skills_dir=skills_dir,
                instructions=params.get("instructions", ""),
                triggers=params.get("triggers") or [],
                model_hint=params.get("model_hint", "casual"),
            )

            return {
                "skill_name": skill_dir.name,
                "skill_path": str(skill_dir),
                "message": (
                    f"Skill '{skill_dir.name}' created at {skill_dir}. "
                    "It will be available after the next hot-reload cycle."
                ),
            }

        except ValueError as exc:
            # Skill already exists, invalid name, etc.
            return {
                "message": str(exc),
                "error": "value_error",
            }
        except Exception as exc:
            logger.error("[SkillCreator] generate_from_conversation failed: %s", exc, exc_info=True)
            return {
                "message": (
                    f"Skill creation failed: {type(exc).__name__}: {str(exc)[:200]}. "
                    "Please try again."
                ),
                "error": "unexpected_error",
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_response(raw: str) -> dict:
        """Parse a JSON string from an LLM response.

        Handles:
        1. Bare JSON object
        2. JSON embedded in a markdown code block (```json ... ```)
        3. JSON embedded in a plain code block (``` ... ```)

        Raises:
            ValueError: If no valid JSON object can be extracted.
        """
        # Try bare JSON first
        stripped = raw.strip()
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the response
        json_match = re.search(r"\{[^{}]*\}", stripped, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        raise ValueError(f"No valid JSON object found in LLM response: {raw[:200]!r}")
