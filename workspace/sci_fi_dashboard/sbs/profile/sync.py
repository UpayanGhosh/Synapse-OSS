from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .manager import ProfileManager

_INTERACTION_STYLE_KEY = "preferred_response_style"
_INTERACTION_ROUTINES_KEY = "stable_routines"
_INTERACTION_CORRECTIONS_KEY = "correction_rules"
_DOMAIN_IDENTITY_NOTES_KEY = "stable_identity_notes"
_DOMAIN_PEOPLE_KEY = "important_people"
_DOMAIN_PROJECTS_KEY = "important_projects"

_DYNAMIC_BEGIN = "<!-- SYNAPSE:DYNAMIC_USER_PROFILE:BEGIN -->"
_DYNAMIC_END = "<!-- SYNAPSE:DYNAMIC_USER_PROFILE:END -->"
_RUNTIME_FILES = ("SOUL.md", "CORE.md", "IDENTITY.md", "USER.md", "MEMORY.md")


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
    workspace_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Sync active user_memory_facts into SBS profile layers.

    - preference/response_style -> interaction.preferred_response_style
    - identity summaries         -> domain.stable_identity_notes
    """
    result: dict[str, Any] = {
        "synced": False,
        "interaction_updated": False,
        "domain_updated": False,
        "workspace_files_updated": 0,
        "active_facts": 0,
    }

    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return result

    rows = _load_active_user_memory_facts(Path(db_path), clean_user_id)
    result["active_facts"] = len(rows)

    interaction = profile_mgr.load_layer("interaction")
    domain = profile_mgr.load_layer("domain")

    interaction_updated = False
    domain_updated = False

    # Unique key by (kind, key). Query order prefers most-recent values.
    latest: dict[tuple[str, str], sqlite3.Row] = {}
    identity_notes: list[str] = []
    routine_notes: list[str] = []
    correction_notes: list[str] = []
    people_notes: list[str] = []
    project_notes: list[str] = []
    for row in rows:
        kind = str(row["kind"] or "").strip()
        key = str(row["key"] or "").strip()
        latest.setdefault((kind, key), row)
        summary = str(row["summary"] or "").strip()
        if not summary:
            continue
        if kind == "identity" and summary not in identity_notes:
            identity_notes.append(summary)
        elif kind == "routine" and summary not in routine_notes:
            routine_notes.append(summary)
        elif kind == "correction" and summary not in correction_notes:
            correction_notes.append(summary)
        elif kind == "relationship" and summary not in people_notes:
            people_notes.append(summary)
        elif kind == "project" and summary not in project_notes:
            project_notes.append(summary)

    preferred_response_style = ""
    style_row = latest.get(("preference", "response_style"))
    if style_row is not None:
        preferred_response_style = str(style_row["value"] or "").strip()

    current_style = interaction.get(_INTERACTION_STYLE_KEY)
    if preferred_response_style:
        if current_style != preferred_response_style:
            interaction[_INTERACTION_STYLE_KEY] = preferred_response_style
            interaction_updated = True
    elif _INTERACTION_STYLE_KEY in interaction:
        interaction.pop(_INTERACTION_STYLE_KEY, None)
        interaction_updated = True

    routines_updated = _set_list(interaction, _INTERACTION_ROUTINES_KEY, routine_notes)
    corrections_updated = _set_list(
        interaction, _INTERACTION_CORRECTIONS_KEY, correction_notes
    )
    identity_updated = _set_list(domain, _DOMAIN_IDENTITY_NOTES_KEY, identity_notes)
    people_updated = _set_list(domain, _DOMAIN_PEOPLE_KEY, people_notes)
    projects_updated = _set_list(domain, _DOMAIN_PROJECTS_KEY, project_notes)

    interaction_updated = interaction_updated or routines_updated or corrections_updated
    domain_updated = domain_updated or identity_updated or people_updated or projects_updated

    if interaction_updated:
        profile_mgr.save_layer("interaction", interaction)
    if domain_updated:
        profile_mgr.save_layer("domain", domain)

    result["interaction_updated"] = interaction_updated
    result["domain_updated"] = domain_updated
    result["synced"] = interaction_updated or domain_updated
    if workspace_dir is not None:
        workspace_result = sync_runtime_identity_workspace(
            workspace_dir=workspace_dir,
            user_id=clean_user_id,
            db_path=db_path,
            rows=rows,
        )
        result["workspace_files_updated"] = workspace_result["files_updated"]
        result["synced"] = result["synced"] or workspace_result["files_updated"] > 0
    return result


def _set_list(layer: dict[str, Any], key: str, values: list[str]) -> bool:
    clean_values = [value for value in values if value]
    if clean_values:
        if layer.get(key) != clean_values:
            layer[key] = clean_values
            return True
        return False
    if key in layer:
        layer.pop(key, None)
        return True
    return False


def sync_runtime_identity_workspace(
    *,
    workspace_dir: str | Path,
    user_id: str,
    db_path: str | Path,
    rows: list[sqlite3.Row] | None = None,
) -> dict[str, Any]:
    """Write distilled user behavior into managed runtime markdown sections.

    This updates only the block between SYNAPSE:DYNAMIC_USER_PROFILE markers.
    Shipped templates and human-authored text outside the block are preserved.
    """
    clean_user_id = str(user_id or "").strip()
    target_dir = Path(workspace_dir)
    facts = rows if rows is not None else _load_active_user_memory_facts(Path(db_path), clean_user_id)
    grouped = _group_fact_summaries(facts)
    blocks = _build_runtime_blocks(grouped)

    target_dir.mkdir(parents=True, exist_ok=True)
    files_updated = 0
    updated_files: list[str] = []
    for filename in _RUNTIME_FILES:
        path = target_dir / filename
        before = path.read_text(encoding="utf-8") if path.exists() else _default_file_text(filename)
        after = _replace_managed_block(before, blocks.get(filename, ""))
        if before != after:
            _atomic_write_text(path, after)
            files_updated += 1
            updated_files.append(filename)

    return {
        "synced": files_updated > 0,
        "files_updated": files_updated,
        "updated_files": updated_files,
        "active_facts": len(facts),
    }


def _group_fact_summaries(rows: list[sqlite3.Row]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        "identity": [],
        "preference": [],
        "routine": [],
        "relationship": [],
        "project": [],
        "correction": [],
    }
    for row in rows:
        kind = str(row["kind"] or "").strip()
        summary = str(row["summary"] or "").strip()
        if not summary:
            continue
        grouped.setdefault(kind, [])
        if summary not in grouped[kind]:
            grouped[kind].append(summary)
    return grouped


def _build_runtime_blocks(grouped: dict[str, list[str]]) -> dict[str, str]:
    if not any(grouped.values()):
        return {filename: "" for filename in _RUNTIME_FILES}

    preferences = grouped.get("preference", [])
    routines = grouped.get("routine", [])
    people = grouped.get("relationship", [])
    projects = grouped.get("project", [])
    corrections = grouped.get("correction", [])
    identities = grouped.get("identity", [])

    core_lines = [
        "## Dynamic User Profile",
        "",
        "This section is generated from structured memory. It may change as the user changes.",
        "",
        *_bullet_section("Communication preferences", preferences),
        *_bullet_section("Important people", people),
        *_bullet_section("Active projects", projects),
        *_bullet_section("Routines and commitments", routines),
        *_bullet_section("Correction rules", corrections),
    ]
    soul_lines = [
        "## Dynamic Personality Adaptation",
        "",
        "For this user, adapt behavior using these stable signals:",
        "",
        *_bullet_section("Tone and response style", preferences),
        *_bullet_section("Emotional and routine cues", routines),
        *_bullet_section("Do-not-repeat corrections", corrections),
        "",
        "Use these quietly. Do not announce that memory was updated.",
    ]
    identity_lines = [
        "## Dynamic Relationship Shape",
        "",
        "Synapse's identity for this user should lean toward the following learned shape:",
        "",
        *_bullet_section("User identity cues", identities),
        *_bullet_section("Preferred interaction style", preferences),
        *_bullet_section("Correction rules", corrections),
    ]
    user_lines = [
        "## Learned User Context",
        "",
        *_bullet_section("Identity", identities),
        *_bullet_section("Preferences", preferences),
        *_bullet_section("People", people),
        *_bullet_section("Projects", projects),
        *_bullet_section("Routines", routines),
        *_bullet_section("Corrections", corrections),
    ]
    memory_lines = [
        "## Dynamic Memory Distillation",
        "",
        *_bullet_section("Identity", identities),
        *_bullet_section("Preferences", preferences),
        *_bullet_section("Relationships", people),
        *_bullet_section("Projects", projects),
        *_bullet_section("Routines", routines),
        *_bullet_section("Corrections", corrections),
    ]

    return {
        "CORE.md": _clean_block(core_lines),
        "SOUL.md": _clean_block(soul_lines),
        "IDENTITY.md": _clean_block(identity_lines),
        "USER.md": _clean_block(user_lines),
        "MEMORY.md": _clean_block(memory_lines),
    }


def _bullet_section(title: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [f"{title}:", *[f"- {value}" for value in values[:8]], ""]


def _clean_block(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    return text + "\n" if text else ""


def _replace_managed_block(original: str, block: str) -> str:
    text = str(original or "").rstrip()
    start = text.find(_DYNAMIC_BEGIN)
    end = text.find(_DYNAMIC_END)
    if start != -1 and end != -1 and end > start:
        end += len(_DYNAMIC_END)
        text = (text[:start].rstrip() + "\n\n" + text[end:].lstrip()).rstrip()

    clean_block = str(block or "").strip()
    if not clean_block:
        return text + "\n" if text else ""
    return f"{text}\n\n{_DYNAMIC_BEGIN}\n{clean_block}\n{_DYNAMIC_END}\n"


def _default_file_text(filename: str) -> str:
    title = filename.rsplit(".", 1)[0]
    return f"# {title}\n\nRuntime file created by Synapse identity evolution.\n"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f"{path.name}.",
    )
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
