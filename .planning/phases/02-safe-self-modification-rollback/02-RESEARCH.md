# Phase 2: Safe Self-Modification + Rollback - Research

**Researched:** 2026-04-07
**Domain:** Filesystem snapshot management, consent protocol orchestration, Zone enforcement, OS scheduling integration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MOD-01 | Before any Zone 2 modification, Synapse explains in plain language what it will change and why — and waits for explicit yes | ConsentProtocol class wired into chat_pipeline.py; intent detection before any write |
| MOD-02 | After confirmation, Synapse executes the modification and writes a timestamped snapshot to ~/.synapse/snapshots/ | SnapshotEngine writes to data_root / "snapshots/"; atomic temp+os.replace pattern established in codebase |
| MOD-03 | On modification failure, Synapse auto-reverts to the pre-modification state and informs the user | SnapshotEngine.restore() called in except block inside ConsentProtocol.execute() |
| MOD-04 | User can roll back to a prior snapshot by date: "go back to how you were on March 15" | RollbackResolver matches date string to nearest snapshot metadata |
| MOD-05 | User can roll back to a prior snapshot by description: "undo the last change", "you were better last week" | RollbackResolver covers snapshot ID, latest snapshot, natural-language date |
| MOD-06 | Rolling back never destroys forward history — the user can roll forward again | Snapshots are never deleted during rollback; restore creates a new snapshot of the pre-rollback state |
| MOD-07 | Zone 1 components are immutable to model-initiated writes — Sentinel enforces this | Sentinel already has CRITICAL_FILES + CRITICAL_DIRECTORIES; Phase 2 adds explicit Zone1 constants |
| MOD-08 | Zone 2 components are explicitly listed and writable with consent | WRITABLE_ZONES in manifest.py already exists; extend to named Zone 2 list with consent gate |
| MOD-09 | GET /snapshots lists all snapshots with timestamps and change descriptions | SnapshotEngine.list_snapshots() → FastAPI route in routes/ |
| MOD-10 | Each snapshot is self-contained and restorable in isolation — restoring snapshot N does not require all prior snapshots | Snapshots are full copies (shutil.copytree), not incremental diffs |

</phase_requirements>

---

## Summary

Phase 2 builds on an existing, well-structured foundation. The Sentinel gateway (gateway.py + manifest.py + tools.py) already enforces Zone 1 as CRITICAL-locked and Zone 2 as MONITORED writable zones. The primary work is: (1) adding explicit ZONE_1 / ZONE_2 named constants to manifest.py so plans and tests can reference them by name, (2) building SnapshotEngine that takes full-directory tarballs atomically, (3) building ConsentProtocol that orchestrates the explain→confirm→execute→snapshot cycle, (4) wiring intent detection into the existing pipeline, and (5) building a RollbackResolver that understands "undo", "last week", and ISO-date forms.

The cron scheduling subsystem already exists in `cron/` (CronStore, CronSchedule, CronJob dataclasses) and `cron_service.py`. A "cron skill" created by the user's request is a new CronJob entry written to `~/.synapse/state/agents/{agent_id}/cron.json`, which is already in WRITABLE_ZONES via `~/.synapse/`. OS-level task scheduling (schtasks on Windows, cron on Linux) is not used by this codebase — the internal CronService asyncio scheduler is the correct target, simplifying rollback significantly.

The critical implementation risk is snapshot atomicity: write to temp path, validate integrity, then os.rename() into place. Partial writes must never overwrite the clean state. This pattern is already used in Sentinel.safe_write() and CronStore.save() — Phase 2 reuses it directly.

**Primary recommendation:** Build SnapshotEngine first (Plan 02-01), then Zone registry (Plan 02-02), then ConsentProtocol (Plan 02-03), then wire into pipeline (Plan 02-04), then rollback (Plan 02-05), then integration tests (Plan 02-06). This order ensures every dependency is in place before the next plan starts.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `shutil` | 3.11+ | `shutil.copytree()` for full snapshot copies | No dependencies; atomic via copy-then-rename pattern |
| Python stdlib `tarfile` | 3.11+ | Optional compressed snapshots (`tar.gz`) | Smaller on disk for large skills dirs |
| Python stdlib `os` | 3.11+ | `os.replace()` atomic rename across platforms | Already used throughout codebase (Sentinel, CronStore, write_config) |
| Python stdlib `json` | 3.11+ | Snapshot metadata manifest (snapshot_id, timestamp, description, change_type) | Already used everywhere |
| Python `dataclasses` | 3.11+ | SnapshotMeta dataclass (frozen=True, pattern matches SynapseConfig) | Consistent with project style |
| FastAPI | existing | `GET /snapshots` endpoint | Already used for all API routes |
| `filelock` | existing | Serialize snapshot writes (already used in AuditLogger) | Prevent concurrent snapshots corrupting each other |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `difflib` | 3.11+ | Generate human-readable diff for change descriptions | Optional — enrich snapshot metadata |
| Python stdlib `re` | 3.11+ | Natural-language date parsing ("last week", "March 15") | RollbackResolver date extraction |
| `dateparser` | check registry | Robust NLP date parsing | Preferred over hand-rolled regex if already in deps |

