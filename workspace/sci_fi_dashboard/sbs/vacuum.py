import argparse
import shutil
import sqlite3
from pathlib import Path


def vacuum_sbs(data_dir: str = "./data", retain_days: int = 30, keep_versions: int = 10):
    """
    Maintenance task to keep SBS performant.
    1. Vacuums SQLite database to reclaim space
    2. Moves old raw JSONL records to cold storage (optional/future)
    3. Prunes old profile versions beyond the `keep_versions` limit.
    """
    print(f"[CLEAN] Starting SBS Vacuum (Retain: {retain_days} days, Keep Versions: {keep_versions})")

    data_path = Path(data_dir)
    db_path = data_path / "indices" / "messages.db"
    profiles_archive = data_path / "profiles" / "archive"

    if not db_path.exists():
        print("[WARN] No SQLite database found.")
        return

    # 1. Vacuum SQLite
    print("[PKG] Rebuilding SQLite indices and reclaiming space...")
    with sqlite3.connect(db_path) as conn:
        before_size = db_path.stat().st_size
        # SQLite VACUUM physically reconstructs the database file
        conn.execute("VACUUM")
        after_size = db_path.stat().st_size

        saved = (before_size - after_size) / 1024
        print(f"   Done. Saved: {saved:.1f} KB")

    # 2. Prune old profile archives
    if profiles_archive.exists():
        versions = sorted(
            [d for d in profiles_archive.iterdir() if d.is_dir()], key=lambda x: x.name
        )

        if len(versions) > keep_versions:
            to_delete = versions[:-keep_versions]
            print(f"[DEL] Pruning {len(to_delete)} old profile versions...")

            for v_dir in to_delete:
                shutil.rmtree(v_dir)
                print(f"   Deleted: {v_dir.name}")
        else:
            print(f"[OK] Profile archive healthy ({len(versions)} versions).")

    print("[SPARK] Vacuum complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SBS Maintenance Vacuum")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./synapse_data/the_creator",
        help="Path to SBS data directory",
    )
    parser.add_argument(
        "--retain", type=int, default=30, help="Days of logs to keep in active DB (N/A yet)"
    )
    parser.add_argument("--keep", type=int, default=10, help="Number of profile versions to keep")

    args = parser.parse_args()
    vacuum_sbs(data_dir=args.data_dir, retain_days=args.retain, keep_versions=args.keep)
