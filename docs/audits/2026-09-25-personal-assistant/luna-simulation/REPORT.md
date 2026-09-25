# Luna memory/personality simulation

## Outcome

The real Synapse inbound worker, prompt/profile path, scoped memory service, `query_memory` tool, and outbox ran against synthetic Alice and Bob profiles. Luna responses were relayed through a test-only file adapter; WhatsApp was an in-process fake. No external network, process launch, real account, or non-memory tool was available.

The v6 run completed **5 conversational turns plus `/new`**: 6 fake-channel sends accepted, 15 Luna inference requests, and 3 real `query_memory` tool executions. Backfill classified Alice's two active legacy style rows as `professional_precise` and `concise`; the source database logical digest and original episode text/IDs remained unchanged. A one-turn playful/brief override affected that reply but did not change her persistent profile. The following neutral turn used the formal/concise runtime profile.

Alice's post-`/new` tool query returned the umbrella incident source (`3001668d…e08de`). It also returned an older query echo (`1798…9a52`), not the current query episode (`458a…96eca6`). The transcript was empty after `/new`; this demonstrates DB-backed recall after session rotation, but `/new` occurred in the same process, so it is not an OS-process restart test.

Bob's first v6 lookup failed to retrieve his earlier lunch story; Luna appropriately declined to guess. After the bounded weak-candidate recall fix, a separate fresh-process, transcript-free Bob run returned the original source (`254903c1…15054a6`) and Luna answered “A pigeon stole your lunch sandwich from the balcony. You called it your CFO.” That targeted run used **2 Luna inference requests**, made **1 `query_memory` call**, and had **1 fake-channel send accepted**. The new inbound episode remains `pending` enrichment because the memory pump was intentionally disabled in this recall-only run. Stronger query echoes still ranked ahead of the incident, so retrieval ordering remains a quality limitation.

## Fixes exercised and remaining findings

- Targeted legacy backfill filled only NULL tone/verbosity controls; profile evidence and raw episodes were preserved. Humor remains descriptive and is not converted into tone.
- Current-turn style detection now recognizes the anchored “for this answer only” playful/brief directive, while the saved formal profile remains effective on adjacent neutral turns.
- Recall now adds at most one qualifying weak candidate when stronger results leave a slot. The targeted Bob receipt proves the actual incident is present, but it ranked fourth at score `0.1387`, after three query/assistant echoes.
- The immediate synchronous fact-save path logged `ValueError: fact evidence is absent from the user source episode`. Raw capture remained durable, and Luna-mediated V2 enrichment ran separately; this is a path-specific evidence-validation failure, not evidence that all typed extraction failed.
- Memory search used lexical fallback; no embedding provider was configured. Do not interpret this small synthetic run as a general naturalness, semantic-recall, provider-compatibility, or production-latency benchmark.

## Method and validation

Inference used the same GPT-6 Luna Codex worker sequentially because a fresh child per request could not be created under the thread limit. The relay was instructed to return only packet-constrained JSON/text and no tools; this is agent-mediated inference, not Synapse's authenticated native provider integration. Only `query_memory` was exposed. No external MCPs, calendar, browser, or other tools were tested. “Accepted” is the fake channel adapter's result, not handset delivery.

The earlier v5 attempt is retained as a diagnostic timeout and is not counted as a completed run. The definitive deterministic suite after the final source changes passed **168 tests, 0 skipped**; Ruff, compile, and `git diff --check` passed per the validation run. Private reference parity was unavailable.

## Evidence

- Full synthetic run (temporary, local-only evidence; excluded from commit): [`run-style-backfill-20260925-v6`](../../../../.tmp/synapse-luna-sim/run-style-backfill-20260925-v6/summary.json)
- Post-fix Bob recall-only run (temporary, local-only evidence; excluded from commit): [`run-bob-recall-postpatch-20260925-v1`](../../../../.tmp/synapse-luna-sim/run-bob-recall-postpatch-20260925-v1/summary.json)
- User-facing exchanges and receipts: [TRANSCRIPT.md](TRANSCRIPT.md)
