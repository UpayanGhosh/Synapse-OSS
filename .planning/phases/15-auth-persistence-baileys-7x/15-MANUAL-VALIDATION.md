---
phase: 15
slug: auth-persistence-baileys-7x
type: manual
created: 2026-04-22
---

# Phase 15 — Manual Validation Checklist

Validates the 3 requirements that have no automated path: BAIL-02 (pairing), BAIL-03 (media
delivery), BAIL-04 (group round-trip).

Automated tests cover AUTH-V31-01..03 and the static shape assertions for BAIL-03/04.
The manual steps here confirm end-to-end delivery on a real WhatsApp client — something
no test harness can substitute.

---

## Prerequisites

- Dev host has Node 20+ (`node --version` prints v20.x.x or higher)
- `cd baileys-bridge && npm install` has been run after the Baileys 7.x bump (Plan 04)
- A spare Android or iOS phone with WhatsApp installed
- A WhatsApp account NOT currently paired to another Synapse instance
- A second phone (or test group with 2+ participants) for BAIL-04

---

## BAIL-02: QR pairing + multi-device login on Baileys 7.x

**Goal:** Confirm the bridge pairs successfully with Baileys 7.0.0-rc.9, connects, and
reports `connected` on `/health` without errors.

### Steps

1. Reset auth state completely:
   ```bash
   cd baileys-bridge
   rm -rf auth_state/ auth_state.bak/
   ```

2. Confirm the installed version:
   ```bash
   npm install
   node -e "console.log(require('./node_modules/@whiskeysockets/baileys/package.json').version)"
   # Expected: 7.0.0-rc.9
   ```

3. Start the bridge:
   ```bash
   node index.js
   ```

4. Observe: terminal prints a QR code in ASCII art within 15 seconds.

5. On the spare phone: WhatsApp → Settings → Linked Devices → Link a Device → scan QR.

6. Observe: bridge logs `[BRIDGE] Connected to WhatsApp` (or equivalent connection event).

7. Verify via HTTP:
   ```bash
   curl http://127.0.0.1:5010/health
   # Expected: {"status":"ok","connectionState":"connected",...}
   ```

**Pass criterion:** `/health` returns `connectionState: "connected"` and `restartCount: 0`.
`authTimestamp` field is a valid ISO 8601 string.

**Resume signal:** Paste the bridge log line showing the connection event + the `/health`
JSON response.

**If fails:** Capture full bridge stdout. Note any Baileys error code (e.g., `401`, `515`,
`428`). Escalate to planner — do not proceed to BAIL-03/04.

**Expected time:** 2 minutes.

---

## BAIL-03: Media send matrix (5 sends)

Run **after** BAIL-02 passes. Replace `<your-jid>` with your own WhatsApp JID
(format: `<countrycode><number>@s.whatsapp.net`, e.g. `919876543210@s.whatsapp.net`).

Use `curl` against `http://127.0.0.1:5010/send` and `/send-voice`.

| # | Media | Command | Expected WA client outcome |
|---|-------|---------|---------------------------|
| 1 | Text | `curl -s -X POST http://localhost:5010/send -H 'Content-Type: application/json' -d '{"jid":"<your-jid>","text":"BAIL-03 test 1/5"}'` | Message "BAIL-03 test 1/5" appears on phone within 10s with double grey tick (delivered) |
| 2 | Image | `curl -s -X POST http://localhost:5010/send -H 'Content-Type: application/json' -d '{"jid":"<your-jid>","mediaUrl":"https://httpbin.org/image/jpeg","mediaType":"image","caption":"BAIL-03 img"}'` | JPEG image delivered with caption "BAIL-03 img" visible |
| 3 | Voice (OGG Opus) | `curl -s -X POST http://localhost:5010/send-voice -H 'Content-Type: application/json' -d '{"jid":"<your-jid>","audioUrl":"http://127.0.0.1:8080/test_voice.ogg"}'` (serve fixture first: `cd baileys-bridge/test/fixtures && python -m http.server 8080`) | WA shows voice note bubble with play button (PTT), duration ~1s |
| 4 | PDF | `curl -s -X POST http://localhost:5010/send -H 'Content-Type: application/json' -d '{"jid":"<your-jid>","mediaUrl":"https://www.w3.org/WAI/WCAG21/Techniques/pdf/PDF1.pdf","mediaType":"document","caption":"BAIL-03 pdf","fileName":"test.pdf"}'` | PDF delivered; filename "test.pdf" visible in WA document bubble |
| 5 | Video | `curl -s -X POST http://localhost:5010/send -H 'Content-Type: application/json' -d '{"jid":"<your-jid>","mediaUrl":"https://www.w3.org/2010/Talks/www2010-tbl-ucnf/w3c_home_2010.mp4","mediaType":"video","caption":"BAIL-03 vid"}'` | Video delivered with thumbnail and caption "BAIL-03 vid" |

