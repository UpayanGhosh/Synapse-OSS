from __future__ import annotations

import pytest
from sci_fi_dashboard.style_policy import (
    SessionStyleStore,
    StylePolicyResolver,
    detect_style_intent,
)

FORMAL_PROFILE = {
    "linguistic": {"current_style": {"preferred_style": "formal_and_precise"}},
    "interaction": {"avg_response_length": 10},
}
FORMAL_DETAILED_PROFILE = {
    "linguistic": {"current_style": {"preferred_style": "formal_and_precise"}},
    "interaction": {"avg_response_length": 150},
}
ONE_TURN_REQUEST = "For this answer only, make it playful and keep it brief."


def test_explicit_playful_brief_turn_overrides_formal_then_reverts() -> None:
    store = SessionStyleStore()
    resolver = StylePolicyResolver(store)

    temporary = resolver.resolve(ONE_TURN_REQUEST, "alice", FORMAL_PROFILE)

    assert (temporary.tone, temporary.length) == ("creative_playful", "concise")
    assert temporary.scope == "turn"
    assert store.get("alice") is None

    following = resolver.resolve("What is the status?", "alice", FORMAL_PROFILE)
    assert (following.tone, following.length) == ("professional_precise", "concise")


def test_playful_brief_directive_shortens_a_detailed_baseline() -> None:
    resolver = StylePolicyResolver(SessionStyleStore())
    temporary = resolver.resolve(ONE_TURN_REQUEST, "alice", FORMAL_DETAILED_PROFILE)
    assert (temporary.tone, temporary.length) == ("creative_playful", "concise")
    assert resolver.resolve("What is the status?", "alice", FORMAL_DETAILED_PROFILE).length == "detailed"


@pytest.mark.parametrize(
    "message",
    [
        "For this answer only, do not make it playful and keep it brief.",
        '"For this answer only, make it playful and keep it brief" is a quote.',
        "If I said 'For this answer only, make it playful and keep it brief,' would you change style?",
    ],
)
def test_mentions_of_playful_instruction_do_not_override_formal(message: str) -> None:
    intent = detect_style_intent(message)
    assert intent is None or intent.tone != "creative_playful"

    resolver = StylePolicyResolver(SessionStyleStore())
    policy = resolver.resolve(message, "alice", FORMAL_DETAILED_PROFILE)
    assert (policy.tone, policy.length) == ("professional_precise", "detailed")


def test_plain_playful_request_is_turn_scoped_unless_session_is_explicit() -> None:
    assert detect_style_intent("Make it playful.").scope == "turn"
    assert detect_style_intent("Be playful.").scope == "turn"
    assert detect_style_intent("From now on, make it playful.").scope == "session"
