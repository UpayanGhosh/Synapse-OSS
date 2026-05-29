# Calendar Core V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Calendar Core V1 so Synapse can answer calendar questions, resolve date math, search/list events, check free/busy, and create safe one-off or recurring personal events.

**Architecture:** Add a focused `sci_fi_dashboard.calendar_core` package with models, policy, date/intent parsing, Google Calendar service adapters, and response orchestration. Keep `mcp_servers/calendar_server.py` as transport and expose a chat-facing `calendar` tool through `tool_registry.py` so normal chat can use the same core.

**Tech Stack:** Python 3, Pydantic/dataclasses, Google Calendar API client, existing MCP server/client, existing ToolRegistry, pytest/pytest-asyncio.

---

## File Structure

- Create `workspace/sci_fi_dashboard/calendar_core/__init__.py`: public exports.
- Create `workspace/sci_fi_dashboard/calendar_core/models.py`: request/result dataclasses and enums.
- Create `workspace/sci_fi_dashboard/calendar_core/date_math.py`: deterministic date/range phrase resolver.
- Create `workspace/sci_fi_dashboard/calendar_core/policy.py`: quick-add, confirmation, recurrence, conflict rules.
- Create `workspace/sci_fi_dashboard/calendar_core/service.py`: Google Calendar operation wrapper.
- Create `workspace/sci_fi_dashboard/calendar_core/intents.py`: rule-based V1 intent parser.
- Create `workspace/sci_fi_dashboard/calendar_core/assistant.py`: high-level `handle_calendar_request()` orchestration for chat/tool use.
- Modify `workspace/sci_fi_dashboard/mcp_servers/calendar_server.py`: use Calendar Core and expose richer MCP tools.
- Modify `workspace/sci_fi_dashboard/tool_registry.py`: register chat-facing `calendar` tool.
- Modify `workspace/sci_fi_dashboard/mcp_config.py`: add calendar preference model with safe defaults.
- Add tests under `workspace/tests/calendar_core/` and extend `workspace/tests/test_mcp_calendar_server.py`.

## Task 1: Calendar Models

**Files:**
- Create: `workspace/sci_fi_dashboard/calendar_core/__init__.py`
- Create: `workspace/sci_fi_dashboard/calendar_core/models.py`
- Test: `workspace/tests/calendar_core/test_models.py`

- [ ] Write failing tests for default preferences, recurrence summaries, and action result receipts.

```python
from datetime import datetime, timezone

from sci_fi_dashboard.calendar_core.models import (
    CalendarPreferences,
    CalendarActionResult,
    CreateEventRequest,
    RecurrenceRule,
)


def test_preferences_default_to_trusted_quick_add_enabled():
    prefs = CalendarPreferences()
    assert prefs.default_calendar_id == "primary"
    assert prefs.trusted_quick_add is True
    assert prefs.default_event_duration_minutes == 60


def test_yearly_recurrence_summary_for_birthday():
    rule = RecurrenceRule(frequency="yearly")
    assert rule.to_google_rrule() == ["RRULE:FREQ=YEARLY"]
    assert rule.summary() == "every year"


def test_action_result_receipt_includes_event_evidence():
    result = CalendarActionResult.created(
        event_id="evt_123",
        link="https://calendar.google.com/event?id=evt_123",
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    assert result.status == "created"
    assert "Gym" in result.user_message
    assert "evt_123" in result.receipt_evidence
```

- [ ] Run red test:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\calendar_core\test_models.py
```

Expected: import failure for `sci_fi_dashboard.calendar_core`.

- [ ] Implement `models.py` with dataclasses:

```python
@dataclass(slots=True)
class CalendarPreferences:
    default_calendar_id: str = "primary"
    timezone: str = "Asia/Calcutta"
    locale_country: str = "IN"
    trusted_quick_add: bool = True
    default_event_duration_minutes: int = 60
    allow_open_ended_recurring_personal_events: bool = True
