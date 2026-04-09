"""
Entry point for synapse.dictionary skill.

Calls the Free Dictionary API (https://dictionaryapi.dev) — no API key required.
Returns definitions, phonetics, and example usage for the requested word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DICT_API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"


@dataclass
class DictionaryResult:
    context_block: str
    source_urls: list[str] = field(default_factory=list)
    error: str = ""


async def get_definition_context(
    user_message: str, session_context: dict | None
) -> DictionaryResult:
    """
    Extract the word to define from user_message, fetch from dictionaryapi.dev,
    and return formatted definition context for the LLM.
    """
    import httpx  # lazy import

    word = _extract_word(user_message)
    if not word:
        return DictionaryResult(
            context_block="",
            error="Could not detect a word to define in the message.",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_DICT_API_BASE}/{word.lower()}",
                headers={"Accept": "application/json"},
            )

            if resp.status_code == 404:
                return DictionaryResult(
                    context_block="",
                    error=f"Word not found in dictionary: {word!r}",
                )

            resp.raise_for_status()
            data = resp.json()

        context_block = _format_definition(word, data)
        return DictionaryResult(
            context_block=context_block,
            source_urls=["https://dictionaryapi.dev"],
        )

    except httpx.HTTPStatusError as exc:
        return DictionaryResult(
            context_block="",
            error=f"HTTP {exc.response.status_code} fetching definition for {word!r}",
        )
    except Exception as exc:  # noqa: BLE001
        return DictionaryResult(
            context_block="",
            error=f"Unexpected error: {exc}",
        )


def _extract_word(text: str) -> str:
    """
    Pull the target word from natural-language definition queries.

    Handles patterns like:
      "define serendipity"
      "what does ephemeral mean"
      "meaning of ubiquitous"
      "definition of cogent"
      "what is the word for X"
      "dictionary: luminous"
    """
    text = text.strip()

    patterns = [
        r"\bdefin(?:e|ition\s+of)\s+([A-Za-z\-]+)",
        r"\bmeaning\s+of\s+([A-Za-z\-]+)",
        r"\bwhat\s+does\s+([A-Za-z\-]+)\s+mean",
        r"\blook\s+up\s+([A-Za-z\-]+)",
        r"\bdictionary[:\s]+([A-Za-z\-]+)",
        r"\bword\s+for\s+([A-Za-z\-]+)",
        r"\bwhat\s+is\s+([A-Za-z\-]+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Last resort: grab the last standalone capitalised or standalone word
    words = re.findall(r"\b[A-Za-z]{3,}\b", text)
    # Filter out common question words
    stop = {"what", "does", "mean", "define", "the", "a", "an", "is", "are", "how",
            "can", "you", "tell", "me", "about", "please", "dictionary", "meaning",
            "definition", "word", "for", "look", "up"}
    candidates = [w for w in words if w.lower() not in stop]
    return candidates[-1] if candidates else ""


def _format_definition(word: str, data: list[dict]) -> str:
    """
    Format dictionaryapi.dev JSON response into a readable context block.
    """
    if not data or not isinstance(data, list):
        return ""

    entry = data[0]
    lines = [f"Dictionary entry for: {word}"]

    # Phonetics
    phonetics = entry.get("phonetics", [])
    phonetic_text = next(
        (p.get("text", "") for p in phonetics if p.get("text")), ""
    )
    if phonetic_text:
        lines.append(f"Pronunciation: {phonetic_text}")

    lines.append("")  # blank line

    # Meanings
    for meaning in entry.get("meanings", []):
        pos = meaning.get("partOfSpeech", "")
        lines.append(f"[{pos}]" if pos else "[unknown]")

        definitions = meaning.get("definitions", [])
        for i, defn in enumerate(definitions[:3], 1):  # cap at 3 per part-of-speech
            definition_text = defn.get("definition", "")
            example = defn.get("example", "")
            lines.append(f"  {i}. {definition_text}")
            if example:
                lines.append(f'     Example: "{example}"')

        # Synonyms
        synonyms = meaning.get("synonyms", [])[:5]
        if synonyms:
            lines.append(f"  Synonyms: {', '.join(synonyms)}")

        lines.append("")  # blank line between parts of speech

    lines.append("Source: https://dictionaryapi.dev")
    return "\n".join(lines)
