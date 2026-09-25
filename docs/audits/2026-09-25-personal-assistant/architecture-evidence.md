# Scheduler, delivery, and external-capability evidence

Read-only audit of the current checkout. No live account, channel, private memory DB, or external send was used. Repository-specific docs had no `docs/AGENTS.md`; current source takes precedence over older design documents.

## Saturday WhatsApp reminder

The explicit reminder path in [pipeline_helpers.py](../../../workspace/sci_fi_dashboard/pipeline_helpers.py:373) parses a request into one timezone-aware date, then [pipeline_helpers.py](../../../workspace/sci_fi_dashboard/pipeline_helpers.py:600) adds a CronService `at` job carrying the incoming channel and recipient. It returns a schedule receipt after `add()` succeeds. A pure-source probe exercised the actual parser definitions with fixed Tuesday `2026-09-22 14:00 Asia/Kolkata`: “Please remind me Saturday morning at 9 am to get movie tickets” resolved to `2026-09-26T09:00:00+05:30`, task `get movie tickets`.

CronService persists each add/update/remove to the per-agent JSON store using an atomic temp-file replace ([store.py](../../../workspace/sci_fi_dashboard/cron/store.py:31), [service.py](../../../workspace/sci_fi_dashboard/cron/service.py:93), [service.py](../../../workspace/sci_fi_dashboard/cron/service.py:165)). A synthetic future WhatsApp job survived service stop/start with its ISO time and recipient intact; removing it remained effective after reload. Scheduler timezone cron expressions use `ZoneInfo`; one-shot ISO datetimes preserve their explicit offset, while naive `at` values are assumed UTC ([schedule.py](../../../workspace/sci_fi_dashboard/cron/schedule.py:53), [schedule.py](../../../workspace/sci_fi_dashboard/cron/schedule.py:85)). Natural-language reminder timezone comes from numeric `timezone_offset_hours`, then machine-local fixed offset, so DST-aware IANA preference is not represented on this path ([pipeline_helpers.py](../../../workspace/sci_fi_dashboard/pipeline_helpers.py:277)).

Restart behavior is explicit: overdue `wake_mode=now` jobs execute during startup; `next-heartbeat` jobs advance without delivery ([service.py](../../../workspace/sci_fi_dashboard/cron/service.py:462)). The reminder path uses `now`, so a long outage can deliver a stale reminder on restart. Cron jobs have CRUD methods internally, but the authenticated route file exposes list and force-run only—no cancel endpoint surfaced ([routes/cron.py](../../../workspace/sci_fi_dashboard/routes/cron.py:15)).

## Delivery reliability

WhatsApp ordinary worker replies have a persistent SQLite retry queue. The gateway starts it and attaches it to the WhatsApp channel ([api_gateway.py](../../../workspace/sci_fi_dashboard/api_gateway.py:104)); the worker enqueues when `channel.send()` returns false ([worker.py](../../../workspace/sci_fi_dashboard/gateway/worker.py:226)). It polls every 10 seconds and retries after 30s, 60s, 120s, 300s, and 600s, then dead-letters after six total attempts ([retry_queue.py](../../../workspace/sci_fi_dashboard/gateway/retry_queue.py:20), [retry_queue.py](../../../workspace/sci_fi_dashboard/gateway/retry_queue.py:27), [retry_queue.py](../../../workspace/sci_fi_dashboard/gateway/retry_queue.py:185)).

Scheduled Cron delivery takes a separate route: `CronService._execute_job()` calls `deliver_output()` and records the returned delivery status ([service.py](../../../workspace/sci_fi_dashboard/cron/service.py:288)); announce delivery calls `channel.send()` directly and returns an error receipt on `False` ([delivery.py](../../../workspace/sci_fi_dashboard/cron/delivery.py:73)). It does not enqueue through the WhatsApp retry queue. A fake channel returning false verified this behavior: one send attempt, `delivery_status=error`, `last_run_status=ok`, `next_run_at_ms=null` for the expired one-shot, and no retry call. This is a concrete lost-reminder path; the job execution status remains `ok` even though delivery failed.