```

Also define:
- `RecurrenceRule(frequency: Literal["daily","weekly","monthly","yearly"], until: str | None = None, count: int | None = None)`
- `CreateEventRequest`
- `AvailabilityRequest`
- `CalendarEvent`
- `CalendarConflict`
- `ConfirmationRequired`
- `CalendarActionResult`

- [ ] Run model tests green.

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\calendar_core workspace\tests\calendar_core\test_models.py
git commit -m "feat(calendar): add core models"
```

## Task 2: Date Math Parser

**Files:**
- Create: `workspace/sci_fi_dashboard/calendar_core/date_math.py`
- Test: `workspace/tests/calendar_core/test_date_math.py`

- [ ] Write tests for common phrases.

```python
from datetime import date

from sci_fi_dashboard.calendar_core.date_math import resolve_date_phrase


BASE = date(2026, 5, 5)  # Tuesday


def test_resolves_next_tuesday_as_following_week():
    result = resolve_date_phrase("next Tuesday", base_date=BASE)
    assert result.date.isoformat() == "2026-05-12"
    assert result.confidence >= 0.8


def test_resolves_tomorrow_afternoon_range():
    result = resolve_date_phrase("tomorrow afternoon", base_date=BASE)
    assert result.start.isoformat().startswith("2026-05-06T12:00:00")
    assert result.end.isoformat().startswith("2026-05-06T17:00:00")


def test_resolves_first_friday_of_june():
    result = resolve_date_phrase("first Friday of June", base_date=BASE)
    assert result.date.isoformat() == "2026-06-05"
```

- [ ] Implement deterministic resolver for:
  - today, tomorrow, yesterday
  - weekday names and `next <weekday>`
  - morning/afternoon/evening/night ranges
  - `first|second|third|fourth|last <weekday> of <month>`
  - ISO dates and month-day phrases

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\calendar_core\test_date_math.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\calendar_core\date_math.py workspace\tests\calendar_core\test_date_math.py
git commit -m "feat(calendar): resolve common date phrases"
```

## Task 3: Calendar Policy

**Files:**
- Create: `workspace/sci_fi_dashboard/calendar_core/policy.py`
- Test: `workspace/tests/calendar_core/test_policy.py`

- [ ] Write tests for quick-add and confirmation gates.

```python
from sci_fi_dashboard.calendar_core.models import CalendarPreferences, CreateEventRequest, CalendarConflict, RecurrenceRule
from sci_fi_dashboard.calendar_core.policy import evaluate_create_policy


def test_safe_personal_event_quick_adds_without_confirmation():
    req = CreateEventRequest(title="Gym", start="2026-05-06T19:00:00+05:30", end="2026-05-06T20:00:00+05:30")
    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])
    assert decision.can_create_now is True


def test_attendees_require_confirmation():
    req = CreateEventRequest(title="Call", start="2026-05-06T16:00:00+05:30", end="2026-05-06T17:00:00+05:30", attendees=["a@example.com"])
    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])
    assert decision.can_create_now is False
    assert "attendees" in decision.reasons


def test_conflict_requires_confirmation_and_slot_suggestions():
    req = CreateEventRequest(title="Gym", start="2026-05-06T19:00:00+05:30", end="2026-05-06T20:00:00+05:30")
    conflict = CalendarConflict(title="Standup", start="2026-05-06T19:00:00+05:30", end="2026-05-06T19:30:00+05:30")
    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[conflict])
    assert decision.can_create_now is False
    assert "conflict" in decision.reasons


def test_yearly_birthday_can_quick_add_when_clear():
    req = CreateEventRequest(title="Arjun birthday", start="2026-07-12", end="2026-07-13", all_day=True, recurrence=RecurrenceRule("yearly"))
    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])
    assert decision.can_create_now is True
```

- [ ] Implement `evaluate_create_policy()`:
  - allow quick-add only when trusted quick-add enabled, no attendees, primary calendar, high parse confidence, no conflict
  - require confirmation for attendees, conflict, non-primary calendar, low confidence, ambiguous recurrence

- [ ] Run policy tests.

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\calendar_core\policy.py workspace\tests\calendar_core\test_policy.py
git commit -m "feat(calendar): add quick-add policy"
```

