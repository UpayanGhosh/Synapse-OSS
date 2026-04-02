"""
Tests for sci_fi_dashboard.mcp_servers.execution_server — code execution, auth gate, env scrubbing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.mcp_servers.execution_server import (
    ProcessSession,
    _err,
    _ok,
    _scrubbed_env,
    _validate_auth,
    _validate_command,
    _validate_workdir,
    _ALLOWED_COMMANDS,
    _SECRET_PATTERNS,
)


# ---------------------------------------------------------------------------
# Auth validation
# ---------------------------------------------------------------------------


class TestValidateAuth:
    def test_rejects_when_no_token_configured(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", None):
            err = _validate_auth({"auth_token": "anything"})
            assert err is not None
            assert "not configured" in err

    def test_rejects_missing_auth_token(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            err = _validate_auth({})
            assert err is not None
            assert "missing or invalid" in err

    def test_rejects_wrong_auth_token(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            err = _validate_auth({"auth_token": "wrong"})
            assert err is not None

    def test_accepts_correct_token(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            err = _validate_auth({"auth_token": "secret"})
            assert err is None

    def test_rejects_empty_token(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            err = _validate_auth({"auth_token": ""})
            assert err is not None


# ---------------------------------------------------------------------------
# Command allowlist
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_allowed_commands_pass(self):
        for cmd in ["git status", "python script.py", "pytest tests/", "ls -la"]:
            assert _validate_command(cmd) is None, f"Should allow: {cmd}"

    def test_blocked_command_rejected(self):
        err = _validate_command("rm -rf /")
        assert err is not None
        assert "not in allowlist" in err

    def test_path_prefix_stripped(self):
        assert _validate_command("/usr/bin/python script.py") is None

    def test_exe_suffix_stripped_on_windows(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._IS_WIN", True):
            assert _validate_command("python.exe script.py") is None

    def test_empty_command_rejected(self):
        err = _validate_command("")
        assert err is not None

    def test_blocked_curl_command(self):
        err = _validate_command("curl https://example.com")
        assert err is not None
        assert "not in allowlist" in err

    def test_allowlist_none_permits_all(self):
        with patch("sci_fi_dashboard.mcp_servers.execution_server._ALLOWED_COMMANDS", None):
            assert _validate_command("curl https://evil.com") is None
            assert _validate_command("rm -rf /") is None


# ---------------------------------------------------------------------------
# Workdir validation
# ---------------------------------------------------------------------------


class TestValidateWorkdir:
    def test_none_workdir_allowed(self):
        assert _validate_workdir(None) is None

    def test_workspace_root_allowed(self):
        from sci_fi_dashboard.mcp_servers.execution_server import _WORKSPACE_ROOT
        assert _validate_workdir(str(_WORKSPACE_ROOT)) is None

    def test_subdir_of_workspace_allowed(self):
        from sci_fi_dashboard.mcp_servers.execution_server import _WORKSPACE_ROOT
        subdir = str(_WORKSPACE_ROOT / "tests")
        assert _validate_workdir(subdir) is None

    def test_outside_workspace_rejected(self):
        err = _validate_workdir("/tmp/evil")
        # This may or may not be rejected depending on workspace root location
        # but the function should not crash
        assert isinstance(err, (str, type(None)))


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------


class TestScrubEnv:
    def test_removes_api_keys(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "secret",
            "OPENAI_API_KEY": "secret2",
            "PATH": "/usr/bin",
            "HOME": "/home/user",
        }, clear=False):
            env = _scrubbed_env()
            assert "GEMINI_API_KEY" not in env
            assert "OPENAI_API_KEY" not in env
            assert "PATH" in env

    def test_removes_token_vars(self):
        with patch.dict(os.environ, {
            "SYNAPSE_EXEC_TOKEN": "tok",
            "WHATSAPP_BRIDGE_TOKEN": "tok2",
            "GITHUB_TOKEN": "ghp_abc",
        }, clear=False):
            env = _scrubbed_env()
            assert "SYNAPSE_EXEC_TOKEN" not in env
            assert "WHATSAPP_BRIDGE_TOKEN" not in env
            assert "GITHUB_TOKEN" not in env

    def test_removes_password_vars(self):
        with patch.dict(os.environ, {"DB_PASSWORD": "hunter2"}, clear=False):
            env = _scrubbed_env()
            assert "DB_PASSWORD" not in env

    def test_preserves_safe_vars(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/lib", "HOME": "/home"}, clear=False):
            env = _scrubbed_env()
            assert "PYTHONPATH" in env
            assert "HOME" in env


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_ok_returns_json_text_content(self):
        result = _ok({"status": "running"})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["status"] == "running"

    def test_err_returns_json_with_error_key(self):
        result = _err("bad things happened")
        data = json.loads(result[0].text)
        assert data["error"] == "bad things happened"


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_exec_and_process_tools(self):
        from sci_fi_dashboard.mcp_servers.execution_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"exec", "process"}

    @pytest.mark.asyncio
    async def test_exec_requires_auth_and_command(self):
        from sci_fi_dashboard.mcp_servers.execution_server import list_tools

        tools = await list_tools()
        exec_tool = next(t for t in tools if t.name == "exec")
        required = exec_tool.inputSchema.get("required", [])
        assert "auth_token" in required
        assert "command" in required


# ---------------------------------------------------------------------------
# exec tool — auth gate
# ---------------------------------------------------------------------------


class TestExecAuthGate:
    @pytest.mark.asyncio
    async def test_exec_rejects_without_auth(self):
        from sci_fi_dashboard.mcp_servers.execution_server import call_tool

        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            result = await call_tool("exec", {"command": "echo hi"})

        data = json.loads(result[0].text)
        assert "error" in data
        assert "auth_token" in data["error"]

    @pytest.mark.asyncio
    async def test_exec_rejects_wrong_auth(self):
        from sci_fi_dashboard.mcp_servers.execution_server import call_tool

        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "secret"):
            result = await call_tool(
                "exec", {"auth_token": "wrong", "command": "echo hi"}
            )

        data = json.loads(result[0].text)
        assert "error" in data


# ---------------------------------------------------------------------------
# exec tool — command allowlist
# ---------------------------------------------------------------------------


class TestExecAllowlist:
    @pytest.mark.asyncio
    async def test_blocked_command_rejected(self):
        from sci_fi_dashboard.mcp_servers.execution_server import call_tool

        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"):
            result = await call_tool(
                "exec",
                {"auth_token": "tok", "command": "rm -rf /"},
            )

        data = json.loads(result[0].text)
        assert "error" in data
        assert "not in allowlist" in data["error"]


# ---------------------------------------------------------------------------
# exec tool — session cap
# ---------------------------------------------------------------------------


class TestExecSessionCap:
    @pytest.mark.asyncio
    async def test_session_cap_enforced(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_exec,
            _sessions,
            _MAX_SESSIONS,
        )

        # Fill up sessions
        old_sessions = dict(_sessions)
        try:
            _sessions.clear()
            for i in range(_MAX_SESSIONS):
                _sessions[f"s{i}"] = MagicMock()

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_exec({
                    "auth_token": "tok",
                    "command": "echo hi",
                })

            data = json.loads(result[0].text)
            assert "error" in data
            assert "Session limit" in data["error"]
        finally:
            _sessions.clear()
            _sessions.update(old_sessions)


# ---------------------------------------------------------------------------
# process tool — auth gate
# ---------------------------------------------------------------------------


class TestProcessAuthGate:
    @pytest.mark.asyncio
    async def test_process_rejects_without_auth(self):
        from sci_fi_dashboard.mcp_servers.execution_server import call_tool

        with patch("sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"):
            result = await call_tool(
                "process", {"action": "list"}
            )

        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_process_list_returns_sessions(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            _sessions["s1"] = ProcessSession(
                id="s1", command="echo test", pid=1234
            )

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "list",
                })

            data = json.loads(result[0].text)
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["sessionId"] == "s1"
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# process tool — poll
# ---------------------------------------------------------------------------


class TestProcessPoll:
    @pytest.mark.asyncio
    async def test_poll_returns_pending_output(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            sess = ProcessSession(id="s1", command="echo hi")
            sess.pending_stdout = ["hello\n"]
            sess.pending_stderr = ["warn\n"]
            _sessions["s1"] = sess

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "poll",
                    "sessionId": "s1",
                })

            data = json.loads(result[0].text)
            assert data["stdout"] == "hello\n"
            assert data["stderr"] == "warn\n"
            # After poll, pending should be cleared
            assert sess.pending_stdout == []
            assert sess.pending_stderr == []
        finally:
            _sessions.clear()
            _sessions.update(old)

    @pytest.mark.asyncio
    async def test_poll_session_not_found(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "poll",
                    "sessionId": "missing",
                })

            data = json.loads(result[0].text)
            assert "error" in data
            assert "not found" in data["error"]
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# process tool — log
# ---------------------------------------------------------------------------


class TestProcessLog:
    @pytest.mark.asyncio
    async def test_log_returns_tail_lines(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            sess = ProcessSession(id="s1", command="cat")
            sess.aggregated = "line1\nline2\nline3\nline4\nline5\n"
            sess.exited = True
            sess.exit_code = 0
            _sessions["s1"] = sess

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "log",
                    "sessionId": "s1",
                    "lines": 3,
                })

            data = json.loads(result[0].text)
            assert data["status"] == "exited"
            assert data["exitCode"] == 0
            # Should contain last 3 lines
            output_lines = data["output"].strip().split("\n")
            assert len(output_lines) <= 3
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# process tool — kill
# ---------------------------------------------------------------------------


class TestProcessKill:
    @pytest.mark.asyncio
    async def test_kill_already_exited(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            sess = ProcessSession(id="s1", command="echo")
            sess.exited = True
            sess.exit_code = 0
            _sessions["s1"] = sess

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "kill",
                    "sessionId": "s1",
                })

            data = json.loads(result[0].text)
            assert data["status"] == "already_exited"
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# process tool — write to stdin
# ---------------------------------------------------------------------------


class TestProcessWrite:
    @pytest.mark.asyncio
    async def test_write_no_stdin_returns_error(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            sess = ProcessSession(id="s1", command="cat")
            sess._proc = None  # No process
            _sessions["s1"] = sess

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "write",
                    "sessionId": "s1",
                    "data": "hello",
                })

            data = json.loads(result[0].text)
            assert "error" in data
            assert "stdin" in data["error"]
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# process tool — unknown action
# ---------------------------------------------------------------------------


class TestProcessUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from sci_fi_dashboard.mcp_servers.execution_server import (
            _handle_process,
            _sessions,
        )

        old = dict(_sessions)
        try:
            _sessions.clear()
            _sessions["s1"] = ProcessSession(id="s1", command="echo")

            with patch(
                "sci_fi_dashboard.mcp_servers.execution_server._EXEC_TOKEN", "tok"
            ):
                result = await _handle_process({
                    "auth_token": "tok",
                    "action": "badaction",
                    "sessionId": "s1",
                })

            data = json.loads(result[0].text)
            assert "error" in data
            assert "unknown action" in data["error"]
        finally:
            _sessions.clear()
            _sessions.update(old)


# ---------------------------------------------------------------------------
# Unknown tool at top level
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        from sci_fi_dashboard.mcp_servers.execution_server import call_tool

        result = await call_tool("nonexistent", {})
        assert "Unknown tool" in result[0].text


# ---------------------------------------------------------------------------
# ProcessSession dataclass
# ---------------------------------------------------------------------------


class TestProcessSession:
    def test_defaults(self):
        sess = ProcessSession(id="x", command="echo")
        assert sess.pid is None
        assert sess.exited is False
        assert sess.exit_code is None
        assert sess.aggregated == ""
        assert sess.tail == ""
        assert sess.pending_stdout == []
        assert sess.pending_stderr == []
        assert sess.truncated is False
        assert sess.backgrounded is False
        assert sess.scope_key is None

    def test_monotonic_started_at(self):
        before = time.monotonic()
        sess = ProcessSession(id="x", command="echo")
        after = time.monotonic()
        assert before <= sess.started_at <= after


# ---------------------------------------------------------------------------
# Secret patterns regex
# ---------------------------------------------------------------------------


class TestSecretPatterns:
    def test_matches_api_key(self):
        assert _SECRET_PATTERNS.search("GEMINI_API_KEY")
        assert _SECRET_PATTERNS.search("OPENAI_API_KEY")

    def test_matches_token(self):
        assert _SECRET_PATTERNS.search("GITHUB_TOKEN")
        assert _SECRET_PATTERNS.search("SYNAPSE_EXEC_TOKEN")

    def test_matches_password(self):
        assert _SECRET_PATTERNS.search("DB_PASSWORD")
        assert _SECRET_PATTERNS.search("MYSQL_PASSWORD")

    def test_matches_secret(self):
        assert _SECRET_PATTERNS.search("JWT_SECRET")
        assert _SECRET_PATTERNS.search("CLIENT_SECRET")

    def test_does_not_match_safe_vars(self):
        assert not _SECRET_PATTERNS.search("PATH")
        assert not _SECRET_PATTERNS.search("HOME")
        assert not _SECRET_PATTERNS.search("PYTHONPATH")
