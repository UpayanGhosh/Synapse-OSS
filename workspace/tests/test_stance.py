from sci_fi_dashboard.stance import decide_turn_stance
from sci_fi_dashboard.style_policy import StylePolicy


def test_venting_stance_allies_before_advice():
    decision = decide_turn_stance(
        "I need to vent. Rohan dumped cleanup on me again and I am pissed.",
        role="casual",
        session_mode="safe",
    )

    prompt = decision.to_prompt()
    assert decision.stance == "ally first, reality-check second"
    assert "Say the annoying part plainly" in prompt
    assert "Do not open with a checklist" in prompt


def test_anxiety_stance_keeps_help_small_and_human():
    decision = decide_turn_stance(
        "I am scared this dinner will get awkward and I will look stupid.",
        role="casual",
        session_mode="safe",
    )

    prompt = decision.to_prompt()
    assert decision.stance == "steady close friend"
    assert decision.humor_dose == "soft micro-tease only if it reduces shame"
    assert "Cut the scary story down to facts" in prompt
    assert "No therapy-template phrasing" in prompt


def test_practical_stance_requires_action_receipts():
    decision = decide_turn_stance(
        "Can you look up the official TVS towing route near Kolkata?",
        role="casual",
        session_mode="safe",
    )

    prompt = decision.to_prompt()
    assert decision.evidence_required is True
    assert decision.stance == "action-first friend operator"
    assert "unless a tool/cron/memory receipt exists" in prompt
    assert "Separate official route from fallback route" in prompt


def test_professional_style_policy_suppresses_friend_stance():
    policy = StylePolicy(
        tone="professional_precise",
        length="normal",
        scope="session",
        source="session_override",
        session_key="cli:the_creator:local",
        reason="user requested professional tone",
        updated_at=0,
    )

    decision = decide_turn_stance(
        "I need to vent. Rohan dumped cleanup on me again and I am pissed.",
        role="casual",
        session_mode="safe",
        style_policy=policy,
    )

    assert decision.stance == "precise operator"
    assert decision.humor_dose == "none unless user invites it"
    assert "friend banter" in decision.to_prompt()