## Task 4: Calendar Service

**Files:**
- Create: `workspace/sci_fi_dashboard/calendar_core/service.py`
- Test: `workspace/tests/calendar_core/test_service.py`

- [ ] Write tests with mocked Google Calendar service for list/search/free-busy/create/recurrence.

```python
from unittest.mock import MagicMock

from sci_fi_dashboard.calendar_core.models import CreateEventRequest, RecurrenceRule
from sci_fi_dashboard.calendar_core.service import GoogleCalendarService


def test_create_recurring_event_writes_google_rrule():
    svc = MagicMock()
    svc.events().insert().execute.return_value = {"id": "evt_1", "htmlLink": "https://calendar/event"}
    calendar = GoogleCalendarService(svc)

    result = calendar.create_event(CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        recurrence=RecurrenceRule("daily"),
    ))

    body = svc.events().insert.call_args.kwargs["body"]
    assert body["recurrence"] == ["RRULE:FREQ=DAILY"]
    assert result.status == "created"
```

- [ ] Implement service methods:
  - `list_events(start, end, calendar_id="primary", query=None)`
  - `search_events(query, start, end, calendar_id="primary")`
  - `check_conflicts(start, end, calendar_id="primary")`
  - `suggest_free_slots(day_start, day_end, duration_minutes, calendar_id="primary")`
  - `create_event(request, calendar_id="primary")`
  - `find_holidays(name_or_range, preferences)`

- [ ] Preserve Google Calendar API shapes:
  - timed start/end: `{"dateTime": "..."}`
  - all-day start/end: `{"date": "YYYY-MM-DD"}`
  - recurrence: `["RRULE:FREQ=DAILY"]`, `WEEKLY`, `MONTHLY`, `YEARLY`

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\calendar_core\test_service.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\calendar_core\service.py workspace\tests\calendar_core\test_service.py
git commit -m "feat(calendar): add Google Calendar service"
```

## Task 5: Intent Parser And Assistant Orchestrator

**Files:**
- Create: `workspace/sci_fi_dashboard/calendar_core/intents.py`
- Create: `workspace/sci_fi_dashboard/calendar_core/assistant.py`
- Test: `workspace/tests/calendar_core/test_intents.py`
- Test: `workspace/tests/calendar_core/test_assistant.py`

- [ ] Write tests for natural phrases:

```python
from sci_fi_dashboard.calendar_core.intents import parse_calendar_intent


def test_parse_gym_daily_recurring_create():
    intent = parse_calendar_intent("Add gym every day at 7 PM starting tomorrow")
    assert intent.kind == "create_event"
    assert intent.create.title.lower() == "gym"
    assert intent.create.recurrence.frequency == "daily"


def test_parse_birthday_as_yearly_all_day():
    intent = parse_calendar_intent("Remember Arjun's birthday on July 12 every year")
    assert intent.kind == "create_event"
    assert intent.create.all_day is True
    assert intent.create.recurrence.frequency == "yearly"


def test_parse_availability_question():
    intent = parse_calendar_intent("Am I free Friday afternoon?")
    assert intent.kind == "availability"
```

- [ ] Implement V1 parser with deterministic rules for:
  - list/search: `what do I have`, `meetings`, `events`, `calendar`
  - availability: `am I free`, `find me <N> min`, `free slot`
  - create: `add`, `schedule`, `put`, `create`
  - recurrence: `every day`, `daily`, `weekly`, `every Monday`, `monthly`, `every year`
  - birthdays/anniversaries: yearly all-day
  - holiday: `holiday`, `holidays`, named holiday

- [ ] Implement `handle_calendar_request(text, calendar_service, preferences, now=None)`:
  - parse intent
  - execute read/date/availability immediately
  - for creates, check conflicts, evaluate policy, create only when allowed
  - return `CalendarActionResult` with user message and receipt evidence

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\calendar_core\test_intents.py workspace\tests\calendar_core\test_assistant.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\calendar_core\intents.py workspace\sci_fi_dashboard\calendar_core\assistant.py workspace\tests\calendar_core
git commit -m "feat(calendar): add intent orchestration"
```