The channel adapter's `send()` result is an HTTP 200 check against the local bridge ([whatsapp.py](../../../workspace/sci_fi_dashboard/channels/whatsapp.py:494)); no external WhatsApp delivery receipt was checked. The cron responder currently hardcodes `persona_chat(req, "the_creator")` even though it builds `ChatRequest.user_id` from the scheduled recipient ([api_gateway.py](../../../workspace/sci_fi_dashboard/api_gateway.py:290)). That is documented separately in the identity evidence.

## Calendar, Gmail, weather, and maps

Calendar and Gmail are real optional integrations, not active by default for a fresh config: `load_mcp_config(None)` disables MCP ([mcp_config.py](../../../workspace/sci_fi_dashboard/mcp_config.py:87)); configured built-ins are connected only when enabled ([mcp_client.py](../../../workspace/sci_fi_dashboard/mcp_client.py:138)). Calendar provides event listing/search, upcoming events, availability, create/edit/delete and other operations; Gmail provides search/read/unread/send. Calendar preferences include timezone and default calendar ([mcp_config.py](../../../workspace/sci_fi_dashboard/mcp_config.py:32)); OAuth credentials/scopes are required by the integration setup docs and code. No live credentials were loaded or tested.

The optional proactive poller queries configured Calendar `get_upcoming`, Gmail `get_unread`, and Slack `get_mentions` sources ([proactive_engine.py](../../../workspace/sci_fi_dashboard/proactive_engine.py:98)). Default poll interval is 60 seconds and Calendar lookahead 30 minutes, but the source map defaults empty ([mcp_config.py](../../../workspace/sci_fi_dashboard/mcp_config.py:10)). A separate GentleWorker can ask the policy for a reach-out and send directly through a channel ([gentle_worker.py](../../../workspace/sci_fi_dashboard/gentle_worker.py:239)). This is polling plus a generic check-in, not an event-owned planner with a durable per-event plan.

Weather exists as a bundled, user-invoked skill using Open-Meteo geocoding and current conditions ([weather.py](../../../workspace/sci_fi_dashboard/skills/bundled/synapse.weather/scripts/weather.py:21)); it does not currently fetch departure-time forecasts for a scheduled event. Repository search found no first-party Maps, Places, Directions, traffic, or travel-time service/tool. A custom MCP server is extensible, but that is not installed or verified evidence of current capability ([mcp_client.py](../../../workspace/sci_fi_dashboard/mcp_client.py:138)).

For the “5pm date” scenario, an already-configured Calendar poll could surface an event within its 30-minute lookahead. The checked-in proactive inputs contain calendar/email/Slack, with no location, route, traffic, weather-at-arrival, or departure-time computation. Nothing currently creates and refreshes a durable event watcher when an event is added or changed. Fresh restaurant/movie/flower research would need a user-triggered web source or a new configured service; no Maps-backed local recommendation path surfaced.

## General action execution boundary

The repo has generic web scrape and browser automation primitives, but this audit verified no dedicated merchant checkout/order integration or idempotent purchase workflow. Treat placing orders as a future example of a general authorized task executor: identify an available capability, verify item/address/price/payment terms, persist an attempt, reconcile uncertain results before retry, and return a receipt. Browser primitives alone are not proof a transaction completed.

## Test and environment evidence

- Natural-language parser synthetic scenario: PASS, Tuesday → Saturday 09:00 `+05:30`.
- Cron lifecycle synthetic scenario: PASS, future one-shot persisted across stop/start; cancellation persisted.
- Cron delivery failure synthetic scenario: PASS, failure status captured; no retry; one-shot exhausted.
- No live WhatsApp send or Google/MCP call was performed.
- Importing the full gateway/parser path fails in this environment because `pyarrow` is absent (through `memory_engine`); no package installation was attempted. The parser probe used the checked-in pure definitions with a fixed clock/timezone instead.
