"""
Test Suite: SBS Sentinel — File Access Governance
==================================================
Tests for the Sentinel gateway, manifest, audit logger, and agent tool wrappers.

Covers:
- Path traversal prevention
- Protection level classification (CRITICAL, PROTECTED, MONITORED, OPEN)
- Access rule enforcement (FAIL-CLOSED)
- Atomic safe_write via tempfile + os.replace
- safe_read, safe_delete, safe_list
- Forbidden operations validator
- Manifest integrity self-check
- Agent tool wrappers (init, read, write, delete, list, check_access)
- AuditLogger append-only JSONL
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sbs.sentinel.audit import AuditLogger
from sci_fi_dashboard.sbs.sentinel.gateway import Sentinel, SentinelError
from sci_fi_dashboard.sbs.sentinel.manifest import (
    CRITICAL_DIRECTORIES,
    CRITICAL_FILES,
    FORBIDDEN_OPERATIONS,
    WRITABLE_ZONES,
    ProtectionLevel,
)

# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class TestAuditLogger:
    """Tests for the append-only audit trail."""

    @pytest.fixture
    def audit(self, tmp_path):
        return AuditLogger(tmp_path / "audit")

    @pytest.mark.unit
    def test_log_access_writes_jsonl(self, audit):
        """log_access should write a valid JSONL entry."""
        audit.log_access("/tmp/file.txt", "read", "monitored", "test context")
        lines = audit.log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["decision"] == "ALLOWED"
        assert entry["path"] == "/tmp/file.txt"
        assert entry["operation"] == "read"

    @pytest.mark.unit
    def test_log_denial_writes_jsonl(self, audit):
        """log_denial should write a DENIED entry."""
        audit.log_denial("/etc/passwd", "read", "path traversal")
        lines = audit.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["decision"] == "DENIED"
        assert "path traversal" in entry["reason"]

    @pytest.mark.unit
    def test_log_event_writes_jsonl(self, audit):
        """log_event should write a system event entry."""
        audit.log_event("SENTINEL_INIT", {"project_root": "/test"})
        lines = audit.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["event_type"] == "SENTINEL_INIT"
        assert entry["details"]["project_root"] == "/test"

    @pytest.mark.unit
    def test_multiple_logs_append(self, audit):
        """Multiple log calls should append, not overwrite."""
        audit.log_access("a", "read", "open", "")
        audit.log_access("b", "read", "open", "")
        audit.log_denial("c", "write", "denied")
        lines = audit.log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    @pytest.mark.unit
    def test_audit_dir_created(self, tmp_path):
        """AuditLogger should create the audit directory if it doesn't exist."""
        audit_dir = tmp_path / "deep" / "nested" / "audit"
        AuditLogger(audit_dir)
        assert audit_dir.exists()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    """Tests for the manifest configuration."""

    @pytest.mark.unit
    def test_protection_levels_enum(self):
        """ProtectionLevel enum should have all 4 levels."""
        assert ProtectionLevel.CRITICAL.value == "critical"
        assert ProtectionLevel.PROTECTED.value == "protected"
        assert ProtectionLevel.MONITORED.value == "monitored"
        assert ProtectionLevel.OPEN.value == "open"

    @pytest.mark.unit
    def test_critical_files_contains_key_entries(self):
        """CRITICAL_FILES should contain api_gateway.py and sentinel files."""
        assert "api_gateway.py" in CRITICAL_FILES
        assert "sbs/sentinel/gateway.py" in CRITICAL_FILES
        assert "sbs/sentinel/manifest.py" in CRITICAL_FILES
        assert ".env" in CRITICAL_FILES

    @pytest.mark.unit
    def test_critical_directories_contains_sentinel(self):
        """CRITICAL_DIRECTORIES should include sentinel/ and .git/."""
        assert "sbs/sentinel/" in CRITICAL_DIRECTORIES
        assert ".git/" in CRITICAL_DIRECTORIES

    @pytest.mark.unit
    def test_forbidden_operations_contains_dangerous_ops(self):
        """FORBIDDEN_OPERATIONS should include dangerous patterns."""
        assert "rmtree" in FORBIDDEN_OPERATIONS
        assert "os.system" in FORBIDDEN_OPERATIONS
        assert "exec" in FORBIDDEN_OPERATIONS
        assert "eval" in FORBIDDEN_OPERATIONS

    @pytest.mark.unit
    def test_writable_zones_contains_data_dirs(self):
        """WRITABLE_ZONES should include data/ subdirectories."""
        assert "data/raw/" in WRITABLE_ZONES
        assert "data/indices/" in WRITABLE_ZONES
        assert "data/temp/" in WRITABLE_ZONES