**Version verification:** [VERIFIED: existing project Python 3.13.6 on Windows 11; all stdlib modules available]

**Installation:** No new packages required. All dependencies are stdlib or already installed.

```bash
# If dateparser not already installed:
pip install dateparser
```

---

## Architecture Patterns

### Recommended Project Structure

```
workspace/sci_fi_dashboard/
├── snapshot_engine.py       # SnapshotEngine class (new — Plan 02-01)
├── consent_protocol.py      # ConsentProtocol class (new — Plan 02-03)
├── rollback.py              # RollbackResolver class (new — Plan 02-05)
├── sbs/sentinel/
│   └── manifest.py          # ZONE_1_PATHS + ZONE_2_PATHS constants (extend — Plan 02-02)
├── routes/
│   └── snapshots.py         # GET /snapshots route (new — Plan 02-01)
└── chat_pipeline.py         # Wire ConsentProtocol (extend — Plan 02-04)

~/.synapse/
└── snapshots/
    ├── 20260407T083000-create-medication-reminder/
    │   ├── SNAPSHOT.json    # metadata: id, timestamp, description, change_type, zone2_paths
    │   └── zone2/           # full copy of all Zone 2 contents at snapshot time
    │       ├── skills/
    │       └── state/agents/
```

### Pattern 1: Atomic Snapshot Write

**What:** Write snapshot contents to a `.tmp` directory, validate, then `os.rename()` into the final path. Partial writes never become visible.

**When to use:** Every time SnapshotEngine.create() is called.

**Example:**
```python
# Source: established in workspace/sci_fi_dashboard/sbs/sentinel/gateway.py (safe_write)
# and workspace/sci_fi_dashboard/cron/store.py (save)

import os
import shutil
from pathlib import Path

class SnapshotEngine:
    def create(self, description: str, change_type: str) -> "SnapshotMeta":
        snapshot_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{slugify(description)}"
        tmp_path = self._snapshots_dir / f"{snapshot_id}.tmp"
        final_path = self._snapshots_dir / snapshot_id
        try:
            tmp_path.mkdir(parents=True)
            # Copy all Zone 2 paths
            for zone2_path in ZONE_2_PATHS:
                src = self._data_root / zone2_path
                if src.exists():
                    dst = tmp_path / "zone2" / zone2_path
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
            # Write metadata
            meta = SnapshotMeta(id=snapshot_id, timestamp=..., description=description)
            (tmp_path / "SNAPSHOT.json").write_text(json.dumps(asdict(meta)))
            # Atomic rename: only succeeds when copy is complete
            os.replace(str(tmp_path), str(final_path))
            return meta
        except Exception:
            shutil.rmtree(str(tmp_path), ignore_errors=True)  # clean up partial
            raise
```

### Pattern 2: ConsentProtocol Orchestration

**What:** Detect modification intent → explain in plain language → wait for confirmation → execute → snapshot (pre-flight) → on failure revert.

**When to use:** Any time the chat pipeline detects a Zone 2 modification intent.

**Example:**
```python
# Source: [ASSUMED] — pattern derived from phase description requirements
class ConsentProtocol:
    async def run(self, intent: "ModificationIntent", request, target) -> dict:
        # Step 1: Explain
        explanation = await self._generate_explanation(intent)
        # Return explanation — wait for next user message
        return {"status": "awaiting_confirmation", "explanation": explanation}

    async def confirm_and_execute(self, intent, request, target) -> dict:
        # Step 2: Snapshot BEFORE execution
        pre_snapshot = self.snapshot_engine.create(
            description=f"pre: {intent.description}", change_type="pre_modification"
        )
        try:
            # Step 3: Execute
            result = await intent.execute()
            # Step 4: Snapshot AFTER success
            self.snapshot_engine.create(
                description=intent.description, change_type=intent.change_type
            )
            return {"status": "success", "result": result}
        except Exception as e:
            # Step 5: Auto-revert on failure
            self.snapshot_engine.restore(pre_snapshot.id)
            return {"status": "reverted", "error": str(e)}
```

### Pattern 3: Sentinel Zone Registry Extension

