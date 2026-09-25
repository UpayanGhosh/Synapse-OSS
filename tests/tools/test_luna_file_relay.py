from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.tools.luna_file_relay import FileRelayRouter, RelayLimitError, RelayProtocolError


@pytest.fixture
def relay_run_dir() -> Path:
    run_dir = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-luna-relay-tests" / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _read_request(run_dir: Path, request_id: str) -> dict:
    return json.loads((run_dir / "requests" / f"{request_id}.json").read_text(encoding="utf-8"))


def _write_response(run_dir: Path, request_id: str, **payload) -> None:
    response = {"request_id": request_id, **payload}
    (run_dir / "responses").mkdir(parents=True, exist_ok=True)
    (run_dir / "responses" / f"{request_id}.json").write_text(
        json.dumps(response), encoding="utf-8"
    )


def test_call_round_trips_only_the_current_request_and_preserves_real_prompt(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        messages = [{"role": "user", "content": "Remember our paper boat joke."}]
        pending = asyncio.create_task(router.call("casual", messages))
        request_path = await _wait_for_request(relay_run_dir)
        packet = json.loads(request_path.read_text(encoding="utf-8"))
        assert packet["model"] == "gpt-6-luna"
        assert packet["kind"] == "text"
        assert packet["role"] == "casual"
        assert packet["messages"] == messages
        _write_response(relay_run_dir, packet["request_id"], text="I’ll keep the paper boat joke in mind.")
        assert await pending == "I’ll keep the paper boat joke in mind."

    asyncio.run(scenario())


def test_tool_call_round_trip_validates_schema_and_adapts_router_result(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        tools = [{
            "type": "function",
            "function": {"name": "query_memory", "parameters": {"type": "object"}},
        }]
        pending = asyncio.create_task(
            router.call_with_tools("casual", [{"role": "user", "content": "Find the joke."}], tools)
        )
        request_path = await _wait_for_request(relay_run_dir)
        packet = json.loads(request_path.read_text(encoding="utf-8"))
        assert packet["kind"] == "tools"
        assert packet["tools"] == tools
        _write_response(
            relay_run_dir,
            packet["request_id"],
            text="",
            tool_calls=[{"id": "call-1", "name": "query_memory", "arguments": {"query": "paper boat"}}],
        )
        result = await pending
        assert result.model == "gpt-6-luna"
        assert result.text == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "query_memory"
        assert json.loads(result.tool_calls[0].arguments) == {"query": "paper boat"}

    asyncio.run(scenario())


def test_metadata_call_returns_synapse_result_shape(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        pending = asyncio.create_task(
            router.call_with_metadata("casual", [{"role": "user", "content": "Keep it short."}])
        )
        packet = json.loads((await _wait_for_request(relay_run_dir)).read_text(encoding="utf-8"))
        _write_response(
            relay_run_dir,
            packet["request_id"],
            text='{"confirmed_facts": [], "relationship_updates": []}',
            finish_reason="stop",
        )
        result = await pending
        assert result.model == "gpt-6-luna"
        assert result.text.startswith("{")
        assert result.finish_reason == "stop"
        assert result.prompt_tokens == 0

    asyncio.run(scenario())


def test_only_one_inference_request_is_outstanding_at_a_time(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        first = asyncio.create_task(router.call("casual", [{"role": "user", "content": "A"}]))
        first_path = await _wait_for_request(relay_run_dir)
        first_packet = json.loads(first_path.read_text(encoding="utf-8"))
        second = asyncio.create_task(router.call("casual", [{"role": "user", "content": "B"}]))
        await asyncio.sleep(0.02)
        assert len(list((relay_run_dir / "requests").glob("*.json"))) == 1

        _write_response(relay_run_dir, first_packet["request_id"], text="A reply")
        assert await first == "A reply"
        second_path = await _wait_for_request_after(relay_run_dir, {first_packet["request_id"]})
        second_packet = json.loads(second_path.read_text(encoding="utf-8"))
        assert second_packet["messages"] == [{"role": "user", "content": "B"}]
        _write_response(relay_run_dir, second_packet["request_id"], text="B reply")
        assert await second == "B reply"

    asyncio.run(scenario())


def test_mismatched_request_id_is_rejected_and_never_accepted_as_reply(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        pending = asyncio.create_task(router.call("casual", [{"role": "user", "content": "Hi."}]))
        request_path = await _wait_for_request(relay_run_dir)
        packet = json.loads(request_path.read_text(encoding="utf-8"))
        response_dir = relay_run_dir / "responses"
        response_dir.mkdir(exist_ok=True)
        (response_dir / f"{packet['request_id']}.json").write_text(
            json.dumps({"request_id": "another-request", "text": "wrong turn"}), encoding="utf-8"
        )
        with pytest.raises(RelayProtocolError, match="request_id"):
            await pending

    asyncio.run(scenario())


def test_tool_response_cannot_invoke_a_tool_missing_from_current_schema(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=1, poll_interval_seconds=0.005)
        tools = [{
            "type": "function",
            "function": {"name": "query_memory", "parameters": {"type": "object"}},
        }]
        pending = asyncio.create_task(
            router.call_with_tools("casual", [{"role": "user", "content": "Find it."}], tools)
        )
        request_path = await _wait_for_request(relay_run_dir)
        packet = json.loads(request_path.read_text(encoding="utf-8"))
        _write_response(
            relay_run_dir,
            packet["request_id"],
            text="",
            tool_calls=[{"id": "call-1", "name": "bash_exec", "arguments": {"command": "whoami"}}],
        )
        with pytest.raises(RelayProtocolError, match="tool"):
            await pending

    asyncio.run(scenario())


def test_wait_is_bounded_when_no_model_response_arrives(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(relay_run_dir, timeout_seconds=0.02, poll_interval_seconds=0.005)
        with pytest.raises(TimeoutError, match="gpt-6-luna"):
            await router.call("casual", [{"role": "user", "content": "Never answer."}])

    asyncio.run(scenario())


def test_request_budget_stops_before_publishing_an_over_limit_prompt(relay_run_dir: Path):
    async def scenario() -> None:
        router = FileRelayRouter(
            relay_run_dir,
            timeout_seconds=1,
            poll_interval_seconds=0.005,
            max_requests=1,
        )
        first = asyncio.create_task(router.call("casual", [{"role": "user", "content": "A"}]))
        packet = json.loads((await _wait_for_request(relay_run_dir)).read_text(encoding="utf-8"))
        _write_response(relay_run_dir, packet["request_id"], text="A reply")
        assert await first == "A reply"
        with pytest.raises(RelayLimitError, match="max_requests=1"):
            await router.call("casual", [{"role": "user", "content": "B"}])
        assert len(list((relay_run_dir / "requests").glob("*.json"))) == 1

    asyncio.run(scenario())


async def _wait_for_request(run_dir: Path) -> Path:
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        requests = sorted((run_dir / "requests").glob("*.json")) if (run_dir / "requests").exists() else []
        if requests:
            return requests[0]
        await asyncio.sleep(0.005)
    raise AssertionError("relay did not publish its inference request")


async def _wait_for_request_after(run_dir: Path, seen_ids: set[str]) -> Path:
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        requests = sorted((run_dir / "requests").glob("*.json")) if (run_dir / "requests").exists() else []
        unseen = [path for path in requests if path.stem not in seen_ids]
        if unseen:
            return unseen[0]
        await asyncio.sleep(0.005)
    raise AssertionError("relay did not publish the next inference request")
