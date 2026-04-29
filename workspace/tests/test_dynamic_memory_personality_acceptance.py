from __future__ import annotations

import json
import os
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _create_memory_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                filename        TEXT,
                content         TEXT,
                hemisphere_tag  TEXT,
                processed       INTEGER DEFAULT 0,
                unix_timestamp  INTEGER,
                importance      INTEGER DEFAULT 5,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memory_affect (
                doc_id          INTEGER PRIMARY KEY,
                mood            TEXT,
                tension_type    TEXT,
                user_need       TEXT,
                raw_json        TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ingest_failures (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_key     TEXT,
                agent_id        TEXT,
                archived_path   TEXT,
                batch_index     INTEGER,
                total_batches   INTEGER,
                phase           TEXT NOT NULL,
                exception_type  TEXT,
                exception_msg   TEXT,
                traceback       TEXT,
                ingested_vec    INTEGER,
                ingested_kg     INTEGER
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_fresh_db_closes_memory_personality_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sci_fi_dashboard import session_ingest
    from sci_fi_dashboard import user_memory
    from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator
    from synapse_config import SynapseConfig

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    cfg = SynapseConfig.load()
    ingest_cfg = types.SimpleNamespace(
        db_dir=cfg.db_dir,
        kg_extraction=types.SimpleNamespace(enabled=False, kg_role="casual"),
    )
    db_path = cfg.db_dir / "memory.db"
    _create_memory_db(db_path)

    archived = tmp_path / "phase7-loop.jsonl.deleted.1234567890"
    user_text = "I prefer concise technical replies. My temporary codename is Blue Lantern."
    archived_messages = [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": "Noted."},
    ]
    with archived.open("w", encoding="utf-8") as fh:
        for msg in archived_messages:
            fh.write(json.dumps(msg, separators=(",", ":")) + "\n")

    def _add_memory(*, content: str, category: str = "session", hemisphere: str = "safe") -> dict:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO documents
                    (filename, content, hemisphere_tag, processed, unix_timestamp, importance)
                VALUES (?, ?, ?, 0, 0, 5)
                """,
                (category, content, hemisphere),
            )
            doc_id = int(cur.lastrowid)
            cur.execute(
                """
                INSERT INTO memory_affect (doc_id, mood, tension_type, user_need, raw_json)
                VALUES (?, 'focused', 'none', 'clarity', '{}')
                """,
                (doc_id,),
            )
            conn.commit()
            return {"status": "stored", "id": doc_id}
        finally:
            conn.close()

    prior_deps = sys.modules.get("sci_fi_dashboard._deps")
    sys.modules["sci_fi_dashboard._deps"] = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(add_memory=_add_memory),
        brain=types.SimpleNamespace(
            add_node=lambda *args, **kwargs: None,
            add_relation=lambda *args, **kwargs: None,
            save_graph=lambda *args, **kwargs: None,
        ),
        synapse_llm_router=object(),
    )

    style_rules = (
        (
            "concise technical replies",
            (r"\bconcise technical replies\b",),
            "Prefers concise technical replies.",
            0.9,
        ),
    ) + tuple(user_memory._RESPONSE_STYLE_RULES)

    codename_patterns = (
        r"\bmy temporary codename is\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*)?)\b",
    ) + tuple(user_memory._CODENAME_PATTERNS)

    try:
        with (
            patch("synapse_config.SynapseConfig.load", return_value=ingest_cfg),
            patch.object(user_memory, "_RESPONSE_STYLE_RULES", style_rules),
            patch.object(user_memory, "_CODENAME_PATTERNS", codename_patterns),
        ):
            await session_ingest._ingest_session_background(
                archived_path=archived,
                agent_id="the_creator",
                session_key="the_creator",
                hemisphere="safe",
            )
    finally:
        if prior_deps is None:
            sys.modules.pop("sci_fi_dashboard._deps", None)
        else:
            sys.modules["sci_fi_dashboard._deps"] = prior_deps

    conn = sqlite3.connect(str(db_path))
    try:
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        facts = conn.execute(
            "SELECT COUNT(*) FROM user_memory_facts WHERE user_id = ? AND status = 'active'",
            ("the_creator",),
        ).fetchone()[0]
        affect = conn.execute("SELECT COUNT(*) FROM memory_affect").fetchone()[0]
    finally:
        conn.close()

    assert documents == 1
    assert facts >= 2
    assert affect == 1

    cfg = SynapseConfig.load()
    orchestrator = SBSOrchestrator(data_dir=str(cfg.sbs_dir / "the_creator"))
    sync_result = orchestrator.sync_user_memory("the_creator", str(db_path))
    assert sync_result["active_facts"] >= 2

    prompt = orchestrator.get_system_prompt()
    assert "concise technical replies" in prompt
    assert "Blue Lantern" in prompt
