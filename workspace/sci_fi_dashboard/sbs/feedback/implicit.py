import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..profile.manager import ProfileManager

# Built-in fallback patterns (English only) used when language_patterns.yaml is absent.
_DEFAULT_PATTERNS: dict[str, list[str]] = {
    "correction_formal": [
        r"why (are you|so) formal",
        r"stop being (formal|robotic)",
        r"sound[s]? like a robot",
    ],
    "correction_casual": [r"too casual", r"be serious", r"professional"],
    "correction_length": [
        r"too long",
        r"keep it short",
        r"tl;dr",
        r"stop yapping",
        r"too much text",
    ],
    "correction_short": [r"elaborate", r"explain more", r"too short"],
    "praise": [r"good (boy|job)", r"perfect", r"exactly", r"love this tone"],
    "rejection": [r"no that'?s wrong", r"not what i meant", r"shut up"],
}


def _adjust_style_ratio(style: dict[str, Any], delta: float) -> None:
    """Adjust whichever linguistic ratio schema the profile currently uses."""

    ratio_keys = [key for key in ("primary_language_ratio", "banglish_ratio") if key in style]
    if not ratio_keys:
        ratio_keys = ["banglish_ratio"]
    for key in ratio_keys:
        current_ratio = style.get(key, 0.3)
        style[key] = max(0.0, min(1.0, current_ratio + delta))


def _load_patterns() -> dict[str, list[str]]:
    """Load feedback patterns from language_patterns.yaml, falling back to built-ins."""
    yaml_path = Path(__file__).parent / "language_patterns.yaml"
    if yaml_path.exists():
        try:
            import yaml  # PyYAML — listed in requirements

            with open(yaml_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                # Strip comment-only keys and keep non-empty lists
                return {k: v for k, v in data.items() if isinstance(v, list) and v}
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] Could not load language_patterns.yaml: {exc}. Using built-ins.")
    return _DEFAULT_PATTERNS


class ImplicitFeedbackDetector:
    """
    Detects when the user is implicitly correcting or praising the assistant's
    style, tone, or behavior.

    This is NOT for explicit commands (e.g., "Change your name").
    This is for natural conversational feedback (e.g., "Why are you so formal today?")

    Patterns are loaded from ``language_patterns.yaml`` (next to this file).
    If the file is missing, built-in English-only defaults are used instead.
    Add your own language-specific phrases to the YAML to customise detection.
    """

    def __init__(self, profile_manager: ProfileManager):
        self.profile_mgr = profile_manager

        # Load patterns from YAML (or built-in defaults) and compile once
        raw_patterns = _load_patterns()
        self.compiled_patterns = {
            category: [re.compile(p, re.IGNORECASE) for p in patterns]
            for category, patterns in raw_patterns.items()
        }

    def analyze(self, user_text: str, last_assistant_text: str = "") -> dict[str, Any] | None:
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
                    break  # only need one match per category

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
            "matched_text": user_text,  # In a real system, you'd extract the span
            "context": last_assistant_text[:50] + "..." if last_assistant_text else None,
        }

    def apply_feedback(self, signal: dict[str, Any]):
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
            # Increase the user's preferred primary/casual language ratio.
            _adjust_style_ratio(style, 0.2)
            needs_linguistic_update = True

        elif signal_type == "correction_casual":
            # Decrease the user's preferred primary/casual language ratio.
            _adjust_style_ratio(style, -0.2)
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
            # Reinforce current linguistic settings by narrowing variance
            style["confirmed_at"] = datetime.utcnow().isoformat()
            style["praise_count"] = style.get("praise_count", 0) + 1
            needs_linguistic_update = True

        elif signal_type == "rejection":
            # Flag that current style needs review on next batch
            meta = self.profile_mgr.load_layer("meta")
            meta["rejection_pending"] = True
            meta["last_rejection"] = datetime.utcnow().isoformat()
            self.profile_mgr.save_layer("meta", meta)

        if needs_linguistic_update:
            linguistic["current_style"] = style
            self.profile_mgr.save_layer("linguistic", linguistic)

        if needs_interaction_update:
            self.profile_mgr.save_layer("interaction", interaction)
