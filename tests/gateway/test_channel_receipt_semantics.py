from sci_fi_dashboard.action_receipts import ActionReceipt


def test_channel_acceptance_does_not_prove_recipient_delivery() -> None:
    receipt = ActionReceipt(
        action="channel_send",
        status="verified",
        evidence="channel accepted outbound request",
    )
    assert receipt.supports("send")
    assert not receipt.supports("deliver")
