# Legacy style-control re-extraction

The saved Luna simulation database has ten processed personal observations across two owners and two active tone/verbosity relationship rows, both for Alice. Its older relationship table lacks `style_control`. Resetting those processed observations would replay unrelated fact and preference extraction, so this change uses a separate, explicit style-only job queue.

## Contract

- `PersonalMemoryService.queue_missing_style_controls(context, limit=32) -> int` seeds one bounded page for a verified private owner. SQL restricts candidates to active, same-owner user episodes with tone/verbosity and a NULL control, and excludes already queued rows before `LIMIT`. A trusted private inbound capture seeds at most four jobs; no global startup scan runs.
- `await process_style_reextract_once(context, limit=4)` handles that owner's queued jobs. The existing background pump handles at most two queued jobs per cycle. `style_reextract_status(context)` returns owner-scoped counts for `pending`, `processing`, `classified`, `unclassified`, `failed`, and `skipped`.
- A job is unique per relationship row and extractor version (`style-control-v1`). Claim uses a 60-second lease and random token; the production extraction timeout is 15 seconds. Constructor overrides for a test relay require the lease to exceed the timeout by more than five seconds. An expired lease is reclaimable; a late result cannot apply after its token or lease loses validity.
- The existing V2 router extractor receives the captured user turn and exact existing field/value/evidence as quoted JSON data. It returns only `{ "style_control": <field-valid enum or null> }`. Explicit null is a terminal, honest abstention. Missing keys, extra keys, bad enums, or model failures retry at most three times with backoff, then become `failed`.
- Classification updates only the NULL control on the same row when the source is still active, private, and same-owner. Existing value, evidence, timestamps, facts, and non-NULL controls are unchanged. Correction or scope change during model inference marks the job skipped. A successful projection increments the relationship version.

## TDD and limits

The first four tests failed because the API did not exist. A later RED test exposed an owner mismatch reaching the extractor after queueing; claim-time owner validation fixed it. A sync-extractor timeout RED showed that synchronous work could exceed the lease-safe timeout; it now runs under the same bounded async timeout.

The focused re-extraction suite passed **9 tests**. It covers old-table migration, unchanged provenance, bounded and idempotent seeding, owner and stale-source filters, automatic capture/pump progress after restart, explicit abstention, malformed-output retries, expired-lease reclaim with stale-token rejection, scope change before model input, and synchronous timeout. The broader service/retrieval regression suite and the synthetic Luna backup migration are separate validation steps. The original definitive simulation database remains untouched; the migration harness must run on a SQLite backup.
