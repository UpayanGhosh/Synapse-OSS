import json
from types import SimpleNamespace

import pytest

from sci_fi_dashboard.calendar_core.models import CalendarActionResult, CalendarPreferences
from sci_fi_dashboard.tool_registry import ToolContext, ToolRegistry, register_builtin_tools


def _context() -> ToolContext:
    return ToolContext(
        chat_id="chat_001",
        sender_id="owner_123",
        sender_is_owner=True,
        workspace_dir="/tmp/synapse",
        config={},
        channel_id="api",
    )


def _calendar_tool():
    registry = ToolRegistry()
    register_builtin_tools(registry, memory_engine=SimpleNamespace(query=lambda **_: {}), project_root=".")
    return next(tool for tool in registry.resolve(_context()) if tool.name == "calendar")


def test_register_builtin_tools_includes_calendar_when_registry_resolves():
    tool = _calendar_tool()

    assert tool.name == "calendar"
    assert tool.serial is True
    assert tool.parameters["required"] == ["request"]


@pytest.mark.asyncio
async def test_calendar_tool_reports_not_connected_without_calendar_config(monkeypatch):
    import sci_fi_dashboard.tool_registry as tool_registry

    monkeypatch.setattr(
        tool_registry,
        "_get_calendar_runtime",
        lambda: (None, CalendarPreferences()),
    )
    tool = _calendar_tool()

    result = await tool.execute({"request": "What meetings do I have tomorrow?"})

    payload = json.loads(result.content)
    assert result.is_error is True
    assert "Calendar not connected" in payload["error"]


@pytest.mark.asyncio
async def test_calendar_tool_executes_natural_language_request_with_preferences(monkeypatch):
    import sci_fi_dashboard.tool_registry as tool_registry

    seen = {}
    prefs = CalendarPreferences(default_calendar_id="work", trusted_quick_add=False)

    def fake_handle(request, calendar, preferences):
        seen["request"] = request
        seen["calendar"] = calendar
        seen["preferences"] = preferences
        return CalendarActionResult(
            status="answered",
            user_message="You have standup tomorrow.",
            receipt_evidence="Checked Google Calendar through calendar service.",
            data={"events": [{"title": "Standup"}]},
        )

    calendar = object()
    monkeypatch.setattr(tool_registry, "_get_calendar_runtime", lambda: (calendar, prefs))
    monkeypatch.setattr(tool_registry, "handle_calendar_request", fake_handle)
    tool = _calendar_tool()

    result = await tool.execute({"request": "What meetings do I have tomorrow?"})

    payload = json.loads(result.content)
    assert result.is_error is False
    assert payload["status"] == "answered"
    assert payload["data"]["events"][0]["title"] == "Standup"
    assert seen == {
        "request": "What meetings do I have tomorrow?",
        "calendar": calendar,
        "preferences": prefs,
    }
