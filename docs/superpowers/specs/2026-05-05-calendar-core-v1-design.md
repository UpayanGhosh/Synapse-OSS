# Calendar Core V1 Design

## Goal

Build first real Calendar capability for Synapse: user can ask useful calendar questions, search/list events, check availability, create one-off or recurring personal events, and trust Synapse to avoid unsafe writes.

This is not proactive nudges yet. This is Calendar Core: stable capability layer that later proactive workflows can call.

## Product Scope

Calendar Core V1 supports:

- Calendar Q&A:
  - "What do I have tomorrow?"
  - "How packed is my week?"
  - "Do I have anything after 5?"
- Date math:
  - "What date is next Tuesday?"
  - "First Friday of June"
  - "Tomorrow afternoon"
- Event list/search:
  - by day, week, range, title, person, or loose query
- Free/busy:
  - "Am I free Friday afternoon?"
  - "Find me 30 minutes tomorrow"
- Event creation:
  - one-off events
  - recurring personal events
  - birthday/anniversary yearly all-day events
  - daily/weekly/monthly routine events
- Trusted quick-add:
  - low-risk personal events can be created without confirmation
  - risky writes require confirmation
- Conflict handling:
  - if requested slot conflicts, do not silently create
  - ask before adding anyway
  - suggest 2-3 nearby free slots
- Holiday answers:
  - check user's visible calendar first
  - fall back to locale holiday data
  - clearly label fallback answers as locale-derived, not personal-calendar-derived

## Out Of Scope For V1

- Update/delete/reschedule existing events.
- Proactive meeting nudges.
- Meeting prep briefs.
- Daily agenda delivery.
- Multi-calendar management beyond default calendar.
- Background notification delivery.
- Sending attendee invites without confirmation.

These move to later slices after Calendar Core is stable.

## Recommended Approach

Use Option B: Calendar Core service plus MCP tools.

Do not make MCP handlers own business logic. MCP should be transport. Calendar Core owns parsing, policy, conflict checks, normalized service calls, and result formatting.

This keeps later proactive workflows simple: they can call Calendar Core methods instead of duplicating Google Calendar/MCP/tool policy logic.

## Architecture

### `calendar_models.py`

Typed request/result objects:

- `CalendarIntent`
- `CalendarQuery`
- `DateMathRequest`
- `EventSearchRequest`
- `AvailabilityRequest`
- `CreateEventRequest`
- `RecurrenceRule`
- `CalendarActionResult`
- `ConfirmationRequired`
- `ConflictResult`

Models should be plain dataclasses or Pydantic models, matching local repo style near MCP/config code.

### `calendar_policy.py`

Owns safety decisions:

- trusted quick-add eligibility
- confirmation required reasons
- conflict policy
- recurrence guardrails
- attendee/invite guardrails

Quick-add allowed only when all are true:

- action is create-only
- event is personal
- no attendees
- default calendar
- clear title
- clear start time or clear all-day yearly birthday/anniversary
- recurrence is clear if present
- no conflict detected

Confirmation required when any are true:

- attendees exist
- event sends invites
- recurrence is ambiguous
- recurrence is high-frequency and open-ended, unless user prefs allow it
- all-day/multi-day event is ambiguous
- non-default calendar
- conflict exists
- date/time parse confidence is low

### `calendar_service.py`

Normalized calendar operations:

- list events in range
- search events
- get upcoming events
- check free/busy
- suggest free slots
- create event
- create recurring event
- find holiday from personal calendar
- find holiday from locale fallback

Service wraps Google Calendar semantics and hides raw API/MCP shapes from chat and proactive layers.

### `calendar_intents.py`

Classifies and parses user requests into structured requests:

- date math
- list/search
- availability
- create event
- create recurring event
- holiday question

Parsing can start rule-based plus existing LLM/tool routing. V1 should be deterministic enough for tests around common phrases.

### `mcp_servers/calendar_server.py`

Expand current MCP server, but keep it thin:

- expose richer tools backed by Calendar Core
- keep auth check at boundary
- convert MCP arguments to model objects
- return structured JSON result