## Task 6: MCP Calendar Server Expansion

**Files:**
- Modify: `workspace/sci_fi_dashboard/mcp_servers/calendar_server.py`
- Test: `workspace/tests/test_mcp_calendar_server.py`

- [ ] Update MCP tool list to include:
  - `get_upcoming`
  - `list_events`
  - `search_events`
  - `check_availability`
  - `suggest_free_slots`
  - `create_event`
  - `resolve_date`
  - `get_holidays`
  - `calendar_request`

- [ ] Keep existing tool names backward compatible.

- [ ] Add MCP tests:

```python
@pytest.mark.asyncio
async def test_lists_expanded_calendar_tools():
    from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

    names = {t.name for t in await list_tools()}
    assert {"get_upcoming", "list_events", "create_event", "search_events", "check_availability", "calendar_request"} <= names
```

- [ ] Route `call_tool()` handlers through Calendar Core. Convert returned `CalendarActionResult` to JSON:

```json
{
  "status": "created|answered|confirmation_required|failed",
  "message": "user-visible answer",
  "receipt_evidence": "verified evidence",
  "data": {}
}
```

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\test_mcp_calendar_server.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\mcp_servers\calendar_server.py workspace\tests\test_mcp_calendar_server.py
git commit -m "feat(calendar): expand MCP server tools"
```

## Task 7: Chat Tool Registration

**Files:**
- Modify: `workspace/sci_fi_dashboard/tool_registry.py`
- Test: `workspace/tests/calendar_core/test_tool_registry_calendar.py`

- [ ] Add `calendar` SynapseTool factory after existing web/memory/read/write factories.

Tool schema:

```python
{
    "type": "object",
    "properties": {
        "request": {
            "type": "string",
            "description": "The user's calendar request in natural language.",
        }
    },
    "required": ["request"],
}
```

- [ ] Factory behavior:
  - if MCP calendar config absent/disabled, return tool that says Calendar not connected
  - otherwise build Google Calendar service using same credential resolver as MCP server
  - call `handle_calendar_request()`
  - return `ToolResult(content=json.dumps(result.to_dict()), is_error=result.status == "failed")`
  - mark tool `serial=True`

- [ ] Tests:

```python
def test_register_builtin_tools_includes_calendar_when_registry_resolves():
    from sci_fi_dashboard.tool_registry import ToolRegistry, register_builtin_tools, ToolContext

    registry = ToolRegistry()
    register_builtin_tools(registry, memory_engine=None, project_root=".")
    tools = registry.resolve(ToolContext("u", "u", True, ".", {}, "api"))
    assert any(t.name == "calendar" for t in tools)
```

- [ ] Add one persona/chat pipeline canary if needed:
  - user message containing `calendar` enables tools
  - tool result receipt prevents fake calendar claims

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\calendar_core\test_tool_registry_calendar.py workspace\tests\pipeline\test_call_budget.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\tool_registry.py workspace\tests\calendar_core\test_tool_registry_calendar.py workspace\tests\pipeline\test_call_budget.py
git commit -m "feat(calendar): expose calendar chat tool"
```

## Task 8: Config Preferences

**Files:**
- Modify: `workspace/sci_fi_dashboard/mcp_config.py`
- Test: `workspace/tests/test_mcp_config.py`

- [ ] Add `CalendarPreferencesConfig` and optional `calendar_preferences` to `MCPConfig`.

Expected config shape:

```json
{
  "mcp": {
    "calendar_preferences": {
      "default_calendar_id": "primary",
      "timezone": "Asia/Calcutta",
      "locale_country": "IN",
      "trusted_quick_add": true,
      "default_event_duration_minutes": 60,
      "allow_open_ended_recurring_personal_events": true
    }
  }
}
```

- [ ] Tests:

```python
def test_calendar_preferences_defaults():
    from sci_fi_dashboard.mcp_config import load_mcp_config

    cfg = load_mcp_config({"enabled": True})
    assert cfg.calendar_preferences.default_calendar_id == "primary"
    assert cfg.calendar_preferences.trusted_quick_add is True
```

