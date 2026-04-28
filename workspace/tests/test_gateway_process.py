import subprocess
from unittest.mock import Mock

import pytest

from cli.gateway_process import GatewayProcessManager


def test_reachable_returns_true_for_healthy_response(monkeypatch):
    response = Mock(status_code=200)
    monkeypatch.setattr("cli.gateway_process.httpx.get", lambda *a, **k: response)
    manager = GatewayProcessManager(port=9001)
    assert manager.is_reachable()


def test_reachable_returns_false_on_request_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("cli.gateway_process.httpx.get", raise_error)
    manager = GatewayProcessManager(port=9001)
    assert not manager.is_reachable()


def test_reachable_returns_false_for_not_found_response(monkeypatch):
    response = Mock(status_code=404)
    monkeypatch.setattr("cli.gateway_process.httpx.get", lambda *a, **k: response)
    manager = GatewayProcessManager(port=9001)
    assert not manager.is_reachable()


def test_start_spawns_uvicorn_when_unreachable(monkeypatch):
    process = Mock()
    calls = []
    monkeypatch.setattr(GatewayProcessManager, "is_reachable", lambda self: False)
    monkeypatch.setattr(GatewayProcessManager, "wait_until_ready", lambda self: True)
    monkeypatch.setattr(
        "cli.gateway_process.subprocess.Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or process,
    )

    manager = GatewayProcessManager(port=9001)
    assert manager.ensure_running() is process
    assert "uvicorn" in calls[0][0]
    assert "9001" in calls[0][0]


def test_stop_only_terminates_owned_process():
    process = Mock()
    manager = GatewayProcessManager(port=9001)
    manager._owned_process = process
    manager.stop()
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert manager._owned_process is None


def test_stop_kills_owned_process_when_terminate_wait_times_out():
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("gateway", 5), None]
    manager = GatewayProcessManager(port=9001)
    manager._owned_process = process

    manager.stop()

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert manager._owned_process is None


def test_ensure_running_reports_owned_process_early_exit(monkeypatch):
    process = Mock()
    process.poll.return_value = 7
    monkeypatch.setattr(GatewayProcessManager, "is_reachable", lambda self: False)
    monkeypatch.setattr(
        "cli.gateway_process.subprocess.Popen", lambda *args, **kwargs: process
    )

    manager = GatewayProcessManager(port=9001, timeout_sec=0)
    with pytest.raises(RuntimeError, match="exited early.*7"):
        manager.ensure_running()
