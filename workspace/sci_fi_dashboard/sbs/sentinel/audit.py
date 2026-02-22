# sci_fi_dashboard/sbs/sentinel/audit.py

import json
from pathlib import Path
from datetime import datetime
from filelock import FileLock

class AuditLogger:
    """
    Immutable audit trail for all Sentinel decisions.
    
    This log is append-only. The agent cannot modify or delete it
    because the audit directory lives under sentinel/ which is CRITICAL.
    """
    
    def __init__(self, audit_dir: Path):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.audit_dir / "sentinel_audit.jsonl"
        self.lock = FileLock(str(self.log_path) + ".lock")
    
    def log_access(self, path: str, operation: str, 
                    protection_level: str, context: str):
        """Log an ALLOWED access."""
        self._append({
            "timestamp": datetime.now().isoformat(),
            "decision": "ALLOWED",
            "path": path,
            "operation": operation,
            "protection_level": protection_level,
            "context": context
        })
    
    def log_denial(self, path: str, operation: str, reason: str):
        """Log a DENIED access."""
        self._append({
            "timestamp": datetime.now().isoformat(),
            "decision": "DENIED",
            "path": path,
            "operation": operation,
            "reason": reason
        })
    
    def log_event(self, event_type: str, details: dict):
        """Log a system event."""
        self._append({
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "details": details
        })
    
    def _append(self, record: dict):
        with self.lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
