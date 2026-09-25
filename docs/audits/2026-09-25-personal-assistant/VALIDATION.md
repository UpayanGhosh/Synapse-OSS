# Durable reminder slice validation

Status: focused implementation validation complete. No live account, message, purchase, or outside service was used.

## Test-first evidence

- **Reminder delivery RED:** Existing `CronService.run()` with fake `channel.send=False` returned `delivery.status='error'`; the one-shot's next run was cleared and there was no retryable send. The first acceptance run was 1 failed / 3 passed. After outbox integration, that suite passed.
- **Inbound RED:** New `InboxStore` was absent; the inbound durability suite could not collect. `FloodGate` now commits a provider envelope before buffering and route ACK. Inbound capture failure returns 503, allowing provider retry. Dedicated route and replay tests pass.
- **Time parsing RED:** Checked-in `_parse_reminder_request` resolved Tuesday 2026-09-22 14:00 +05:30, “remind me at 9am” to 2027-09-22 09:00. After the narrow rollover fix it resolves to Wednesday 2026-09-23 09:00; Sunday→next Saturday remains correct.
- **Receipt semantics RED:** A verified channel acceptance receipt incorrectly supported a `deliver` claim. The alias now supports `send` but does not prove recipient delivery.
- **TDD sequence exception:** Independent review found that the gateway started the outbox poller and message worker before restoring CronService jobs. The startup order was corrected before a dedicated regression was captured. This was a review-first correction, not a test-first change. The later structural guard passes on current source and fails on an isolated copy with the old early `retry_queue.start()` position. This does not execute the full gateway lifespan.
- **Online inbound recovery RED:** With the existing worker constructor and a running FloodGate/MessageWorker, a transient processor error left the captured row pending without a second call; a permanent error never reached dead-letter. Both behavior tests failed before the worker change. The first draft of the new API tests had failed earlier at a missing constructor argument, which alone was not behavioral proof. After the fix, transient work completes on attempt two, and permanent failure stops at the configured cap and queues one safe terminal notice.
- **Batch callback RED:** After the poller claimed an overdue inbound row, an exception in FloodGate's async batch callback left the row `processing` while the gateway stayed alive. The callback now records the failed claim in the same bounded retry path. A concurrent-claim test confirms a duplicate queued task cannot invoke the processor twice.

## Verification commands

From repository root on Windows, with repo-local temp/cache settings as needed:

```powershell
$env:PYTHONPATH='workspace'
rtk proxy python -m pytest -q -p no:tmpdir -p no:cacheprovider tests
rtk proxy python -m ruff check workspace/sci_fi_dashboard/gateway/durable_io.py workspace/sci_fi_dashboard/gateway/flood.py workspace/sci_fi_dashboard/gateway/queue.py workspace/sci_fi_dashboard/gateway/retry_queue.py workspace/sci_fi_dashboard/gateway/worker.py workspace/sci_fi_dashboard/routes/whatsapp.py workspace/sci_fi_dashboard/channel_setup.py workspace/sci_fi_dashboard/cron/types.py workspace/sci_fi_dashboard/cron/store.py workspace/sci_fi_dashboard/cron/service.py workspace/sci_fi_dashboard/cron/delivery.py workspace/sci_fi_dashboard/pipeline_helpers.py workspace/sci_fi_dashboard/action_receipts.py workspace/sci_fi_dashboard/api_gateway.py tests
rtk git diff --check
```

Final checkpoint after online recovery: **28 tests passed**, touched-source and test Ruff checks passed, and `git diff --check` passed. Independent review found no P0/P1 blocker in the fake-channel scope.

## Proof boundaries

Fake channels prove durable local handoff, retry, stable occurrence deduplication, owner rejection, overdue catch-up, and restart behavior. Unhandled processing failures now retry with stored attempts/backoff while the gateway is online and stop at dead-letter after the configured cap. A handled failure that produces a persisted user reply remains completed. A local SQLite failure while recording a processing failure can leave its claim until gateway restart. `accepted` means the channel adapter returned success; it is not proof a human device received or read the message. External transports without idempotency can still duplicate an accepted send if the process crashes after provider acceptance but before the local status commit. A channel provider without a stable message ID cannot deduplicate independent retries across callbacks; it receives a generated fallback ID per callback. A sleeping/offline gateway cannot dispatch on time; catch-up runs after restart. Full gateway import remains blocked in this environment by missing `pyarrow`, so route tests use narrowly stubbed heavyweight dependencies while exercising the real handler; the startup test verifies source order structurally. No live bridge or Google account was used. The maintainer's private behavioral reference was unavailable in this workspace, so reference parity is unverified.
