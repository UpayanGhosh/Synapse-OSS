from cli.chat_types import ChatLaunchOptions, ChatTurn, normalize_session_type


def test_normalize_session_type_defaults_to_safe():
    assert normalize_session_type(None) == "safe"
    assert normalize_session_type("") == "safe"


def test_normalize_session_type_accepts_safe_and_spicy():
    assert normalize_session_type("safe") == "safe"
    assert normalize_session_type("spicy") == "spicy"


def test_normalize_session_type_rejects_unknown():
    try:
        normalize_session_type("admin")
    except ValueError as exc:
        assert "safe or spicy" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_launch_options_build_session_key():
    opts = ChatLaunchOptions(target="the_creator", user_id="local", session_key=None)
    assert opts.resolved_session_key() == "cli:the_creator:local"


def test_chat_turn_roundtrip_payload():
    turn = ChatTurn(role="assistant", content="hello")
    assert turn.as_history_message() == {"role": "assistant", "content": "hello"}
