---
phase: 13
slug: structured-observability
status: template
created: 2026-04-22
---

# Phase 13 -- Manual Validation Procedure

> Three acceptance checks that pytest cannot fully reproduce. Run these AFTER
> the automated suite (plans 13-00 through 13-06) is green.

---

## Prerequisites

- Synapse stack fully running (`./synapse_start.sh` Mac/Linux or `synapse_start.bat` Windows)
- WhatsApp bridge paired with a test phone (NOT your personal number)
- `jq` installed (`brew install jq` / `apt install jq`)
- Log path: `~/.synapse/logs/app.jsonl`

---

## Check 1 -- Real WhatsApp produces single-runId conversation (OBS-01)

**Why manual:** requires live Baileys bridge + real phone send.

**Steps:**

1. Start the full stack.
2. Send **1 WhatsApp message** from the test phone.
3. Wait for a reply from Synapse.
4. Capture the recent log window:
   ```bash
   tail -n 200 ~/.synapse/logs/app.jsonl > /tmp/smoke.jsonl
   ```
5. Extract distinct runIds (null-safe filter -- mirrors automated smoke test):
   ```bash
   jq -r 'select(.runId != null and .runId != "<no-run>") | .runId' /tmp/smoke.jsonl | sort -u
   ```
   -> Expect **ONE** 12-char hex string `RID` for this conversation turn.

6. Assert zero null-runId critical-path lines:
   ```bash
   jq -r 'select(.runId == null and (.module | test("flood|dedup|queue|worker|pipeline|llm|channel"))) | .module' /tmp/smoke.jsonl | wc -l
   ```
   -> **MUST equal 0.** Any non-zero count means ContextVar propagation broke.

7. Confirm all Phase 13 modules fired under `RID`:
   ```bash
   jq -r 'select(.runId == "RID") | .module' /tmp/smoke.jsonl | sort -u
   ```
   -> Expect at minimum: `channel.whatsapp`, `gateway.worker`, `llm.router`, `pipeline.chat`, `route.whatsapp`

**Pass criteria:** All 5 modules appear; zero null-runId critical-path lines; no other runId for this turn.

---

## Check 2 -- No raw digits in production logs over a 10-message session (OBS-02)

**Why manual:** unit fuzz gives confidence; live grep over real JIDs is the final acceptance gate.

**Steps:**

1. Send 10 WhatsApp messages including ones with numbers:
   - `"my number is 9876543210"`
   - `"call 212-555-0100"`
   - `"order #12345678901234"`
2. Grep for raw 10+ digit runs:
   ```bash
   grep -E '[0-9]{10,}' ~/.synapse/logs/app.jsonl | tail -n 50
   ```
3. Targeted check excluding timestamp fields:
   ```bash
   jq -rc 'to_entries | map(select(.value | tostring | test("[0-9]{10,}"))) | .[] | select(.key != "ts" and .key != "timestamp")' ~/.synapse/logs/app.jsonl
   ```
   -> Expect **empty output**.

**Known caveat:** `bridge_stderr` logger is opt-in DEBUG only. If enabled, raw JIDs can appear there; this check is waived for that specific logger.

**Pass criteria:** Zero matches outside `ts`/`timestamp` fields.

---

## Check 3 -- Per-module level changes take effect after config reload (OBS-04)

**Why manual:** config reload requires a full restart; operators need to observe the toggle end-to-end.

**Steps:**

1. Edit `~/.synapse/synapse.json` and add:
   ```json
   "logging": {
     "level": "INFO",
     "modules": {
       "llm.router": "DEBUG",
       "channel.whatsapp": "WARNING"
     }
   }
   ```
2. Restart the stack.
3. Send 1 message.
4. Verify `llm.router` DEBUG lines appear:
   ```bash
   jq 'select(.module == "llm.router" and .level == "DEBUG")' ~/.synapse/logs/app.jsonl | head -5
   ```
   -> Should show at least 1 entry.
5. Verify `channel.whatsapp` INFO lines are suppressed:
   ```bash
   jq 'select(.module == "channel.whatsapp" and .level == "INFO")' ~/.synapse/logs/app.jsonl | tail -5
   ```
   -> Should show 0 new entries after the restart timestamp.
6. Change `channel.whatsapp` back to `"INFO"`, restart, send a message, verify INFO lines resume.

**Pass criteria:** All three state transitions produce expected visibility changes.

---

## Sign-Off

- [ ] Check 1 -- Real WhatsApp single-runId
- [ ] Check 2 -- No raw digits in 10-message session
- [ ] Check 3 -- Per-module level toggle after restart

**Operator:** ______________________

**Date:** ______________________
