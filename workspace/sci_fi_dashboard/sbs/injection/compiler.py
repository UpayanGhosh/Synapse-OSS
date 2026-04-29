from ..profile.manager import ProfileManager


class PromptCompiler:
    """
    Compiles the layered persona profile into a single prompt-injectable string.

    Token Budget: ~1500 tokens (approximately 6KB text)

    Priority order (if budget is tight, lower priority gets trimmed):
    1. Core Identity          (~300 tokens) -- NEVER trimmed
    2. Current Emotional State (~100 tokens) -- NEVER trimmed
    3. Active Vocabulary       (~150 tokens) -- trimmed to top 15 words
    4. Communication Style     (~100 tokens) -- trimmed to essentials
    5. Few-Shot Exemplars      (~600 tokens) -- trimmed from 14 to 6 pairs
    6. Domain Context          (~100 tokens) -- trimmed to top 3 domains
    7. Interaction Notes       (~50 tokens)  -- first to be trimmed
    """

    DEFAULT_MAX_CHARS = 6000  # ~1500 tokens at 4 chars per token

    def __init__(self, profile_manager: ProfileManager, max_chars: int = 0):
        self.profile_mgr = profile_manager
        self.MAX_CHARS = max_chars if max_chars > 0 else self.DEFAULT_MAX_CHARS

    def compile(self) -> str:
        """
        Returns a complete persona instruction block ready for
        system prompt injection.
        """
        profile = self.profile_mgr.load_full_profile()

        sections = []
        char_budget = self.MAX_CHARS

        # === SECTION 1: Core Identity (mandatory) ===
        core_block = self._compile_core(profile["core_identity"])
        sections.append(core_block)
        char_budget -= len(core_block)

        # === SECTION 2: Emotional Context (mandatory) ===
        emotional_block = self._compile_emotional(profile["emotional_state"])
        sections.append(emotional_block)
        char_budget -= len(emotional_block)

        # === SECTION 3: Active Vocabulary ===
        vocab_block = self._compile_vocabulary(profile["vocabulary"], char_budget)
        if vocab_block:
            sections.append(vocab_block)
            char_budget -= len(vocab_block)

        # === SECTION 4: Communication Style ===
        style_block = self._compile_style(profile["linguistic"])
        if style_block and len(style_block) < char_budget:
            sections.append(style_block)
            char_budget -= len(style_block)

        # === SECTION 5: Few-Shot Exemplars ===
        exemplar_block = self._compile_exemplars(
            profile["exemplars"], max_chars=min(char_budget, 2400)
        )
        if exemplar_block:
            sections.append(exemplar_block)
            char_budget -= len(exemplar_block)

        # === SECTION 6: Domain Context ===
        domain_block = self._compile_domain(profile["domain"])
        if domain_block and len(domain_block) < char_budget:
            sections.append(domain_block)
            char_budget -= len(domain_block)

        # === SECTION 7: Interaction Notes ===
        interaction_block = self._compile_interaction(profile["interaction"], profile["domain"])
        if interaction_block and len(interaction_block) < char_budget:
            sections.append(interaction_block)

        compiled = "\n\n".join(sections)

        return compiled

    def _compile_core(self, core: dict) -> str:
        pillars = "\n".join(f"  - {p}" for p in core.get("personality_pillars", []))
        red_lines = "\n".join(f"  - {r}" for r in core.get("red_lines", []))

        return f"""[IDENTITY]
You are {core.get("assistant_name", "Synapse")}, {core.get("user_name", "primary_user")}'s {core.get("relationship", "trusted_technical_companion")}.
Call him "{core.get("user_nickname", "user_nickname")}".
Base tone: {core.get("base_tone", "casual_caring_witty")}.
Language default: {core.get("base_language", "banglish_with_english_technical")}.

Personality:
{pillars}

Absolute rules:
{red_lines}"""

    def _compile_emotional(self, emotional: dict) -> str:
        mood = emotional.get("current_dominant_mood", "neutral")
        sentiment = emotional.get("current_sentiment_avg", 0.0)

        # Generate adaptive instruction based on mood
        mood_instructions = {
            "stressed": "He's under pressure right now. Be extra supportive, keep responses concise, offer to help prioritize.",
            "playful": "He's in a good mood. Match his energy, joke around, use more Banglish slang.",
            "tired": "He's fatigued. Keep it short, warm, suggest rest if appropriate.",
            "focused": "He's in deep work mode. Be precise, technical, no fluff.",
            "excited": "He's hyped about something. Share his excitement, be enthusiastic.",
            "frustrated": "Something's annoying him. Be patient, acknowledge the frustration, help solve it.",
            "neutral": "Normal mode. Be your usual self.",
            # Wizard-sourced moods (mapped from energy_level by sbs_profile_init)
            "energetic": "User is high-energy right now. Match their enthusiasm and keep the pace up.",
            "calm": "User prefers a calm, steady interaction. Be measured and thoughtful in tone.",
        }

        instruction = mood_instructions.get(mood, mood_instructions["neutral"])

        return f"""[EMOTIONAL CONTEXT]
Current mood: {mood} (sentiment: {sentiment:+.2f})
Instruction: {instruction}"""

    def _compile_vocabulary(self, vocab: dict, budget: int) -> str:
        top_banglish = vocab.get("top_banglish", {})
        if not top_banglish:
            return ""

        # Take top terms that fit in budget
        terms = list(top_banglish.keys())[:15]
        term_list = ", ".join(terms)

        return f"""[ACTIVE VOCABULARY]
User's current Banglish terms (use these naturally): {term_list}"""

    def _compile_style(self, linguistic: dict) -> str:
        style = linguistic.get("current_style", {})
        banglish_ratio = style.get("banglish_ratio", 0.3)
        drift = style.get("drift_direction", "stable")
        preferred_style = style.get("preferred_style", "")

        # Convert ratio to instruction
        if banglish_ratio > 0.5:
            lang_instruction = "Use heavy Banglish. Most of your response should be in Banglish."
        elif banglish_ratio > 0.25:
            lang_instruction = "Mix Banglish and English naturally. Technical terms in English, casual parts in Banglish."
        else:
            lang_instruction = "Primarily English with occasional Banglish flavor."

        # Map preferred_style (written by setup wizard) to a tone directive
        style_directives = {
            "casual_and_witty": "Keep your tone casual, warm, and witty. Use humor where natural.",
            "formal_and_precise": "Keep your tone professional and precise. Avoid slang or excessive informality.",
            "technical_depth": "Prioritize technical depth and accuracy. Be thorough in explanations.",
            "creative_and_playful": "Be creative and playful in your responses. Use metaphors and colorful language.",
        }
        tone_line = style_directives.get(preferred_style, "")

        return f"""[COMMUNICATION STYLE]
{lang_instruction}
Banglish trend: {drift}.
Avg message length preference: {style.get("avg_message_length", 15)} words.
Emoji usage: {"common" if style.get("emoji_frequency", 0) > 0.2 else "occasional" if style.get("emoji_frequency", 0) > 0.05 else "rare"}.
{tone_line}""".rstrip()

    def _compile_exemplars(self, exemplars: dict, max_chars: int) -> str:
        pairs = exemplars.get("pairs", [])
        if not pairs:
            return ""

        block = "[EXAMPLE INTERACTIONS]\nRespond in a style consistent with these examples:\n\n"

        for _i, pair in enumerate(pairs):
            entry = f'User: "{pair.get("user", "")}"\n{pair.get("context", {}).get("mood", "")} -> Assistant: "{pair.get("assistant", "")}"\n\n'

            if len(block) + len(entry) > max_chars:
                break
            block += entry

        return block.strip()

    def _compile_domain(self, domain: dict) -> str:
        active = domain.get("active_domains", [])
        if not active:
            return ""

        return f"""[CURRENT INTERESTS]
User is currently focused on: {", ".join(active[:3])}.
Tailor technical depth accordingly."""

    def _compile_interaction(self, interaction: dict, domain: dict | None = None) -> str:
        parts = []

        peak = interaction.get("peak_hours", [])
        if peak:
            peak_str = ", ".join(f"{h}:00" for h in peak[:3])
            parts.append(f"User's peak active hours: {peak_str}.")
            parts.append(
                f"Preferred response length: ~{int(interaction.get('avg_response_length', 50))} words."
            )

        # privacy_sensitivity written by setup wizard via sbs_profile_init
        privacy = interaction.get("privacy_sensitivity", "")
        privacy_directives = {
            "open": "User is comfortable with open data storage. Remember details freely for personalization.",
            "selective": "User prefers selective memory. Store key preferences but avoid logging sensitive personal details.",
            "private": "User values maximum privacy. Minimize data retention. Do not reference past conversations unless explicitly asked.",
        }
        if privacy and privacy in privacy_directives:
            parts.append(privacy_directives[privacy])

        preferred_response_style = str(interaction.get("preferred_response_style", "")).strip()
        if preferred_response_style:
            parts.append(f"Preferred response style: {preferred_response_style}.")

        stable_identity_notes: list[str] = []
        if isinstance(domain, dict):
            notes = domain.get("stable_identity_notes")
            if isinstance(notes, list):
                stable_identity_notes = [str(item).strip() for item in notes if str(item).strip()]
            elif isinstance(notes, str) and notes.strip():
                stable_identity_notes = [notes.strip()]
        if stable_identity_notes:
            parts.append(f"Stable identity notes: {'; '.join(stable_identity_notes[:3])}")

        if not parts:
            return ""

        return "[INTERACTION PATTERN]\n" + "\n".join(parts)
