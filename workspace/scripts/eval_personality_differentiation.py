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


def _seed_home(home_root: Path, *, user_id: str, response_style: str, source_doc_id: int) -> str:
    db_path = home_root / "workspace" / "db" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_user_memory_facts_table(conn)
        conn.execute(
            """
            INSERT INTO user_memory_facts
                (user_id, kind, key, value, summary, confidence, source_doc_id, evidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "preference",
                "response_style",
                response_style,
                f"Prefers {response_style}.",
                0.9,
                source_doc_id,
                response_style,
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(home_root / "workspace" / "sbs" / "profiles")
    sync_user_memory_profile(profile_mgr, user_id=user_id, db_path=db_path)
    return PromptCompiler(profile_mgr).compile()


def run_eval(root: Path) -> dict:
    root = Path(root)
    style_a = "concise technical replies"
    style_b = "warm emotionally supportive replies"
    eval_root = root / ".phase6_personality_eval_tmp"
    shutil.rmtree(eval_root, ignore_errors=True)
    eval_root.mkdir(parents=True, exist_ok=True)
    try:
        prompt_a = _seed_home(
            eval_root / "home_a",
            user_id="agent:creator:phase6:user_a",
            response_style=style_a,
            source_doc_id=601,
        )
        prompt_b = _seed_home(
            eval_root / "home_b",
            user_id="agent:creator:phase6:user_b",
            response_style=style_b,
            source_doc_id=602,
        )
    finally:
        shutil.rmtree(eval_root, ignore_errors=True)

    return {
        "user_a_contains": style_a if style_a in prompt_a else "",
        "user_b_contains": style_b if style_b in prompt_b else "",
        "prompts_are_different": prompt_a != prompt_b,
    }


if __name__ == "__main__":
    print(json.dumps(run_eval(WORKSPACE_ROOT), indent=2, sort_keys=True))
