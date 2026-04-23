---
phase: 15
plan: 5
status: complete
wave: 4
---

## Plan 05 — LID-mapping user_id_alt + ownerPn + Phase 13 PII registration

### Test Results
- Node full suite: **16 pass, 4 fail** (4 RED = send_shapes stubs, Plan 06 responsibility)
- `extract_payload.test.js`: **6/6 GREEN** (was 4 RED stubs in Wave 0)
  - 4 original: PN/LID × DM/group message paths
  - +2 added post-review: reaction+LID path, no-alt-fields edge case
- Python `test_group_metadata_shape`: **SKIPPED** cleanly (correct — no env vars set)
- Python `_SENSITIVE_FIELDS` assertion: **OK**

### Changes

**baileys-bridge/index.js** (722 lines)
- `isLid(jid)` helper added (type-safe, handles null/undefined)
- `extractPayload()` computes `userIdAlt` from `participantAlt` (group) or `remoteJidAlt` (DM), default null
- Both `type: 'reaction'` and `type: 'message'` payloads carry `user_id_alt: userIdAlt`
- `GET /groups/:jid` enriched with `ownerPn` + `descOwnerPn` keys (null when owner is PN or LID→PN unavailable)
- `require.main === module` guard wraps `app.listen`, SIGTERM handler, and `startSocket()` — tests can now `require('../index.js')` without side effects
- `module.exports = { extractPayload }` added at bottom
- `setInterval(...).unref()` on media cache cleanup timer — prevents test runner from hanging

**workspace/sci_fi_dashboard/observability/formatter.py**
- `_SENSITIVE_FIELDS` frozenset extended with `"user_id_alt"` (T-15-16 mitigation, 5→6 entries)

**workspace/tests/test_bridge_auth.py**
- `test_group_metadata_shape` replaced stub with real implementation — `skipif` guards on `WAVE_15_LIVE_BRIDGE_7X` + `WAVE_15_TEST_GROUP_JID`, asserts `{id, subject, participants, owner, ownerPn}` keys

**baileys-bridge/test/extract_payload.test.js** (113 lines, was 70)
- 6 tests covering all cases: DM+PN, DM+LID, group+PN, group+LID, reaction+LID, no-alt-fields edge

### WhatsAppMessage Pydantic Model
No `WhatsAppMessage` Pydantic model with `extra='forbid'` found in the workspace — webhook handler accepts raw dict. No model change needed.

### Phase 13 PII Coverage
`user_id_alt` is now in `_SENSITIVE_FIELDS`. Any `logger.info('...', extra={'user_id_alt': pn})` call produces `user_id_alt_redacted: id_<8hex>` in the JSON log output (T-15-16 mitigated).

### ownerPn Behavior on 7.x
If Baileys 7.x populates `meta.ownerPn` natively → forwarded directly. If owner is a PN (not LID) → `ownerPn` mirrors the owner value. If owner is a LID and Baileys doesn't provide `ownerPn` → null. LID→PN resolution out of scope for Phase 15; Phase 18 multi-account can add `getPhoneForLID`.

### Plan 06 Unblocked
All Phase 15 Wave 4 requirements satisfied. Wave 5 (Plan 06: `send_payload.js` + BAIL-03 media matrix + final operator sign-off) is unblocked.
