# Calendar Core V2 — Implementation Plan (executed 2026-05-08)

> **Goal**: Bring Synapse's Google Calendar surface to parity with what
> Claude Desktop's Google Calendar connector / `nspady/google-calendar-mcp`
> exposes. V1 (2026-05-05) shipped read + safe-create. V2 closes the
> destructive-ops gap behind a two-turn confirmation flow.
>
> **Design doc**: `docs/superpowers/specs/2026-05-08-calendar-core-v2-design.md`

## Summary of changes (one PR)

- 9 new MCP tools wired through `mcp_servers/calendar_server.py`
  (`list_calendars`, `get_event`, `update_event`, `delete_event`,
  `move_event`, `respond_to_event`, `get_freebusy`, `quick_add`,
  `list_colors`). V1's 9 tools stay backwards-compatible.
- `calendar_core/` extended with 6 new request dataclasses, 4 new
  result-factory methods, 9 new `GoogleCalendarService` methods, 3 new
  policy evaluators (update/delete/move), V2 intent verbs +
  affirmation/negation parsers.
- New `calendar_core/confirmations.py` with a TTL-bounded
  `PendingActionStore` (default 600s, max 100 entries) keyed by
  `chat_id`.
- `assistant.handle_calendar_request` extended with a `chat_id` keyword;
  destructive intents park a pending action and return
  `confirmation_required`. Affirmation on the next turn pops the action
  and executes it.
- `tool_registry._calendar_factory` accepts and threads `chat_id`.
- `chat_pipeline._should_prefetch_calendar_write` now passes
  destructive verbs (delete/cancel/move/reschedule/update/RSVP/quick-add)
  and threads `chat_id` into the calendar tool. Affirmation phrases also
  trigger prefetch when a pending action exists for that chat_id.
- Tests across all layers: `test_models`, `test_confirmations`,
  `test_service`, `test_policy`, `test_intents`, `test_assistant`,
  `test_mcp_calendar_server`, `test_chat_pipeline_skill_routing`, plus
  new `test_calendar_v2_e2e`.

## File map

```
workspace/sci_fi_dashboard/calendar_core/
  models.py              EXTENDED
  service.py             EXTENDED (+9 methods)
  policy.py              EXTENDED (+3 evaluators)
  intents.py             EXTENDED
  assistant.py           REWRITTEN (V1 paths preserved)
  confirmations.py       NEW
  __init__.py            EXTENDED exports

workspace/sci_fi_dashboard/
  mcp_servers/calendar_server.py   EXTENDED (+9 tools, +9 handlers)
  chat_pipeline.py                 EXTENDED (write-prefetch + chat_id)
  tool_registry.py                 EXTENDED (calendar tool accepts chat_id)

workspace/tests/
  calendar_core/test_models.py
  calendar_core/test_service.py
  calendar_core/test_policy.py
  calendar_core/test_intents.py
  calendar_core/test_assistant.py
  calendar_core/test_confirmations.py   NEW
  test_mcp_calendar_server.py
  test_chat_pipeline_skill_routing.py
  test_calendar_v2_e2e.py               NEW
```

## OAuth scopes

V1's existing scopes (`calendar.readonly`, `calendar.events`) cover every
V2 endpoint. **No re-OAuth required.** If Google returns 403, the
assistant surfaces "Calendar token missing scope X — run `synapse
calendar connect`".

## Confirmation-flow contract

1. User: destructive request (e.g. "delete the 4 PM standup").
2. Assistant: `confirmation_required` + `confirmation_id`, parks
   `(intent, request, evidence, expires_at)` in `PendingActionStore`.
3. User: "yes" → assistant pops, re-evaluates policy with `force=True`,
   executes, returns receipt with verified Google event id.
4. User: "no" / "cancel" → assistant discards.
5. User: unrelated → pending stays parked until TTL.

## Verification commands

```powershell
$env:PYTHONPATH='workspace'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'

pytest -q -o addopts='' `
  workspace\tests\calendar_core `
  workspace\tests\test_mcp_calendar_server.py `
  workspace\tests\test_calendar_v2_e2e.py `
  workspace\tests\test_chat_pipeline_skill_routing.py

ruff check workspace/sci_fi_dashboard/calendar_core workspace/sci_fi_dashboard/mcp_servers/calendar_server.py
black --check workspace/sci_fi_dashboard/calendar_core workspace/sci_fi_dashboard/mcp_servers/calendar_server.py

# Live opt-in smoke
synapse calendar verify
# Then in chat: "delete tomorrow's standup", confirm with "yes".
```

## Out of scope (V3 backlog)

- `events.watch` / push notifications.
- ACL CRUD.
- Attachments.
- Multi-Google-account session.
- Auto-sync of fetched events into `memory.db`.
