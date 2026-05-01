"""Turn-level stance selection for human-feeling replies.

This is the runtime contract that turns affect/memory/cognition signals into
behavioral pressure. It is deliberately deterministic so every channel path gets
the same guardrails before the LLM writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StanceDecision:
    """A compact behavior contract for the next assistant reply."""

    stance: str
    emotional_label: str
    humor_dose: str
    autonomy: str
    response_shape: tuple[str, ...] = field(default_factory=tuple)
    forbidden_moves: tuple[str, ...] = field(default_factory=tuple)
    evidence_required: bool = False

    def to_prompt(self) -> str:
        shape = "\n".join(f"- {item}" for item in self.response_shape)
        forbidden = "\n".join(f"- {item}" for item in self.forbidden_moves)
        evidence = (
            "- Do not claim you checked, saved, sent, scheduled, or found anything unless a tool/cron/memory receipt exists."
            if self.evidence_required
            else "- If you did not use a tool, speak from judgment and say what you would do next."
        )
        return (
            "TURN STANCE DECISION - runtime contract for this reply:\n"
            f"- Stance: {self.stance}\n"
            f"- Emotion read: {self.emotional_label}\n"
            f"- Humor/teasing dose: {self.humor_dose}\n"
            f"- Autonomy level: {self.autonomy}\n"
            f"{evidence}\n"
            "Response shape:\n"
            f"{shape or '- React like a close friend, then make one useful move.'}\n"
            "Forbidden moves:\n"
            f"{forbidden or '- No generic AI/customer-support phrasing.'}"
        )


def decide_turn_stance(
    user_msg: str,
    *,
    role: str = "casual",
    session_mode: str = "safe",
    cognitive_merge=None,
) -> StanceDecision:
    """Choose stance, humor dose, and autonomy from the current user turn."""

    msg = " ".join(str(user_msg or "").lower().split())
    role_l = str(role or "").lower()
    strategy = str(getattr(cognitive_merge, "response_strategy", "") or "").lower()
    tone = str(getattr(cognitive_merge, "suggested_tone", "") or "").lower()
    tension = float(getattr(cognitive_merge, "tension_level", 0.0) or 0.0)

    if session_mode == "spicy" or role_l != "casual":
        return StanceDecision(
            stance="precise operator",
            emotional_label="task focused",
            humor_dose="none unless user invites it",
            autonomy="answer directly, use tools only when needed",
            response_shape=(
                "Give the useful answer first.",
                "Keep personality light; do not force closeness into non-casual work.",
            ),
            forbidden_moves=("Do not perform friend banter where precision is more important.",),
        )

    high_distress = any(
        marker in msg
        for marker in (
            "panic",
            "panicking",
            "can't breathe",
            "cant breathe",
            "unsafe",
            "hurt myself",
            "kill myself",
            "suicide",
        )
    )
    if high_distress:
        return StanceDecision(
            stance="steady safety anchor",
            emotional_label="acute distress",
            humor_dose="none",
            autonomy="slow down, stabilize, suggest immediate support if safety risk exists",
            response_shape=(
                "Name the distress plainly and stay with them.",
                "Give one immediate grounding or safety move.",
                "Ask one concrete check-in question.",
            ),
            forbidden_moves=(
                "No sarcasm, roasting, or productivity advice.",
                "No long lists.",
            ),
        )

    practical = any(
        marker in msg
        for marker in (
            "look up",
            "search",
            "find",
            "check",
            "book",
            "tow",
            "service centre",
            "service center",
            "official",
            "near me",
            "price",
            "weather",
        )
    )
    if practical:
        return StanceDecision(
            stance="action-first friend operator",
            emotional_label="needs practical help",
            humor_dose="tiny if stress is low",
            autonomy="do/check when safe, then report receipts",
            response_shape=(
                "Acknowledge the hassle in one human line.",
                "Use available evidence/results directly.",
                "Separate official route from fallback route.",
                "Give exact next steps.",
            ),
            forbidden_moves=(
                "Do not say 'one sec' unless an actual tool call is running.",
                "Do not end with a vague offer when the next step is obvious.",
            ),
            evidence_required=True,
        )

    venting = any(
        marker in msg
        for marker in (
            "vent",
            "rant",
            "bitch",
            "pissed",
            "annoyed",
            "irritated",
            "dumped",
            "unfair",
            "toxic",
            "office politics",
        )
    )
    if venting:
        return StanceDecision(
            stance="ally first, reality-check second",
            emotional_label="anger or frustration",
            humor_dose="light bite if the user is not ashamed",
            autonomy="join the feeling before advice",
            response_shape=(
                "Say the annoying part plainly.",
                "Give one opinion with spine.",
                "Only then offer the adult move or pushback.",
            ),
            forbidden_moves=(
                "Do not open with a checklist.",
                "Do not only validate; disagree if the user is being unfair.",
                "Do not end every vent with 'I can help draft a message'.",
            ),
        )

    anxious = any(
        marker in msg
        for marker in (
            "anxious",
            "scared",
            "fear",
            "stressed",
            "pressure",
            "nervous",
            "worried",
            "awkward",
            "look stupid",
        )
    )
    if anxious or strategy == "support" or tone in {"concerned", "warm"} and tension >= 0.45:
        return StanceDecision(
            stance="steady close friend",
            emotional_label="anxiety or insecurity",
            humor_dose="soft micro-tease only if it reduces shame",
            autonomy="one grounding move, one next step",
            response_shape=(
                "Normalize the feeling without sounding clinical.",
                "Cut the scary story down to facts.",
                "Give one small move the user can do now.",
            ),
            forbidden_moves=(
                "No therapy-template phrasing.",
                "No big menus or over-explaining.",
            ),
        )

    romance = any(marker in msg for marker in ("crush", "love", "date", "birthday dinner"))
    if romance:
        return StanceDecision(
            stance="playful hype, then ground",
            emotional_label="romance or affection",
            humor_dose="one gentle leg-pull",
            autonomy="help shape the move without taking over",
            response_shape=(
                "React like a friend who is invested.",
                "Tease lightly once.",
                "Give the clean, emotionally safe move.",
            ),
            forbidden_moves=(
                "Do not turn romance into a dating checklist.",
                "Do not overplay sarcasm when the user feels exposed.",
            ),
        )

    tender = any(
        marker in msg
        for marker in ("sad", "hurt", "lonely", "alone", "jealous", "guilty", "small")
    )
    if tender:
        return StanceDecision(
            stance="soft but not syrupy",
            emotional_label="tenderness or attachment pain",
            humor_dose="very light only after care lands",
            autonomy="stay present, then offer one grounded interpretation",
            response_shape=(
                "Meet the feeling first.",
                "Separate fact from story.",
                "Offer one kind, practical next move.",
            ),
            forbidden_moves=("No empty reassurance. No robotic empathy labels.",),
        )

    if strategy == "challenge" or tone == "firm" or tension > 0.55:
        return StanceDecision(
            stance="protective pushback",
            emotional_label="possible contradiction or overreach",
            humor_dose="none to light",
            autonomy="challenge gently with evidence",
            response_shape=(
                "Name what does not add up.",
                "Be on the user's side while refusing the bad premise.",
                "Give the safer path.",
            ),
            forbidden_moves=("Do not flatter a bad plan.", "Do not sound like a scolding policy bot."),
        )

    return StanceDecision(
        stance="warm operator friend",
        emotional_label="ordinary life update",
        humor_dose="light if natural",
        autonomy="react, then make one useful move",
        response_shape=(
            "React with a human stance.",
            "Use memory/context if relevant.",
            "Give one concrete next move or opinion.",
        ),
        forbidden_moves=("No generic helper ending.", "No customer-support voice."),
    )