- [ ] Run:

```powershell
$env:PYTHONPATH='workspace'; pytest -q -o addopts='' workspace\tests\test_mcp_config.py
```

- [ ] Commit:

```powershell
git add workspace\sci_fi_dashboard\mcp_config.py workspace\tests\test_mcp_config.py
git commit -m "feat(calendar): add calendar preferences"
```

## Task 9: Docs And Status Update

**Files:**
- Modify: `ONBOARDING_BUGS.md`
- Optional modify: `docs/superpowers/specs/2026-05-05-calendar-core-v1-design.md`

- [ ] Update Issue 9 / FR-2 status:
  - Calendar Core V1 implemented
  - proactive nudges still future slice
  - live Google Calendar smoke remains opt-in

- [ ] Add a short verification block with exact pytest command and result.

- [ ] Commit:

```powershell
git add ONBOARDING_BUGS.md docs\superpowers\specs\2026-05-05-calendar-core-v1-design.md
git commit -m "docs(calendar): record core integration status"
```

## Task 10: Final Verification

**Files:** no edits expected.

- [ ] Run focused calendar suite:

```powershell
$env:PYTHONPATH='workspace'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
pytest -q -o addopts='' workspace\tests\calendar_core workspace\tests\test_mcp_calendar_server.py workspace\tests\test_mcp_config.py workspace\tests\pipeline\test_call_budget.py
```

- [ ] Run MCP foundation suite:

```powershell
$env:PYTHONPATH='workspace'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
pytest -q -o addopts='' workspace\tests\test_mcp_calendar_server.py workspace\tests\test_mcp_client.py workspace\tests\test_mcp_config.py workspace\tests\test_proactive_engine.py workspace\tests\test_proactive_policy.py
```

- [ ] Run graph risk scan:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
uv tool run --offline code-review-graph detect-changes --base HEAD --brief
```

- [ ] If Windows temp/cache ACLs break pytest, rerun with repo-local temp:

```powershell
$stamp=[guid]::NewGuid().ToString('N')
$temp="D:\Shorty\Synapse-OSS\.codex-tmp\calendar-core-tmp-$stamp"
$base="D:\Shorty\Synapse-OSS\.codex-tmp\calendar-core-base-$stamp"
$cache="D:\Shorty\Synapse-OSS\.codex-tmp\calendar-core-pycache-$stamp"
New-Item -ItemType Directory -Force -Path $temp | Out-Null
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$env:PYTHONPATH='workspace'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:TEMP=$temp
$env:TMP=$temp
$env:PYTHONPYCACHEPREFIX=$cache
pytest -q -o addopts='' --basetemp=$base workspace\tests\calendar_core workspace\tests\test_mcp_calendar_server.py workspace\tests\test_mcp_config.py
```

## Acceptance Checklist

- [ ] Calendar read/date/free-busy questions return grounded answers.
- [ ] Safe personal one-off creates without confirmation.
- [ ] Safe birthday/anniversary yearly recurrence creates without confirmation.
- [ ] Safe routine daily/weekly/monthly recurrence creates without confirmation.
- [ ] Attendee/invite writes require confirmation.
- [ ] Conflicts require confirmation and include 2-3 alternate slots.
- [ ] MCP calendar server exposes expanded tool list.
- [ ] Chat tool `calendar` is available in tool registry.
- [ ] Calendar failures do not create fake action receipts.
- [ ] `ONBOARDING_BUGS.md` reflects Core done, proactive still open.

## Implementation Notes

- Do not implement update/delete/reschedule in V1.
- Do not add proactive nudges in this slice.
- Do not claim live Google Calendar success in tests; mock API calls.
- Keep MCP auth behavior unchanged: `check_mcp_auth(arguments)` remains boundary guard.
- Keep existing `get_upcoming`, `list_events`, and `create_event` tool names backward compatible.
- Use repo-local temp/cache when pytest hits Windows ACL weirdness.