**What:** Add explicit ZONE_1_PATHS and ZONE_2_PATHS named constants to manifest.py so code can reference zones symbolically rather than duplicating path lists.

**When to use:** Plan 02-02 extends manifest.py.

**Example:**
```python
# Extend workspace/sci_fi_dashboard/sbs/sentinel/manifest.py

# Zone 1: cryptographically immutable — maps to CRITICAL_FILES + CRITICAL_DIRECTORIES
ZONE_1_PATHS: frozenset[str] = frozenset(CRITICAL_FILES | CRITICAL_DIRECTORIES)

# Zone 2: writable with consent — subset of WRITABLE_ZONES that self-modification targets
ZONE_2_PATHS: tuple[str, ...] = (
    "skills/",                               # skill directories
    os.path.expanduser("~/.synapse/skills/"), # user skill store
    os.path.expanduser("~/.synapse/state/agents/"),  # cron jobs
    os.path.expanduser("~/.synapse/cron/"),  # legacy cron jobs.json
    os.path.expanduser("~/.synapse/snapshots/"),  # snapshot store itself
)

ZONE_2_DESCRIPTION: dict[str, str] = {
    "skills/": "Skill capabilities (what Synapse can do)",
    "~/.synapse/skills/": "User skill store",
    "~/.synapse/state/agents/": "Scheduled job definitions (cron)",
    "~/.synapse/cron/": "Legacy cron job definitions",
}
```

### Pattern 4: Session-State Consent Tracking

**What:** The consent protocol spans two user turns (explanation turn + confirmation turn). The state machine must be persisted between turns using the existing session infrastructure.

**When to use:** Wiring ConsentProtocol into chat_pipeline.py (Plan 02-04).

**Key insight:** Use the existing ConversationCache / session infrastructure from multiuser/ to store pending consent state keyed by session. Do NOT use a global dict — that breaks per-user isolation.

```python
# In chat_pipeline.py, before LLM call:
pending_consent = session.get_pending_consent()
if pending_consent and _is_affirmative(user_msg):
    return await consent_protocol.confirm_and_execute(pending_consent, ...)
elif pending_consent and _is_negative(user_msg):
    session.clear_pending_consent()
    return {"reply": "OK, I won't make that change."}
```

### Anti-Patterns to Avoid

- **Incremental/diff snapshots:** Every snapshot must be self-contained (MOD-10). Do not store only diffs — restoring snapshot N must not require snapshot N-1.
- **Deleting snapshots on rollback:** MOD-06 requires forward history preservation. Rollback creates a new "restore" snapshot, never deletes prior snapshots.
- **Zone 1 enforcement via prompt only:** LLMs can be manipulated into believing they have permission. Sentinel's `check_access()` must block writes at the filesystem level — the prompt is informational only.
- **Global dict for pending consent:** Breaks when two users have simultaneous pending consents. Use session-scoped storage.
- **OS-level schtasks for cron skills:** The codebase uses `CronService` (asyncio-based, reads from `~/.synapse/cron/jobs.json`). Adding a medication reminder means adding a `CronJob` entry to `CronStore`, not registering with schtasks. This is entirely in Zone 2 and requires no OS-level scheduling.
- **Writing temp files outside the snapshot directory:** `os.replace()` only works atomically within the same filesystem. Always write temp files into the same parent directory as the target.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic file writes | Custom write logic | `os.replace()` (already in Sentinel.safe_write + CronStore.save) | Same-filesystem atomic rename — crash-safe |
| Zone enforcement | Duplicate path checks | `Sentinel.check_access()` (already exists) | Centralized, audited, manifest-hash-verified |
| Directory copy for snapshots | Custom recursive copy | `shutil.copytree()` | Handles symlinks, permissions, deep nesting correctly |
| NLP date parsing | Hand-rolled regex for "last Tuesday" | `dateparser.parse()` (or stdlib fallback) | Edge cases in natural-language dates are vast |
| Cron scheduling | OS `schtasks`/`cron` calls | `CronStore` + `CronService` (already exists) | Entire cron stack is in Zone 2, asyncio-based, already snapshottable |
| Concurrent snapshot protection | Manual locking | `filelock.FileLock` (already used in AuditLogger) | Prevents concurrent snapshot writers from corrupting state |

**Key insight:** The Sentinel file governance system is the correct enforcement layer. The consent protocol runs above it — Sentinel is the floor, not the ceiling.

---

## Runtime State Inventory

