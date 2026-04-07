# sci_fi_dashboard/sbs/sentinel/manifest.py

"""
SENTINEL PROTECTED MANIFEST
============================
This file defines what the AI agent can and cannot touch.
This file ITSELF is protected -- the agent cannot modify it.

Protection Levels:
  CRITICAL  -- Cannot read, write, delete, or list. Total blackout.
  PROTECTED -- Can read, cannot write or delete.
  MONITORED -- Can read and write, but all writes are logged and diffed.
  OPEN      -- No restrictions (default for writable zones).
"""

from enum import Enum


class ProtectionLevel(Enum):
    CRITICAL = "critical"  # Total lockout
    PROTECTED = "protected"  # Read-only
    MONITORED = "monitored"  # Read-write with audit
    OPEN = "open"  # Unrestricted


# ============================================================
# CRITICAL FILES -- Touch these and the system dies
# The agent cannot read, write, or even list these paths
# ============================================================
CRITICAL_FILES: set[str] = {
    # Core application entry points
    "api_gateway.py",
    "main.py",
    "run.py",
    "app.py",
    # SBS Core -- the brain itself
    "sbs/orchestrator.py",
    "sbs/injection/compiler.py",
    "sbs/profile/manager.py",
    # Sentinel -- self-protection
    "sbs/sentinel/__init__.py",
    "sbs/sentinel/manifest.py",
    "sbs/sentinel/gateway.py",
    "sbs/sentinel/audit.py",
    "sbs/sentinel/tools.py",
    # Configuration and secrets
    ".env",
    "config.py",
    "settings.py",
    "requirements.txt",
    "pyproject.toml",
    # Profile immutable layer
    "data/profiles/current/core_identity.json",
}

# ============================================================
# CRITICAL DIRECTORIES -- Everything inside is locked
# ============================================================
CRITICAL_DIRECTORIES: set[str] = {
    "sbs/sentinel/",
    "sbs/feedback/",  # Prevents bot from disabling its own correction system
    ".git/",
    "__pycache__/",
    "venv/",
    ".venv/",
}

# ============================================================
# PROTECTED FILES -- Read-only access
# ============================================================
PROTECTED_FILES: set[str] = {
    "sbs/ingestion/schema.py",
    "sbs/ingestion/logger.py",
    "sbs/processing/realtime.py",
    "sbs/processing/batch.py",
    "sbs/processing/selectors/exemplar.py",
    "sbs/vacuum.py",
}

# ============================================================
# WRITABLE ZONES -- Agent CAN write here (monitored)
# ============================================================
WRITABLE_ZONES: set[str] = {
    "data/raw/",  # Chat logs
    "data/indices/",  # SQLite DBs
    "data/profiles/current/",  # Profile layers (except core_identity)
    "data/profiles/archive/",  # Version snapshots
    "data/temp/",  # Scratch space
    "data/exports/",  # User-requested exports
    "generated/",  # Any generated content
    "logs/",  # Application logs
}

# ============================================================
# DANGEROUS OPERATIONS -- Always denied regardless of path
# ============================================================
FORBIDDEN_OPERATIONS: set[str] = {
    "rmtree",  # Recursive delete
    "shutil.rmtree",
    "os.system",  # Shell execution
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "exec",
    "eval",
    "importlib",
    "chmod",  # Permission changes
    "chown",
}

# ============================================================
# ZONE CONSTANTS — Named references for Phase 2 self-modification
# These derive from the sets above and provide symbolic names
# for SnapshotEngine, ConsentProtocol, and tests.
# ============================================================

# Zone 1: Immutable to model-initiated writes.
# Union of CRITICAL_FILES and CRITICAL_DIRECTORIES.
# Sentinel classifies these as CRITICAL (total lockout) or PROTECTED (read-only).
ZONE_1_PATHS: frozenset[str] = frozenset(CRITICAL_FILES | CRITICAL_DIRECTORIES)

# Zone 2: Writable with consent — the subset of ~/.synapse/ that self-modification targets.
# These are relative to data_root (~/.synapse/) — SnapshotEngine resolves them.
# IMPORTANT: No trailing slashes. SnapshotEngine joins these with data_root directly.
ZONE_2_PATHS: tuple[str, ...] = (
    "skills",                    # User skill directories (Phase 1 output format)
    "state/agents",              # CronStore per-agent cron.json files
)

# Human-readable descriptions for consent protocol explanations
ZONE_2_DESCRIPTIONS: dict[str, str] = {
    "skills": "Skill capabilities (what Synapse can do)",
    "state/agents": "Scheduled job definitions (cron reminders, recurring tasks)",
}
