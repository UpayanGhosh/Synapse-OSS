---
phase: 15
plan: 6
status: complete
wave: 5
---

## Plan 06 — buildSendPayload extraction + BAIL-02/03/04 manual sign-off

### Test Results
- Node full suite: **25 pass, 0 fail** (5 creds_queue + 5 restore + 6 extract_payload + 9 send_shapes)
- Python `test_baileys_version_pin` + `test_node_engine_requirement` + `test_corruption_recovery_no_qr`: **PASS**
- Python `test_group_metadata_shape` + `test_qr_endpoint_returns_string`: **SKIPPED** (by design — live env vars not set)

### Changes

**baileys-bridge/lib/send_payload.js** (new, 72 lines)
- Pure `buildSendPayload(mediaType, buffer, opts)` function — zero I/O, no Baileys dep
- Handles: `text`, `image`, `audio`, `voice` (PTT alias), `video`, `document`, `sticker`
- `voice` hard-codes `{ audio, ptt: true, mimetype: 'audio/ogg; codecs=opus' }` — WA PTT shape
- Exports `DEFAULT_VOICE_MIMETYPE` + `DEFAULT_STICKER_MIMETYPE` constants

**baileys-bridge/test/send_shapes.test.js** (66 lines, was 40 RED stubs)
- 4 core BAIL-03 tests GREEN: image mimetype, voice PTT+opus, document fileName, video gifPlayback
- 5 regression tests: text, sticker default mimetype, audio non-PTT, image without optionals, invalid mediaType throws

**baileys-bridge/index.js** (722 lines, unchanged count)
- `require('./lib/send_payload.js')` added at top
- POST /send: `req.body` destructuring extended with `mediaMimeType`, `fileName`, `gifPlayback`
- POST /send: inline `const messageContent = { [mediaTypeKey]: buffer }` dead code removed; replaced with `buildSendPayload(mt, buffer, { caption, mimetype: mediaMimeType, fileName, gifPlayback })`
- POST /send text path: `sock.sendMessage(jid, buildSendPayload('text', null, { text }))`
- POST /send-voice: `sock.sendMessage(jid, buildSendPayload('voice', buffer, {}))` — single line

### Manual Sign-Off (2026-04-23, UpayanGhosh)

| Req | Result | Notes |
|-----|--------|-------|
| BAIL-02 | PASS | QR paired on 7.0.0-rc.9; code=515 transient recovered; `/health` → connected |
| BAIL-03 | PASS (5/5) | text / JPEG image / OGG voice PTT bubble / PDF with filename / MP4 video — all delivered with double grey tick |
| BAIL-04 | PASS | `/groups/:jid` returned `ownerPn` + LID `addressingMode`; `buildSendPayload` round-trip to group delivered |

### BAIL-04 Live Observation
Group `120363409062647775@g.us` (Test, 2 participants) returned full 7.x shape:
- `addressingMode: "lid"` — confirms Baileys 7.x LID addressing active
- `ownerPn: "918583944645@s.whatsapp.net"` — LID→PN resolution working
- Both participants have `id` (@lid) + `phoneNumber` (@s.whatsapp.net) — `user_id_alt` surfacing confirmed

### Phase 15 Closure
- VALIDATION.md: all 23 rows ✅ green or ✅ manual-passed (zero ⬜ pending)
- ROADMAP.md Phase 15 row: ready to update to `7/7 Complete`
- Phase 15 ready for `/gsd-verify-work`
