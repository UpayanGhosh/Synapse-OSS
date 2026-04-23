"""Phase 16 HEART-01..05 — RED test stubs.

Every test imports sci_fi_dashboard.gateway.heartbeat_runner which does NOT exist in Wave 0.
When Plan 02 lands the module, these tests flip RED → GREEN without further edits.
"""

from __future__ import annotations

import asyncio
import types

import pytest

# Module-level import — Wave 0 RED via ImportError; Plan 02 makes it GREEN.
pytestmark = pytest.mark.asyncio


@pytest.fixture
def heartbeat_cfg_factory():
    def _make(**overrides) -> types.SimpleNamespace:
        base = {
            "enabled": True,
            "interval_s": 0.05,
            "recipients": ["1234567890@s.whatsapp.net"],
            "prompt": "ping",
            "ack_max_chars": 300,
            "visibility": {"showOk": False, "showAlerts": True, "useIndicator": True},
        }
        base.update(overrides)
        return types.SimpleNamespace(heartbeat=base)

    return _make


# ---------------------------------------------------------------------------
# HEART-01: recipient resolution
# ---------------------------------------------------------------------------


def test_config_recipient_is_sent(heartbeat_cfg_factory):
    """HEART-01: configured recipient JID appears in resolve_recipients output."""
    from sci_fi_dashboard.gateway.heartbeat_runner import resolve_recipients

    cfg = heartbeat_cfg_factory(recipients=["919000000000@s.whatsapp.net"])
    got = resolve_recipients(cfg)
    assert got == ["919000000000@s.whatsapp.net"]


def test_no_recipients_is_noop(heartbeat_cfg_factory):
    """HEART-01: empty recipients list returns []."""
    from sci_fi_dashboard.gateway.heartbeat_runner import resolve_recipients

    cfg = heartbeat_cfg_factory(recipients=[])
    assert resolve_recipients(cfg) == []


# ---------------------------------------------------------------------------
# HEART-02: prompt configuration
# ---------------------------------------------------------------------------


async def test_prompt_override(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-02: synapse.json heartbeat.prompt overrides default."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    observed = {"prompt": None}

    async def fake_reply(prompt: str) -> str:
        observed["prompt"] = prompt
        return "nothing to report"

    cfg = heartbeat_cfg_factory(prompt="custom-prompt-xyz")
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)
    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.05
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert observed["prompt"] == "custom-prompt-xyz"


