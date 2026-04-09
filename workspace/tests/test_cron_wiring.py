"""
Tests for Phase 10: Cron wiring to persona_chat().

Covers:
- CRON-01: unique session keys for each isolated cron agent invocation
- CRON-02: execute_fn adapter called with correct arguments
- CRON-03: light_context kwarg forwarding
- CRON-04: timeout wrapping raises asyncio.TimeoutError
- DASH-01: SSE events (cron.job_start / cron.job_done) emitted during cron execution
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sci_fi_dashboard.cron.isolated_agent import run_isolated_agent
from sci_fi_dashboard.cron.types import CronPayload, PayloadKind
from sci_fi_dashboard.schemas import ChatRequest


# ---------------------------------------------------------------------------
# CRON-01: ChatRequest.session_key field
# ---------------------------------------------------------------------------


class TestChatRequestSessionKey:
    def test_chatrequest_accepts_session_key(self):
        """session_key field is accepted and stored on ChatRequest (CRON-01)."""
        request = ChatRequest(message="test", session_key="cron-abc-12345678")
        assert request.session_key == "cron-abc-12345678"

    def test_chatrequest_session_key_defaults_to_none(self):
        """session_key defaults to None when not provided (CRON-01)."""
        request = ChatRequest(message="test")
        assert request.session_key is None


# ---------------------------------------------------------------------------
# CRON-01: Isolated agent session key isolation
# ---------------------------------------------------------------------------


class TestIsolatedAgentSessionKey:
    @pytest.mark.asyncio
    async def test_isolated_agent_passes_unique_session_key(self):
        """run_isolated_agent forwards the caller-supplied session_key to execute_fn (CRON-01)."""
        captured_keys: list[str] = []

        async def record_fn(message: str, session_key: str, **kwargs):
            captured_keys.append(session_key)
            return "ok"

        payload = CronPayload(kind=PayloadKind.AGENT_TURN, message="hello")

        await run_isolated_agent(payload, session_key="cron-job1-aabb", execute_fn=record_fn)
        assert captured_keys[-1] == "cron-job1-aabb"

        await run_isolated_agent(payload, session_key="cron-job2-ccdd", execute_fn=record_fn)
        assert captured_keys[-1] == "cron-job2-ccdd"

        # The two keys must be distinct
        assert captured_keys[0] != captured_keys[1]

    @pytest.mark.asyncio
    async def test_two_concurrent_jobs_different_sessions(self):
        """Two concurrent run_isolated_agent calls receive distinct session_keys (CRON-01)."""
        captured_keys: list[str] = []

        async def record_fn(message: str, session_key: str, **kwargs):
            captured_keys.append(session_key)
            await asyncio.sleep(0.01)
            return "done"

        payload = CronPayload(kind=PayloadKind.AGENT_TURN, message="concurrent")

        await asyncio.gather(
            run_isolated_agent(payload, session_key="cron-job-AAA", execute_fn=record_fn),
            run_isolated_agent(payload, session_key="cron-job-BBB", execute_fn=record_fn),
        )

        assert len(captured_keys) == 2
        assert captured_keys[0] != captured_keys[1]


# ---------------------------------------------------------------------------
# CRON-02: execute_fn adapter correctness
# ---------------------------------------------------------------------------


class TestExecuteFnAdapter:
    @pytest.mark.asyncio
    async def test_execute_fn_called_with_message(self):
        """execute_fn receives the payload message as positional arg (CRON-02)."""
        mock_fn = AsyncMock(return_value="response")
        payload = CronPayload(kind=PayloadKind.AGENT_TURN, message="do the thing")

        result = await run_isolated_agent(
            payload, session_key="cron-test-session", execute_fn=mock_fn
        )

        mock_fn.assert_awaited_once()
        call_args = mock_fn.call_args
        # First positional arg is the message
        assert call_args.args[0] == "do the thing"
        assert result == "response"

    @pytest.mark.asyncio
    async def test_no_execute_fn_returns_empty_string(self):
        """When execute_fn is None, run_isolated_agent returns empty string (CRON-02)."""
        payload = CronPayload(kind=PayloadKind.AGENT_TURN, message="test")
        result = await run_isolated_agent(payload, session_key="cron-no-fn", execute_fn=None)
        assert result == ""


# ---------------------------------------------------------------------------
# CRON-03: light_context kwarg forwarding
# ---------------------------------------------------------------------------


class TestLightContextKwarg:
    @pytest.mark.asyncio
    async def test_light_context_kwarg_passed(self):
        """light_context=True in CronPayload is forwarded to execute_fn as kwarg (CRON-03)."""
        captured_kwargs: dict = {}

        async def record_kwargs(message: str, session_key: str, **kwargs):
            captured_kwargs.update(kwargs)
            return "ok"

        payload = CronPayload(
            kind=PayloadKind.AGENT_TURN,
            message="light context test",
            light_context=True,
        )
        await run_isolated_agent(payload, session_key="cron-ctx", execute_fn=record_kwargs)

        assert "light_context" in captured_kwargs
        assert captured_kwargs["light_context"] is True

    @pytest.mark.asyncio
    async def test_light_context_false_not_forwarded(self):
        """light_context=False (default) is NOT forwarded to execute_fn kwargs (CRON-03)."""
        captured_kwargs: dict = {}

        async def record_kwargs(message: str, session_key: str, **kwargs):
            captured_kwargs.update(kwargs)
            return "ok"

        payload = CronPayload(
            kind=PayloadKind.AGENT_TURN,
            message="no light context",
            light_context=False,
        )
        await run_isolated_agent(payload, session_key="cron-no-ctx", execute_fn=record_kwargs)

        # light_context=False should not be present — only truthy values are forwarded
        assert captured_kwargs.get("light_context") is None


# ---------------------------------------------------------------------------
# CRON-04: timeout wrapping raises asyncio.TimeoutError
# ---------------------------------------------------------------------------


class TestTimeoutWrapping:
    @pytest.mark.asyncio
    async def test_execute_fn_receives_timeout_kwarg(self):
        """timeout_seconds from CronPayload is forwarded to execute_fn as kwarg (CRON-04)."""
        captured_kwargs: dict = {}

        async def record_kwargs(message: str, session_key: str, **kwargs):
            captured_kwargs.update(kwargs)
            return "ok"

        payload = CronPayload(
            kind=PayloadKind.AGENT_TURN,
            message="timeout test",
            timeout_seconds=60,
        )
        await run_isolated_agent(payload, session_key="cron-timeout", execute_fn=record_kwargs)

        assert captured_kwargs.get("timeout_seconds") == 60

    @pytest.mark.asyncio
    async def test_execute_fn_timeout_raises(self):
        """asyncio.wait_for raises TimeoutError when execute_fn exceeds the deadline (CRON-04)."""
        async def slow_fn(message: str, session_key: str, **kwargs):
            await asyncio.sleep(5)
            return "late"

        payload = CronPayload(kind=PayloadKind.AGENT_TURN, message="slow")

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                run_isolated_agent(payload, session_key="cron-slow", execute_fn=slow_fn),
                timeout=0.1,
            )


# ---------------------------------------------------------------------------
# DASH-01: SSE events emitted during cron execution
# ---------------------------------------------------------------------------


class TestCronSSEEmission:
    @pytest.mark.asyncio
    async def test_cron_service_emits_sse_events(self, tmp_path):
        """CronService._execute_job emits cron.job_start and cron.job_done SSE events (DASH-01)."""
        from sci_fi_dashboard.cron.service import CronService

        mock_execute_fn = AsyncMock(return_value="cron output")
        svc = CronService(
            agent_id="test_agent",
            data_root=str(tmp_path),
            execute_fn=mock_execute_fn,
            channel_registry=None,
        )

        # Add a test job
        job = svc.add({
            "schedule": {"kind": "every", "every_ms": 60_000, "anchor_ms": 0},
            "payload": {"kind": "agentTurn", "message": "sse test"},
            "name": "sse-test-job",
        })

        emitted_events: list[str] = []
        mock_emitter = MagicMock()
        mock_emitter.emit = MagicMock(side_effect=lambda et, data=None: emitted_events.append(et))

        # The service uses a lazy `from sci_fi_dashboard.pipeline_emitter import get_emitter`
        # inside _execute_job — patch the function on the already-loaded module object.
        with patch("sci_fi_dashboard.pipeline_emitter.get_emitter", return_value=mock_emitter):
            result = await svc._execute_job(job)

        assert result["status"] == "ok"
        # SSE events must include job_start and job_done
        assert "cron.job_start" in emitted_events
        assert "cron.job_done" in emitted_events

    @pytest.mark.asyncio
    async def test_cron_service_emits_job_error_on_failure(self, tmp_path):
        """CronService._execute_job emits cron.job_error when execute_fn raises (DASH-01)."""
        from sci_fi_dashboard.cron.service import CronService

        failing_execute_fn = AsyncMock(side_effect=RuntimeError("boom"))
        svc = CronService(
            agent_id="test_agent",
            data_root=str(tmp_path),
            execute_fn=failing_execute_fn,
            channel_registry=None,
        )

        job = svc.add({
            "schedule": {"kind": "every", "every_ms": 60_000, "anchor_ms": 0},
            "payload": {"kind": "agentTurn", "message": "error test"},
            "name": "error-test-job",
        })

        emitted_events: list[str] = []
        mock_emitter = MagicMock()
        mock_emitter.emit = MagicMock(side_effect=lambda et, data=None: emitted_events.append(et))

        with patch("sci_fi_dashboard.pipeline_emitter.get_emitter", return_value=mock_emitter):
            result = await svc._execute_job(job)

        assert result["status"] == "error"
        assert "cron.job_start" in emitted_events
        assert "cron.job_error" in emitted_events
