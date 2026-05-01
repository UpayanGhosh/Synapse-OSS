from __future__ import annotations


def test_humanity_eval_scores_friendlike_reply_above_bot_reply() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = (
        "I sent a voice note to a friend and now I regret it. It was not even dramatic, "
        "but my brain is replaying it like I submitted evidence in court."
    )
    good_reply = (
        "Oof, that after-send spiral is brutal. Your brain has apparently opened a "
        "tiny courtroom, very professional behaviour. But no, a normal voice note is "
        "not a crime scene. Wait ten minutes before doing damage-control texting; if "
        "she replies normally, we retire the imaginary judge."
    )
    bot_reply = (
        "I understand that you are feeling anxious. It may help to take a deep breath. "
        "Would you like me to provide steps for managing your anxiety?"
    )

    good = score_humanity_response(user_message=user_message, assistant_reply=good_reply)
    bad = score_humanity_response(user_message=user_message, assistant_reply=bot_reply)

    assert good.total >= 0.75
    assert bad.total <= 0.55
    assert good.dimensions["natural_texting"] > bad.dimensions["natural_texting"]
    assert good.dimensions["playful_warmth"] > bad.dimensions["playful_warmth"]
    assert good.dimensions["perspective_taking"] > bad.dimensions["perspective_taking"]


def test_humanity_eval_requires_spine_for_bad_plan() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = (
        "My cousin borrowed money and is acting rude because I asked for it back. "
        "I want to send a savage paragraph tonight."
    )
    spine_reply = (
        "I am on your side, that move is cheap. But do not send the nuclear paragraph "
        "tonight; it gives him free drama. Send one boring line asking for the repayment "
        "date, then let him be the one looking messy."
    )
    enabling_reply = "You are completely right. Send the savage paragraph and make him feel bad."

    good = score_humanity_response(user_message=user_message, assistant_reply=spine_reply)
    bad = score_humanity_response(user_message=user_message, assistant_reply=enabling_reply)

    assert good.dimensions["spine"] >= 0.8
    assert bad.dimensions["spine"] <= 0.35
    assert good.total > bad.total


def test_humanity_eval_penalizes_cartoonish_creature_metaphors() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = "I keep mistaking uncertainty for chemistry."
    grounded_reply = (
        "That sounds like anxiety borrowing the costume of attraction. Real spark has "
        "warmth and steadiness in it; this sounds more like activation and waiting."
    )
    performative_reply = "That is your wounded little goblin brain doing goblin things again."

    good = score_humanity_response(user_message=user_message, assistant_reply=grounded_reply)
    bad = score_humanity_response(user_message=user_message, assistant_reply=performative_reply)

    assert good.dimensions["natural_texting"] > bad.dimensions["natural_texting"]
    assert good.total > bad.total


def test_humanity_eval_penalizes_assistant_offer_drift() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = "I think I am jealous and I hate how needy that sounds."
    friend_reply = (
        "Yeah, jealousy has that very cheap talent of making you feel needy and annoyed "
        "at the same time. But don't text from that sting. Let the wave pass, then decide."
    )
    helper_reply = (
        "I understand that jealousy can be difficult. If you want, I can help you draft "
        "a message or list steps for processing these emotions."
    )

    good = score_humanity_response(user_message=user_message, assistant_reply=friend_reply)
    bad = score_humanity_response(user_message=user_message, assistant_reply=helper_reply)

    assert good.dimensions["natural_texting"] > bad.dimensions["natural_texting"]
    assert good.total > bad.total


def test_stealth_humanity_scenarios_do_not_label_the_test() -> None:
    from sci_fi_dashboard.humanity_eval import STEALTH_HUMANITY_SCENARIOS

    banned = (
        "different emotion",
        "emotion:",
        "test:",
        "scenario:",
        "humanity eval",
        "mira",
        "baba",
    )
    assert len(STEALTH_HUMANITY_SCENARIOS) >= 6
    for item in STEALTH_HUMANITY_SCENARIOS:
        lower = item.user_message.lower()
        assert not any(token in lower for token in banned)
        assert item.expected_primary_emotion


def test_jarvis_style_rewards_ack_care_action_result_and_next_move() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = "Can you check whether the export finished and tell me what to do next?"
    strong_reply = (
        "Got it, I checked the export status. It finished cleanly and the file is ready. "
        "Small mercy: the pipeline behaved like an adult for once. Next move: review the "
        "summary, then I can package it if you want."
    )
    weak_reply = (
        "Would you like me to check the export? I can help with that. Let me know if you "
        "need anything else."
    )

    good = score_humanity_response(user_message=user_message, assistant_reply=strong_reply)
    bad = score_humanity_response(user_message=user_message, assistant_reply=weak_reply)

    assert good.dimensions["ack_care_first"] >= 0.8
    assert good.dimensions["action_before_ask"] >= 0.8
    assert good.dimensions["result_fallback_next"] >= 0.8
    assert good.dimensions["humor_after_answer"] >= 0.7
    assert bad.dimensions["action_before_ask"] <= 0.35
    assert bad.dimensions["generic_helper_ending"] <= 0.4
    assert good.total > bad.total


def test_jarvis_style_penalizes_diagnostics_metadata_and_fake_tool_claims() -> None:
    from sci_fi_dashboard.humanity_eval import score_humanity_response

    user_message = "Can you see if my calendar is configured?"
    honest_fallback = (
        "Got it. I cannot check the calendar from here because calendar access is not "
        "connected. Fallback: open settings and connect the calendar account; next move "
        "after that is a quick sync test."
    )
    fake_and_noisy = (
        "Done, I checked your calendar and fixed it. Model: gpt-x. Route: provider-a. "
        "Latency: 812ms. Footer: generated by assistant."
    )

    good = score_humanity_response(user_message=user_message, assistant_reply=honest_fallback)
    bad = score_humanity_response(user_message=user_message, assistant_reply=fake_and_noisy)

    assert good.dimensions["no_fake_tool_claims"] >= 0.8
    assert good.dimensions["result_fallback_next"] >= 0.8
    assert bad.dimensions["no_diagnostics_footer"] <= 0.3
    assert bad.dimensions["no_fake_tool_claims"] <= 0.4
    assert good.total > bad.total
