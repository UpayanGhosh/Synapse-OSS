# Scoped lexical recall fix

## Observed failure

In the Luna simulation, Bob's `query_memory` call for `lunch incident what got taken` returned only the active question episode. The earlier user episode said a pigeon stole his lunch sandwich. The active question was durably captured before the model call and shared four query tokens; the older event shared only `lunch`. The lexical recall code discarded every one-token match for queries longer than two tokens, so the source was not a candidate.

## Change and boundary

- The inbound capture's exact episode ID is carried internally to prompt recall and native `query_memory`. The scoped SQLite query excludes that ID before ranking. The model cannot supply or change the exclusion through tool arguments. Older episodes with identical text remain eligible.
- If there is no multi-token or semantic hit, lexical recall may return at most one one-token result anchored by a specific query term. Common retrieval terms such as `incident` and `memory` cannot be the sole anchor. A stronger hit always wins. This is a lexical fallback, not paraphrase understanding: a query with no shared meaningful token still returns nothing without embeddings.
- Owner scope, group scope, accepted-assistant filtering, active/superseded status, and correction labels stay in the existing store path. The SQL has no candidate `LIMIT`; it scans the verified owner's eligible episodes before result limiting, so an old source beyond many recent irrelevant rows is considered. Large owner histories remain a linear-scan scaling gap.
- Prior historical question episodes are not classified or excluded. Repeated earlier questions with strong lexical overlap can still outrank a weak event source. This bounded fix excludes only the active inbound episode.

## TDD and verification

RED: four focused tests failed before the store/tool changes (`exclude_episode_id` absent and weak lunch match dropped). The prompt integration regression separately failed because `persona_chat` did not yet accept the internal ID.

GREEN: the focused store, service, embedding, native tool, and scope suite passed: **26 tests**. It covers limit one after 17 newer irrelevant rows, exact-ID exclusion preserving an identical historical source, weak versus strong ranking, a direct same-owner generic-only negative, a no-anchor negative, and a foreign-owner sentinel. The native tool test also supplies a model-side `exclude_episode_id` argument to prove it is ignored.

The prompt integration test in `test_personal_prompt_runtime.py` asserts that the active episode sentinel is absent from the compiled prompt while older evidence and correction labels remain. Direct and channel capture tests assert that the exact captured ID reaches `persona_chat`. The prompt, retrieval, and capture boundary suite passed: **25 tests**. Ruff passed for the new/modified retrieval tests and store/service/helper files. `tool_registry.py` has two pre-existing import-order Ruff findings unrelated to this change. `compileall` and `git diff --check` passed.