**Pass criterion:** All 5 show double grey tick (delivered) within 30 seconds each.

**Resume signal:** For each send, paste the bridge log line showing `messageId` emitted
(e.g., `[BRIDGE] sent <messageId> to <jid>`).

**Expected time:** 5–10 minutes.

---

## BAIL-04: Group metadata + round-trip reply

**Goal:** Confirm `/groups/:jid` returns the expected 7.x shape (including `ownerPn`),
and that inbound group messages carry `user_id` + `user_id_alt` in the webhook payload.

### Steps

1. Ensure the paired bot account is a member of at least one group with 2+ other participants.

2. Get the group JID. Options:
   - From WA client: group info → copy invite link → extract JID from URL
   - From bridge logs: inbound group messages log `remoteJid` ending in `@g.us`
   - From the bot: list groups via `curl http://127.0.0.1:5010/groups` (if endpoint exists)

3. Fetch group metadata:
   ```bash
   curl http://127.0.0.1:5010/groups/<group-jid>
   ```
   Expected response shape (7.x):
   ```json
   {
     "id": "<group-jid>",
     "subject": "<group name>",
     "participants": [{"id": "...", "admin": null}, ...],
     "owner": "<owner-jid-or-lid>",
     "ownerPn": "<pn-jid-if-owner-is-lid-else-null>"
   }
   ```
   `ownerPn` is new in Baileys 7.x — its presence confirms the 7.x shape.

4. From another phone in the group, send a message.

5. Observe the webhook payload forwarded to `POST http://127.0.0.1:8000/webhook/whatsapp`
   (or check bridge logs for the outbound payload). Confirm:
   - `user_id` is populated (LID format `@lid` OR PN format `@s.whatsapp.net`)
   - `user_id_alt` is populated when sender is LID (the `@s.whatsapp.net` counterpart)
   - `is_group: true`

6. Send a reply from the bot:
   ```bash
   curl -s -X POST http://localhost:5010/send \
     -H 'Content-Type: application/json' \
     -d '{"jid":"<group-jid>","text":"BAIL-04 round-trip"}'
   ```

7. Observe: message "BAIL-04 round-trip" appears in the group on the second phone within 10s.

**Pass criterion:**
- `/groups/:jid` response includes `ownerPn` key (value may be null if owner uses PN addressing)
- Inbound group webhook payload has `user_id` + `user_id_alt` fields (alt may be null for PN senders)
- Round-trip reply delivered to group

**Resume signal:** Paste the `/groups/:jid` JSON response + one inbound webhook payload
showing `user_id` / `user_id_alt` values.

**Expected time:** 5 minutes.

---

## Sign-Off

| Req | Date | Tester | Result |
|-----|------|--------|--------|
| BAIL-02 | | | ⬜ PASS / ⬜ FAIL |
| BAIL-03 | | | ⬜ PASS (5/5) / ⬜ FAIL (_/5) |
| BAIL-04 | | | ⬜ PASS / ⬜ FAIL |

*Sign-off rows are completed by Plan 06 Task 3 after operator walkthrough.*
