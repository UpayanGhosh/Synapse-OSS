from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_local_db_path(tag: str) -> Path:
    return Path(__file__).parent / f".{tag}-{uuid.uuid4().hex}.db"


def _table_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def _table_indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def test_user_memory_schema_created_on_first_boot() -> None:
    from sci_fi_dashboard.db import DatabaseManager

    db_path = _make_local_db_path("user-memory-schema")
    try:
        with patch("sci_fi_dashboard.db.DB_PATH", str(db_path)):
            DatabaseManager._initialized = False
            DatabaseManager._ensure_db()
            DatabaseManager._initialized = False

        cols = _table_columns(db_path, "user_memory_facts")
        assert {
            "id",
            "user_id",
            "kind",
            "key",
            "value",
            "summary",
            "confidence",
            "source_doc_id",
            "evidence",
            "status",
            "sentiment",
            "mood",
            "emotional_intensity",
            "tension_type",
            "user_need",
            "response_style_hint",
            "emotion_tags_json",
            "affect_topics_json",
            "first_seen",
            "last_seen",
        }.issubset(cols)

        indexes = _table_indexes(db_path, "user_memory_facts")
        assert "idx_user_memory_facts_user_kind_status" in indexes
        assert "idx_user_memory_facts_last_seen" in indexes
        assert "idx_user_memory_facts_source_doc_id" in indexes
        assert "idx_user_memory_facts_mood" in indexes
        assert "idx_user_memory_facts_tension" in indexes
    finally:
        if db_path.exists():
            db_path.unlink()


def test_distill_and_upsert_response_style_and_codename() -> None:
    from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

    conn = sqlite3.connect(":memory:")
    try:
        text = (
            "[WhatsApp session - 2026-04-29]\n"
            "User: Keep it short and direct.\n"
            "Me: Noted.\n"
            "User: Call me Nova."
        )
        facts = distill_and_upsert_user_memory_facts(
            conn,
            text=text,
            user_id="agent:creator:whatsapp:dm:+15551230000",
            source_doc_id=101,
        )
        conn.commit()

        assert {(fact.key, fact.value) for fact in facts} == {
            ("response_style", "direct"),
            ("codename", "Nova"),
        }

        rows = conn.execute("""
            SELECT kind, key, value, source_doc_id, status
            FROM user_memory_facts
            ORDER BY key
            """).fetchall()
        assert rows == [
            ("identity", "codename", "Nova", 101, "active"),
            ("preference", "response_style", "direct", 101, "active"),
        ]
    finally:
        conn.close()


def test_distill_routines_people_projects_and_corrections() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    text = (
        "[WhatsApp session - 2026-04-30]\n"
        "User: My routine is standup at 10am every day.\n"
        "User: Priya is my design partner.\n"
        "User: Synapse-OSS is my main project.\n"
        "User: Don't call me bro."
    )

    facts = distill_user_memory_facts(
        text=text,
        user_id="agent:creator:whatsapp:dm:+15551230000",
        source_doc_id=201,
    )

    by_kind_key = {(fact.kind, fact.key): fact for fact in facts}
    assert by_kind_key[("routine", "standup_at_10am_every_day")].value == (
        "standup at 10am every day"
    )
    assert by_kind_key[("relationship", "person_priya")].summary == (
        "Priya is user's design partner."
    )
    assert by_kind_key[("project", "project_synapse-oss")].summary == (
        "Current project: Synapse-OSS."
    )
    assert by_kind_key[("correction", "avoid_calling_me_bro")].summary == (
        "Do not call the user bro."
    )


