"""
migrate_openclaw.py — Safe migration from ~/.openclaw/workspace/ to ~/.synapse/workspace/

Implements the verified WAL checkpoint → copy-to-staging → checksum verify → row count
verify → move-to-final → write-manifest sequence. Original source data is NEVER deleted.

Usage:
    python workspace/scripts/migrate_openclaw.py [--source ~/.openclaw] [--dest ~/.synapse] [--dry-run]

Implements requirements CONF-06 and CONF-07.
"""

import argparse
import hashlib
import json
import shutil
import socket
import sqlite3
import tempfile
import time
from pathlib import Path

DATABASES = [
    "memory.db",
    "knowledge_graph.db",
    "emotional_trajectory.db",
]


def _port_open(port: int) -> bool:
    """Return True if something is listening on 127.0.0.1:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _sha256(path: Path) -> str:
    """Return hex SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _checkpoint_and_close(db_path: Path) -> None:
    """Run PRAGMA wal_checkpoint(TRUNCATE) and raise RuntimeError if incomplete."""
    conn = sqlite3.connect(str(db_path))
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        # result = (busy, log, checkpointed)
        if result and result[0] > 0:
            raise RuntimeError(
                f"WAL checkpoint incomplete for {db_path.name}: "
                f"{result[0]} pages in WAL, only {result[1]} checkpointed. "
                f"Is another process writing to the database?"
            )
    finally:
        conn.close()


def migrate(source_root: Path, dest_root: Path, dry_run: bool = False) -> dict:
    """
    Safely migrate all data from source_root to dest_root.

    Steps:
    0. Port guard — raises RuntimeError if API gateway on port 8000 is running
    1. Collect source file triplets (.db, .db-wal, .db-shm)
    2. Initialize manifest
    3-9. Inside TemporaryDirectory:
        3. WAL checkpoint all source databases
        4. Copy triplets to staging
        5. Verify SHA-256 checksums
        6. Verify row counts
        7. Copy SBS profiles directory
        8. Return if dry_run
        9. Write to final destination
    10. Write manifest file

    Returns the manifest dict. Source data is NEVER deleted.
    """
    # Step 0 — Port guard
    if _port_open(8000):
        raise RuntimeError(
            "API gateway is running on port 8000. Stop it before migrating.\n"
            "Run: synapse_stop.sh  (or press Ctrl+C in the uvicorn terminal)"
        )

    # Step 1 — Collect source files
    source_db_dir = source_root / "workspace" / "db"
    if not source_db_dir.exists():
        raise RuntimeError(
            f"Source database directory not found: {source_db_dir}\n"
            f"Is ~/.openclaw/workspace/db/ the correct location?"
        )

    files_to_copy: list[tuple[Path, Path]] = []  # (src, staged_dst)

    # Check that at least one primary .db file exists
    found_any = False
    for db_name in DATABASES:
        if (source_db_dir / db_name).exists():
            found_any = True
            break

    if not found_any:
        raise RuntimeError(
            f"No database files found in {source_db_dir}\n"
            f"Expected: memory.db, knowledge_graph.db, or emotional_trajectory.db"
        )

    # Step 2 — Initialize manifest
    manifest: dict = {
        "source": str(source_root),
        "dest": str(dest_root),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "databases": [],
        "sbs_profiles": False,
        "dry_run": dry_run,
    }

    # Steps 3-9 are ALL inside the TemporaryDirectory context
    with tempfile.TemporaryDirectory() as staging:
        staging_path = Path(staging)
        staging_db = staging_path / "db"
        staging_db.mkdir(parents=True, exist_ok=True)

        # Build files_to_copy list (inside with-block so staging exists)
        for db_name in DATABASES:
            for suffix in ("", "-wal", "-shm"):
                src = source_db_dir / f"{db_name}{suffix}"
                if src.exists():
                    dst = staging_db / f"{db_name}{suffix}"
                    files_to_copy.append((src, dst))

        # Step 3 — WAL checkpoint
        for db_name in DATABASES:
            db_file = source_db_dir / db_name
            if db_file.exists():
                _checkpoint_and_close(db_file)

        # Step 4 — Copy to staging
        for src, dst in files_to_copy:
            shutil.copy2(str(src), str(dst))

        # Step 5 — Verify checksums
        for src, staged in files_to_copy:
            src_hash = _sha256(src)
            dst_hash = _sha256(staged)
            if src_hash != dst_hash:
                raise RuntimeError(
                    f"Checksum mismatch for {src.name}: "
                    f"source={src_hash[:12]}... staged={dst_hash[:12]}..."
                )
            manifest["databases"].append(
                {
                    "file": src.name,
                    "src_hash": src_hash,
                    "dst_hash": dst_hash,
                    "size_bytes": src.stat().st_size,
                }
            )

        # Step 6 — Verify row counts
        for db_name in DATABASES:
            src_db = source_db_dir / db_name
            staged_db_path = staging_db / db_name
            if not src_db.exists() or not staged_db_path.exists():
                continue
            src_conn = sqlite3.connect(str(src_db))
            dst_conn = sqlite3.connect(str(staged_db_path))
            try:
                tables = [
                    r[0]
                    for r in src_conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                ]
                for table in tables:
                    src_count = src_conn.execute(f"SELECT count(*) FROM [{table}]").fetchone()[0]
                    dst_count = dst_conn.execute(f"SELECT count(*) FROM [{table}]").fetchone()[0]
                    if src_count != dst_count:
                        raise RuntimeError(
                            f"Row count mismatch: {db_name}.{table} "
                            f"— source={src_count} staged={dst_count}"
                        )
            finally:
                src_conn.close()
                dst_conn.close()

        # Step 7 — SBS profiles copy
        sbs_src = source_root / "workspace" / "sci_fi_dashboard" / "synapse_data"
        if sbs_src.exists():
            sbs_staged = staging_path / "synapse_data"
            shutil.copytree(str(sbs_src), str(sbs_staged))
            manifest["sbs_profiles"] = True

        # Step 8 — Return early if dry_run (before writing to dest)
        if dry_run:
            return manifest

        # Step 9 — Write to final destination (INSIDE with-block — staging still valid)
        dest_db_dir = dest_root / "workspace" / "db"
        dest_db_dir.mkdir(parents=True, exist_ok=True)

        for src, staged in files_to_copy:
            final = dest_db_dir / staged.name
            shutil.copy2(str(staged), str(final))

        dest_sbs = dest_root / "workspace" / "sci_fi_dashboard" / "synapse_data"
        if (staging_path / "synapse_data").exists():
            if dest_sbs.exists():
                shutil.rmtree(str(dest_sbs))
            shutil.copytree(str(staging_path / "synapse_data"), str(dest_sbs))

    # Step 10 — Write manifest (OUTSIDE with-block — dest files are already written)
    manifest_path = dest_root / "migration_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(manifest_path), "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from synapse_config import SynapseConfig

    parser = argparse.ArgumentParser(description="Migrate ~/.openclaw/ data to ~/.synapse/")
    parser.add_argument(
        "--source",
        default=str(Path.home() / ".openclaw"),
        help="Source root (default: ~/.openclaw)",
    )
    parser.add_argument(
        "--dest",
        default="",
        help="Destination root (default: from SYNAPSE_HOME or ~/.synapse)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Check without writing")
    args = parser.parse_args()

    dest = Path(args.dest).expanduser() if args.dest else SynapseConfig.load().data_root
    result = migrate(Path(args.source).expanduser(), dest, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