This phase involves writing to `~/.synapse/` directories. No rename/refactor operations are involved. The runtime state inventory below describes existing state that snapshots must capture.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `~/.synapse/state/agents/{agent_id}/cron.json` — CronJob entries | Snapshot includes; restore overwrites |
| Stored data | `~/.synapse/cron/jobs.json` — legacy CronService jobs file | Snapshot includes; restore overwrites |
| Stored data | `~/.synapse/skills/` — user skill directories (Phase 1 output) | Snapshot includes; restore replaces directory tree |
| Live service config | CronService holds in-memory CronJob list loaded at startup | After restore, call `cron_service.reload()` to re-read from disk |
| OS-registered state | None — CronService uses asyncio loops, NOT schtasks/system cron | No OS-level cleanup needed on rollback |
| Secrets/env vars | No secrets involved in Zone 2 modification targets | None |
| Build artifacts | None — no compiled artifacts in Zone 2 | None |

**Nothing found in OS-registered state category:** Verified by reviewing CronService (asyncio-based, not OS scheduler) and cron/service.py. The ROADMAP mentions schtasks as a risk but this codebase does NOT use it. [VERIFIED: workspace/sci_fi_dashboard/cron_service.py, workspace/sci_fi_dashboard/cron/service.py]

---

## Common Pitfalls

### Pitfall 1: Snapshot of Running CronService State
**What goes wrong:** Snapshot copies cron.json from disk, but CronService holds modified state in memory that hasn't been flushed. Restored snapshot appears correct on disk but CronService re-reads nothing (no auto-reload).
**Why it happens:** CronService.start() loads jobs once at startup; subsequent modifications by ConsentProtocol write to disk but don't call reload().
**How to avoid:** After any Zone 2 modification that touches cron data, call `app.state.cron_service.reload()`. After any restore, call `cron_service.reload()` immediately.
**Warning signs:** User says "undo the reminder" but Synapse still fires the cron job.

### Pitfall 2: Partial Snapshot on Power Loss / Process Kill
**What goes wrong:** Snapshot copy is interrupted mid-write. The `.tmp` directory exists but is incomplete. Next startup finds a corrupt snapshot.
**Why it happens:** `shutil.copytree()` is not atomic — it copies files one by one.
**How to avoid:** Write to `snapshot_id.tmp`, only `os.rename()` to `snapshot_id` when fully written. On startup, scan for any `.tmp` directories in `~/.synapse/snapshots/` and delete them (they are incomplete). This is the established pattern in CronStore.save() and Sentinel.safe_write().
**Warning signs:** `GET /snapshots` shows entries with `.tmp` suffix.

### Pitfall 3: Zone 1 Path Boundary Confusion (Relative vs Absolute)
**What goes wrong:** Sentinel is initialized with `project_root` set to the source code directory. CRITICAL_FILES are relative to that root (e.g., `"api_gateway.py"`). But `~/.synapse/` paths are absolute. A path check against `~/.synapse/sbs/sentinel/` incorrectly passes because Sentinel's `_classify_path()` resolves relative to project_root, not the home directory.
**Why it happens:** `manifest.py` mixes relative paths (CRITICAL_FILES) and absolute paths (WRITABLE_ZONES uses `os.path.expanduser("~/.synapse/")`). Sentinel resolves relative paths against `self.project_root` but absolute paths are used as-is.
**How to avoid:** ZONE_2_PATHS constants must use absolute paths (expanduser). Test that writing to `~/.synapse/some-path` is correctly classified as MONITORED, not PROTECTED.
**Warning signs:** `SentinelError` when ConsentProtocol tries to write a skill to `~/.synapse/skills/`.

### Pitfall 4: Consent State Lost on Server Restart
**What goes wrong:** User says "create a medication reminder skill", Synapse explains and waits for confirmation. User says "yes" but the server was restarted between turns. Pending consent state is gone.
**Why it happens:** If consent state is stored only in memory (e.g., a dict on ConsentProtocol instance), it is lost on restart.
**How to avoid:** Store pending consent in the session JSONL transcript (via the existing session infrastructure from Phase 0) or as a small JSON file in `~/.synapse/state/`. At restart, check for incomplete consent and either prompt again or expire it.
**Warning signs:** "yes" gets treated as a normal message and routes to casual LLM.

### Pitfall 5: Rollback Creates Infinite Snapshot Chain
**What goes wrong:** Each rollback creates a new snapshot ("restore of snapshot X"). User rolls back 10 times → 10 new snapshots created → disk fills up.
**Why it happens:** MOD-06 requires rolling back never destroys history. Naive implementation creates a new full snapshot for every rollback event.
**How to avoid:** Rollback snapshots are metadata-tagged as `change_type="restore"` so they can be filtered or pruned separately. Implement a configurable max-snapshots limit (default 50) with cleanup of oldest when exceeded — excluding the current live state.
**Warning signs:** `~/.synapse/snapshots/` grows unboundedly.