def test_distill_day_to_day_personality_facts() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    text = (
        "[Telegram session - 2026-04-30]\n"
        "User: Personal update: I think I have a real crush on Naina now. "
        "She remembered I like filter coffee.\n"
        "User: Raghav said my Kestrel scope is too fuzzy.\n"
        "User: I almost bought 18000 INR headphones, but I still need to save 30000 INR. "
        "Remember that impulse-buying audio gear is my weakness.\n"
        "User: When I am anxious, give me one next action and one reason.\n"
        "User: I always underestimate handoff time.\n"
        "User: Forget the Goa maybe-plan."
    )

    facts = distill_user_memory_facts(
        text=text,
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=303,
    )

    keys = {(fact.kind, fact.key) for fact in facts}
    summaries = " ".join(fact.summary for fact in facts)

    assert ("relationship", "person_naina") in keys
    assert ("relationship", "person_raghav") in keys
    assert ("project", "project_kestrel") in keys
    assert ("preference", "audio_gear_impulse") in keys
    assert ("preference", "anxiety_next_action") in keys
    assert ("preference", "handoff_time_underestimate") in keys
    assert ("correction", "forget_the_goa_maybe-plan") in keys
    assert "Naina" in summaries
    assert "Raghav" in summaries
    assert "Kestrel" in summaries


def test_distill_relationships_ignores_sentence_initial_fillers() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: Okay, one more real check before I try sleeping: I'm still mad about Rohan, "
            "but I also know if I go into tomorrow visibly pissed, he'll win the optics game. "
            "User: Keep it human. User: Say it like a friend, not a report."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=404,
    )

    keys = {(fact.kind, fact.key) for fact in facts}
    assert ("relationship", "person_rohan") in keys
    assert ("relationship", "person_okay") not in keys
    assert ("relationship", "person_keep") not in keys
    assert ("relationship", "person_say") not in keys


def test_relationships_ignores_natural_sentence_starters() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: Tiny good thing before I sleep: the client actually liked the prototype today. "
            "User: It wasn't even dramatic, but my brain is replaying it like evidence in court. "
            "User: Don't make it a wellness poster, just talk sense into me. "
            "User: If Mira says no, I know the mature thing is to respect it. "
            "User: This is the part I don't like admitting. "
            "User: Part of me wants to read hope into every comma. "
            "User: Give me the brother answer, not the motivational answer."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=505,
    )

    keys = {(fact.kind, fact.key) for fact in facts}
    assert ("relationship", "person_tiny") not in keys
    assert ("relationship", "person_it") not in keys
    assert ("relationship", "person_don") not in keys
    assert ("relationship", "person_if") not in keys
    assert ("relationship", "person_this") not in keys
    assert ("relationship", "person_part") not in keys
    assert ("relationship", "person_give") not in keys
    assert ("relationship", "person_mira") in keys


def test_kind_of_person_does_not_set_soft_response_style() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: How do I not become the kind of person who quietly punishes "
            "someone for not giving me attention?"
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=606,
    )

    assert ("preference", "response_style") not in {(fact.kind, fact.key) for fact in facts}


def test_joined_session_does_not_promote_give_as_person() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: I’m thinking of asking Mira out tomorrow, but I also know I’m low sleep "
            "and a bit needy tonight. Give me the brother answer, not the motivational "
            "answer: am I making a clean move or trying to get relief from uncertainty? "
            "User: If I’m honest, when she mentions other guys I want to act unbothered."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=808,
    )

    keys = {(fact.kind, fact.key) for fact in facts}
    assert ("relationship", "person_mira") in keys
    assert ("relationship", "person_give") not in keys


