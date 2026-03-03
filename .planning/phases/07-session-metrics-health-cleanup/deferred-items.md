# Deferred Items — Phase 07

Items discovered during Phase 7 execution that are out-of-scope (pre-existing issues
not caused by Phase 7 changes). Document here for future cleanup.

---

## Cosmetic "openclaw" References in Active Files

**Found during:** Plan 07-04, Task 2 (test_sessions.py openclaw cleanup test)
**Nature:** Pre-existing cosmetic/descriptive references — NOT active binary calls

### workspace/main.py

- **Line 138:** `OPENCLAW_GATEWAY_TOKEN` — env var name used as API auth header key
  - Action: Rename to `SYNAPSE_GATEWAY_TOKEN` for consistency with Synapse-OSS branding
- **Line 200:** `argparse.ArgumentParser(description="OpenClaw Centralized CLI")`
  - Action: Update description to "Synapse Centralized CLI"

### workspace/monitor.py

- **Line 412:** `# Hapi/Boom HTTP error from OpenClaw gateway layer` — comment
- **Line 417:** `msg_part = f"OpenClaw HTTP {status}: {err_msg}"` — f-string error label
  - Action: Update to "Synapse HTTP" for consistency

### Cleanup Notes

These files were not modified in Phase 7 because:
1. No binary executable calls to the `openclaw` CLI binary
2. Only cosmetic/descriptive text (env var names, argparse descriptions, error labels)
3. Out-of-scope per deviation rules (pre-existing, not caused by Phase 7 changes)

**Recommended fix:** Simple string replacements in a future maintenance PR.
