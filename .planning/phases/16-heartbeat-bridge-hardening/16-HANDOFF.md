---
phase: 16
slug: heartbeat-bridge-hardening
status: manual-validation-pending
created: 2026-04-23
---

# Phase 16 — Session Handoff

Pause point: all 12 implementation tasks complete on branch `develop`. Waiting on 8 manual validation rows before Phase 16 COMPLETE.

## Current State

- **Branch:** `develop`
- **Head commit:** `91582d4` (M1 JID redaction fix)
- **Phase 16 range:** `cfb0f6e..91582d4` (18 commits)
- **Automated tests:** 30/30 Python Phase 16 + 4/4 Node + 37/37 Phase 14 regression — all GREEN
- **Zero regressions**
- **Lint:** ruff + black clean across all Phase 16 files

## What Shipped (all 9 REQs)

| REQ | What | Commit |
|-----|------|--------|
| HEART-01..05 | `gateway/heartbeat_runner.py` (481 LOC) — recipient resolver + token strip + visibility matrix + never-crash loop | `2534846` + `8f0ec98` |
| BRIDGE-01 | `baileys-bridge/index.js` — /health augmented with 4 new fields + test-mode guard | `ef71344` + `02ae239` |
| BRIDGE-02/03 | `channels/bridge_health_poller.py` (312 LOC) — 3-strike gated restart + 60s grace + 401-as-degraded | `bbd2c32` + `0f216df` |
| BRIDGE-04 | `gateway/dedup.py` hit/miss counters + `/status.dedup` surface | `5f43e95` + `e3df6dc` |
| (wiring) | `channels/whatsapp.py` `_restart_in_progress` + `bridge_health` + `dedup` in `get_status` | `39f9b16` |
| (wiring) | `api_gateway.py` lifespan integration | `2da5cc8` |
| (config) | `synapse_config.py` heartbeat+bridge fields + `synapse.json.example` blocks | `db860a5` |
| (admin) | `routes/whatsapp.py` POST `/channels/whatsapp/heartbeat/test` dry-run | `9a0dca6` + `91582d4` |

## Tomorrow — Resume Steps

### 1. Re-enter context

```bash
cd /d/Shorty/Synapse-OSS
git log --oneline cfb0f6e..HEAD | head -20
git status --short
cat .planning/phases/16-heartbeat-bridge-hardening/16-HANDOFF.md  # this file
cat .planning/phases/16-heartbeat-bridge-hardening/16-MANUAL-VALIDATION.md  # manual steps
```

### 2. Run 8 manual validation rows

Full procedures in `16-MANUAL-VALIDATION.md`. Compact order-of-effort:

**Setup once:**
- Edit `~/.synapse/synapse.json` to add a `heartbeat` block with your own WhatsApp JID:
  ```json
  "heartbeat": {
    "enabled": true,
    "interval_s": 60,
    "recipients": ["<YOUR_REAL_JID>@s.whatsapp.net"],
    "prompt": "Health check — any updates?",
    "visibility": {"showOk": false, "showAlerts": true, "useIndicator": true}
  }
  ```
- Restart gateway: `./synapse_stop.sh && ./synapse_start.sh`

**Quick (~5 min each):**
- [ ] **HEART-01 live** — within 60s your phone receives msg OR log shows `heartbeat.ok_token silent=true`
- [ ] **HEART-03 live strip** — reply literal `HEARTBEAT_OK` from phone. `jq 'select(.event=="heartbeat.ok_token")' logs/gateway.log` shows `silent: true`. No echo on phone.
- [ ] **BRIDGE-04 TTL** — same webhook twice (expect `duplicate`), wait 310s, send again (expect accepted-fresh). Use curl `POST /channels/whatsapp/webhook` with same `message_id`.
- [ ] **BRIDGE-01 version bump** — bump `baileys-bridge/package.json` version, restart bridge, `curl http://127.0.0.1:5010/health | jq .bridge_version` matches.

**Medium (~10-15 min):**
- [ ] **BRIDGE-01 flood** — 2nd phone sends 50 msgs in 10s. In parallel: `for i in $(seq 1 30); do curl -sf http://127.0.0.1:5010/health > /dev/null && echo OK || echo FAIL; sleep 1; done`. Expect 30 OKs.
- [ ] **BRIDGE-03 kill-pid** — Windows: `Get-Process node | Where {$_.CommandLine -like '*baileys-bridge*'} | Stop-Process -Force`. Expect exactly 3 `bridge.health.failed` + 1 `bridge.health.restart` events within 120s. `healthState` transitions `connected → reconnecting → connected`.
- [ ] **HEART-04 dashboard SSE** — open dashboard heartbeat panel. `curl -X POST http://127.0.0.1:8000/channels/whatsapp/heartbeat/test -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN"`. SSE stream shows `heartbeat.*` events within 5s.

**Long (set and forget):**
- [ ] **HEART-05 longevity** — set `interval_s: 3600`, leave running 24h. After: `jq 'select(.event=="heartbeat.failed")' logs/gateway.log | wc -l` ≤ 10% of `heartbeat.send_start` count. Gateway `/healthz` still 200.

### 3. Mark PASS in signoff table

Each row in `16-MANUAL-VALIDATION.md` Sign-Off table → check `⬜ PASS` box, add date + tester name.

### 4. Close Phase 16

All 8 PASS → run `/gsd-verify-work 16` → then decide merge strategy (PR to `main` or keep on develop).

## If Something Fails

- **HEART-01 silent after 60s** — check `cat logs/gateway.log | jq 'select(.module=="gateway.heartbeat")'` for error lines. Likely `persona_chat` timeout (60s adapter) or channel.send failure.
- **BRIDGE-03 restart fires on 1st failure (not 3rd)** — poller is reading `supervisor.stop_reconnect` wrong, or grace window is 0. Check `cfg.bridge.healthGraceWindowSeconds`.
- **BRIDGE-04 second call NOT duplicate** — dedup TTL misconfigured or `MessageDeduplicator` not imported in `routes/whatsapp.py` webhook handler.
- **Dashboard SSE empty** — `pipeline_emitter` singleton not passed into `HeartbeatRunner` via `api_gateway.lifespan`. Check `grep -n "emitter=" workspace/sci_fi_dashboard/api_gateway.py`.

## Known Non-Blockers

- 5 pytest warnings on sync tests with `pytestmark = pytest.mark.asyncio` — benign, M2 from final review, fix any time.
- Plan had typo `synapse.example.json` but correct file is `synapse.json.example` — followed repo convention, noted for plan hygiene.
- Pre-existing `test_dedup.py` 3 failures (from Phase 14 commit `73b77b2` L-14 periodic cleanup change) — out of Phase 16 scope.

## Reference Files

- `16-VALIDATION.md` — 15-row Per-Task Verification Map (all automated rows GREEN)
- `16-MANUAL-VALIDATION.md` — 8 manual procedures (reference copy of the checklist above with full reproduction details)
- `16-00-SUMMARY.md` / `16-01-SUMMARY.md` / ... `16-05-SUMMARY.md` — per-plan wrap-ups
- `CLAUDE.md` § "OSS Development Workflow" — pre-push OSS standards before any `main` merge

## Session Metadata

- Pause timestamp: 2026-04-23
- Execution skill: `superpowers:subagent-driven-development`
- Total tasks: 12 (3 Wave 0 + 2 Wave 1 + 4 Wave 2 + 3 Wave 3)
- Implementer model: Sonnet
- Reviewer model: Opus (per user preference: Opus=review+planning, Sonnet=execution)