### Pitfall 6: Skills Directory Scope Mismatch
**What goes wrong:** Phase 1 plans write bundled skills to `workspace/sci_fi_dashboard/skills/bundled/` and seed them to `~/.synapse/skills/`. Snapshot must capture `~/.synapse/skills/`, NOT the source-tree `skills/` directory (which is Zone 1 in Sentinel's CRITICAL sense — not in the project's WRITABLE_ZONES).
**Why it happens:** Two different `skills/` paths exist: the source-code bundled skills and the user's runtime skills.
**How to avoid:** ZONE_2_PATHS for snapshots must reference `~/.synapse/skills/` (absolute, expanduser), not the relative `"skills/"` entry in WRITABLE_ZONES (which refers to a project-relative path for the SBS data dir context).
**Warning signs:** Snapshot restores change the bundled skill source code instead of user's ~/.synapse/skills/.

---

## Code Examples

Verified patterns from official sources:

### Atomic directory rename (snapshot finalization)
```python
# Source: established in workspace/sci_fi_dashboard/cron/store.py::CronStore.save()
# and workspace/sci_fi_dashboard/sbs/sentinel/gateway.py::Sentinel.safe_write()
import os
import shutil
from pathlib import Path

# Pattern: write to .tmp, then rename atomically
tmp_path = final_path.with_suffix(".tmp")
try:
    shutil.copytree(src, tmp_path)
    os.replace(str(tmp_path), str(final_path))  # atomic on same filesystem
except Exception:
    shutil.rmtree(str(tmp_path), ignore_errors=True)
    raise
```

### Sentinel check_access for Zone 2 write gate
```python
# Source: workspace/sci_fi_dashboard/sbs/sentinel/tools.py::agent_check_write_access()
from sci_fi_dashboard.sbs.sentinel.tools import agent_check_write_access
from sci_fi_dashboard.sbs.sentinel.gateway import SentinelError

def verify_zone2_write(path: str, reason: str) -> bool:
    try:
        agent_check_write_access(path, reason)
        return True
    except SentinelError as e:
        logger.error("Zone 1 write rejected: %s", e)
        raise  # ConsentProtocol re-raises as a hard block
```

### CronService reload after restore
```python
# Source: workspace/sci_fi_dashboard/cron_service.py::CronService.reload()
# After snapshot restore, reload cron state:
if hasattr(app.state, "cron_service") and app.state.cron_service:
    app.state.cron_service.reload()  # calls stop() + start() with fresh jobs from disk
```

### Snapshot metadata dataclass (project style)
```python
# Source: Pattern from workspace/synapse_config.py (frozen dataclass with field defaults)
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class SnapshotMeta:
    id: str                        # e.g. "20260407T083000-medication-reminder"
    timestamp: str                 # ISO 8601
    description: str               # plain-language description of the change
    change_type: str               # "create_skill" | "delete_skill" | "create_cron" | "restore"
    zone2_paths: tuple[str, ...]   # which Zone 2 paths were captured
    pre_snapshot_id: str = ""      # for restore events: which snapshot was restored from
    path: Path = field(default_factory=lambda: Path("."))  # absolute path to snapshot dir
```

