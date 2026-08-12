# Phase 16-05 Summary — POST /channels/whatsapp/heartbeat/test

## Status: COMPLETE

## What was built

Added `POST /channels/whatsapp/heartbeat/test` admin dry-run endpoint to
`workspace/sci_fi_dashboard/routes/whatsapp.py` (inserted after
`whatsapp_connection_state`, lines 186-226).

## Key decisions

- **Auth**: `Depends(deps._require_gateway_auth)` — consistent with all other
  admin WhatsApp routes (`/status`, `/logout`, `/relink`, retry-queue).
- **503 guard**: returns immediately if `app.state.heartbeat_runner is None`
  (feature disabled or init failed) — operator gets a clear error, not a 500.
- **HEART-05 contract**: per-recipient `try/except` so a single bad recipient
  never aborts the cycle; failures are logged at WARNING level.
- **dry_run=True**: passed to `runner.run_heartbeat_once(to, dry_run=True)` —
  LLM is still consulted, SSE events are still emitted, but no real WhatsApp
  send occurs.
- **Response shape**: `{ok, cycle_count, recipients, dry_run}` — no message
  text, no emitted events in body (events go to SSE as designed).
- **Pre-existing SIM102 lint fix**: collapsed nested `if` in `unified_webhook`
  (ACL-02 self-echo block) while in the file — no functional change.

## Verification

- `grep -c "heartbeat/test" routes/whatsapp.py` → 2 (decorator + docstring)
- `grep -c "dry_run=True" routes/whatsapp.py` → 4
- `grep -c "_require_gateway_auth" routes/whatsapp.py` → 8 (was 7)
- Route registered: `python -c "...assert any('heartbeat/test' in p ...)"` → ok
- ruff + black → clean
- 30/30 tests pass (test_webhook_dedup, test_heartbeat_runner, test_bridge_health_poller)

## Phase 16 REQ-ID completion

| REQ-ID    | Area           | Status    | Automated test |
|-----------|----------------|-----------|----------------|
| HEART-01  | HeartbeatRunner init + interval | DONE | test_heartbeat_runner.py |
| HEART-02  | LLM message generation          | DONE | test_heartbeat_runner.py |
| HEART-03  | WA send + dry_run guard         | DONE | test_heartbeat_runner.py |
| HEART-04  | SSE event emission              | DONE | test_heartbeat_runner.py |
| HEART-05  | Per-recipient isolation         | DONE | test_heartbeat_runner.py |
| BRIDGE-01 | /health polling + SSE           | DONE | test_bridge_health_poller.py |
| BRIDGE-02 | Reconnect logic                 | DONE | test_bridge_health_poller.py |
| BRIDGE-03 | Webhook dedup (UUID fallback)   | DONE | test_webhook_dedup.py |
| BRIDGE-04 | Admin dry-run endpoint          | DONE | route registration + manual |

All 9 REQ-IDs have automated tests. Manual validation rows in
`16-MANUAL-VALIDATION.md`. Phase 16 ready for `/gsd-verify-work 16`.
