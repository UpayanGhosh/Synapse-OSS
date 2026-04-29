"""Deterministic structured user-memory distillation and storage."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

EXTRACTOR_VERSION = "deterministic-v1"


@dataclass(frozen=True)
class UserMemoryFact:
    user_id: str
    kind: str
    key: str
    value: str
    summary: str
    confidence: float
    source_doc_id: int | None
    evidence: str
    status: str = "active"


_RESPONSE_STYLE_RULES: tuple[tuple[str, tuple[str, ...], str, float], ...] = (
    (
        "direct",
        (
            r"\bshort and direct\b",
            r"\bdirect and short\b",
            r"\bkeep it short\b",
            r"\bconcise\b",
            r"\bno fluff\b",
            r"\bstraight to the point\b",
            r"\bbrief\b",
        ),
        "Prefers concise, direct responses.",
        0.86,
    ),
    (
        "soft",
        (
            r"\bgentle\b",
            r"\bsoft\b",
            r"\bkind\b",
            r"\breassuring\b",
        ),
        "Prefers gentle, emotionally supportive responses.",
        0.8,
    ),
    (
        "playful",
        (
            r"\bplayful\b",
            r"\btease\b",
            r"\bfunny\b",
            r"\blighthearted\b",
        ),
        "Prefers playful response tone.",
        0.78,
    ),
)

_CODENAME_PATTERNS: tuple[str, ...] = (
    r"\bcall me\s+([A-Za-z][A-Za-z0-9_-]{1,31})\b",
    r"\bmy codename is\s+([A-Za-z][A-Za-z0-9_-]{1,31})\b",
    r"\bcodename(?:\s+is|:)\s*([A-Za-z][A-Za-z0-9_-]{1,31})\b",
    r"\buse\s+([A-Za-z][A-Za-z0-9_-]{1,31})\s+as my codename\b",
)


def _slug(value: str, *, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_")
    return (slug[:max_len].strip("_")) or "unknown"


def _clean_value(value: str, *, max_len: int = 96) -> str:
    return " ".join(str(value or "").strip().strip(".,!?;:\"'`").split())[:max_len].strip()


def ensure_user_memory_facts_table(conn: sqlite3.Connection) -> None:
    """Create structured user-memory table and indexes idempotently."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_memory_facts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            kind            TEXT NOT NULL,
            key             TEXT NOT NULL,
            value           TEXT NOT NULL,
            summary         TEXT NOT NULL,
            confidence      REAL NOT NULL DEFAULT 0.0,
            source_doc_id   INTEGER,
            evidence        TEXT,
            status          TEXT NOT NULL DEFAULT 'active',
            first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, kind, key)
        );
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_user_kind_status
            ON user_memory_facts(user_id, kind, status);
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_last_seen
            ON user_memory_facts(last_seen);
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_source_doc_id
            ON user_memory_facts(source_doc_id);
    """)


def _extract_user_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        match = re.match(r"^\s*User:\s*(.+?)\s*$", raw_line, re.IGNORECASE)
        if match:
            lines.append(match.group(1))
    if not lines:
        return " ".join(str(text or "").split())
    return " ".join(" ".join(lines).split())


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 3)))


def _distill_response_style(user_text: str) -> tuple[str, str, str, float] | None:
    lower = user_text.lower()
    for style_value, patterns, summary, confidence in _RESPONSE_STYLE_RULES:
        for pattern in patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                return style_value, summary, match.group(0).strip(), confidence
    return None


def _distill_codename(user_text: str) -> tuple[str, str, str, float] | None:
    for pattern in _CODENAME_PATTERNS:
        match = re.search(pattern, user_text, re.IGNORECASE)
        if not match:
            continue
        raw_value = match.group(1).strip().strip(".,!?;:\"'`")
        if not raw_value:
            continue
        value = raw_value[:32]
        summary = f"Preferred codename: {value}."
        return value, summary, match.group(0).strip(), 0.95
    return None


def _distill_routines(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    patterns = (
        r"\bmy routine is\s+([^.!?]{3,96})",
        r"\bevery\s+(morning|day|night|evening)\s+i\s+([^.!?]{3,96})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, user_text, re.IGNORECASE):
            if len(match.groups()) == 2:
                value = _clean_value(f"{match.group(2)} every {match.group(1).lower()}")
            else:
                value = _clean_value(match.group(1))
            if not value:
                continue
            facts.append((f"routine_{_slug(value)}", value, f"Routine: {value}.", 0.82))
    return facts


def _distill_relationships(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    pattern = r"\b([A-Z][A-Za-z0-9_-]{1,31})\s+is my\s+([^.!?]{3,80})"
    for match in re.finditer(pattern, user_text):
        name = _clean_value(match.group(1), max_len=32)
        role = _clean_value(match.group(2).lower(), max_len=80)
        if not name or not role or "project" in role:
            continue
        facts.append((f"person_{_slug(name)}", role, f"{name} is user's {role}.", 0.84))
    return facts


def _distill_projects(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    pattern = r"\b([A-Z][A-Za-z0-9_-]{1,63})\s+is my\s+(?:main|primary|current)\s+project\b"
    for match in re.finditer(pattern, user_text):
        project = _clean_value(match.group(1), max_len=64)
        if not project:
            continue
        facts.append((f"project_{_slug(project)}", project, f"Current project: {project}.", 0.84))
    return facts


def _distill_corrections(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    for match in re.finditer(r"\b(?:don't|do not)\s+call me\s+([^.!?;,]{2,40})", user_text, re.IGNORECASE):
        bad_name = _clean_value(match.group(1).lower(), max_len=40)
        if not bad_name:
            continue
        facts.append(
            (
                f"avoid_calling_me_{_slug(bad_name)}",
                bad_name,
                f"Do not call the user {bad_name}.",
                0.9,
            )
        )
    for match in re.finditer(r"\bforget that\s+([^.!?]{3,96})", user_text, re.IGNORECASE):
        value = _clean_value(match.group(1), max_len=96)
        if value:
            facts.append((f"forget_{_slug(value)}", value, f"Forget rule: {value}.", 0.88))
    return facts


def distill_user_memory_facts(
    *,
    text: str,
    user_id: str,
    source_doc_id: int | None,
    status: str = "active",
) -> list[UserMemoryFact]:
    """Distill deterministic user-memory facts from transcript text."""
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return []

    user_text = _extract_user_text(text)
    if not user_text:
        return []

    clean_status = str(status or "active").strip() or "active"
    facts: list[UserMemoryFact] = []

    style = _distill_response_style(user_text)
    if style is not None:
        value, summary, evidence, confidence = style
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="preference",
                key="response_style",
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=evidence,
                status=clean_status,
            )
        )

    codename = _distill_codename(user_text)
    if codename is not None:
        value, summary, evidence, confidence = codename
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="identity",
                key="codename",
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=evidence,
                status=clean_status,
            )
        )

    for key, value, summary, confidence in _distill_routines(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="routine",
                key=key.removeprefix("routine_"),
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=value,
                status=clean_status,
            )
        )

    for key, value, summary, confidence in _distill_relationships(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="relationship",
                key=key,
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=summary,
                status=clean_status,
            )
        )

    for key, value, summary, confidence in _distill_projects(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="project",
                key=key,
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=summary,
                status=clean_status,
            )
        )

    for key, value, summary, confidence in _distill_corrections(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="correction",
                key=key,
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=summary,
                status=clean_status,
            )
        )

    return facts


def upsert_user_memory_facts(conn: sqlite3.Connection, facts: list[UserMemoryFact]) -> int:
    """Insert or update structured user-memory facts."""
    ensure_user_memory_facts_table(conn)
    count = 0
    for fact in facts:
        conn.execute(
            """
            INSERT INTO user_memory_facts
                (user_id, kind, key, value, summary, confidence,
                 source_doc_id, evidence, status, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, kind, key) DO UPDATE SET
                value = excluded.value,
                summary = excluded.summary,
                confidence = excluded.confidence,
                source_doc_id = excluded.source_doc_id,
                evidence = excluded.evidence,
                status = excluded.status,
                last_seen = CURRENT_TIMESTAMP
            """,
            (
                fact.user_id,
                fact.kind,
                fact.key,
                fact.value,
                fact.summary,
                float(fact.confidence),
                fact.source_doc_id,
                fact.evidence,
                fact.status,
            ),
        )
        count += 1
    return count


def distill_and_upsert_user_memory_facts(
    conn: sqlite3.Connection,
    *,
    text: str,
    user_id: str,
    source_doc_id: int | None,
    status: str = "active",
) -> list[UserMemoryFact]:
    """Distill facts from text and upsert into user_memory_facts."""
    facts = distill_user_memory_facts(
        text=text,
        user_id=user_id,
        source_doc_id=source_doc_id,
        status=status,
    )
    if facts:
        upsert_user_memory_facts(conn, facts)
    else:
        ensure_user_memory_facts_table(conn)
    return facts
