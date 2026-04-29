from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_distiller_v2_processes_llm_json_into_structured_tables() -> None:
    from sci_fi_dashboard.user_memory_distiller_v2 import UserMemoryDistillerV2

    async def _extractor(observation: dict) -> str:
        assert observation["user_id"] == "agent:creator:test"
        return json.dumps(
            {
                "observations": [
                    {
                        "kind": "preference",
                        "key": "planning_style",
                        "value": "phase based execution",
                        "summary": "Prefers phase based execution plans.",
                        "confidence": 0.91,
                        "evidence": "I like phase based execution",
                    }
                ],
                "candidate_facts": [
                    {
                        "kind": "preference",
                        "key": "planning_style",
                        "value": "phase based execution",
                        "summary": "Prefers phase based execution plans.",
                        "confidence": 0.91,
                        "evidence": "I like phase based execution",
                        "status": "confirmed",
                    }
                ],
                "confirmed_facts": [
                    {
                        "kind": "preference",
                        "key": "planning_style",
                        "value": "phase based execution",
                        "summary": "Prefers phase based execution plans.",
                        "confidence": 0.91,
                        "evidence": "I like phase based execution",
                    }
                ],
                "profile_updates": [
                    {
                        "layer": "interaction",
                        "field": "planning_style",
                        "value": "phase based execution",
                        "reason": "confirmed preference",
                    }
                ],
            }
        )

    conn = sqlite3.connect(":memory:")
    try:
        distiller = UserMemoryDistillerV2(conn, extractor=_extractor)
        observation_id = distiller.enqueue(
            user_id="agent:creator:test",
            text="User: I like phase based execution.",
            source_doc_id=42,
        )
        result = asyncio.run(distiller.process_pending())

        assert result.processed == 1
        assert result.confirmed_facts == 1
        assert result.fallback_used == 0

        obs = conn.execute(
            "SELECT status, source_doc_id FROM user_memory_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        assert obs == ("processed", 42)

        candidate = conn.execute(
            """
            SELECT kind, key, value, status
            FROM user_memory_candidate_facts
            WHERE observation_id = ?
            """,
            (observation_id,),
        ).fetchone()
        assert candidate == (
            "preference",
            "planning_style",
            "phase based execution",
            "confirmed",
        )

        fact = conn.execute(
            """
            SELECT kind, key, value, source_doc_id, status
            FROM user_memory_facts
            WHERE user_id = ?
            """,
            ("agent:creator:test",),
        ).fetchone()
        assert fact == (
            "preference",
            "planning_style",
            "phase based execution",
            42,
            "active",
        )

        update = conn.execute(
            """
            SELECT layer, field, value, status
            FROM user_memory_profile_updates
            WHERE observation_id = ?
            """,
            (observation_id,),
        ).fetchone()
        assert update == (
            "interaction",
            "planning_style",
            "phase based execution",
            "pending",
        )
    finally:
        conn.close()


def test_distiller_v2_falls_back_to_deterministic_rules_on_invalid_llm_output() -> None:
    from sci_fi_dashboard.user_memory_distiller_v2 import UserMemoryDistillerV2

    async def _bad_extractor(_observation: dict) -> str:
        return "{not valid json"

    conn = sqlite3.connect(":memory:")
    try:
        distiller = UserMemoryDistillerV2(conn, extractor=_bad_extractor)
        distiller.enqueue(
            user_id="agent:creator:test",
            text="User: Keep it short and direct. Call me Nova.",
            source_doc_id=7,
        )
        result = asyncio.run(distiller.process_pending())

        assert result.processed == 1
        assert result.confirmed_facts == 2
        assert result.fallback_used == 1

        rows = conn.execute(
            """
            SELECT kind, key, value
            FROM user_memory_facts
            WHERE user_id = ?
            ORDER BY key
            """,
            ("agent:creator:test",),
        ).fetchall()
        assert rows == [
            ("identity", "codename", "Nova"),
            ("preference", "response_style", "direct"),
        ]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_distiller_v2_handles_async_extractor_timeout() -> None:
    from sci_fi_dashboard.user_memory_distiller_v2 import UserMemoryDistillerV2

    async def _slow_extractor(_observation: dict) -> str:
        await asyncio.sleep(0.05)
        return "{}"

    conn = sqlite3.connect(":memory:")
    try:
        distiller = UserMemoryDistillerV2(conn, extractor=_slow_extractor, extractor_timeout=0.001)
        distiller.enqueue(
            user_id="agent:creator:test",
            text="User: Keep it concise.",
            source_doc_id=8,
        )
        result = await distiller.process_pending()

        assert result.processed == 1
        assert result.fallback_used == 1
        assert result.errors == 0
        assert conn.execute(
            "SELECT value FROM user_memory_facts WHERE kind = 'preference'"
        ).fetchone()[0] == "direct"
    finally:
        conn.close()
