---
phase: 16
plan: 1
status: complete
wave: 1
---

# Plan 16-01 Summary — BRIDGE-01: /health augmentation + test-mode guard

## Tests flipped RED → GREEN

```
ok 1 - GET /health returns 4 new Phase 16 fields (BRIDGE-01)
ok 2 - last_inbound_at updates when messages.upsert fires (BRIDGE-01)
ok 3 - last_outbound_at updates when /send path succeeds (BRIDGE-01)
ok 4 - bridge_version matches package.json version (BRIDGE-01)
# pass 4
# fail 0
```

## 6 edits applied to `baileys-bridge/index.js`

| Edit | Location | Change |
|------|----------|--------|
| 1 | After require block (module state) | Added `BRIDGE_VERSION`, `processStartMs`, `lastInboundAtMs`, `lastOutboundAtMs` |
| 2 | `messages.upsert` handler, after fromMe filter | `lastInboundAtMs = Date.now()` |
| 3a | `/send` route, after `sock.sendMessage` | `lastOutboundAtMs = Date.now()` |
| 3b | `/send-voice` route, after `sock.sendMessage` | `lastOutboundAtMs = Date.now()` |
| 3c | `/react` route, after `sock.sendMessage` | `lastOutboundAtMs = Date.now()` |
| 4 | `GET /health` handler | Added 4 new fields; kept all 8 existing fields |
| 5 | Startup block | Replaced `require.main === module` with `START_BRIDGE_SOCKET !== 'false'` guard |
| 6 | End of file | Conditional `module.exports = { app, __testTriggerInbound, __testTriggerOutbound, __getState }` |

## Grep proof

```
lastInboundAtMs = Date.now  : 2  (>= 1 required)
lastOutboundAtMs = Date.now : 4  (>= 3 required: send + send-voice + react + __testTriggerOutbound)
bridge_version: BRIDGE_VERSION : 1  (== 1 required)
START_BRIDGE_SOCKET         : 3  (>= 3 required: 2 guards + 1 export check)
```

## Zero regressions

- Zero new npm dependencies (`package.json` unchanged)
- Zero new routes added
- Zero files modified outside `baileys-bridge/index.js`
- All 8 existing `/health` fields preserved (backward compat with Phase 14 `channels/whatsapp.py::health_check`)
- Production mode unaffected: `node index.js` (no env var) triggers `START_BRIDGE_SOCKET !== 'false'` → starts Baileys normally

## Contract delivered to Plan 03

`BridgeHealthPoller` (Plan 03) can now consume `last_inbound_at`, `last_outbound_at`, `uptime_ms`,
and `bridge_version` from `GET /health` on every poll cycle.