def test_user_memory_facts_persist_affect_tags_for_realtime_turns() -> None:
    from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

    conn = sqlite3.connect(":memory:")
    try:
        facts = distill_and_upsert_user_memory_facts(
            conn,
            text=(
                "User: Mira posted a story with someone and I felt lonely and jealous. "
                "Ma called and I felt guilty for ignoring it."
            ),
            user_id="agent:the_creator:telegram:dm:123",
            source_doc_id=None,
        )
        conn.commit()

        assert facts
        row = conn.execute(
            """
            SELECT mood, sentiment, emotional_intensity, user_need, emotion_tags_json, affect_topics_json
            FROM user_memory_facts
            WHERE user_id = ? AND status = 'active'
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            ("agent:the_creator:telegram:dm:123",),
        ).fetchone()

        assert row is not None
        assert row[0] in {"lonely", "guilty", "hurt", "sad"}
        assert row[1] in {"negative", "mixed"}
        assert row[2] > 0
        assert row[3] in {"comfort", "validation", "reassurance"}
        assert "lonely" in row[4].lower() or "guilty" in row[4].lower()
        assert "mira" in row[5].lower() or "lonely" in row[5].lower()
    finally:
        conn.close()


def test_user_memory_does_not_promote_remember_as_person() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: Remember this little thing: Baba is my father. "
            "Blue-kulfi night means I felt quietly happy and loved, but also lonely."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=None,
    )

    keys = {(fact.kind, fact.key) for fact in facts}
    assert ("relationship", "person_baba") in keys
    assert ("relationship", "person_remember") not in keys

    baba = next(fact for fact in facts if fact.key == "person_baba")
    assert {"happy", "loving", "lonely"}.issubset(set(baba.affect.emotion_tags))


def test_distill_family_money_boundary_with_anger_affect() -> None:
    from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

    conn = sqlite3.connect(":memory:")
    try:
        facts = distill_and_upsert_user_memory_facts(
            conn,
            text=(
                "User: I am angry at my cousin because he borrowed money and now "
                "acts like I am rude for asking it back."
            ),
            user_id="agent:the_creator:telegram:dm:123",
            source_doc_id=None,
        )
        conn.commit()

        by_key = {fact.key: fact for fact in facts}
        assert "person_cousin" in by_key
        assert "money_boundary_cousin" in by_key

        row = conn.execute("""
            SELECT mood, sentiment, emotion_tags_json, tension_type, user_need
            FROM user_memory_facts
            WHERE key = 'money_boundary_cousin'
            """).fetchone()

        assert row is not None
        assert row[0] == "angry"
        assert row[1] == "negative"
        assert "angry" in row[2]
        assert row[3] in {"boundary", "conflict", "none"}
        assert row[4] in {"space", "validation", "clarity", "none"}
    finally:
        conn.close()


def test_forget_that_does_not_duplicate_forget_rule() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text="User: Forget that Goa maybe-plan.",
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=None,
    )

    forget_keys = [fact.key for fact in facts if fact.kind == "correction"]
    assert forget_keys == ["forget_goa_maybe-plan"]


def test_distill_live_memory_update_into_clean_rows() -> None:
    from sci_fi_dashboard.user_memory import distill_user_memory_facts

    facts = distill_user_memory_facts(
        text=(
            "User: Memory update: Raghav is the person who calls my Kestrel scope fuzzy, "
            "headphones/audio gear are my impulse-buy weakness, and when I am anxious "
            "I want one next action with one reason."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=None,
    )

    by_kind_key = {(fact.kind, fact.key): fact for fact in facts}

    assert by_kind_key[("relationship", "person_raghav")].value == (
        "calls my kestrel scope fuzzy, headphones/audio gear are my impulse-buy weakness, "
        "and when i am anxious i want one next action with one reason"
    )
    assert ("project", "project_raghav") not in by_kind_key
    assert ("project", "project_memory") not in by_kind_key
    assert ("project", "project_patch") not in by_kind_key
    assert ("project", "project_final") not in by_kind_key
    assert ("project", "project_kestrel") in by_kind_key
    assert ("preference", "audio_gear_impulse") in by_kind_key
    assert ("preference", "anxiety_next_action") in by_kind_key

    shorthand_facts = distill_user_memory_facts(
        text=(
            "User: Patch live check 04: Raghav is the person who calls my Kestrel scope fuzzy; "
            "headphones/audio gear are my impulse-buy weakness; when anxious I want one next "
            "action with one reason."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=None,
    )
    shorthand_keys = {(fact.kind, fact.key) for fact in shorthand_facts}
    assert ("project", "project_patch") not in shorthand_keys
    assert ("project", "project_final") not in shorthand_keys
    assert ("preference", "anxiety_next_action") in shorthand_keys

    final_label_facts = distill_user_memory_facts(
        text=(
            "User: Final memory check 05: Raghav is the person who calls my Kestrel scope fuzzy; "
            "headphones/audio gear are my impulse-buy weakness; when anxious I want one next "
            "action with one reason."
        ),
        user_id="agent:the_creator:telegram:dm:123",
        source_doc_id=None,
    )
    final_label_keys = {(fact.kind, fact.key) for fact in final_label_facts}
    assert ("project", "project_final") not in final_label_keys
    assert ("project", "project_kestrel") in final_label_keys


def test_sync_user_memory_writes_preferred_response_style_to_interaction(tmp_path) -> None:
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager
    from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
    from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

    db_path = tmp_path / "sync-memory.db"
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
                "agent:creator:whatsapp:dm:+15551230000",
                "preference",
                "response_style",
                "direct",
                "Prefers concise, direct responses.",
                0.86,
                101,
                "keep it short and direct",
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(tmp_path / "profiles")
    sync_user_memory_profile(
        profile_mgr,
        user_id="agent:creator:whatsapp:dm:+15551230000",
        db_path=db_path,
    )

    interaction = profile_mgr.load_layer("interaction")
    assert interaction.get("preferred_response_style") == "direct"


def test_compiled_prompt_includes_synced_preference_string(tmp_path) -> None:
    from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager
    from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
    from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

    db_path = tmp_path / "sync-memory.db"
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
                "agent:creator:whatsapp:dm:+15551230000",
                "preference",
                "response_style",
                "direct",
                "Prefers concise, direct responses.",
                0.86,
                102,
                "keep it short and direct",
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(tmp_path / "profiles")
    sync_user_memory_profile(
        profile_mgr,
        user_id="agent:creator:whatsapp:dm:+15551230000",
        db_path=db_path,
    )

    prompt = PromptCompiler(profile_mgr).compile()
    assert "Preferred response style: direct." in prompt


def test_compiled_prompt_prioritizes_learned_style_before_examples(tmp_path) -> None:
    from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager

    profile_mgr = ProfileManager(tmp_path / "profiles")
    interaction = profile_mgr.load_layer("interaction")
    interaction["preferred_response_style"] = "blunt, warm, and compact"
    interaction["correction_rules"] = ["Do not call the user bro."]
    profile_mgr.save_layer("interaction", interaction)

    exemplars = profile_mgr.load_layer("exemplars")
    exemplars["pairs"] = [
        {
            "user": f"example {idx}",
            "assistant": "long exemplar " * 40,
            "context": {"mood": "neutral"},
        }
        for idx in range(10)
    ]
    profile_mgr.save_layer("exemplars", exemplars)

    prompt = PromptCompiler(profile_mgr).compile()

    assert "Preferred response style: blunt, warm, and compact." in prompt
    assert "Correction rules: Do not call the user bro." in prompt
    assert prompt.index("[INTERACTION PATTERN]") < prompt.index("[EXAMPLE INTERACTIONS]")


def test_compiled_prompt_includes_rich_user_memory_facts(tmp_path) -> None:
    from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager
    from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
    from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

    user_id = "agent:creator:whatsapp:dm:+15551230000"
    db_path = tmp_path / "sync-rich-memory.db"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_user_memory_facts_table(conn)
        rows = [
            (
                user_id,
                "routine",
                "standup_at_10am_every_day",
                "standup at 10am every day",
                "Routine: standup at 10am every day.",
                0.82,
                201,
                "My routine is standup at 10am every day",
                "active",
            ),
            (
                user_id,
                "relationship",
                "person_priya",
                "design partner",
                "Priya is user's design partner.",
                0.84,
                201,
                "Priya is my design partner",
                "active",
            ),
            (
                user_id,
                "project",
                "project_synapse-oss",
                "Synapse-OSS",
                "Current project: Synapse-OSS.",
                0.84,
                201,
                "Synapse-OSS is my main project",
                "active",
            ),
            (
                user_id,
                "correction",
                "avoid_calling_me_bro",
                "bro",
                "Do not call the user bro.",
                0.9,
                201,
                "Don't call me bro",
                "active",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO user_memory_facts
                (user_id, kind, key, value, summary, confidence, source_doc_id, evidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(tmp_path / "profiles")
    sync_result = sync_user_memory_profile(profile_mgr, user_id=user_id, db_path=db_path)
    prompt = PromptCompiler(profile_mgr).compile()

    assert sync_result["active_facts"] == 4
    assert "User routines: Routine: standup at 10am every day." in prompt
    assert "Important people: Priya is user's design partner." in prompt
    assert "Important projects: Current project: Synapse-OSS." in prompt
    assert "Correction rules: Do not call the user bro." in prompt


def test_sync_user_memory_clears_synced_fields_when_no_active_facts(tmp_path) -> None:
    from sci_fi_dashboard.sbs.profile.manager import ProfileManager
    from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
    from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

    user_id = "agent:creator:whatsapp:dm:+15551230000"
    db_path = tmp_path / "sync-memory.db"
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
                "direct",
                "Prefers concise, direct responses.",
                0.86,
                101,
                "keep it short and direct",
                "active",
            ),
        )
        conn.execute(
            """
            INSERT INTO user_memory_facts
                (user_id, kind, key, value, summary, confidence, source_doc_id, evidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "identity",
                "codename",
                "Nova",
                "Preferred codename: Nova.",
                0.95,
                101,
                "call me Nova",
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    profile_mgr = ProfileManager(tmp_path / "profiles")
    first_sync = sync_user_memory_profile(profile_mgr, user_id=user_id, db_path=db_path)
    assert first_sync["active_facts"] == 2

    interaction = profile_mgr.load_layer("interaction")
    domain = profile_mgr.load_layer("domain")
    assert interaction.get("preferred_response_style") == "direct"
    assert domain.get("stable_identity_notes") == ["Preferred codename: Nova."]

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE user_memory_facts SET status = 'inactive' WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cleared = sync_user_memory_profile(profile_mgr, user_id=user_id, db_path=db_path)
    assert set(cleared.keys()) == {
        "synced",
        "interaction_updated",
        "domain_updated",
        "workspace_files_updated",
        "active_facts",
    }
    assert cleared["active_facts"] == 0
    assert cleared["workspace_files_updated"] == 0
    assert cleared["synced"] is True
    assert cleared["interaction_updated"] is True
    assert cleared["domain_updated"] is True

    interaction = profile_mgr.load_layer("interaction")
    domain = profile_mgr.load_layer("domain")
    assert "preferred_response_style" not in interaction
    assert "stable_identity_notes" not in domain


def test_orchestrator_sync_writes_runtime_workspace_and_clears_prompt_cache(
    tmp_path, monkeypatch
) -> None:
    from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator
    from sci_fi_dashboard.user_memory import ensure_user_memory_facts_table

    user_id = "agent:creator:whatsapp:dm:+15551230000"
    db_path = tmp_path / "sync-memory.db"
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
                "compact",
                "Prefers compact reassurance.",
                0.9,
                501,
                "keep it compact",
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    cleared: list[str | None] = []
    import sci_fi_dashboard.chat_pipeline as chat_pipeline

    monkeypatch.setattr(
        chat_pipeline,
        "clear_agent_workspace_session_prefix",
        lambda session_key=None: cleared.append(session_key),
    )

    runtime_workspace = tmp_path / "workspace"
    orchestrator = SBSOrchestrator(
        data_dir=str(tmp_path / "sbs"),
        workspace_dir=runtime_workspace,
    )
    result = orchestrator.sync_user_memory(user_id, str(db_path))

    assert result["workspace_files_updated"] > 0
    assert "Prefers compact reassurance." in (runtime_workspace / "USER.md").read_text(
        encoding="utf-8"
    )
    assert cleared == [user_id]
