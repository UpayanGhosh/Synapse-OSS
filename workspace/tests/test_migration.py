"""
test_migration.py — Integration tests for migrate_openclaw.py

Tests CONF-06 (safe WAL migration: checkpoint + copy + checksum + rowcount + manifest)
and CONF-07 (SBS profiles migration and data integrity).

All tests use real SQLite databases created in pytest tmp_path directories.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.migrate_openclaw import DATABASES, migrate


def _create_source(root: Path) -> None:
    """Create a fake ~/.openclaw/ layout with real SQLite databases."""
    db_dir = root / "workspace" / "db"
    db_dir.mkdir(parents=True)
    for db_name in DATABASES:
        conn = sqlite3.connect(str(db_dir / db_name))
        conn.execute("CREATE TABLE test_items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO test_items (value) VALUES (?)", [("a",), ("b",), ("c",)])
        conn.commit()
        conn.close()
    sbs_dir = root / "workspace" / "sci_fi_dashboard" / "synapse_data"
    sbs_dir.mkdir(parents=True)
    (sbs_dir / "core_identity.json").write_text('{"name": "Synapse"}')


def test_migrate_copies_all_databases(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    migrate(source, dest)
    for db_name in DATABASES:
        assert (dest / "workspace" / "db" / db_name).exists(), f"{db_name} missing from dest"


def test_migrate_row_counts_match(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    migrate(source, dest)
    for db_name in DATABASES:
        src_conn = sqlite3.connect(str(source / "workspace" / "db" / db_name))
        dst_conn = sqlite3.connect(str(dest / "workspace" / "db" / db_name))
        try:
            src_count = src_conn.execute("SELECT count(*) FROM test_items").fetchone()[0]
            dst_count = dst_conn.execute("SELECT count(*) FROM test_items").fetchone()[0]
            assert src_count == dst_count == 3
        finally:
            src_conn.close()
            dst_conn.close()


def test_migrate_sbs_profiles_copied(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    migrate(source, dest)
    assert (
        dest / "workspace" / "sci_fi_dashboard" / "synapse_data" / "core_identity.json"
    ).exists()


def test_migrate_writes_manifest(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    migrate(source, dest)
    manifest_path = dest / "migration_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert str(source) in manifest["source"]
    assert str(dest) in manifest["dest"]
    assert len(manifest["databases"]) > 0
    assert all(
        "file" in entry and "src_hash" in entry and "dst_hash" in entry
        for entry in manifest["databases"]
    )


def test_migrate_source_untouched(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    # Record row counts before migration
    pre_counts = {}
    for db_name in DATABASES:
        conn = sqlite3.connect(str(source / "workspace" / "db" / db_name))
        pre_counts[db_name] = conn.execute("SELECT count(*) FROM test_items").fetchone()[0]
        conn.close()
    migrate(source, dest)
    # Verify source is unchanged
    for db_name in DATABASES:
        conn = sqlite3.connect(str(source / "workspace" / "db" / db_name))
        count = conn.execute("SELECT count(*) FROM test_items").fetchone()[0]
        conn.close()
        assert count == pre_counts[db_name]


def test_migrate_dry_run_no_dest_written(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    result = migrate(source, dest, dry_run=True)
    assert not (dest / "workspace" / "db" / "memory.db").exists()
    assert result["dry_run"] is True


def test_migrate_port_8000_guard(tmp_path, monkeypatch):
    import scripts.migrate_openclaw as mod

    monkeypatch.setattr(mod, "_port_open", lambda port: True)
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _create_source(source)
    with pytest.raises(RuntimeError, match="port 8000"):
        migrate(source, dest)


def test_migrate_missing_source_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        migrate(tmp_path / "nonexistent_source", tmp_path / "dest")