Likely tools:

- `get_upcoming`
- `list_events`
- `search_events`
- `check_availability`
- `suggest_free_slots`
- `create_event`
- `resolve_date`
- `get_holidays`

### Chat Integration

Chat pipeline/router should detect calendar intent before ordinary model reply when user clearly asks calendar work.

Flow:

1. User asks calendar-related question.
2. Intent layer returns structured request.
3. Calendar service executes read/date/free-busy immediately.
4. For writes, policy decides quick-add vs confirmation.
5. Synapse replies with answer, confirmation prompt, or action receipt.

Writes must produce action receipts with enough evidence:

- event title
- start/end
- recurrence summary if any
- calendar target
- event id/link when created
- confirmation reason when blocked

## Recurring Events

Recurring events are V1 because birthdays, anniversaries, routines, gym, medication, rent, and weekly calls are normal calendar usage.

Supported recurrence:

- daily
- weekly
- monthly
- yearly

Birthday/anniversary behavior:

- default to yearly all-day recurring event
- no attendees
- title from user phrase
- start date from provided date
- confirmation required if person/date/title ambiguous

Routine behavior:

- daily/weekly/monthly timed recurrence
- default duration from preference or safe default
- confirmation required if duration/time/start date ambiguous

No advanced recurrence in V1:

- "third weekday every other month"
- exceptions/skipped dates
- complex RRULE editing

## Conflict Handling

Before create, Calendar Core checks overlap.

If no conflict and quick-add safe:

- create event
- reply with concise receipt

If conflict:

- do not create silently
- explain conflict
- suggest 2-3 nearby free slots
- ask whether to create anyway or choose a suggested slot

## Preferences

V1 needs simple calendar preferences:

- default calendar id
- locale/country for holiday fallback
- timezone
- trusted quick-add enabled
- default event duration
- allow open-ended recurring personal events

These can live in existing config/profile storage if suitable. Do not create a second preferences system unless current config cannot represent this cleanly.

## Error Handling

User-facing errors should be useful, not raw API dumps:

- calendar not connected
- auth expired
- missing write scope
- ambiguous date/time
- no free slots found
- conflict found
- Google Calendar API failure

Each error should include next action:

- connect Calendar
- refresh auth
- clarify date/time
- confirm conflict
- choose slot

## Security And Privacy

- Calendar reads require configured Calendar MCP/auth.
- Calendar writes require events write scope.
- Invites/attendees always require confirmation.
- No delete/update in V1.
- Do not claim event creation unless Google Calendar returns created event id/link.
- Do not expose raw OAuth tokens or config paths in user chat.

## Testing

Required test groups:

- Calendar MCP tool list and schemas.
- Date math parser for common phrases.
- Event search/list range handling.
- Free/busy and slot suggestion.
- Trusted quick-add allowed cases.
- Confirmation-required blocked cases.
- Conflict detection and alternate slot suggestions.
- Recurring birthday/anniversary yearly event creation.
- Recurring routine daily/weekly/monthly creation.
- Holiday personal-calendar-first behavior.
- Locale holiday fallback labeling.
- Action receipt evidence after create.

Tests should mock Google Calendar service/API. Live Google Calendar smoke tests remain opt-in.

## Acceptance Criteria

Calendar Core V1 is done when:

- user can ask calendar read/date/free-busy questions and get grounded answers
- user can create safe one-off personal events without friction
- user can create safe recurring personal events without friction
- risky writes ask for confirmation
- conflicts never silently create
- holiday answers work from personal calendar or labeled locale fallback
- MCP Calendar server exposes expanded tools
- chat integration routes clear calendar requests
- local targeted tests pass
- live smoke path is documented but not required for normal CI

## Spec Self-Review

- No placeholder sections remain.
- Scope is limited to Calendar Core, not proactive workflows.
- Recurring events included with guardrails.
- Update/delete deferred to avoid destructive ambiguity.
- Option B chosen explicitly; Option C remains next milestone after stable Core.
