"""TDD RED: Verify ZONE_1_PATHS, ZONE_2_PATHS, ZONE_2_DESCRIPTIONS exist in manifest.py."""
from __future__ import annotations

import pytest


def test_zone1_paths_exists():
    from sci_fi_dashboard.sbs.sentinel.manifest import ZONE_1_PATHS  # noqa: F401

    assert isinstance(ZONE_1_PATHS, frozenset)


def test_zone2_paths_exists():
    from sci_fi_dashboard.sbs.sentinel.manifest import ZONE_2_PATHS  # noqa: F401

    assert isinstance(ZONE_2_PATHS, tuple)


def test_zone2_descriptions_exists():
    from sci_fi_dashboard.sbs.sentinel.manifest import ZONE_2_DESCRIPTIONS  # noqa: F401

    assert isinstance(ZONE_2_DESCRIPTIONS, dict)
