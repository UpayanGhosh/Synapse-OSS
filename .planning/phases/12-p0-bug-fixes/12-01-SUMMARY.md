---
phase: 12
plan: 1
status: complete
wave: 2
---

## Plan 01 — WA-FIX-01 / WA-FIX-02 / WA-FIX-03

### Changes

**workspace/sci_fi_dashboard/routes/whatsapp.py**
- Task 1: Added `await` to `wa_channel.update_connection_state(payload)` at the connection-state webhook handler. One character change (`await `) that unblocks WA-FIX-01 (retry queue flush) and WA-FIX-02 (code-515 restart path) simultaneously — both fixes share the same coroutine.

**workspace/sci_fi_dashboard/channels/whatsapp.py**
- Task 2: Added `base["isLoggedOut"] = self._connection_state == "logged_out"` to `get_status()`. One new line, camelCase as required by the roadmap success criterion. Rides existing `_require_gateway_auth` gate — no new surface.

### Test Results
- `test_whatsapp_routes.py::TestConnectionStateRoute::test_route_awaits_update` ✅ green
- `test_whatsapp_routes.py::TestConnectionStateRoute::test_515_routes_to_restart` ✅ green
- `test_whatsapp_routes.py::TestGetStatusIsLoggedOut::test_is_logged_out_true_when_connection_state_logged_out` ✅ green
- `test_whatsapp_routes.py::TestGetStatusIsLoggedOut::test_is_logged_out_false_when_connected` ✅ green
- `test_polling_resilience.py` ✅ no regression
- `test_channel_whatsapp_extended.py` ✅ no regression

### Manual Smoke (required for full sign-off)
1. Start Synapse, pair personal WhatsApp, `kill -9` the bridge, observe auto-restart with code 515, send inbound message, verify bot replies within 15s — confirms WA-FIX-01/02.
2. Bridge reports `logged_out` event, `GET /channels/whatsapp/status` returns `isLoggedOut: true` within 10s — confirms WA-FIX-03.

### Acceptance Criteria Verification
- `grep -n "await wa_channel.update_connection_state" routes/whatsapp.py` → 1 match ✅
- `grep -n 'isLoggedOut' channels/whatsapp.py` → 1 match ✅
- `ruff check` + `black --check` both files → clean ✅
