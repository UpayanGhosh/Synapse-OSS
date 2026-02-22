# sci_fi_dashboard/sbs/sentinel/manifest.py

"""
SENTINEL PROTECTED MANIFEST
============================
This file defines what the AI agent can and cannot touch.
This file ITSELF is protected — the agent cannot modify it.

Protection Levels:
  CRITICAL  — Cannot read, write, delete, or list. Total blackout.
  PROTECTED — Can read, cannot write or delete.
  MONITORED — Can read and write, but all writes are logged and diffed.
  OPEN      — No restrictions (default for writable zones).
"""

from pathlib import Path
from enum import Enum
from typing import Dict, Set

class ProtectionLevel(Enum):
    CRITICAL = "critical"      # Total lockout
    PROTECTED = "protected"    # Read-only
    MONITORED = "monitored"    # Read-write with audit
    OPEN = "open"              # Unrestricted


# ============================================================
# CRITICAL FILES — Touch these and the system dies
# The agent cannot read, write, or even list these paths
# ============================================================
CRITICAL_FILES: Set[str] = {
    # Core application entry points
    "api_gateway.py",
    "main.py",
    "run.py",
    "app.py",
    
    # SBS Core — the brain itself
    "sbs/orchestrator.py",
    "sbs/injection/compiler.py",
    "sbs/profile/manager.py",
    
    # Sentinel — self-protection
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
# CRITICAL DIRECTORIES — Everything inside is locked
# ============================================================
CRITICAL_DIRECTORIES: Set[str] = {
    "sbs/sentinel/",
    "sbs/feedback/",       # Prevents bot from disabling its own correction system
    ".git/",
    "__pycache__/",
    "venv/",
    ".venv/",
}

# ============================================================
# PROTECTED FILES — Read-only access
# ============================================================
PROTECTED_FILES: Set[str] = {
    "sbs/ingestion/schema.py",
    "sbs/ingestion/logger.py",
    "sbs/processing/realtime.py",
    "sbs/processing/batch.py",
    "sbs/processing/selectors/exemplar.py",
    "sbs/vacuum.py",
}

# ============================================================
# WRITABLE ZONES — Agent CAN write here (monitored)
# ============================================================
WRITABLE_ZONES: Set[str] = {
    "data/raw/",                    # Chat logs
    "data/indices/",                # SQLite DBs
    "data/profiles/current/",       # Profile layers (except core_identity)
    "data/profiles/archive/",       # Version snapshots
    "data/temp/",                   # Scratch space
    "data/exports/",                # User-requested exports
    "generated/",                   # Any generated content
    "logs/",                        # Application logs
}

# ============================================================
# DANGEROUS OPERATIONS — Always denied regardless of path
# ============================================================
FORBIDDEN_OPERATIONS: Set[str] = {
    "rmtree",           # Recursive delete
    "shutil.rmtree",
    "os.system",        # Shell execution
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "exec",
    "eval",
    "importlib",
    "chmod",            # Permission changes
    "chown",
}
