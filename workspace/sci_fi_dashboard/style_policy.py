"""Runtime style policy resolution for Synapse chat sessions."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, replace
from threading import RLock
from typing import Any

Tone = str
Length = str
Scope = str
Source = str

DEFAULT_TONE: Tone = "casual_witty"
DEFAULT_LENGTH: Length = "normal"


@dataclass(frozen=True)
class StylePolicy:
    tone: Tone
    length: Length
    scope: Scope
    source: Source
    session_key: str
    reason: str
    updated_at: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt(self) -> str:
        tone_rule = {
            "professional_precise": (
                "Use a professional, precise, restrained voice. Avoid teasing, quirky banter, "
                "slang, emojis, close-friend leg-pulls, and excessive informality."
            ),
            "casual_witty": (
                "Use a relaxed, warm, casual voice while staying useful. Humor is allowed only "
                "when it fits the user's mood and request."
            ),
            "technical_depth": (
                "Prioritize technical depth, correctness, and clear reasoning over personality."
            ),
            "creative_playful": (
                "Use a creative, playful voice, but keep the user's actual request clear."
            ),
        }.get(self.tone, "Use a clear, neutral voice that fits the user's request.")
        length_rule = {
            "concise": (
                "Keep the reply concise. Prefer 1-3 short sentences unless safety or "
                "correctness requires more."
            ),
            "detailed": "Give a fuller answer with enough detail to be useful, but avoid filler.",
            "normal": "Use normal chat length and mirror the user's level of detail.",
        }.get(self.length, "Use normal chat length and mirror the user's level of detail.")
        return (
            "STYLE POLICY - highest priority runtime style contract:\n"
            f"- Tone: {self.tone}. {tone_rule}\n"
            f"- Length: {self.length}. {length_rule}\n"
            f"- Scope: {self.scope}; source: {self.source}.\n"
            f"- Reason: {self.reason}\n"
            "- This policy overrides SBS profile tone, relationship voice, stance defaults, "
            "and compact prompt defaults for this reply."
        )


@dataclass(frozen=True)
class _StyleIntent:
    tone: Tone | None = None
    length: Length | None = None
    scope: Scope = "session"
    reason: str = ""


class SessionStyleStore:
    """Small in-memory store for runtime session style overrides."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._policies: dict[str, StylePolicy] = {}

    def get(self, session_key: str) -> StylePolicy | None:
        with self._lock:
            return self._policies.get(_normalize_session_key(session_key))

    def set(self, policy: StylePolicy) -> StylePolicy:
        with self._lock:
            self._policies[_normalize_session_key(policy.session_key)] = policy
        return policy

    def clear(self, session_key: str | None = None) -> None:
        with self._lock:
            if session_key is None:
                self._policies.clear()
            else:
                self._policies.pop(_normalize_session_key(session_key), None)


class StylePolicyResolver:
    """Resolve one canonical style policy for the current turn."""

    def __init__(self, store: SessionStyleStore | None = None) -> None:
        self.store = store or SessionStyleStore()

    def resolve(
        self,
        user_msg: str,
        session_key: str,
        sbs_profile: dict[str, Any] | None = None,
        history: list | None = None,
    ) -> StylePolicy:
        del history  # reserved for later signals without changing the public call shape
        normalized_key = _normalize_session_key(session_key)
        now = time.time()
        base = self.store.get(normalized_key) or _policy_from_sbs_profile(
            sbs_profile,
            normalized_key,
            now,
        )
        intent = detect_style_intent(user_msg)
        if intent is None:
            return base

        policy = StylePolicy(
            tone=intent.tone or base.tone,
            length=intent.length or base.length,
            scope=intent.scope,
            source="explicit_turn" if intent.scope == "turn" else "session_override",
            session_key=normalized_key,
            reason=intent.reason,
            updated_at=now,
        )
        if intent.scope == "session":
            self.store.set(replace(policy, scope="session", source="session_override"))
        return policy

    def current(
        self,
        session_key: str,
        sbs_profile: dict[str, Any] | None = None,
    ) -> StylePolicy:
        normalized_key = _normalize_session_key(session_key)
        return self.store.get(normalized_key) or _policy_from_sbs_profile(
            sbs_profile,
            normalized_key,
            time.time(),
        )


def detect_style_intent(user_msg: str) -> _StyleIntent | None:
    msg = _normalize_message(user_msg)
    if not msg:
        return None

    tone: Tone | None = None
    length: Length | None = None
    reasons: list[str] = []

    if _matches_any(msg, _PROFESSIONAL_PATTERNS):
        tone = "professional_precise"
        reasons.append("user requested professional/precise tone")
    elif _matches_any(msg, _CASUAL_PATTERNS):
        tone = "casual_witty"
        reasons.append("user requested casual tone")

    if _matches_any(msg, _CONCISE_PATTERNS):
        length = "concise"
        reasons.append("user requested shorter replies")
    elif _matches_any(msg, _DETAILED_PATTERNS):
        length = "detailed"
        reasons.append("user requested more detail")

    if tone is None and length is None:
        return None

    scope = "turn" if _matches_any(msg, _TURN_SCOPE_PATTERNS) else "session"
    return _StyleIntent(
        tone=tone,
        length=length,
        scope=scope,
        reason="; ".join(reasons),
    )