### Intent detection hook in chat_pipeline.py
```python
# Source: [ASSUMED] pattern — matches how traffic cop classification works
# Insert BEFORE the traffic cop / skill routing step in persona_chat():

from sci_fi_dashboard.consent_protocol import ConsentProtocol, detect_modification_intent

# Check for pending consent first (user said "yes"/"no" to a previous proposal)
pending = _get_pending_consent(request)
if pending:
    if _is_affirmative(user_msg):
        return await consent_protocol.confirm_and_execute(pending, request, target)
    elif _is_negative(user_msg):
        _clear_pending_consent(request)
        return {"reply": "Got it, I won't make that change.", ...}

# Check for new modification intent
intent = await detect_modification_intent(user_msg, deps.synapse_llm_router)
if intent:
    explanation = await consent_protocol.explain(intent)
    _set_pending_consent(request, intent)
    return {"reply": explanation, ...}

# Otherwise: normal pipeline continues
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OS-level schtasks for cron | asyncio CronService + CronStore JSON | v1.0 era | Rollback is a JSON file update, not OS task deletion |
| Global Sentinel (singleton) | Project-root-scoped Sentinel (init_sentinel) | v1.0 | Multiple projects can have isolated Sentinels |
| Flat jobs.json (cron_service.py) | Typed CronJob dataclasses in CronStore (cron/) | Recent refactor | Rich scheduling (cron expressions, stagger, delivery modes) |

**Deprecated/outdated:**
- `workspace/sci_fi_dashboard/cron_service.py`: The simple `jobs.json` reader. Still used in api_gateway.py lifespan (line 225). The richer `cron/` module exists alongside it but may not be fully wired. Plan 02-03 (ConsentProtocol for "remind me to...") should write to `CronStore` (the richer system), not the legacy `cron_service.py` `jobs.json`. Clarify in planning which system gets the consent-created cron entries. [ASSUMED — needs verification of which CronService is wired in lifespan]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The codebase does NOT use OS-level schtasks — only asyncio CronService | Runtime State Inventory | If wrong, rollback of cron jobs must also call schtasks /delete — adds cross-platform complexity |
| A2 | Skills live in `~/.synapse/skills/` (absolute) for Zone 2 snapshot purposes, not `workspace/sci_fi_dashboard/skills/` (source tree) | Pitfall 6 | If Phase 1 seeded skills somewhere else, snapshot paths need adjustment |
| A3 | `app.state.cron_service` in api_gateway.py refers to the legacy `cron_service.py::CronService`, not the richer `cron/service.py` | Code Examples | If the richer CronService is also wired, consent-created jobs must target the correct one |
| A4 | Phase 1 will have been fully executed before Phase 2 begins (SkillLoader, SkillRegistry, SkillRouter all exist) | Architecture Patterns | If Phase 1 is incomplete, Plan 02-03 cannot write skills as the output format for self-modification |
| A5 | `dateparser` is not yet in requirements; stdlib `re` + manual date parsing may be needed as fallback | Standard Stack | Low impact — worst case RollbackResolver uses regex instead of dateparser |

**If this table is empty:** Not applicable — several assumptions are present.

---

## Open Questions (RESOLVED)

1. **Which CronService gets consent-created jobs?** (RESOLVED)
   - What we know: `api_gateway.py` imports `cron_service.py::CronService` (the legacy flat-file version). The richer `cron/` module exists with `CronStore` but may not be the active runtime path.
   - What's unclear: Does ConsentProtocol write to `~/.synapse/cron/jobs.json` (legacy) or `~/.synapse/state/agents/{agent_id}/cron.json` (CronStore)?
   - Recommendation: In Plan 02-03, use `CronStore` (the richer system) because it supports typed dataclasses and has migration support. The lifespan wiring may need updating to also initialize CronStore.
   - **RESOLVED:** Phase 2 implements a noop executor for `change_type=="create_cron"` (infrastructure only). The consent-detect-explain-confirm flow works for cron intents, but actual CronJob creation is deferred to Phase 3 (subagent system) where async tool execution is supported. `CronService` is not touched in Phase 2. Plan 02-04 documents this as explicit partial delivery with a code comment.

2. **Where does pending consent state live between turns?** (RESOLVED)
   - What we know: Phase 0 wires in ConversationCache and session persistence. Session JSONL transcripts are already written per-turn.
   - What's unclear: Whether the session infrastructure from Phase 0 is complete and available before Phase 2 begins.
   - Recommendation: Store pending consent as a small `pending_consent.json` in `~/.synapse/state/` as a fallback if Phase 0 session infrastructure is not yet available.
   - **RESOLVED:** Pending consent is stored in an in-memory dict in `_deps.py`, keyed by `(session_key, sender_id)` tuple. Known limitation: does not survive server restart. Acceptable for single-user deployment. Multi-user persistence fix deferred.

3. **Snapshot size and retention policy** (RESOLVED)
   - What we know: Zone 2 includes `~/.synapse/skills/` which could grow large over time.
   - What's unclear: Whether to snapshot the entire `~/.synapse/` or only explicitly listed Zone 2 paths.
   - Recommendation: Snapshot only the explicitly listed Zone 2 paths (skills/, cron state, model_mappings config section). Do NOT snapshot the full `~/.synapse/` (includes memory.db which can be GBs).
   - **RESOLVED:** SnapshotEngine snapshots `ZONE_2_PATHS` from manifest.py (`"skills"`, `"state/agents"`) -- the full Zone 2 scope, not all of `~/.synapse/`. Retention: max 50 snapshots, configurable via `synapse.json -> snapshots.max_count`. Oldest pruned on create.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ stdlib (shutil, tarfile, os, json) | SnapshotEngine | Yes | Python 3.13.6 | — |
| `filelock` | Snapshot write serialization | Yes | installed (used by AuditLogger) | Manual lock file |
| `pytest` + `pytest-asyncio` | All test plans | Yes | pytest 9.0.2, asyncio 1.3.0 | — |
| `schtasks.exe` | NOT needed | Available at `/c/WINDOWS/system32/schtasks` | — | Not needed — internal CronService used |
| `dateparser` | RollbackResolver NLP dates | Unknown — not verified in pyproject.toml | — | Regex fallback for common patterns |

**Missing dependencies with no fallback:** None blocking.

**Missing dependencies with fallback:**
- `dateparser`: If not installed, RollbackResolver implements regex patterns for "last week", "yesterday", ISO dates, and "X days ago". Recommend checking `pyproject.toml` before Plan 02-05.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `workspace/tests/pytest.ini` |
| Quick run command | `cd workspace && python -m pytest tests/test_snapshot_engine.py tests/test_consent_protocol.py -v -x` |
| Full suite command | `cd workspace && python -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MOD-01 | ConsentProtocol explains before any write | unit | `pytest tests/test_consent_protocol.py::test_explanation_before_write -x` | No — Wave 0 |
| MOD-02 | Snapshot written to ~/.synapse/snapshots/ after confirm | unit | `pytest tests/test_snapshot_engine.py::test_snapshot_created_after_confirm -x` | No — Wave 0 |
| MOD-03 | Auto-revert on failure | unit | `pytest tests/test_consent_protocol.py::test_auto_revert_on_failure -x` | No — Wave 0 |
| MOD-04 | Rollback by date string | unit | `pytest tests/test_rollback.py::test_rollback_by_date -x` | No — Wave 0 |
| MOD-05 | Rollback by "undo last" | unit | `pytest tests/test_rollback.py::test_rollback_undo_last -x` | No — Wave 0 |
| MOD-06 | Rollback preserves forward history | unit | `pytest tests/test_rollback.py::test_rollback_preserves_forward_history -x` | No — Wave 0 |
| MOD-07 | Sentinel rejects Zone 1 writes | unit | `pytest tests/test_sbs_sentinel.py::TestSentinel::test_critical_file_all_ops_denied -x` | Yes (existing, 2 pre-existing failures unrelated) |
| MOD-08 | Zone 2 list explicit | unit | `pytest tests/test_zone_registry.py::test_zone2_paths_all_writable -x` | No — Wave 0 |
| MOD-09 | GET /snapshots returns list | integration | `pytest tests/test_snapshots_api.py::test_list_snapshots -x` | No — Wave 0 |
| MOD-10 | Snapshot self-contained restore | integration | `pytest tests/test_snapshot_engine.py::test_restore_without_prior_snapshots -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `cd workspace && python -m pytest tests/test_snapshot_engine.py tests/test_consent_protocol.py -v -x`
- **Per wave merge:** `cd workspace && python -m pytest tests/ -v`
- **Phase gate:** Full suite green (minus 2 pre-existing sentinel failures) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_snapshot_engine.py` — covers MOD-02, MOD-03, MOD-10
- [ ] `tests/test_consent_protocol.py` — covers MOD-01, MOD-03
- [ ] `tests/test_rollback.py` — covers MOD-04, MOD-05, MOD-06
- [ ] `tests/test_zone_registry.py` — covers MOD-07, MOD-08
- [ ] `tests/test_snapshots_api.py` — covers MOD-09