# ---------------------------------------------------------------------------
# Sentinel Gateway
# ---------------------------------------------------------------------------


class TestSentinel:
    """Tests for the Sentinel file access governance gateway."""

    @pytest.fixture
    def sentinel_env(self, tmp_path):
        """Create a Sentinel with a project root containing writable zones."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        # Create some directories that match WRITABLE_ZONES
        (project_root / "data" / "raw").mkdir(parents=True)
        (project_root / "data" / "indices").mkdir(parents=True)
        (project_root / "data" / "temp").mkdir(parents=True)
        (project_root / "data" / "profiles" / "current").mkdir(parents=True)
        (project_root / "generated").mkdir(parents=True)
        (project_root / "logs").mkdir(parents=True)

        sentinel = Sentinel(project_root)
        return sentinel, project_root

    @pytest.mark.unit
    def test_init_creates_audit_log(self, sentinel_env):
        """Sentinel init should create an audit directory and log the init event."""
        sentinel, project_root = sentinel_env
        audit_path = project_root / "logs" / "sentinel" / "sentinel_audit.jsonl"
        assert audit_path.exists()

    @pytest.mark.unit
    def test_path_traversal_denied(self, sentinel_env):
        """Paths escaping the project root should be denied."""
        sentinel, project_root = sentinel_env
        with pytest.raises(SentinelError, match="escapes project boundary"):
            sentinel.check_access("../../etc/passwd", "read")

    @pytest.mark.unit
    def test_null_byte_in_path_denied(self, sentinel_env):
        """Paths with null bytes should be rejected."""
        sentinel, _ = sentinel_env
        with pytest.raises(SentinelError, match="Invalid path"):
            sentinel.check_access("data/raw/file\x00.txt", "read")

    @pytest.mark.unit
    def test_critical_file_all_ops_denied(self, sentinel_env):
        """CRITICAL files should deny all operations, even read."""
        sentinel, project_root = sentinel_env
        # Create the critical file
        api_gw = project_root / "api_gateway.py"
        api_gw.write_text("app = FastAPI()")

        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("api_gateway.py", "read")

        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("api_gateway.py", "write")

    @pytest.mark.unit
    def test_protected_file_read_allowed(self, sentinel_env):
        """PROTECTED files should allow read but deny write."""
        sentinel, project_root = sentinel_env
        # Create a protected file path
        (project_root / "sbs" / "ingestion").mkdir(parents=True)
        schema_file = project_root / "sbs" / "ingestion" / "schema.py"
        schema_file.write_text("class RawMessage: pass")

        # Read should succeed
        resolved = sentinel.check_access("sbs/ingestion/schema.py", "read")
        assert resolved.exists()

        # Write should fail
        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("sbs/ingestion/schema.py", "write")

    @pytest.mark.unit
    def test_monitored_zone_read_write_allowed(self, sentinel_env):
        """MONITORED (writable) zone should allow read and write."""
        sentinel, project_root = sentinel_env
        test_file = project_root / "data" / "raw" / "test.jsonl"
        test_file.write_text("{}")

        # Read allowed
        resolved = sentinel.check_access("data/raw/test.jsonl", "read")
        assert resolved.exists()

        # Write allowed
        resolved = sentinel.check_access("data/raw/test.jsonl", "write")
        assert resolved is not None

    @pytest.mark.unit
    def test_monitored_zone_delete_restricted(self, sentinel_env):
        """Delete in monitored zone only allowed for temp/ or archive/ paths."""
        sentinel, project_root = sentinel_env
        # Delete from temp should work
        temp_file = project_root / "data" / "temp" / "scratch.txt"
        temp_file.write_text("temp data")
        resolved = sentinel.check_access("data/temp/scratch.txt", "delete")
        assert resolved is not None

        # Delete from raw should be denied
        raw_file = project_root / "data" / "raw" / "important.jsonl"
        raw_file.write_text("{}")
        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("data/raw/important.jsonl", "delete")

    @pytest.mark.unit
    def test_default_classification_is_protected(self, sentinel_env):
        """Paths not in any explicit zone default to PROTECTED (fail-closed)."""
        sentinel, project_root = sentinel_env
        # Create a file outside known zones
        unknown_file = project_root / "random_script.py"
        unknown_file.write_text("print('hello')")

        # Read should work (PROTECTED = read-only)
        sentinel.check_access("random_script.py", "read")

        # Write should fail
        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("random_script.py", "write")

    @pytest.mark.unit
    def test_safe_read_returns_content(self, sentinel_env):
        """safe_read should return file content for allowed paths."""
        sentinel, project_root = sentinel_env
        test_file = project_root / "data" / "raw" / "readable.txt"
        test_file.write_text("Hello, Sentinel!")

        content = sentinel.safe_read("data/raw/readable.txt")
        assert content == "Hello, Sentinel!"

    @pytest.mark.unit
    def test_safe_write_atomic(self, sentinel_env):
        """safe_write should atomically write content."""
        sentinel, project_root = sentinel_env

        result = sentinel.safe_write(
            "data/raw/output.txt",
            "Atomic content",
            "test write",
        )
        assert result is True

        written = (project_root / "data" / "raw" / "output.txt").read_text(encoding="utf-8")
        assert written == "Atomic content"

    @pytest.mark.unit
    def test_safe_write_creates_parent_dirs(self, sentinel_env):
        """safe_write should create parent directories if needed."""
        sentinel, project_root = sentinel_env
        result = sentinel.safe_write(
            "data/raw/subdir/deep/file.txt",
            "nested content",
        )
        assert result is True
        assert (project_root / "data" / "raw" / "subdir" / "deep" / "file.txt").exists()

    @pytest.mark.unit
    def test_safe_delete(self, sentinel_env):
        """safe_delete should remove file for allowed paths."""
        sentinel, project_root = sentinel_env
        temp_file = project_root / "data" / "temp" / "deleteme.txt"
        temp_file.write_text("delete me")

        result = sentinel.safe_delete("data/temp/deleteme.txt")
        assert result is True
        assert not temp_file.exists()

    @pytest.mark.unit
    def test_safe_list(self, sentinel_env):
        """safe_list should return sorted entry names."""
        sentinel, project_root = sentinel_env
        raw_dir = project_root / "data" / "raw"
        (raw_dir / "b.txt").write_text("b")
        (raw_dir / "a.txt").write_text("a")
        (raw_dir / "c.txt").write_text("c")

        entries = sentinel.safe_list("data/raw")
        assert entries == ["a.txt", "b.txt", "c.txt"]

    @pytest.mark.unit
    def test_safe_list_not_directory_raises(self, sentinel_env):
        """safe_list on a file should raise SentinelError."""
        sentinel, project_root = sentinel_env
        file_path = project_root / "data" / "raw" / "notdir.txt"
        file_path.write_text("not a dir")

        with pytest.raises(SentinelError, match="Not a directory"):
            sentinel.safe_list("data/raw/notdir.txt")

    @pytest.mark.unit
    def test_validate_operation_string_forbidden(self, sentinel_env):
        """validate_operation_string should reject forbidden patterns."""
        sentinel, _ = sentinel_env
        with pytest.raises(SentinelError, match="OPERATION DENIED"):
            sentinel.validate_operation_string("shutil.rmtree('/tmp')")

        with pytest.raises(SentinelError, match="OPERATION DENIED"):
            sentinel.validate_operation_string("os.system('rm -rf /')")

        with pytest.raises(SentinelError, match="OPERATION DENIED"):
            sentinel.validate_operation_string("eval(user_input)")

    @pytest.mark.unit
    def test_validate_operation_string_allowed(self, sentinel_env):
        """validate_operation_string should allow safe operations."""
        sentinel, _ = sentinel_env
        assert sentinel.validate_operation_string("open('file.txt', 'r')") is True
        assert sentinel.validate_operation_string("json.dumps(data)") is True

    @pytest.mark.unit
    def test_manifest_integrity_check(self, sentinel_env):
        """Manifest hash should match on repeated checks."""
        sentinel, _ = sentinel_env
        assert sentinel._verify_manifest_integrity() is True

    @pytest.mark.unit
    def test_manifest_tampering_blocks_all_access(self, sentinel_env):
        """If manifest hash changes, all operations should be denied."""
        sentinel, project_root = sentinel_env
        # Corrupt the stored hash
        sentinel._manifest_hash = "tampered_hash_value"

        with pytest.raises(SentinelError, match="manifest integrity"):
            sentinel.check_access("data/raw/anything.txt", "read")

    @pytest.mark.unit
    def test_critical_directory_blocks_contents(self, sentinel_env):
        """Files inside CRITICAL_DIRECTORIES should be classified as CRITICAL."""
        sentinel, project_root = sentinel_env
        (project_root / "sbs" / "sentinel").mkdir(parents=True, exist_ok=True)
        secret = project_root / "sbs" / "sentinel" / "secret.py"
        secret.write_text("SECRET = 'dont touch'")

        with pytest.raises(SentinelError, match="ACCESS DENIED"):
            sentinel.check_access("sbs/sentinel/secret.py", "read")


# ---------------------------------------------------------------------------
# Agent Tool Wrappers
# ---------------------------------------------------------------------------


class TestAgentTools:
    """Tests for sbs/sentinel/tools.py agent wrappers."""

    @pytest.mark.unit
    def test_init_sentinel_sets_global(self, tmp_path):
        """init_sentinel should set the global _sentinel variable."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "logs" / "sentinel").mkdir(parents=True)

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            assert tools_mod._sentinel is not None
            assert isinstance(tools_mod._sentinel, Sentinel)
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_read_without_init_raises(self):
        """agent_read_file should raise RuntimeError if sentinel not initialized."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        old = tools_mod._sentinel
        try:
            tools_mod._sentinel = None
            with pytest.raises(RuntimeError, match="not initialized"):
                tools_mod.agent_read_file("/tmp/test.txt")
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_write_without_init_raises(self):
        """agent_write_file should raise RuntimeError if sentinel not initialized."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        old = tools_mod._sentinel
        try:
            tools_mod._sentinel = None
            with pytest.raises(RuntimeError, match="not initialized"):
                tools_mod.agent_write_file("/tmp/test.txt", "content")
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_delete_without_init_raises(self):
        """agent_delete_file should raise RuntimeError if sentinel not initialized."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        old = tools_mod._sentinel
        try:
            tools_mod._sentinel = None
            with pytest.raises(RuntimeError, match="not initialized"):
                tools_mod.agent_delete_file("/tmp/test.txt")
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_read_file_success(self, tmp_path):
        """agent_read_file should return content for readable paths."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "data" / "raw").mkdir(parents=True)
        test_file = project_root / "data" / "raw" / "readable.txt"
        test_file.write_text("file content here")

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            result = tools_mod.agent_read_file("data/raw/readable.txt")
            assert result == "file content here"
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_read_file_denied_returns_message(self, tmp_path):
        """agent_read_file on a critical file should return SENTINEL DENIED message."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "api_gateway.py").write_text("app = FastAPI()")

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            result = tools_mod.agent_read_file("api_gateway.py")
            assert "[SENTINEL DENIED]" in result
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_write_file_success(self, tmp_path):
        """agent_write_file should write and return SUCCESS for writable paths."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "data" / "raw").mkdir(parents=True)

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            result = tools_mod.agent_write_file("data/raw/output.txt", "written content")
            assert "[SUCCESS]" in result
            assert (project_root / "data" / "raw" / "output.txt").read_text() == "written content"
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_check_write_access_returns_path(self, tmp_path):
        """agent_check_write_access should return a Path for writable zones."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "data" / "raw").mkdir(parents=True)

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            result = tools_mod.agent_check_write_access("data/raw/new.txt")
            assert isinstance(result, Path)
        finally:
            tools_mod._sentinel = old

    @pytest.mark.unit
    def test_agent_list_directory_success(self, tmp_path):
        """agent_list_directory should return newline-separated file names."""
        import sci_fi_dashboard.sbs.sentinel.tools as tools_mod

        project_root = tmp_path / "project"
        project_root.mkdir()
        raw_dir = project_root / "data" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "a.txt").write_text("a")
        (raw_dir / "b.txt").write_text("b")

        old = tools_mod._sentinel
        try:
            tools_mod.init_sentinel(project_root)
            result = tools_mod.agent_list_directory("data/raw")
            assert "a.txt" in result
            assert "b.txt" in result
        finally:
            tools_mod._sentinel = old