STYLE_POLICY_STORE = SessionStyleStore()
STYLE_POLICY_RESOLVER = StylePolicyResolver(STYLE_POLICY_STORE)


def resolve_style_policy(
    user_msg: str,
    session_key: str,
    sbs_profile: dict[str, Any] | None = None,
    history: list | None = None,
) -> StylePolicy:
    return STYLE_POLICY_RESOLVER.resolve(user_msg, session_key, sbs_profile, history)


def get_current_style_policy(
    session_key: str,
    sbs_profile: dict[str, Any] | None = None,
) -> StylePolicy:
    return STYLE_POLICY_RESOLVER.current(session_key, sbs_profile)


def _policy_from_sbs_profile(
    sbs_profile: dict[str, Any] | None,
    session_key: str,
    now: float,
) -> StylePolicy:
    style = (
        (sbs_profile or {})
        .get("linguistic", {})
        .get("current_style", {})
    )
    interaction = (sbs_profile or {}).get("interaction", {})
    preferred_style = str(style.get("preferred_style") or "").strip()
    tone = {
        "formal_and_precise": "professional_precise",
        "casual_and_witty": "casual_witty",
        "technical_depth": "technical_depth",
        "creative_and_playful": "creative_playful",
    }.get(preferred_style, DEFAULT_TONE)

    avg_length = interaction.get("avg_response_length")
    length = DEFAULT_LENGTH
    try:
        avg = float(avg_length)
        if avg <= 20:
            length = "concise"
        elif avg >= 120:
            length = "detailed"
    except (TypeError, ValueError):
        pass

    source = "sbs_profile" if preferred_style or length != DEFAULT_LENGTH else "default"
    return StylePolicy(
        tone=tone,
        length=length,
        scope="session",
        source=source,
        session_key=session_key,
        reason="resolved from SBS profile" if source == "sbs_profile" else "default style",
        updated_at=now,
    )


def _normalize_session_key(session_key: str | None) -> str:
    value = str(session_key or "default").strip()
    return value or "default"


def _normalize_message(message: str) -> str:
    return " ".join(str(message or "").lower().split())


def _matches_any(message: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(message) for pattern in patterns)


def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


_PROFESSIONAL_PATTERNS = _compile(
    (
        r"\b(be|stay|sound|act)\s+(more\s+)?professional\b",
        r"\bkeep it professional\b",
        r"\buse (a )?professional tone\b",
        r"\buse (a )?formal tone\b",
        r"\bmake (it|this|your tone|the reply|the answer)\s+(more\s+)?(formal|professional)\b",
        r"\bmake this (reply|answer|response|one|turn)\s+(more\s+)?(formal|professional)\b",
        r"\b(be|stay|keep it)\s+serious\b",
        r"\bno jokes?\b",
        r"\bstop joking\b",
        r"\bstop being (quirky|witty|playful|casual)\b",
    )
)

_CASUAL_PATTERNS = _compile(
    (
        r"\b(be|stay|sound|act)\s+(more\s+)?casual\b",
        r"\bmake (it|this|your tone|the reply|the answer)\s+(more\s+)?casual\b",
        r"\bless formal\b",
        r"\bstop being (formal|robotic)\b",
        r"\bdon'?t sound like (a )?robot\b",
        r"\bwhy (are you|so) formal\b",
    )
)

_CONCISE_PATTERNS = _compile(
    (
        r"\btoo long\b",
        r"\bkeep it short\b",
        r"\bmake (it|this|the reply|the answer)\s+short(er)?\b",
        r"\bbe concise\b",
        r"\bshort answer\b",
        r"\bone[- ]liner\b",
        r"\btl;?dr\b",
        r"\bstop yapping\b",
    )
)

_DETAILED_PATTERNS = _compile(
    (
        r"\belaborate\b",
        r"\bexplain more\b",
        r"\bmore detail(s)?\b",
        r"\bbe detailed\b",
        r"\bgo deeper\b",
        r"\btoo short\b",
    )
)

_TURN_SCOPE_PATTERNS = _compile(
    (
        r"\b(just|only)\s+(for\s+)?(this|the)\s+(reply|answer|response|one|turn)\b",
        r"\bfor this (reply|answer|response|one|turn)\b",
        r"\bthis (reply|answer|response|one|turn) only\b",
        r"\bfor now only\b",
    )
)
