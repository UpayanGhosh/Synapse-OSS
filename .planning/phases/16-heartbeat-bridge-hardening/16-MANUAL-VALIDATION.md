---
phase: 16
slug: heartbeat-bridge-hardening
type: manual
created: 2026-04-23
---

# Phase 16 — Manual Validation Checklist

Validates the 9 scenarios that cannot be fully reproduced in pytest.

## Prerequisites

- Phase 15 complete (Baileys 7.0.0-rc.9 pinned, QR pairing validated)
- A spare phone with WhatsApp paired to the Synapse bridge
- `synapse.json` contains a `heartbeat` block with own JID (placeholder `919000000000@s.whatsapp.net` must be REPLACED with tester's real JID for live tests)
- Bridge + gateway both running (`./synapse_start.sh` or equivalent)

## HEART-01: Real recipient receives scheduled heartbeat

**Setup:**
1. Edit `~/.synapse/synapse.json`:
   ```json
   "heartbeat": {
     "enabled": true,
     "interval_s": 60,
     "recipients": ["<YOUR_PHONE_JID>"],
     "prompt": "Health check — any updates?",
     "visibility": { "showOk": false, "showAlerts": true, "useIndicator": true }
   }
   ```
2. Restart gateway: `./synapse_stop.sh && ./synapse_start.sh`

**Procedure:**
1. Observe your WhatsApp client
2. Within 60 seconds, expect to receive either (a) the LLM's response to "Health check — any updates?" OR (b) silence if LLM returned `HEARTBEAT_OK` and showOk is false
3. Check gateway logs: `jq 'select(.module=="gateway.heartbeat")' logs/gateway.log | tail -5`

**Pass criterion:** At least one WhatsApp message delivered OR log line `heartbeat.ok_token silent=true` within 70s of gateway start.

## HEART-03: HEARTBEAT_TOKEN stripped end-to-end

**Setup:** HEART-01 must have fired at least once.

**Procedure:**
1. From your phone, reply to the heartbeat message with literal text: `HEARTBEAT_OK`
2. Wait 5 seconds
3. Observe gateway logs: `jq 'select(.module=="gateway.heartbeat") | select(.event=="heartbeat.ok_token")' logs/gateway.log`
4. Confirm you do NOT receive any outbound message back from the bot

**Pass criterion:** log entry with `silent: true` + no outbound WhatsApp message visible on phone.

## BRIDGE-01: /health responds during live inbound flood

**Setup:** Two phones paired (or use WhatsApp Desktop as second sender).

**Procedure:**
1. From phone B, send 50 messages to the bot in 10 seconds (copy-paste rapid-fire)
2. In parallel, from dev host: `for i in $(seq 1 30); do curl -sf http://127.0.0.1:5010/health > /dev/null && echo "OK" || echo "FAIL"; sleep 1; done`
3. Observe: all 30 curls return "OK" without timeout

**Pass criterion:** zero FAIL / zero 5xx / zero timeout. The 4 new fields (`last_inbound_at`, `last_outbound_at`, `uptime_ms`, `bridge_version`) present on every response.

## BRIDGE-03: 3-strike restart after real bridge kill

**Setup:** Gateway + bridge running, healthy connection.

**Procedure (Linux/Mac):**
1. Find bridge PID: `pgrep -f "node.*baileys-bridge"`
2. Freeze it: `kill -STOP <pid>` (SIGSTOP — paused but alive)
3. Watch gateway logs for 3 consecutive `bridge.health.failed` events + one `bridge.health.restart`
4. Expected timing: 3 × 30s = 90s until restart fires (default config)
5. Confirm `healthState` transitions via `curl http://127.0.0.1:8000/channels/whatsapp/status | jq .healthState`: `connected` → (during failures) → `reconnecting` → `connected`

**Procedure (Windows):**
1. `Get-Process node -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like '*baileys-bridge*'}`
2. `Stop-Process -Id <pid> -Force` (triggers subprocess death + gateway respawn)
3. Observe same log sequence

**Pass criterion:** exactly 3 `bridge.health.failed` events followed by 1 `bridge.health.restart` event within 120s of freeze/kill.

## BRIDGE-04: 300s dedup TTL real-clock expiry

**Setup:** Gateway running. Use curl to simulate bridge webhook POSTs.

**Procedure:**
1. Send first POST: `curl -X POST http://127.0.0.1:8000/channels/whatsapp/webhook -H 'Content-Type: application/json' -d '{"message_id":"manual-test-001","chat_id":"1234@s.whatsapp.net","text":"test","channel_id":"whatsapp"}'` → expect `status: "queued"` or `status: "skipped"` on self-echo
2. Immediately send same payload again → expect `{"accepted": true, "reason": "duplicate"}` (additional keys like `status: "skipped"` OK)
3. Wait 310 seconds (real wall time)
4. Send same payload third time → expect NOT `reason: "duplicate"` (should be queued or accepted fresh)

**Pass criterion:** step 2 returns `reason: "duplicate"`; step 4 does NOT.

## HEART-04: Dashboard SSE renders heartbeat events

**Procedure:**
1. Open dashboard: `http://127.0.0.1:8000/dashboard/` (or wherever the panel lives)
2. Navigate to heartbeat / pipeline event stream section
3. Trigger heartbeat (either wait for interval OR POST to the dry-run endpoint if Plan 05 Task 2 exposed it: `curl -X POST http://127.0.0.1:8000/channels/whatsapp/heartbeat/test`)
4. Observe SSE stream shows `heartbeat.send_start` → `heartbeat.sent` OR `heartbeat.ok_token` events in order

**Pass criterion:** at least 2 heartbeat.* events appear in dashboard event stream within 5s of trigger.

## HEART-05: 24-hour longevity

**Procedure:**
1. Set `heartbeat.interval_s: 3600` (1 hour)
2. Start gateway and leave running
3. After 24h, run `jq 'select(.module=="gateway.heartbeat") | select(.event=="heartbeat.failed")' logs/gateway.log | wc -l`
4. Confirm gateway still responding: `curl http://127.0.0.1:8000/healthz` → 200

**Pass criterion:** gateway uptime ≥ 86400s; `heartbeat.failed` count ≤ 10% of `heartbeat.send_start` count; no `CRITICAL` or `ERROR` log entries referencing heartbeat module crash.

## BRIDGE-01 (version bump): bridge_version reflects new Baileys

**Procedure:**
1. Edit `baileys-bridge/package.json`: bump `version` field from `1.0.0` to `1.0.1`
2. `cd baileys-bridge && npm install --save @whiskeysockets/baileys@7.0.0-rc.10` (or next RC)
3. Restart bridge
4. `curl http://127.0.0.1:5010/health | jq .bridge_version` → expect `"1.0.1"` (NOT `"1.0.0"`)

**Pass criterion:** `bridge_version` matches the new package.json version.

## Sign-Off

| Req | Date | Tester | Result | Notes |
|-----|------|--------|--------|-------|
| HEART-01 live | | | ⬜ PASS / ⬜ FAIL | |
| HEART-03 live strip | | | ⬜ PASS / ⬜ FAIL | |
| BRIDGE-01 flood | | | ⬜ PASS / ⬜ FAIL | |
| BRIDGE-03 kill-pid | | | ⬜ PASS / ⬜ FAIL | |
| BRIDGE-04 TTL expiry | | | ⬜ PASS / ⬜ FAIL | |
| HEART-04 dashboard SSE | | | ⬜ PASS / ⬜ FAIL | |
| HEART-05 24h longevity | | | ⬜ PASS / ⬜ FAIL | |
| BRIDGE-01 version bump | | | ⬜ PASS / ⬜ FAIL | |
