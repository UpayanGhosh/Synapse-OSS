import re
from typing import Optional, Dict, Any
from ..profile.manager import ProfileManager

class ImplicitFeedbackDetector:
    """
    Detects when the user is implicitly correcting or praising the assistant's
    style, tone, or behavior.

    This is NOT for explicit commands (e.g., "Change your name").
    This is for natural conversational feedback (e.g., "Why are you so formal today?")
    """

    # Heuristic patterns for feedback detection
    FEEDBACK_PATTERNS = {
        "correction_formal": [
            r"why (are you|so) formal", r"stop being (formal|robotic)",
            r"sound[s]? like a robot", r"banglish e bolo", r"bengali te kotha bolo"
        ],
        "correction_casual": [
            r"too casual", r"be serious", r"serious hou", r"professional"
        ],
        "correction_length": [
            r"too long", r"keep it short", r"short e bolo", r"tl;dr",
            r"stop yapping", r"too much text"
        ],
        "correction_short": [
            r"elaborate", r"explain more", r"details dao", r"too short"
        ],
        "praise": [
            r"good boy", r"good job", r"perfect", r"exactly",
            r"love this tone", r"darun bolecho", r"sheraa"
        ],
        "rejection": [
            r"no that'?s wrong", r"vul", r"bhul", r"not what i meant",
            r"shut up", r"off ja"
        ]
    }

    def __init__(self, profile_manager: ProfileManager):
        self.profile_mgr = profile_manager

        # Compile regexes once
        self.compiled_patterns = {
            category: [re.compile(p, re.IGNORECASE) for p in patterns]
            for category, patterns in self.FEEDBACK_PATTERNS.items()
        }

    def analyze(self, user_text: str, last_assistant_text: str = "") -> Optional[Dict[str, Any]]:
        """
        Analyze user text for feedback signals.
        If a signal is detected, returns a dict with the signal type and details.
        """
        user_text = user_text.lower()

        detected_signals = []
        for category, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(user_text):
                    detected_signals.append(category)
                    break # only need one match per category

        if not detected_signals:
            return None

        # Prioritize corrections over general praise
        primary_signal = detected_signals[0]
        for signal in detected_signals:
            if signal.startswith("correction_") or signal == "rejection":
                primary_signal = signal
                break

        return {
            "type": primary_signal,
            "matched_text": user_text, # In a real system, you'd extract the span
            "context": last_assistant_text[:50] + "..." if last_assistant_text else None
        }

    def apply_feedback(self, signal: Dict[str, Any]):
        """
        Act on the detected feedback signal to adjust the persona profile immediately.
        """
        signal_type = signal["type"]
        linguistic = self.profile_mgr.load_layer("linguistic")
        interaction = self.profile_mgr.load_layer("interaction")

        needs_linguistic_update = False
        needs_interaction_update = False

        style = linguistic.get("current_style", {})

        if signal_type == "correction_formal":
            # Increase Banglish ratio, reduce average length slightly
            current_ratio = style.get("banglish_ratio", 0.3)
            style["banglish_ratio"] = min(1.0, current_ratio + 0.2)
            needs_linguistic_update = True

        elif signal_type == "correction_casual":
            # Decrease Banglish ratio
            current_ratio = style.get("banglish_ratio", 0.3)
            style["banglish_ratio"] = max(0.0, current_ratio - 0.2)
            needs_linguistic_update = True

        elif signal_type == "correction_length":
            # Drastically reduce preferred response length
            current_len = interaction.get("avg_response_length", 50)
            interaction["avg_response_length"] = max(10, current_len // 2)
            needs_interaction_update = True

        elif signal_type == "correction_short":
            # Increase preferred response length
            current_len = interaction.get("avg_response_length", 50)
            interaction["avg_response_length"] = min(500, current_len * 2)
            needs_interaction_update = True

        elif signal_type == "praise":
            # Reinforce current behavior - hard to do deterministically without LLM,
            # but we can log it for the batch processor's exemplar selector.
            pass

        elif signal_type == "rejection":
            # We could trigger a rollback here if the rejection is strong enough,
            # but for now, we'll just log it.
            pass

        if needs_linguistic_update:
            linguistic["current_style"] = style
            self.profile_mgr.save_layer("linguistic", linguistic)

        if needs_interaction_update:
            self.profile_mgr.save_layer("interaction", interaction)
