from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
from sci_fi_dashboard.sbs.profile.manager import ProfileManager
from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

SAME_PROMPT = "I am stuck. What should I do next?"


def run_eval(root: Path) -> dict:
    root = Path(root)
    eval_root = root / ".longitudinal_personality_eval"
    shutil.rmtree(eval_root, ignore_errors=True)
    eval_root.mkdir(parents=True, exist_ok=True)
    try:
        users = {
            "user_a": _seed_user(
                eval_root / "user_a",
                user_id="agent:creator:long:user_a",
                style="direct technical triage",
                project="compiler reliability",
                routine="run failing test first",
                proactive_hint="send a concise unblock checklist",
            ),
            "user_b": _seed_user(
                eval_root / "user_b",
                user_id="agent:creator:long:user_b",
                style="warm emotionally supportive replies",
                project="confidence rebuilding",
                routine="evening reflection",
                proactive_hint="send a gentle emotional check-in",
            ),
            "user_c": _seed_user(
                eval_root / "user_c",
                user_id="agent:creator:long:user_c",
                style="strategic product planning",
                project="launch roadmap",
                routine="weekly roadmap review",
                proactive_hint="send a product strategy nudge",
            ),
        }
    finally:
        shutil.rmtree(eval_root, ignore_errors=True)

    prompts = [item["prompt"] for item in users.values()]
    return {
        "same_prompt": SAME_PROMPT,
        "user_count": len(users),
        "all_prompts_distinct": len(set(prompts)) == len(prompts),
        "users": users,
    }


def _seed_user(
    home_root: Path,
    *,
    user_id: str,
    style: str,
    project: str,
    routine: str,
    proactive_hint: str,
) -> dict:
    db_path = home_root / "workspace" / "db" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_user_memory_facts_table(conn)
        _insert_fact(
            conn,
            user_id=user_id,
            kind="preference",
            key="response_style",
            value=style,
            summary=f"Prefers {style}.",
        )
        _insert_fact(
            conn,
            user_id=user_id,
            kind="project",
            key=f"project_{project.replace(' ', '_')}",
            value=project,
            summary=f"Current project: {project}.",
        )
        _insert_fact(
            conn,
            user_id=user_id,
            kind="routine",
            key=f"routine_{routine.replace(' ', '_')}",
            value=routine,
            summary=f"Routine: {routine}.",
        )
        _insert_fact(
            conn,
            user_id=user_id,
            kind="correction",
            key="proactive_hint",
            value=proactive_hint,
            summary=f"Proactive hint: {proactive_hint}.",
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(home_root / "workspace" / "sbs" / "profiles")
    sync_user_memory_profile(profile_mgr, user_id=user_id, db_path=db_path)
    prompt = PromptCompiler(profile_mgr).compile()
    return {
        "prompt": prompt,
        "proactive_hint": proactive_hint,
        "markers": {
            "direct": "direct technical triage" in prompt,
            "supportive": "warm emotionally supportive replies" in prompt,
            "strategic": "strategic product planning" in prompt,
        },
    }


def _insert_fact(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    key: str,
    value: str,
    summary: str,
) -> None:
    conn.execute(
        """
        INSERT INTO user_memory_facts
            (user_id, kind, key, value, summary, confidence, source_doc_id, evidence, status)
        VALUES (?, ?, ?, ?, ?, 0.9, 1, ?, 'active')
        """,
        (user_id, kind, key, value, summary, summary),
    )


if __name__ == "__main__":
    print(json.dumps(run_eval(WORKSPACE_ROOT), indent=2, sort_keys=True))