async def test_prompt_default(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-02: absent prompt falls back to DEFAULT_HEARTBEAT_PROMPT."""
    from sci_fi_dashboard.gateway.heartbeat_runner import (
        DEFAULT_HEARTBEAT_PROMPT,
        HeartbeatRunner,
    )

    observed = {"prompt": None}

    async def fake_reply(prompt: str) -> str:
        observed["prompt"] = prompt
        return "ok"

    # prompt intentionally absent — cfg.heartbeat has no 'prompt' key
    cfg = types.SimpleNamespace(heartbeat={
        "enabled": True, "recipients": ["1234567890@s.whatsapp.net"],
        "visibility": {"showOk": False, "showAlerts": True, "useIndicator": True},
    })
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)
    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.05
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert observed["prompt"] == DEFAULT_HEARTBEAT_PROMPT


# ---------------------------------------------------------------------------
# HEART-03: HEARTBEAT_TOKEN stripping
# ---------------------------------------------------------------------------


def test_token_stripped_silent():
    """HEART-03: exact 'HEARTBEAT_OK' reply → (stripped='', should_skip=True)."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HEARTBEAT_TOKEN, strip_heartbeat_token

    assert HEARTBEAT_TOKEN == "HEARTBEAT_OK"
    stripped, should_skip = strip_heartbeat_token("HEARTBEAT_OK")
    assert stripped == ""
    assert should_skip is True


def test_token_with_trailing_punct_stripped():
    """HEART-03: 'HEARTBEAT_OK!' → (stripped='', should_skip=True)."""
    from sci_fi_dashboard.gateway.heartbeat_runner import strip_heartbeat_token

    for punct in ["!", ".", " .", "!!", "...", " ;"]:
        text = f"HEARTBEAT_OK{punct}"
        stripped, should_skip = strip_heartbeat_token(text)
        assert should_skip is True, f"trailing {punct!r} should strip fully"
        assert stripped == "", f"got {stripped!r} for {text!r}"


def test_token_prefix_stripped():
    """HEART-03: 'HEARTBEAT_OK real content' → (stripped='real content', should_skip=False)."""
    from sci_fi_dashboard.gateway.heartbeat_runner import strip_heartbeat_token

    stripped, should_skip = strip_heartbeat_token("HEARTBEAT_OK real content")
    assert should_skip is False
    assert stripped == "real content"


# ---------------------------------------------------------------------------
# HEART-04: visibility flag independence (8-combination matrix)
# ---------------------------------------------------------------------------


async def test_show_ok_sends_ok_ping(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-04: showOk=True + empty reply → sends literal HEARTBEAT_OK."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HEARTBEAT_TOKEN, HeartbeatRunner

    cfg = heartbeat_cfg_factory(visibility={"showOk": True, "showAlerts": True, "useIndicator": True})
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)

    async def fake_reply(prompt: str) -> str:
        return ""

    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.05
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert fake_channel_with_recorded_sends.calls == [("1234567890@s.whatsapp.net", HEARTBEAT_TOKEN)]


async def test_show_alerts_false_drops_content(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-04: showAlerts=False + content reply → no send, event emitted."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    cfg = heartbeat_cfg_factory(visibility={"showOk": False, "showAlerts": False, "useIndicator": True})
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)

    async def fake_reply(prompt: str) -> str:
        return "this is a real content reply"

    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.05
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert fake_channel_with_recorded_sends.calls == []


async def test_use_indicator_false_omits_field(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-04: useIndicator=False → emit payloads omit 'indicator_type' field."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    emitted: list[tuple[str, dict]] = []

    class FakeEmitter:
        def emit(self, evt: str, data: dict) -> None:
            emitted.append((evt, data))

        def start_run(self, *a, **k):
            pass

    cfg = heartbeat_cfg_factory(visibility={"showOk": False, "showAlerts": True, "useIndicator": False})
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)

    async def fake_reply(prompt: str) -> str:
        return "content"

    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply,
        emitter=FakeEmitter(), interval_s=0.05,
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert emitted, "at least one event should fire"
    for _evt, data in emitted:
        assert "indicator_type" not in data, f"indicator_type leaked into {data}"


@pytest.mark.parametrize(
    "show_ok,show_alerts,use_indicator,reply,expect_send_count",
    [
        # reply empty => HEARTBEAT_OK path
        (False, True, True, "", 0),        # silent ok
        (True, True, True, "", 1),         # send HEARTBEAT_OK
        (False, False, True, "", 0),
        (True, False, True, "", 1),
        # reply content => alert path
        (False, True, True, "content", 1),
        (True, True, True, "content", 1),
        (False, False, True, "content", 0),
        (True, False, True, "content", 0),
    ],
)
async def test_visibility_flag_matrix(
    heartbeat_cfg_factory,
    fake_channel_with_recorded_sends,
    show_ok,
    show_alerts,
    use_indicator,
    reply,
    expect_send_count,
):
    """HEART-04: all 8 visibility combinations produce correct send count."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    cfg = heartbeat_cfg_factory(visibility={
        "showOk": show_ok, "showAlerts": show_alerts, "useIndicator": use_indicator,
    })
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)

    async def fake_reply(prompt: str) -> str:
        return reply

    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.05
    )
    await runner.run_heartbeat_once("1234567890@s.whatsapp.net")
    assert len(fake_channel_with_recorded_sends.calls) == expect_send_count


# ---------------------------------------------------------------------------
# HEART-05: never-crash loop
# ---------------------------------------------------------------------------


async def test_never_crashes_after_failures(heartbeat_cfg_factory):
    """HEART-05: 10 consecutive heartbeat failures do not kill the loop."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    failure_count = 0

    async def fake_send_always_fails(chat_id: str, text: str) -> dict:
        nonlocal failure_count
        failure_count += 1
        raise RuntimeError("simulated network failure")

    ch = types.SimpleNamespace(send=fake_send_always_fails)
    registry = types.SimpleNamespace(get=lambda cid: ch)

    async def fake_reply(prompt: str) -> str:
        return "content that would trigger a send"

    cfg = heartbeat_cfg_factory(interval_s=0.02)
    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=fake_reply, interval_s=0.02
    )
    await runner.start()
    await asyncio.sleep(0.3)  # allow ~15 cycles
    await runner.stop()

    assert failure_count >= 5, f"runner stopped after only {failure_count} failures — HEART-05 violated"


async def test_llm_exception_does_not_stop_loop(heartbeat_cfg_factory, fake_channel_with_recorded_sends):
    """HEART-05: get_reply_fn exception is swallowed, loop continues."""
    from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner

    reply_calls = {"n": 0}

    async def flaky_reply(prompt: str) -> str:
        reply_calls["n"] += 1
        raise RuntimeError("LLM timeout")

    cfg = heartbeat_cfg_factory(interval_s=0.02)
    registry = types.SimpleNamespace(get=lambda cid: fake_channel_with_recorded_sends)
    runner = HeartbeatRunner(
        channel_registry=registry, cfg=cfg, get_reply_fn=flaky_reply, interval_s=0.02
    )
    await runner.start()
    await asyncio.sleep(0.3)
    await runner.stop()

    assert reply_calls["n"] >= 5, f"loop stopped after {reply_calls['n']} LLM exceptions"
    assert fake_channel_with_recorded_sends.calls == []  # no sends because reply always raised
