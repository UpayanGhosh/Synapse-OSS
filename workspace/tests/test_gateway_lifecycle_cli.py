from types import SimpleNamespace

from typer.testing import CliRunner


class FakeProcess:
    pid = 43210


def test_start_gateway_writes_pid_and_launches_uvicorn(tmp_path, monkeypatch):
    from cli.gateway_lifecycle import start_gateway

    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("cli.gateway_lifecycle._is_running", lambda _pid: False)
    config = SimpleNamespace(
        data_root=tmp_path,
        gateway={"bind": "loopback", "port": 8123, "token": "secret"},
    )

    started, message = start_gateway(config, popen_factory=fake_popen)

    assert started is True
    assert "43210" in message
    assert (tmp_path / "state" / "gateway.pid").read_text(encoding="utf-8") == "43210"
    assert (tmp_path / "logs" / "gateway.log").exists()
    command, kwargs = calls[0]
    assert "-m" in command
    assert command[command.index("-m") + 1] == "uvicorn"
    assert "sci_fi_dashboard.api_gateway:app" in command
    assert "--port" in command
    assert command[command.index("--port") + 1] == "8123"
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["SYNAPSE_HOME"] == str(tmp_path)
    assert kwargs["env"]["SYNAPSE_GATEWAY_TOKEN"] == "secret"


def test_start_gateway_reports_existing_live_pid(tmp_path, monkeypatch):
    from cli.gateway_lifecycle import start_gateway

    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "gateway.pid").write_text("123", encoding="utf-8")
    monkeypatch.setattr("cli.gateway_lifecycle._is_running", lambda pid: pid == 123)
    config = SimpleNamespace(data_root=tmp_path, gateway={})

    started, message = start_gateway(config, popen_factory=lambda *_args, **_kwargs: None)

    assert started is False
    assert "already running" in message


def test_stop_gateway_removes_pid_and_stops_tree(tmp_path, monkeypatch):
    from cli.gateway_lifecycle import stop_gateway

    stopped_pids = []
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "gateway.pid").write_text("123", encoding="utf-8")
    monkeypatch.setattr("cli.gateway_lifecycle._stop_process_tree", stopped_pids.append)
    config = SimpleNamespace(data_root=tmp_path, gateway={})

    stopped, message = stop_gateway(config)

    assert stopped is True
    assert message == "Synapse gateway stopped."
    assert stopped_pids == [123]
    assert not (tmp_path / "state" / "gateway.pid").exists()


def test_python_cli_exposes_start_and_stop_commands():
    from synapse_cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "start" in result.output
    assert "stop" in result.output
    assert "uninstall" in result.output
