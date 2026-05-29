# Calendar Core V2 Design

## Goal

Bring Synapse's calendar capability to parity with Claude Desktop's Google
Calendar connector / `nspady/google-calendar-mcp`. After V2, Synapse can
answer **and act on** every common calendar request: read/write/freebusy
across calendars, update/delete/move/RSVP, plus Google's natural-language
`quickAdd` endpoint.

V2 builds directly on V1 (see `2026-05-05-calendar-core-v1-design.md`):
the V1 read + safe-create surface stays untouched. V2 adds the destructive
write operations V1 explicitly deferred, gated behind a two-turn
confirmation flow.

## Product Scope

V2 supports, on top of V1:

- Multi-calendar enumeration: "what calendars do I have?"
- Single-event lookup by id.
- Update / patch event:
  - title, time, description, attendees
  - recurring `modification_scope` (`thisEventOnly`, `thisAndFollowing`, `all`)
- Delete event (recurring + non-recurring).
- Move event between calendars.
- RSVP (accepted / declined / tentative / needsAction).
- `freebusy.query` across multiple calendars.
- `events.quickAdd` natural-language endpoint.
- Color palette read.

## Out Of Scope For V2

- `events.watch` / push webhooks (requires public HTTPS endpoint).
- ACL CRUD (`acl.*`).
- Attachments upload.
- Multi-Google-account session.
- Auto-sync of fetched events into `memory.db` (separate proactive milestone).

## Tool Surface

| Tool                | Status     | Google API                | Notes                                |
|---------------------|------------|---------------------------|--------------------------------------|
| (V1) get_upcoming   | unchanged  | events.list (now+30m)     |                                      |
| (V1) list_events    | unchanged  | events.list (date)        |                                      |
| (V1) search_events  | unchanged  | events.list?q=            |                                      |
| (V1) check_availability | unchanged | events.list + slot calc | conflict detection                   |
| (V1) suggest_free_slots | unchanged | events.list             |                                      |
| (V1) create_event   | unchanged  | events.insert             | now also accepts send_updates        |
| (V1) resolve_date   | unchanged  | local                     |                                      |
| (V1) get_holidays   | unchanged  | events.list + locale      |                                      |
| (V1) calendar_request | extended | local NL → core           | now routes V2 verbs too              |
| (V2) list_calendars | new        | calendarList.list         |                                      |
| (V2) get_event      | new        | events.get                |                                      |
| (V2) update_event   | new        | events.patch              | modification_scope enum              |
| (V2) delete_event   | new        | events.delete             | modification_scope enum              |
| (V2) move_event     | new        | events.move               |                                      |
| (V2) respond_to_event | new      | events.patch (self attendee) | RSVP                              |
| (V2) get_freebusy   | new        | freebusy.query            | multi-calendar                       |
| (V2) quick_add      | new        | events.quickAdd           | natural-language                     |
| (V2) list_colors    | new        | colors.get                |                                      |

Total: 9 V1 + 9 V2 = **18 MCP tools**.

## Confirmation Flow

Destructive ops never auto-execute. Flow:

1. Assistant parses intent → builds typed request → policy evaluator returns
   `can_create_now=False` with reasons.
2. Assistant **parks** the pending action in `PendingActionStore` keyed by
   `chat_id` with TTL=600s and returns `confirmation_required`. The user
   sees event title, id, evidence, reasons, and a `confirmation_id`.
3. Next user turn:
   - Affirmation (`yes`, `confirm`, `go ahead`, …) → assistant pops the
     parked action and executes it. Policy is re-evaluated with
     `force=True` so the audit trail records the decision.
   - Negation (`no`, `cancel`, `never mind`) → assistant discards the
     pending action.
   - Unrelated message → pending action stays parked until TTL expires.

The store is process-local; the cost of losing a parked action across a
gateway restart is one re-prompt.

## Attendee Invites

V1 already blocked attendee writes behind confirmation. V2 makes them
**executable** but never auto-sent:

- `CreateEventRequest.send_updates` defaults to `"none"` (Google default).
- The assistant never sets `send_updates="all"` on the first turn.
- After explicit user affirmation, the assistant retries the create with
  `send_updates="all"` so Google emails attendees.
- Update / move / delete / RSVP follow the same gate.

## Recurring-event Semantics

`modification_scope`:
- `thisEventOnly` (default) — patch / delete a single instance. The service
  resolves the instance id via `events.instances` when not provided.
- `thisAndFollowing` — patch the master. Requires explicit recurrence cutoff
  in V2 simplification; otherwise the service returns a `failed`
  `CalendarActionResult`.
- `all` — patch the master directly.

## Architecture

