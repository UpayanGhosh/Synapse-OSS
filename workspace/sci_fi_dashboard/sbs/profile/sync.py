from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .manager import ProfileManager


def _load_active_user_memory_facts(db_path: Path, user_id: str) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, kind, key, value, summary, confidence, status, last_seen
            FROM user_memory_facts
            WHERE user_id = ? AND status = 'active'
            ORDER BY last_seen DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    finally:
        conn.close()
    return rows


def sync_user_memory_profile(
    profile_mgr: ProfileManager,
    *,
    user_id: str,
    db_path: str | Path,
) -> dict[str, Any]:
    """
    Sync active user_memory_facts into SBS profile layers.

    - preference/response_style -> interaction.preferred_response_style
    - identity summaries         -> domain.stable_identity_notes
    """
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return {"synced": False, "interaction_updated": False, "domain_updated": False}

    rows = _load_active_user_memory_facts(Path(db_path), clean_user_id)
    if not rows:
        return {
            "synced": False,
            "interaction_updated": False,
            "domain_updated": False,
            "active_facts": 0,
        }

    interaction = profile_mgr.load_layer("interaction")
    domain = profile_mgr.load_layer("domain")

    interaction_updated = False
    domain_updated = False

    # Unique key by (kind, key). Query order prefers most-recent values.
    latest: dict[tuple[str, str], sqlite3.Row] = {}
    identity_notes: list[str] = []
    for row in rows:
        kind = str(row["kind"] or "").strip()
        key = str(row["key"] or "").strip()
        latest.setdefault((kind, key), row)
        if kind == "identity":
            summary = str(row["summary"] or "").strip()
            if summary and summary not in identity_notes:
                identity_notes.append(summary)

    style_row = latest.get(("preference", "response_style"))
    if style_row is not None:
        preferred_response_style = str(style_row["value"] or "").strip()
        if preferred_response_style and interaction.get(
            "preferred_response_style"
        ) != preferred_response_style:
            interaction["preferred_response_style"] = preferred_response_style
            interaction_updated = True

    if identity_notes and domain.get("stable_identity_notes") != identity_notes:
        domain["stable_identity_notes"] = identity_notes
        domain_updated = True

    if interaction_updated:
        profile_mgr.save_layer("interaction", interaction)
    if domain_updated:
        profile_mgr.save_layer("domain", domain)

    return {
        "synced": interaction_updated or domain_updated,
        "interaction_updated": interaction_updated,
        "domain_updated": domain_updated,
        "active_facts": len(rows),
    }
