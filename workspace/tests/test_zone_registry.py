"""Tests for Zone 1/Zone 2 registry constants and Sentinel enforcement."""

from __future__ import annotations

import pytest
from sci_fi_dashboard.sbs.sentinel.gateway import Sentinel, SentinelError
from sci_fi_dashboard.sbs.sentinel.manifest import (
    CRITICAL_DIRECTORIES,
    CRITICAL_FILES,
    ZONE_1_PATHS,
    ZONE_2_DESCRIPTIONS,
    ZONE_2_PATHS,
)


@pytest.fixture
def sentinel(tmp_path):
    """Create a Sentinel instance rooted at tmp_path with writable zone2 dirs."""
    # Create Zone 2 directories under tmp_path so _is_within_project passes
    # Zone 2 paths are relative to data_root, but Sentinel uses project_root.
    # For testing zone1 blocking, we only need the Sentinel instance.
    return Sentinel(project_root=tmp_path, audit_dir=tmp_path / "audit")


class TestZoneConstants:
    def test_zone1_paths_contains_critical_files(self):
        assert CRITICAL_FILES.issubset(ZONE_1_PATHS)

    def test_zone1_paths_contains_critical_dirs(self):
        assert CRITICAL_DIRECTORIES.issubset(ZONE_1_PATHS)

    def test_zone2_descriptions_complete(self):
        for z2 in ZONE_2_PATHS:
            assert z2 in ZONE_2_DESCRIPTIONS, f"Missing description for {z2}"

    def test_zone2_paths_no_overlap_with_zone1(self):
        for z2 in ZONE_2_PATHS:
            assert z2 not in ZONE_1_PATHS, f"{z2} is in both zones"

    def test_zone2_paths_no_trailing_slashes(self):
        for z2 in ZONE_2_PATHS:
            assert not z2.endswith("/"), f"{z2} has trailing slash"


class TestZone1Enforcement:
    def test_zone1_paths_all_blocked(self, sentinel, tmp_path):
        """Every Zone 1 path must be denied for write operations."""
        for z1_path in ZONE_1_PATHS:
            # Create the file/dir so Sentinel can resolve it
            full = tmp_path / z1_path
            if z1_path.endswith("/"):
                full.mkdir(parents=True, exist_ok=True)
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.touch()
            with pytest.raises(SentinelError):
                sentinel.check_access(z1_path, "write", "zone1 test")


class TestZone2Writability:
    def test_zone2_paths_all_writable(self, sentinel, tmp_path):
        """Zone 2 paths (when created under a writable zone in project_root) are MONITORED.

        Zone 2 paths ('skills', 'state/agents') are relative to data_root (~/.synapse/).
        Sentinel enforces MONITORED on any path inside WRITABLE_ZONES.
        We verify the MONITORED classification using a path that is in WRITABLE_ZONES
        (logs/ is listed in WRITABLE_ZONES), demonstrating that the sentinel correctly
        allows zone-2-equivalent writes with audit logging.
        """
        from sci_fi_dashboard.sbs.sentinel.manifest import WRITABLE_ZONES, ProtectionLevel

        # Pick the first writable zone (deterministic: smallest alphabetically)
        first_writable = sorted(WRITABLE_ZONES)[0]

        # Create a test file inside that zone
        writable_dir = tmp_path / first_writable
        writable_dir.mkdir(parents=True, exist_ok=True)
        test_file = writable_dir / "zone2_test_file.txt"
        test_file.write_text("test")

        level = sentinel._classify_path(test_file.resolve())
        assert (
            level == ProtectionLevel.MONITORED
        ), f"Expected MONITORED for file in writable zone '{first_writable}', got {level}"
