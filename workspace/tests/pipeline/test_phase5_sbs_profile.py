"""
test_phase5_sbs_profile.py — Phase 5: ProfileManager unit tests.

Tests cover:
  1.  Default layer values are correct after fresh init
  2.  All 8 LAYERS are present in load_full_profile()
  3.  core_identity is immutable (raises PermissionError on save_layer)
  4.  save_layer persists across separate ProfileManager instances
  5.  snapshot_version() returns incrementing integers
  6.  rollback_to() restores a previously snapshotted layer value
  7.  Archive prune keeps at most max_versions snapshots
  8.  vocabulary layer accumulates custom entries
  9.  Two ProfileManagers with different dirs are fully isolated
  10. rollback_to() preserves core_identity (immutability survives rollback)

Run:
    cd workspace && pytest tests/pipeline/test_phase5_sbs_profile.py -v
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_WORKSPACE = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _p in (_WORKSPACE, os.path.dirname(_WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402
from sci_fi_dashboard.sbs.profile.manager import ProfileManager  # noqa: E402

# ===========================================================================
# Test 1 — Default layer returns expected structure and values
# ===========================================================================


def test_load_layer_returns_defaults(pipeline_profile_manager):
    """linguistic layer must contain current_style with the default banglish_ratio."""
    pm = pipeline_profile_manager
    layer = pm.load_layer("linguistic")

    assert isinstance(layer, dict)
    assert "current_style" in layer, f"Expected 'current_style' key, got: {list(layer.keys())}"
    assert (
        layer["current_style"]["banglish_ratio"] == 0.3
    ), f"Default banglish_ratio must be 0.3, got: {layer['current_style']['banglish_ratio']}"


# ===========================================================================
# Test 2 — All 8 layers present in load_full_profile()
# ===========================================================================


def test_all_8_layers_present(pipeline_profile_manager):
    """load_full_profile() must return exactly the 8 canonical LAYERS."""
    pm = pipeline_profile_manager
    profile = pm.load_full_profile()

    assert set(profile.keys()) == set(
        pm.LAYERS
    ), f"Expected keys {pm.LAYERS}, got: {list(profile.keys())}"
    assert len(profile) == 8, f"Expected 8 layers, got: {len(profile)}"


# ===========================================================================
# Test 3 — core_identity is immutable
# ===========================================================================


def test_core_identity_immutable(pipeline_profile_manager):
    """save_layer('core_identity', ...) must raise PermissionError."""
    pm = pipeline_profile_manager

    with pytest.raises(PermissionError):
        pm.save_layer("core_identity", {"assistant_name": "Hacked"})


# ===========================================================================
# Test 4 — save_layer persists across fresh ProfileManager instances
# ===========================================================================


def test_save_and_reload_layer(pipeline_profile_manager, pipeline_profile_dir):
    """Changes saved via save_layer must be readable by a new ProfileManager on the same dir."""
    pm = pipeline_profile_manager
    pm.save_layer(
        "emotional_state",
        {
            "current_dominant_mood": "excited",
            "mood_history": [],
            "current_sentiment_avg": 0.8,
            "last_updated": None,
        },
    )

    # Create a second manager pointing at the same directory
    pm2 = ProfileManager(profile_dir=pipeline_profile_dir)
    layer = pm2.load_layer("emotional_state")

    assert (
        layer["current_dominant_mood"] == "excited"
    ), f"Persisted value must survive a new ProfileManager. Got: {layer['current_dominant_mood']}"


# ===========================================================================
# Test 5 — snapshot_version() increments on each call
# ===========================================================================


def test_snapshot_version_increments(pipeline_profile_manager):
    """Each call to snapshot_version() must return the previous value + 1."""
    pm = pipeline_profile_manager
    v1 = pm.snapshot_version()
    v2 = pm.snapshot_version()

    assert v2 == v1 + 1, f"Second snapshot version ({v2}) must equal first ({v1}) + 1"


# ===========================================================================
# Test 6 — rollback_to() restores an earlier layer value
# ===========================================================================


def test_rollback_to_version(pipeline_profile_manager):
    """rollback_to(v) must restore the profile state captured at version v."""
    pm = pipeline_profile_manager

    # Set linguistic to state A
    state_a = {
        "current_style": {"banglish_ratio": 0.1, "avg_message_length": 10, "emoji_frequency": 0.0},
        "style_history": [],
        "last_updated": "state_a",
    }
    pm.save_layer("linguistic", state_a)
    v = pm.snapshot_version()

    # Mutate to state B
    state_b = {
        "current_style": {"banglish_ratio": 0.9, "avg_message_length": 50, "emoji_frequency": 0.5},
        "style_history": [],
        "last_updated": "state_b",
    }
    pm.save_layer("linguistic", state_b)

    # Verify state B is active
    live = pm.load_layer("linguistic")
    assert live["current_style"]["banglish_ratio"] == 0.9, "Pre-rollback: state B must be active"

    # Rollback and verify state A is restored
    pm.rollback_to(v)
    restored = pm.load_layer("linguistic")
    assert (
        restored["current_style"]["banglish_ratio"] == 0.1
    ), f"After rollback banglish_ratio must be 0.1 (state A), got: {restored['current_style']['banglish_ratio']}"


# ===========================================================================
# Test 7 — Archive prune keeps at most max_versions snapshots
# ===========================================================================


def test_max_versions_enforced(pipeline_profile_dir):
    """Creating 35 snapshots on a manager with max_versions=30 must prune to 30."""
    pm = ProfileManager(profile_dir=pipeline_profile_dir, max_versions=30)

    for i in range(35):
        pm.save_layer(
            "meta",
            {
                "total_messages_processed": i,
                "batch_run_count": 0,
                "last_batch_run": None,
                "current_version": i,
                "schema_version": "2.0",
                "created_at": "2026-01-01",
            },
        )
        pm.snapshot_version()

    archive_dirs = list(pm.archive_dir.iterdir())
    assert (
        len(archive_dirs) <= 30
    ), f"Archive must not exceed max_versions=30, but found {len(archive_dirs)} snapshots"


# ===========================================================================
# Test 8 — vocabulary layer accepts and persists custom entries
# ===========================================================================


def test_vocabulary_layer_accumulates(pipeline_profile_manager):
    """Custom vocabulary entries must survive a save/load round-trip."""
    pm = pipeline_profile_manager

    existing = pm.load_layer("vocabulary")
    existing["registry"]["hello"] = 5
    existing["total_unique_words"] = 1
    pm.save_layer("vocabulary", existing)

    loaded = pm.load_layer("vocabulary")
    assert (
        loaded["registry"]["hello"] == 5
    ), f"vocabulary['registry']['hello'] must be 5, got: {loaded['registry'].get('hello')}"
    assert (
        loaded["total_unique_words"] == 1
    ), f"total_unique_words must be 1, got: {loaded['total_unique_words']}"


# ===========================================================================
# Test 9 — Two ProfileManagers in different dirs are isolated
# ===========================================================================


def test_profile_isolated_per_target(pipeline_profile_dir):
    """ProfileManagers at different paths must not share state."""
    dir_a = pipeline_profile_dir / "creator"
    dir_b = pipeline_profile_dir / "partner"

    pm_a = ProfileManager(profile_dir=dir_a)
    pm_b = ProfileManager(profile_dir=dir_b)

    pm_a.save_layer(
        "linguistic",
        {
            "current_style": {
                "banglish_ratio": 0.3,
                "avg_message_length": 15,
                "emoji_frequency": 0.1,
            },
            "style_history": [],
            "last_updated": "a_val",
        },
    )
    pm_b.save_layer(
        "linguistic",
        {
            "current_style": {
                "banglish_ratio": 0.3,
                "avg_message_length": 15,
                "emoji_frequency": 0.1,
            },
            "style_history": [],
            "last_updated": "b_val",
        },
    )

    a_layer = pm_a.load_layer("linguistic")
    b_layer = pm_b.load_layer("linguistic")

    assert (
        a_layer["last_updated"] == "a_val"
    ), f"pm_a should have 'a_val', got: {a_layer['last_updated']!r}"
    assert (
        b_layer["last_updated"] == "b_val"
    ), f"pm_b should have 'b_val', got: {b_layer['last_updated']!r}"
    assert (
        a_layer["last_updated"] != b_layer["last_updated"]
    ), "Two isolated ProfileManagers must not share state"


# ===========================================================================
# Test 10 — rollback_to() preserves core_identity (immutability survives rollback)
# ===========================================================================


def test_rollback_preserves_core_identity(pipeline_profile_manager):
    """core_identity must be unchanged after rollback_to() because it is immutable."""
    pm = pipeline_profile_manager

    # Read the current core_identity before any snapshot
    original_core = pm.load_layer("core_identity")

    # Take a snapshot (state A)
    v = pm.snapshot_version()

    # Rollback to that version
    pm.rollback_to(v)

    # core_identity must be preserved
    restored_core = pm.load_layer("core_identity")
    assert restored_core["assistant_name"] == original_core["assistant_name"], (
        f"core_identity.assistant_name must survive rollback. "
        f"Expected: {original_core['assistant_name']!r}, got: {restored_core['assistant_name']!r}"
    )
    assert (
        restored_core == original_core
    ), "core_identity must be byte-for-byte identical before and after rollback"