```
chat_pipeline._maybe_prefetch_calendar()
  └─→ tool_registry.calendar (NL tool, threads chat_id)
        └─→ calendar_core.assistant.handle_calendar_request(text, svc, prefs, chat_id=...)
              ├─→ intents.parse_calendar_intent()  → V2 intents
              │   incl. _classify_affirmation / _classify_rsvp / etc.
              ├─→ confirmations.PendingActionStore (per chat_id, TTL=600s)
              ├─→ policy.evaluate_*_policy()
              └─→ service.GoogleCalendarService (extended, +9 methods)
                    └─→ googleapiclient.discovery v3
mcp_servers/calendar_server.py  (transport — same Calendar Core)
```

## Files

New:
- `workspace/sci_fi_dashboard/calendar_core/confirmations.py`
- `workspace/tests/calendar_core/test_confirmations.py`
- `workspace/tests/test_calendar_v2_e2e.py`

Extended:
- `workspace/sci_fi_dashboard/calendar_core/models.py` (+6 request types,
  +4 result factory methods, +`ColorPalette`, +`CalendarListEntry`,
  +`FreeBusyResult`)
- `workspace/sci_fi_dashboard/calendar_core/service.py` (+9 methods)
- `workspace/sci_fi_dashboard/calendar_core/policy.py` (+3 evaluators)
- `workspace/sci_fi_dashboard/calendar_core/intents.py` (V2 verbs +
  affirmations + freebusy/quick_add)
- `workspace/sci_fi_dashboard/calendar_core/assistant.py` (V2 routing +
  pending-action plumbing)
- `workspace/sci_fi_dashboard/mcp_servers/calendar_server.py` (+9 tools +
  handlers)
- `workspace/sci_fi_dashboard/chat_pipeline.py` (write-prefetch detector,
  affirmation passthrough, threads `chat_id` into the tool)
- `workspace/sci_fi_dashboard/tool_registry.py` (calendar tool accepts
  `chat_id` argument; parameter schema documents it)
- `workspace/tests/calendar_core/test_*.py` (extended for every layer)
- `workspace/tests/test_chat_pipeline_skill_routing.py` (V2 verb +
  affirmation cases)

Unchanged:
- `workspace/cli/calendar_commands.py` — existing scopes
  (`calendar.events`, `calendar.readonly`) cover every V2 endpoint. No
  re-OAuth required.
- `workspace/sci_fi_dashboard/mcp_config.py` — no new config keys.

## OAuth Scopes

Already requested in V1:
- `https://www.googleapis.com/auth/calendar.readonly`
- `https://www.googleapis.com/auth/calendar.events`

Coverage check:
- `events.delete` / `events.patch` / `events.move` / `events.insert`:
  `calendar.events`. ✓
- `events.quickAdd`: `calendar.events`. ✓
- `freebusy.query`: `calendar.readonly`. ✓
- `calendarList.list`: `calendar.readonly`. ✓
- `colors.get`: no scope required (public). ✓
- `events.instances`: `calendar.readonly`. ✓

If Google returns 403, the assistant surfaces "Calendar token missing
scope X — run `synapse calendar connect`" with the scope name.

## Testing

Required test groups (delivered):

- `test_models.py` — V2 request validators, result factories.
- `test_confirmations.py` — TTL, eviction, isolation, double-consume.
- `test_service.py` — 16 mocked-Google cases for the new methods.
- `test_policy.py` — 20 cases for update/delete/move evaluators.
- `test_intents.py` — 13 cases for V2 verbs + affirmations.
- `test_assistant.py` — 12 cases incl. the 2-turn confirmation round-trip.
- `test_mcp_calendar_server.py` — schema + happy-path per new tool.
- `test_chat_pipeline_skill_routing.py` — write-verb detection +
  affirmation phrase recognition.
- `test_calendar_v2_e2e.py` — full tool-registry round-trip mocked
  end-to-end.

Live Google Calendar tests remain opt-in via `synapse calendar verify`.

## Acceptance

- [x] User asks "delete the 4 PM standup" → assistant lists candidate,
      asks confirmation, deletes on "yes".
- [x] User asks "move tomorrow's call to Friday at 5" → asks confirmation,
      patches the right scope on "yes".
- [x] User asks "am I free Friday afternoon across both my calendars" →
      `freebusy.query` over given calendar ids.
- [x] User asks "quick add: lunch with Aman thursday 1pm" → routes to
      Google's `quickAdd`.
- [x] User asks "RSVP yes to the budget review" → patches self attendee.
- [x] Attendee invites: confirmation always required; never auto-sent.
- [x] Recurring update with `thisEventOnly` only changes the instance.
- [x] Pending action expires after 600s; affirmation past TTL replies
      "no pending action to confirm".
- [x] All V1 tests still pass.
- [x] No personal data in commits (`entities.json` empty, no token files).

## Self-Review

- Scope is contained. Watch/ACL/attachments deferred with stated reasons.
- Every destructive op has a confirmation gate.
- No new third-party dependencies.
- V1 backwards compatible.
- Plan executable by parallel subagents on the service / policy / MCP
  layers without shared file conflict.
