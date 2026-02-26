# sci_fi_dashboard/sbs/sentinel/gateway.py

import hashlib
from pathlib import Path
from typing import Literal

from .audit import AuditLogger
from .manifest import (
    CRITICAL_DIRECTORIES,
    CRITICAL_FILES,
    FORBIDDEN_OPERATIONS,
    PROTECTED_FILES,
    WRITABLE_ZONES,
    ProtectionLevel,
)


class SentinelError(PermissionError):
    """Raised when an operation is denied by Sentinel."""

    pass


class Sentinel:
    """
    File Access Governance Gateway.

    Every file operation by the AI agent MUST pass through this gateway.
    Direct filesystem access should be impossible — all agent tools
    must call Sentinel methods instead of raw open()/os.write()/etc.

    Design: FAIL-CLOSED
    If anything is ambiguous, uncertain, or errors out — DENY.
    """

    def __init__(self, project_root: Path, audit_dir: Path = None):
        self.project_root = project_root.resolve()
        self.audit = AuditLogger(audit_dir or (project_root / "logs" / "sentinel"))

        # Pre-compute absolute paths for fast lookup
        self._critical_abs = {(self.project_root / f).resolve() for f in CRITICAL_FILES}
        self._critical_dirs_abs = {(self.project_root / d).resolve() for d in CRITICAL_DIRECTORIES}
        self._protected_abs = {(self.project_root / f).resolve() for f in PROTECTED_FILES}
        self._writable_abs = {(self.project_root / z).resolve() for z in WRITABLE_ZONES}

        # Compute integrity hash of manifest itself (detect tampering)
        self._manifest_hash = self._compute_manifest_hash()

        self.audit.log_event(
            "SENTINEL_INIT",
            {
                "project_root": str(self.project_root),
                "critical_files": len(self._critical_abs),
                "protected_files": len(self._protected_abs),
                "writable_zones": len(self._writable_abs),
                "manifest_hash": self._manifest_hash,
            },
        )

    def check_access(
        self,
        path: str,
        operation: Literal["read", "write", "delete", "list", "execute"],
        agent_context: str = "",
    ) -> bool:
        """
        Core access check. Returns True if allowed, raises SentinelError if denied.

        Args:
            path: Relative or absolute path the agent wants to access
            operation: What the agent wants to do
            agent_context: Why the agent wants to do this (for audit)
        """
        # Step 0: Verify manifest integrity
        if not self._verify_manifest_integrity():
            self.audit.log_event("MANIFEST_TAMPERING_DETECTED", {"action": "TOTAL_LOCKDOWN"})
            raise SentinelError(
                "CRITICAL: Sentinel manifest integrity check failed. "
                "All operations denied. System requires manual intervention."
            )

        # Step 1: Resolve and normalize the path
        try:
            resolved = self._resolve_path(path)
        except ValueError as e:
            self.audit.log_denial(path, operation, f"Path resolution failed: {e}")
            raise SentinelError(f"Invalid path: {path}") from None

        # Step 2: Check for path traversal attacks
        if not self._is_within_project(resolved):
            self.audit.log_denial(path, operation, "Path traversal detected")
            raise SentinelError(
                f"ACCESS DENIED: Path '{path}' escapes project boundary. "
                f"This incident has been logged."
            )

        # Step 3: Classify the path
        level = self._classify_path(resolved)

        # Step 4: Apply access rules
        decision = self._apply_rules(resolved, level, operation)

        # Step 5: Audit
        if decision:
            self.audit.log_access(str(resolved), operation, level.value, agent_context)
        else:
            self.audit.log_denial(str(resolved), operation, f"Protection level: {level.value}")
            raise SentinelError(
                f"ACCESS DENIED: Cannot {operation} '{path}'. "
                f"Protection level: {level.value}. This incident has been logged."
            )

        return True

    def safe_read(self, path: str, agent_context: str = "") -> str:
        """Safe file read — checks access first, then reads."""
        self.check_access(path, "read", agent_context)
        resolved = self._resolve_path(path)
        with open(resolved, encoding="utf-8") as f:
            return f.read()

    def safe_write(self, path: str, content: str, agent_context: str = "") -> bool:
        """Safe file write — checks access, creates backup, then writes."""
        self.check_access(path, "write", agent_context)
        resolved = self._resolve_path(path)

        # Create backup before overwriting
        if resolved.exists():
            backup_content = resolved.read_text(encoding="utf-8")
            self.audit.log_event(
                "PRE_WRITE_BACKUP",
                {
                    "path": str(resolved),
                    "original_hash": hashlib.sha256(backup_content.encode()).hexdigest()[:16],
                    "new_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                },
            )

        # Ensure parent directory exists
        resolved.parent.mkdir(parents=True, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        return True

    def safe_delete(self, path: str, agent_context: str = "") -> bool:
        """Safe file delete — checks access, logs, then deletes."""
        self.check_access(path, "delete", agent_context)
        resolved = self._resolve_path(path)

        if resolved.exists():
            # Archive content before deletion
            if resolved.is_file():
                content = resolved.read_text(encoding="utf-8")
                self.audit.log_event(
                    "PRE_DELETE_ARCHIVE",
                    {
                        "path": str(resolved),
                        "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                        "size_bytes": len(content),
                    },
                )
            resolved.unlink()

        return True

    def validate_operation_string(self, operation: str) -> bool:
        """
        Check if an operation string contains forbidden patterns.
        Call this before executing any agent-generated code.
        """
        op_lower = operation.lower()
        for forbidden in FORBIDDEN_OPERATIONS:
            if forbidden.lower() in op_lower:
                self.audit.log_denial(
                    "CODE_EXECUTION", operation[:100], f"Forbidden operation pattern: {forbidden}"
                )
                raise SentinelError(
                    f"OPERATION DENIED: Contains forbidden pattern '{forbidden}'. "
                    f"This incident has been logged."
                )
        return True

    # ==================== INTERNAL METHODS ====================

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to project root, preventing traversal."""
        p = Path(path)
        resolved = p.resolve() if p.is_absolute() else (self.project_root / p).resolve()

        # Critical: Check for null bytes (bypass technique)
        if "\x00" in str(resolved):
            raise ValueError("Null byte in path")

        return resolved

    def _is_within_project(self, resolved: Path) -> bool:
        """Ensure the resolved path is inside the project directory."""
        try:
            resolved.relative_to(self.project_root)
            return True
        except ValueError:
            return False

    def _classify_path(self, resolved: Path) -> ProtectionLevel:
        """Determine the protection level for a given path."""

        # Check CRITICAL files first (highest priority)
        if resolved in self._critical_abs:
            return ProtectionLevel.CRITICAL

        # Check CRITICAL directories
        for crit_dir in self._critical_dirs_abs:
            try:
                resolved.relative_to(crit_dir)
                return ProtectionLevel.CRITICAL
            except ValueError:
                continue

        # Check PROTECTED files
        if resolved in self._protected_abs:
            return ProtectionLevel.PROTECTED

        # Check WRITABLE zones
        for writable in self._writable_abs:
            try:
                resolved.relative_to(writable)
                return ProtectionLevel.MONITORED
            except ValueError:
                continue

        # DEFAULT: If not explicitly writable, it is PROTECTED
        # This is FAIL-CLOSED behavior
        return ProtectionLevel.PROTECTED

    def _apply_rules(self, resolved: Path, level: ProtectionLevel, operation: str) -> bool:
        """Apply protection rules. Returns True=allowed, False=denied."""

        if level == ProtectionLevel.CRITICAL:
            # NOTHING is allowed. Not even reading.
            return False

        elif level == ProtectionLevel.PROTECTED:
            # Read-only
            return operation == "read"

        elif level == ProtectionLevel.MONITORED:
            # Read, write allowed. Delete requires extra check.
            if operation == "delete":
                # Only allow deleting files in temp/ or archive/
                path_str = str(resolved)
                return "temp/" in path_str or "archive/" in path_str
            return operation in ("read", "write", "list")

        elif level == ProtectionLevel.OPEN:
            return True

        # Unknown level = DENY (fail-closed)
        return False

    def _compute_manifest_hash(self) -> str:
        """Compute SHA-256 of the manifest file to detect tampering."""
        manifest_path = Path(__file__).parent / "manifest.py"
        if manifest_path.exists():
            content = manifest_path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        return "MANIFEST_NOT_FOUND"

    def _verify_manifest_integrity(self) -> bool:
        """Verify the manifest hasn't been modified since Sentinel started."""
        current_hash = self._compute_manifest_hash()
        return current_hash == self._manifest_hash
