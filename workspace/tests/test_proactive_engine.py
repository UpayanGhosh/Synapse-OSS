"""
Tests for sci_fi_dashboard.proactive_engine — ProactiveAwarenessEngine and ProactiveContext.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.proactive_engine import (
    ProactiveAwarenessEngine,
    ProactiveContext,
)


# ---------------------------------------------------------------------------
# ProactiveContext
# ---------------------------------------------------------------------------


class TestProactiveContext:
    def test_empty_context_returns_empty_prompt(self):
        ctx = ProactiveContext()
        assert ctx.compile_prompt_block() == ""

    def test_calendar_events_in_prompt(self):
        ctx = ProactiveContext(
            calendar_events=[
                {"summary": "Team Standup", "start": "10:00", "attendees": ["alice", "bob"]}
            ]
        )
        block = ctx.compile_prompt_block()
        assert "UPCOMING EVENTS" in block
        assert "Team Standup" in block
        assert "alice" in block

    def test_unread_emails_in_prompt(self):
        ctx = ProactiveContext(
            unread_emails=[
                {"from": "alice@example.com", "subject": "Important"},
                {"from": "bob@example.com", "subject": "FYI"},
            ]
        )
        block = ctx.compile_prompt_block()
        assert "UNREAD EMAILS: 2" in block
        assert "alice@example.com" in block

    def test_slack_mentions_in_prompt(self):
        ctx = ProactiveContext(
            slack_mentions=[
                {"channel": "general", "user": "carol", "text": "Hey look at this"}
            ]
        )
        block = ctx.compile_prompt_block()
        assert "SLACK MENTIONS: 1" in block
        assert "carol" in block

    def test_combined_prompt_has_all_sections(self):
        ctx = ProactiveContext(
            calendar_events=[{"summary": "Meeting", "start": "14:00"}],
            unread_emails=[{"from": "a@b.com", "subject": "Hi"}],
            slack_mentions=[{"channel": "dev", "user": "u1", "text": "ping"}],
        )
        block = ctx.compile_prompt_block()
        assert "PROACTIVE AWARENESS" in block
        assert "END PROACTIVE" in block
        assert "UPCOMING EVENTS" in block
        assert "UNREAD EMAILS" in block
        assert "SLACK MENTIONS" in block

    def test_only_first_3_emails_shown(self):
        emails = [
            {"from": f"user{i}@test.com", "subject": f"Email {i}"}
            for i in range(10)
        ]
        ctx = ProactiveContext(unread_emails=emails)
        block = ctx.compile_prompt_block()
        assert "user0@test.com" in block
        assert "user2@test.com" in block
        # user3 and beyond should not be in prompt (max 3 shown)
        assert "user3@test.com" not in block

    def test_only_first_3_mentions_shown(self):
        mentions = [
            {"channel": "ch", "user": f"u{i}", "text": f"msg {i}"}
            for i in range(10)
        ]
        ctx = ProactiveContext(slack_mentions=mentions)
        block = ctx.compile_prompt_block()
        assert "u2" in block
        assert "u3" not in block

    def test_slack_text_truncated_at_80_chars(self):
        ctx = ProactiveContext(
            slack_mentions=[
                {"channel": "ch", "user": "u1", "text": "A" * 200}
            ]
        )
        block = ctx.compile_prompt_block()
        # The text in the block should be truncated
        # Find the mention line and check it's reasonable length
        assert "A" * 81 not in block

    def test_has_urgent_items_with_calendar(self):
        ctx = ProactiveContext(calendar_events=[{"summary": "x"}])
        assert ctx.has_urgent_items() is True

    def test_has_urgent_items_with_many_emails(self):
        ctx = ProactiveContext(unread_emails=[{} for _ in range(4)])
        assert ctx.has_urgent_items() is True

    def test_not_urgent_with_few_emails(self):
        ctx = ProactiveContext(unread_emails=[{} for _ in range(2)])
        assert ctx.has_urgent_items() is False

    def test_not_urgent_empty(self):
        ctx = ProactiveContext()
        assert ctx.has_urgent_items() is False

    def test_not_urgent_slack_only(self):
        ctx = ProactiveContext(
            slack_mentions=[{"channel": "ch", "user": "u", "text": "hi"}]
        )
        assert ctx.has_urgent_items() is False


# ---------------------------------------------------------------------------
# ProactiveAwarenessEngine
# ---------------------------------------------------------------------------


class TestProactiveAwarenessEngine:
    @pytest.fixture
    def mock_mcp_client(self):
        client = AsyncMock()
        client.call_tool = AsyncMock(return_value="[]")
        return client

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.poll_interval_seconds = 60
        config.sources = {}
        return config

    @pytest.fixture
    def engine(self, mock_mcp_client, mock_config):
        return ProactiveAwarenessEngine(mock_mcp_client, mock_config)

    def test_initial_context_is_empty(self, engine):
        assert engine.context.calendar_events == []
        assert engine.context.unread_emails == []
        assert engine.context.slack_mentions == []

    def test_get_prompt_injection_empty(self, engine):
        assert engine.get_prompt_injection() == ""

    @pytest.mark.asyncio
    async def test_start_creates_task(self, engine):
        engine._running = False
        with patch.object(engine, "_poll_loop", new_callable=AsyncMock):
            await engine.start()
        assert engine._running is True
        assert engine._task is not None
        # Cleanup
        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, engine):
        engine._running = True
        engine._task = asyncio.create_task(asyncio.sleep(100))
        await engine.stop()
        assert engine._running is False
        assert engine._task.cancelled()


# ---------------------------------------------------------------------------
# _poll_all
# ---------------------------------------------------------------------------


class TestPollAll:
    @pytest.mark.asyncio
    async def test_polls_calendar(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=json.dumps([{"summary": "Meeting", "start": "10:00"}])
        )

        config = MagicMock()
        config.poll_interval_seconds = 60
        cal_src = MagicMock()
        cal_src.proactive = True
        cal_src.lookahead_minutes = 45
        config.sources = {"calendar": cal_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()

        assert len(engine.context.calendar_events) == 1
        assert engine.context.calendar_events[0]["summary"] == "Meeting"

    @pytest.mark.asyncio
    async def test_polls_gmail(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=json.dumps([
                {"from": "alice@test.com", "subject": "Hi"},
            ])
        )

        config = MagicMock()
        config.poll_interval_seconds = 60
        gmail_src = MagicMock()
        gmail_src.proactive = True
        gmail_src.max_unread = 5
        config.sources = {"gmail": gmail_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()

        assert len(engine.context.unread_emails) == 1

    @pytest.mark.asyncio
    async def test_polls_slack(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(
            return_value=json.dumps([
                {"channel": "dev", "user": "bob", "text": "ping"},
            ])
        )

        config = MagicMock()
        config.poll_interval_seconds = 60
        slack_src = MagicMock()
        slack_src.proactive = True
        config.sources = {"slack": slack_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()

        assert len(engine.context.slack_mentions) == 1

    @pytest.mark.asyncio
    async def test_handles_calendar_poll_failure(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=Exception("timeout"))

        config = MagicMock()
        config.poll_interval_seconds = 60
        cal_src = MagicMock()
        cal_src.proactive = True
        cal_src.lookahead_minutes = 30
        config.sources = {"calendar": cal_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        # Should not raise
        await engine._poll_all()
        assert engine.context.calendar_events == []

    @pytest.mark.asyncio
    async def test_skips_disabled_sources(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock()

        config = MagicMock()
        config.poll_interval_seconds = 60
        cal_src = MagicMock()
        cal_src.proactive = False
        config.sources = {"calendar": cal_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()

        mock_client.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_list(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value="not-json")

        config = MagicMock()
        config.poll_interval_seconds = 60
        cal_src = MagicMock()
        cal_src.proactive = True
        cal_src.lookahead_minutes = 30
        config.sources = {"calendar": cal_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        # Should handle JSON decode error gracefully
        await engine._poll_all()
        # Calendar events should be empty (exception caught)
        assert engine.context.calendar_events == []

    @pytest.mark.asyncio
    async def test_non_list_result_treated_as_empty(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value=json.dumps({"error": "oops"}))

        config = MagicMock()
        config.poll_interval_seconds = 60
        cal_src = MagicMock()
        cal_src.proactive = True
        cal_src.lookahead_minutes = 30
        config.sources = {"calendar": cal_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()
        assert engine.context.calendar_events == []

    @pytest.mark.asyncio
    async def test_empty_string_result_treated_as_empty(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value="")

        config = MagicMock()
        config.poll_interval_seconds = 60
        gmail_src = MagicMock()
        gmail_src.proactive = True
        gmail_src.max_unread = 5
        config.sources = {"gmail": gmail_src}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()
        assert engine.context.unread_emails == []

    @pytest.mark.asyncio
    async def test_generated_at_set(self):
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value="[]")

        config = MagicMock()
        config.poll_interval_seconds = 60
        config.sources = {}

        engine = ProactiveAwarenessEngine(mock_client, config)
        await engine._poll_all()
        assert engine.context.generated_at != ""


# ---------------------------------------------------------------------------
# get_prompt_injection
# ---------------------------------------------------------------------------


class TestGetPromptInjection:
    def test_returns_compiled_block(self):
        mock_client = AsyncMock()
        config = MagicMock()
        config.poll_interval_seconds = 60
        config.sources = {}

        engine = ProactiveAwarenessEngine(mock_client, config)
        engine._context = ProactiveContext(
            calendar_events=[{"summary": "Standup", "start": "10:00"}]
        )
        injection = engine.get_prompt_injection()
        assert "Standup" in injection
        assert "PROACTIVE AWARENESS" in injection