**Pre-existing test failures to be aware of:**
`tests/test_sbs_sentinel.py::TestSentinel::test_monitored_zone_delete_restricted` and `test_safe_delete` — 2 tests fail because the current `_apply_rules()` in gateway.py denies delete even for `data/temp/` paths (the "temp/" string check doesn't match because of path resolution). These are pre-existing bugs, NOT introduced by Phase 2. Phase 2's Zone registry work may fix these as a side effect but should not block Phase 2 verification.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | Yes | Session-scoped consent state (prevent consent hijacking across users) |
| V4 Access Control | Yes | Sentinel Zone 1 enforcement at filesystem level — not just prompt |
| V5 Input Validation | Yes | Snapshot description, change_type — sanitize before using as directory names |
| V6 Cryptography | No | Snapshots are plaintext directories; manifest hash is SHA-256 (existing) |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection → "write to api_gateway.py" | Tampering | Sentinel CRITICAL classification blocks at filesystem level |
| Path traversal in snapshot ID (e.g., `../../etc/passwd`) | Tampering | Snapshot ID must be validated: only alphanumeric + hyphen, slugified from description |
| Consent hijacking (attacker sends "yes" before owner sees explanation) | Spoofing | Consent state is session-scoped; ConsentProtocol checks sender_id matches explanation recipient |
| Snapshot directory enumeration | Information Disclosure | `GET /snapshots` requires gateway_token auth (same as all other authenticated routes) |
| DoS via snapshot flooding | Denial of Service | Max snapshot limit (default 50); configurable via `synapse.json → snapshots.max_count` |
| Zone 2 path escape in snapshot restore | Elevation | Restore only writes to explicitly listed ZONE_2_PATHS; any path outside that list is rejected |

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: workspace/sci_fi_dashboard/sbs/sentinel/gateway.py] — Sentinel architecture, safe_write atomic pattern, path classification
- [VERIFIED: workspace/sci_fi_dashboard/sbs/sentinel/manifest.py] — CRITICAL_FILES, CRITICAL_DIRECTORIES, WRITABLE_ZONES, ProtectionLevel
- [VERIFIED: workspace/sci_fi_dashboard/cron/store.py] — atomic write pattern with os.replace
- [VERIFIED: workspace/sci_fi_dashboard/cron/types.py] — CronJob, CronSchedule, CronStore dataclass types
- [VERIFIED: workspace/sci_fi_dashboard/cron_service.py] — legacy CronService; asyncio-only scheduling (no schtasks)
- [VERIFIED: workspace/sci_fi_dashboard/api_gateway.py] — lifespan wiring, CronService init at line 225
- [VERIFIED: workspace/sci_fi_dashboard/chat_pipeline.py] — persona_chat() structure for wiring consent protocol
- [VERIFIED: workspace/synapse_config.py] — data_root path, write_config atomic pattern, SynapseConfig.load()
- [VERIFIED: workspace/tests/test_sbs_sentinel.py] — existing test coverage for Sentinel; 2 pre-existing failures
- [VERIFIED: workspace/tests/pytest.ini] — test framework config, asyncio mode=auto
- [VERIFIED: Python 3.13.6 runtime] — all stdlib modules (shutil, os, json, tarfile) available

