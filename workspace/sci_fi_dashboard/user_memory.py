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
            r"\bleg[- ]?pull\b",
            r"\bhype me\b",
            r"\bhype you up\b",
            r"\bfunny\b",
            r"\blighthearted\b",
            r"\bfriendly\b",
            r"\blike a friend\b",
            r"\bhuman like\b",
        ),
        "Prefers playful, friend-like response tone.",
        0.84,
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
    conn.execute("""
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
        )
    """)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_user_kind_status
            ON user_memory_facts(user_id, kind, status)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_last_seen
            ON user_memory_facts(last_seen)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_memory_facts_source_doc_id
            ON user_memory_facts(source_doc_id)
        """
    )


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
    seen_keys: set[str] = set()
    pattern = r"\b([A-Z][A-Za-z0-9_-]{1,31})\s+is my\s+([^.!?]{3,80})"
    for match in re.finditer(pattern, user_text):
        name = _clean_value(match.group(1), max_len=32)
        role = _clean_value(match.group(2).lower(), max_len=80)
        if not name or not role or "project" in role:
            continue
        key = f"person_{_slug(name)}"
        seen_keys.add(key)
        facts.append((key, role, f"{name} is user's {role}.", 0.84))

    descriptor_patterns = (
        r"\b([A-Z][A-Za-z0-9_-]{1,31})\s+is the person who\s+([^.!?]{3,180})",
        r"\b([A-Z][A-Za-z0-9_-]{1,31})\s+is the one who\s+([^.!?]{3,180})",
    )
    for descriptor_pattern in descriptor_patterns:
        for match in re.finditer(descriptor_pattern, user_text):
            name = _clean_value(match.group(1), max_len=32)
            detail = _clean_value(match.group(2).lower(), max_len=180)
            if not name or not detail:
                continue
            key = f"person_{_slug(name)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            facts.append((key, detail, f"{name} is the person who {detail}.", 0.84))

    # Capture day-to-day people even when the user does not use "X is my ...".
    # These are intentionally conservative: only named entities near relational
    # or emotional context are promoted to long-term facts.
    people_markers = (
        "crush",
        "boss",
        "manager",
        "coworker",
        "colleague",
        "client",
        "friend",
        "partner",
        "ma",
        "mother",
        "father",
        "family",
        "remembered",
        "liked",
        "asked",
        "said",
    )
    sentence_pattern = r"[^.!?]*\b[A-Z][A-Za-z0-9_-]{1,31}\b[^.!?]*(?:[.!?]|$)"
    name_pattern = r"\b[A-Z][A-Za-z0-9_-]{1,31}\b"
    skip_names = {"user", "me", "i", "synapse", "jarvis"}
    for match in re.finditer(sentence_pattern, user_text):
        sentence = _clean_value(match.group(0), max_len=180)
        if not sentence:
            continue
        lower_sentence = sentence.lower()
        if not any(marker in lower_sentence for marker in people_markers):
            continue
        for raw_name in re.findall(name_pattern, sentence):
            name = _clean_value(raw_name, max_len=32)
            if not name or name.lower() in skip_names:
                continue
            key = f"person_{_slug(name)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            facts.append(
                (
                    key,
                    sentence,
                    f"Important person/context: {sentence}.",
                    0.74,
                )
            )
    return facts


def _distill_projects(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    seen_keys: set[str] = set()
    pattern = r"\b([A-Z][A-Za-z0-9_-]{1,63})\s+is my\s+(?:main|primary|current)\s+project\b"
    for match in re.finditer(pattern, user_text):
        project = _clean_value(match.group(1), max_len=64)
        if not project:
            continue
        key = f"project_{_slug(project)}"
        seen_keys.add(key)
        facts.append((key, project, f"Current project: {project}.", 0.84))

    project_context_markers = (
        "project",
        "product",
        "launch",
        "code",
        "onboarding",
        "wireframe",
        "deadline",
        "scope",
        "solo consultant",
    )
    for match in re.finditer(r"[^.!?]*\b[A-Z][A-Za-z0-9_-]{2,63}\b[^.!?]*(?:[.!?]|$)", user_text):
        sentence = _clean_value(match.group(0), max_len=180)
        if not sentence:
            continue
        scan_sentence = re.sub(
            r"^\s*(?:memory update|personal update|patch live check(?:\s+\d+)?|final memory check(?:\s+\d+)?|live check(?:\s+\d+)?)\s*:\s*",
            "",
            sentence,
            flags=re.IGNORECASE,
        )
        lower_sentence = scan_sentence.lower()
        if not any(marker in lower_sentence for marker in project_context_markers):
            continue
        for raw_project in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,63}\b", scan_sentence):
            project = _clean_value(raw_project, max_len=64)
            project_lower = project.lower()
            if (
                not project
                or project_lower in {"user", "synapse", "jarvis", "memory", "patch", "live", "check"}
                or f"{project_lower} is the person" in lower_sentence
                or f"{project_lower} is the one" in lower_sentence
            ):
                continue
            key = f"project_{_slug(project)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            facts.append(
                (
                    key,
                    sentence,
                    f"Project context: {sentence}.",
                    0.76,
                )
            )
    return facts


def _distill_preferences_and_patterns(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    pattern_specs = (
        (
            "anxiety_next_action",
            r"\bwhen (?:i am )?anxious,?\s*(?:i want|please|that)?\s*([^.!?]{6,160})",
            "Anxiety response preference",
            0.88,
        ),
        (
            "low_sleep_reactive",
            r"\blow sleep[^.!?]{0,120}\b(?:reactive|sharp|irritable|angry)[^.!?]*",
            "Low-sleep behavior pattern",
            0.84,
        ),
        (
            "audio_gear_impulse",
            r"\b(?:impulse[- ]buying|buying)\s+(?:headphones|audio gear)\s+is my weakness\b|\b(?:headphones|audio gear)\s+(?:are|is)\s+my\s+impulse[- ]buy\s+weakness\b|\b(?:headphones|audio gear)\s+are my weakness\b",
            "Impulse-buying pattern",
            0.86,
        ),
        (
            "saving_goal",
            r"\bsave\s+([0-9,]+)\s*(?:inr|rs|rupees)\b[^.!?]*",
            "Money goal",
            0.82,
        ),
        (
            "handoff_time_underestimate",
            r"\bunderestimate\s+handoff\s+time\b",
            "Workflow pattern",
            0.86,
        ),
        (
            "cleanup_reset",
            r"\b(?:cleanup|clean up)[^.!?]{0,120}\b(?:reset|less chaotic|product)\b[^.!?]*",
            "Reset pattern",
            0.78,
        ),
    )
    for key, pattern, label, confidence in pattern_specs:
        for match in re.finditer(pattern, user_text, re.IGNORECASE):
            evidence = _clean_value(match.group(0), max_len=180)
            if not evidence:
                continue
            facts.append(
                (
                    key,
                    evidence,
                    f"{label}: {evidence}.",
                    confidence,
                )
            )
    return facts


def _distill_commitments(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    commitment_patterns = (
        r"\b(?:have to|need to|must|should)\s+([^.!?]{6,180})",
        r"\b(?:deadline|due)\s+(?:is|by|at)\s+([^.!?]{6,180})",
        r"\bremind me\s+([^.!?]{6,180})",
    )
    for pattern in commitment_patterns:
        for match in re.finditer(pattern, user_text, re.IGNORECASE):
            value = _clean_value(match.group(1), max_len=180)
            if not value:
                continue
            facts.append(
                (
                    f"commitment_{_slug(value)}",
                    value,
                    f"Commitment/reminder context: {value}.",
                    0.8,
                )
            )
    return facts


def _distill_corrections(user_text: str) -> list[tuple[str, str, str, float]]:
    facts: list[tuple[str, str, str, float]] = []
    seen_forget_keys: set[str] = set()
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
        key = f"forget_{_slug(value)}"
        if value and key not in seen_forget_keys:
            seen_forget_keys.add(key)
            facts.append((key, value, f"Forget rule: {value}.", 0.88))
    for match in re.finditer(r"\bforget\s+(?!that\b)([^.!?]{3,96})", user_text, re.IGNORECASE):
        value = _clean_value(match.group(1), max_len=96)
        key = f"forget_{_slug(value)}"
        if value and key not in seen_forget_keys:
            seen_forget_keys.add(key)
            facts.append((key, value, f"Forget rule: {value}.", 0.88))
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

    for key, value, summary, confidence in _distill_preferences_and_patterns(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="preference",
                key=key,
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=value,
                status=clean_status,
            )
        )

    for key, value, summary, confidence in _distill_commitments(user_text):
        facts.append(
            UserMemoryFact(
                user_id=clean_user_id,
                kind="routine",
                key=key,
                value=value,
                summary=summary,
                confidence=_clamp_confidence(confidence),
                source_doc_id=source_doc_id,
                evidence=value,
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
