from sci_fi_dashboard.style_policy import (
    SessionStyleStore,
    StylePolicyResolver,
    detect_style_intent,
)


def _resolver() -> StylePolicyResolver:
    return StylePolicyResolver(SessionStyleStore())


def test_explicit_professional_policy_persists_for_session():
    resolver = _resolver()

    first = resolver.resolve("Be professional and keep it short.", "cli:the_creator:local")
    second = resolver.resolve("Now help me write the update.", "cli:the_creator:local")

    assert first.tone == "professional_precise"
    assert first.length == "concise"
    assert first.scope == "session"
    assert first.source == "session_override"
    assert second.tone == "professional_precise"
    assert second.length == "concise"
    assert second.source == "session_override"


def test_turn_only_policy_does_not_persist():
    resolver = _resolver()

    turn = resolver.resolve(
        "Make this answer professional, just for this reply.",
        "cli:the_creator:local",
    )
    later = resolver.resolve("Back to normal?", "cli:the_creator:local")

    assert turn.tone == "professional_precise"
    assert turn.scope == "turn"
    assert turn.source == "explicit_turn"
    assert later.tone == "casual_witty"
    assert later.source == "default"


def test_session_style_isolated_by_session_key():
    resolver = _resolver()

    resolver.resolve("Be professional.", "cli:the_creator:a")
    other = resolver.resolve("Hello", "cli:the_creator:b")

    assert other.tone == "casual_witty"
    assert other.source == "default"


def test_sbs_profile_used_when_no_runtime_override():
    resolver = _resolver()
    profile = {
        "linguistic": {"current_style": {"preferred_style": "formal_and_precise"}},
        "interaction": {"avg_response_length": 150},
    }

    policy = resolver.resolve("Hello", "cli:the_creator:local", profile)

    assert policy.tone == "professional_precise"
    assert policy.length == "detailed"
    assert policy.source == "sbs_profile"


def test_explicit_intent_beats_sbs_profile():
    resolver = _resolver()
    profile = {
        "linguistic": {"current_style": {"preferred_style": "formal_and_precise"}},
        "interaction": {"avg_response_length": 150},
    }

    policy = resolver.resolve(
        "Be casual again and keep it short.",
        "cli:the_creator:local",
        profile,
    )

    assert policy.tone == "casual_witty"
    assert policy.length == "concise"
    assert policy.source == "session_override"


def test_professional_false_positives_do_not_trigger():
    assert detect_style_intent("I am a professional chef with a serious problem.") is None
    assert detect_style_intent("This is a serious problem in production.") is None


def test_style_prompt_contains_priority_contract():
    policy = _resolver().resolve("Stop joking and be professional.", "cli:the_creator:local")
    prompt = policy.to_prompt()

    assert "STYLE POLICY - highest priority" in prompt
    assert "overrides SBS profile tone" in prompt
    assert "Avoid teasing" in prompt
