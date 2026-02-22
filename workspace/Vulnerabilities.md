# Concurrency Vulnerabilities & Race Conditions

**Analysis Date:** 2026-02-10
**Status:** ✅ ALL FIXED
**Severity Scale:** CRITICAL | HIGH | MEDIUM | LOW

---

## Executive Summary

The audit previously revealed **5 race conditions**. All have been patched as of 2026-02-10.

- **RC-001 (Critical):** Fixed via list copy iteration.
- **RC-002 (High):** Fixed via logic update (`INSERT OR IGNORE`).
- **RC-003 (Medium):** Fixed via WAL mode atomic transactions.
- **RC-004 (Medium):** Fixed via file locking (`fcntl`).
- **RC-005 (Low):** Fixed via threading locks.

---

## Resolved Vulnerabilities

### RC-001: WebSocket Broadcast Crash

**Status:** FIXED
**Fix:** Iterating over `list(self.active_connections)` instead of the live list prevents runtime errors during disconnects.

### RC-002: User Registration TOCTOU

**Status:** FIXED
**Fix:** Removed check-then-act pattern; replaced with atomic `INSERT OR IGNORE`.

### RC-003: Memory Indexing Availability Blackout

**Status:** FIXED
**Fix:** Switched SQLite to `WAL` mode and removed intermediate commits. The deletion and re-insertion of memory are now a single atomic transaction.

### RC-004: OAuth Token Refresh Race

**Status:** FIXED
**Fix:** Added `fcntl.flock` (exclusive lock) around the token file write operation.

### RC-005: Global Model Initialization Stampede

**Status:** FIXED
**Fix:** Added `threading.Lock()` (Double-Checked Locking pattern) to ensuring the Re-Ranker model loads only once.
