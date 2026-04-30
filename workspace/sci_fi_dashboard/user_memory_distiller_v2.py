"""Async structured user-memory distillation queue.

V2 adds a durable middle layer between raw transcript chunks and confirmed
`user_memory_facts`:

observation -> candidate facts -> confirmed facts -> profile updates

An async extractor may supply strict JSON. If it is missing, invalid, or times
out, deterministic V1 distillation remains the fallback.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sci_fi_dashboard.user_memory import (
    UserMemoryFact,
    ensure_user_memory_facts_table,
    upsert_user_memory_facts,
)

Extractor = Callable[[dict[str, Any]], Awaitable[str | dict[str, Any]] | str | dict[str, Any]]


@dataclass(frozen=True)
class DistillerProcessResult:
    processed: int = 0
    confirmed_facts: int = 0
    fallback_used: int = 0
    errors: int = 0


def ensure_user_memory_distiller_v2_tables(conn: sqlite3.Connection) -> None:
    """Create V2 distillation queue tables idempotently."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_memory_observations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            source_doc_id   INTEGER,
            text            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            error           TEXT,
            extractor_version TEXT DEFAULT 'distiller-v2',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at    TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_user_memory_observations_status
            ON user_memory_observations(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_user_memory_observations_user
            ON user_memory_observations(user_id, created_at);

        CREATE TABLE IF NOT EXISTS user_memory_candidate_facts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id  INTEGER NOT NULL,
            user_id         TEXT NOT NULL,
            kind            TEXT NOT NULL,
            key             TEXT NOT NULL,
            value           TEXT NOT NULL,
            summary         TEXT NOT NULL,
            confidence      REAL NOT NULL DEFAULT 0.0,
            evidence        TEXT,
            status          TEXT NOT NULL DEFAULT 'candidate',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_user_memory_candidate_observation
            ON user_memory_candidate_facts(observation_id);
        CREATE INDEX IF NOT EXISTS idx_user_memory_candidate_user_status
            ON user_memory_candidate_facts(user_id, status);

        CREATE TABLE IF NOT EXISTS user_memory_profile_updates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id  INTEGER NOT NULL,
            user_id         TEXT NOT NULL,
            layer           TEXT NOT NULL,
            field           TEXT NOT NULL,
            value           TEXT NOT NULL,
            reason          TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_at      TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_user_memory_profile_updates_status
            ON user_memory_profile_updates(user_id, status);
        """
    )
    ensure_user_memory_facts_table(conn)


def build_router_extractor(llm_router: Any, *, role: str = "casual") -> Extractor:
    """Build an extractor around the existing Synapse LLM router call API."""

    async def _extract(observation: dict[str, Any]) -> str:
        prompt = (
            "Extract durable user-memory updates from this transcript. "
            "Return strict JSON with keys observations, candidate_facts, "
            "confirmed_facts, profile_updates. Do not include markdown.\n\n"
            "Each fact must include kind, key, value, summary, confidence, evidence. "
            "Only include stable user preferences, identity, routines, projects, "
            "people, correction rules, or recurring workflows.\n\n"
            f"Transcript:\n{observation.get('text', '')}"
        )
        messages = [
            {
                "role": "system",
                "content": "You are Synapse's memory distiller. Return JSON only.",
            },
            {"role": "user", "content": prompt},
        ]
        if hasattr(llm_router, "call"):
            return await llm_router.call(role, messages, temperature=0.0, max_tokens=1200)
        if hasattr(llm_router, "call_with_metadata"):
            result = await llm_router.call_with_metadata(role, messages)
            if isinstance(result, dict):
                return str(result.get("content") or result.get("reply") or "")
            return str(result)
        raise TypeError("llm_router must expose call() or call_with_metadata()")

    return _extract


class UserMemoryDistillerV2:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        extractor: Extractor | None = None,
        extractor_timeout: float = 10.0,
    ) -> None:
        self.conn = conn
        self.extractor = extractor
        self.extractor_timeout = float(extractor_timeout)
        ensure_user_memory_distiller_v2_tables(conn)

    def enqueue(self, *, user_id: str, text: str, source_doc_id: int | None) -> int:
        """Add a raw observation to the distillation queue."""
        clean_user_id = str(user_id or "").strip()
        clean_text = str(text or "").strip()
        if not clean_user_id:
            raise ValueError("user_id is required")
        if not clean_text:
            raise ValueError("text is required")

        cursor = self.conn.execute(
            """
            INSERT INTO user_memory_observations
                (user_id, source_doc_id, text, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (clean_user_id, source_doc_id, clean_text),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    async def process_pending(self, *, limit: int = 10) -> DistillerProcessResult:
        """Process pending observations with LLM extractor plus deterministic fallback."""
        rows = self.conn.execute(
            """
            SELECT id, user_id, source_doc_id, text
            FROM user_memory_observations
            WHERE status = 'pending'
            ORDER BY id
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        processed = 0
        confirmed = 0
        fallback_used = 0
        errors = 0

        for row in rows:
            observation = {
                "id": int(row[0]),
                "user_id": str(row[1]),
                "source_doc_id": row[2],
                "text": str(row[3]),
            }
            try:
                facts = await self._process_one(observation)
                confirmed += len(facts)
                processed += 1
            except Exception as exc:  # pragma: no cover - defensive final guard
                errors += 1
                self._mark_observation(observation["id"], "error", str(exc))
                continue
            if self._last_used_fallback:
                fallback_used += 1

        self.conn.commit()
        return DistillerProcessResult(
            processed=processed,
            confirmed_facts=confirmed,
            fallback_used=fallback_used,
            errors=errors,
        )

    async def _process_one(self, observation: dict[str, Any]) -> list[UserMemoryFact]:
        self._last_used_fallback = False
        payload: dict[str, Any] | None = None
        extractor_error: str | None = None

        if self.extractor is not None:
            try:
                raw = self.extractor(observation)
                if inspect.isawaitable(raw):
                    raw = await asyncio.wait_for(raw, timeout=self.extractor_timeout)
                payload = self._parse_payload(raw)
            except Exception as exc:
                extractor_error = str(exc)
                payload = None

        if payload is None:
            from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

            self._last_used_fallback = True
            facts = distill_and_upsert_user_memory_facts(
                self.conn,
                text=observation["text"],
                user_id=observation["user_id"],
                source_doc_id=observation["source_doc_id"],
            )
            self._mark_observation(observation["id"], "processed", extractor_error)
            return facts

        self._insert_candidate_facts(observation, payload.get("candidate_facts", []))
        self._insert_profile_updates(observation, payload.get("profile_updates", []))
        facts = self._confirmed_to_facts(observation, payload.get("confirmed_facts", []))
        if facts:
            upsert_user_memory_facts(self.conn, facts)
        self._mark_observation(observation["id"], "processed", None)
        return facts

    def _parse_payload(self, raw: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        elif isinstance(raw, dict):
            parsed = raw
        else:
            raise TypeError("extractor output must be str or dict")

        if not isinstance(parsed, dict):
            raise ValueError("extractor output must be a JSON object")
        for key in ("observations", "candidate_facts", "confirmed_facts", "profile_updates"):
            value = parsed.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list")
            parsed[key] = value
        return parsed

    def _insert_candidate_facts(
        self, observation: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> None:
        for item in candidates:
            fact = self._coerce_fact_dict(item)
            self.conn.execute(
                """
                INSERT INTO user_memory_candidate_facts
                    (observation_id, user_id, kind, key, value, summary,
                     confidence, evidence, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation["id"],
                    observation["user_id"],
                    fact["kind"],
                    fact["key"],
                    fact["value"],
                    fact["summary"],
                    fact["confidence"],
                    fact["evidence"],
                    str(item.get("status") or "candidate"),
                ),
            )

    def _insert_profile_updates(
        self, observation: dict[str, Any], updates: list[dict[str, Any]]
    ) -> None:
        for item in updates:
            layer = _clean_required(item, "layer")
            field = _clean_required(item, "field")
            value = _clean_required(item, "value")
            reason = str(item.get("reason") or "").strip()
            self.conn.execute(
                """
                INSERT INTO user_memory_profile_updates
                    (observation_id, user_id, layer, field, value, reason, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (observation["id"], observation["user_id"], layer, field, value, reason),
            )

    def _confirmed_to_facts(
        self, observation: dict[str, Any], confirmed_facts: list[dict[str, Any]]
    ) -> list[UserMemoryFact]:
        facts: list[UserMemoryFact] = []
        for item in confirmed_facts:
            fact = self._coerce_fact_dict(item)
            facts.append(
                UserMemoryFact(
                    user_id=observation["user_id"],
                    kind=fact["kind"],
                    key=fact["key"],
                    value=fact["value"],
                    summary=fact["summary"],
                    confidence=fact["confidence"],
                    source_doc_id=observation["source_doc_id"],
                    evidence=fact["evidence"],
                )
            )
        return facts

    def _coerce_fact_dict(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": _clean_required(item, "kind"),
            "key": _clean_required(item, "key"),
            "value": _clean_required(item, "value"),
            "summary": _clean_required(item, "summary"),
            "confidence": _clamp_float(item.get("confidence", 0.0)),
            "evidence": str(item.get("evidence") or "").strip(),
        }

    def _mark_observation(self, observation_id: int, status: str, error: str | None) -> None:
        self.conn.execute(
            """
            UPDATE user_memory_observations
            SET status = ?, error = ?, processed_at = ?
            WHERE id = ?
            """,
            (
                status,
                error,
                datetime.now(tz=UTC).isoformat(timespec="seconds"),
                observation_id,
            ),
        )


def _clean_required(item: dict[str, Any], key: str) -> str:
    value = str(item.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value[:500]


def _clamp_float(value: Any) -> float:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        raw = 0.0
    return max(0.0, min(1.0, round(raw, 3)))


async def distill_and_upsert_user_memory_facts_v2(
    conn: sqlite3.Connection,
    *,
    text: str,
    user_id: str,
    source_doc_id: int | None,
    extractor: Extractor | None = None,
    extractor_timeout: float = 10.0,
) -> list[UserMemoryFact]:
    """Convenience wrapper for one-shot V2 distillation."""
    distiller = UserMemoryDistillerV2(
        conn,
        extractor=extractor,
        extractor_timeout=extractor_timeout,
    )
    distiller.enqueue(user_id=user_id, text=text, source_doc_id=source_doc_id)
    result = await distiller.process_pending(limit=1)
    if result.errors:
        raise RuntimeError("user memory distiller v2 failed")
    rows = conn.execute(
        """
        SELECT kind, key, value, summary, confidence, source_doc_id, evidence, status
        FROM user_memory_facts
        WHERE user_id = ? AND source_doc_id IS ?
        ORDER BY kind, key
        """,
        (user_id, source_doc_id),
    ).fetchall()
    return [
        UserMemoryFact(
            user_id=user_id,
            kind=row[0],
            key=row[1],
            value=row[2],
            summary=row[3],
            confidence=row[4],
            source_doc_id=row[5],
            evidence=row[6] or "",
            status=row[7],
        )
        for row in rows
    ]
