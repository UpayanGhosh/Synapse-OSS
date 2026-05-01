from sci_fi_dashboard.action_receipts import (
    ActionReceipt,
    guard_reply_against_unreceipted_claims,
    render_receipt_contract,
)


def test_receipt_contract_lists_verified_actions():
    receipt = ActionReceipt(
        action="web_query",
        status="verified",
        evidence="5 results for TVS RSA Kolkata",
        confidence=0.82,
        next_best_action="Prefer official TVS result first.",
    )

    contract = render_receipt_contract([receipt])

    assert "ACTION RECEIPTS" in contract
    assert "web_query" in contract
    assert "verified" in contract
    assert "5 results for TVS RSA Kolkata" in contract
    assert "Only claim an action happened when its receipt status supports it" in contract


def test_successful_tool_claim_without_receipt_is_repaired():
    reply = "I searched the web and found the official route. Use TVS RSA first."

    guarded = guard_reply_against_unreceipted_claims(reply, [])

    assert "I searched" not in guarded
    assert "official route" in guarded
    assert "I haven't verified that live in this turn" in guarded


def test_verified_receipt_allows_matching_claim():
    reply = "I searched the web and found the official route. Use TVS RSA first."
    receipt = ActionReceipt(
        action="web_query",
        status="verified",
        evidence="usable results returned",
        confidence=0.9,
    )

    guarded = guard_reply_against_unreceipted_claims(reply, [receipt])

    assert guarded == reply


def test_failed_receipt_allows_tried_but_not_success_claim():
    failed = ActionReceipt(
        action="web_query",
        status="failed",
        evidence="timeout",
        confidence=0.0,
    )

    guarded = guard_reply_against_unreceipted_claims(
        "I searched the web and confirmed the result.", [failed]
    )

    assert "I searched" not in guarded
    assert "I haven't verified that live in this turn" in guarded
    assert "I tried to search, but it failed." == guard_reply_against_unreceipted_claims(
        "I tried to search, but it failed.", [failed]
    )


def test_inferred_receipt_does_not_allow_success_claim():
    inferred = ActionReceipt(
        action="web_query",
        status="inferred",
        evidence="search ran but returned 0 usable results",
        confidence=0.35,
    )

    guarded = guard_reply_against_unreceipted_claims(
        "I found the official booking route.", [inferred]
    )

    assert "I found" not in guarded
    assert "I haven't verified that live in this turn" in guarded


def test_message_capture_does_not_authorize_memory_save_claim():
    capture = ActionReceipt(
        action="message_capture",
        status="verified",
        evidence="transcript append succeeded",
        confidence=0.99,
    )

    guarded = guard_reply_against_unreceipted_claims(
        "I saved that to memory for later.", [capture]
    )

    assert "I saved" not in guarded
    assert "I haven't saved that as memory in this turn" in guarded


def test_unreceipted_schedule_claim_is_repaired():
    guarded = guard_reply_against_unreceipted_claims(
        "Done - I'll nudge you at 18:00: call mom.", []
    )

    assert "I'll nudge you" not in guarded
    assert "I haven't scheduled that in this turn" in guarded


def test_unreceipted_send_claim_is_repaired():
    guarded = guard_reply_against_unreceipted_claims(
        "I sent that message to Telegram.", []
    )

    assert "I sent" not in guarded
    assert "I haven't sent that anywhere in this turn" in guarded


def test_guard_preserves_formatting_when_no_repair_needed():
    reply = "First line.\n\n- keep this bullet\n- and this one"

    guarded = guard_reply_against_unreceipted_claims(reply, [])

    assert guarded == reply


def test_generic_found_bug_is_not_treated_as_live_search_claim():
    reply = "I found the bug: the receipt list was not merged."

    guarded = guard_reply_against_unreceipted_claims(reply, [])

    assert guarded == reply