### Secondary (MEDIUM confidence)
- [VERIFIED: .planning/phases/01-skill-architecture/01-01-PLAN.md] — Phase 1 skill schema (SkillManifest, OPTIONAL_SUBDIRS, ~/.synapse/skills/ target)
- [VERIFIED: .planning/phases/01-skill-architecture/01-05-PLAN.md] — seed_bundled_skills, skill-creator skill wiring
- [VERIFIED: .planning/ROADMAP.md] — Phase 2 plan names, success criteria, key risks
- [VERIFIED: .planning/REQUIREMENTS.md] — MOD-01 through MOD-10 verbatim requirements

### Tertiary (LOW confidence / ASSUMED)
- [ASSUMED] Natural-language date parsing fallback patterns for RollbackResolver
- [ASSUMED] ConsentProtocol session state storage mechanism (pending Phase 0 session infrastructure availability)

---

## Project Constraints (from CLAUDE.md)

The following directives from `CLAUDE.md` apply to all Phase 2 plans:

1. **OSS standards before every commit**: No personal data in committed files. `entities.json` ships as `{}`. No real tokens/keys.
2. **Python 3.11 | line-length 100 | ruff + black | asyncio throughout** — no Redis/Celery, no sync blocking calls.
3. **SQLite WAL mode** — any new SQLite usage (snapshot index) must use WAL mode.
4. **`synapse_config.py` has wide blast radius** — do not add snapshot config there without careful review. Prefer adding a `snapshots` key to `synapse.json` that `SynapseConfig.load()` reads via `raw.get("snapshots", {})`.
5. **CRITICAL files listed in CLAUDE.md** — `api_gateway.py` and all sentinel files are Zone 1. Do not modify these except in Plan 02-02 (manifest.py constant extension) and Plan 02-04 (minimal wiring in api_gateway.py / chat_pipeline.py).
6. **Kill gateway after code changes** — development workflow requires restarting uvicorn. Tests that exercise the full pipeline must mock the gateway rather than spinning up a live server.
7. **Dual Cognition timeout** — `think()` is wrapped in `asyncio.wait_for(5s)`. ConsentProtocol must not call `think()` directly — it runs after dual cognition has already completed in `persona_chat()`.
8. **`synapse_config.py` is imported by 50+ files** — adding `snapshots_dir` as a derived path from `data_root` is safe (computed, not loaded from file). Adding new JSON keys is safe. Do not rename existing fields.
9. **No personal data files**: `entities.json` is `{}`, `synapse.json` ships with placeholders.
10. **MCP tools not offered during persona chat**: ConsentProtocol runs inside `persona_chat()`, not as an MCP tool. It intercepts the pipeline before the LLM call.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are stdlib or already installed; verified in codebase
- Architecture: HIGH — Sentinel, CronStore, CronService, and synapse_config patterns are all verified in source
- Pitfalls: HIGH — most derived directly from reading the live code, not from training assumptions
- Zone 1/Zone 2 enforcement: HIGH — manifest.py and gateway.py fully read and understood
- Rollback mechanism: MEDIUM — pattern is clear but session state for multi-turn consent is ASSUMED to use Phase 0 infrastructure

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (30 days — stable Python codebase)
