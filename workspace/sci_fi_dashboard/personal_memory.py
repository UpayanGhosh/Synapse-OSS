"""Owner-scoped, durable user episodes and relationship preferences.

This store deliberately never queries the legacy unowned documents or graph.
The caller, not the model, supplies the verified person/conversation scope.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sci_fi_dashboard.user_memory import _normalized_claim

_PREFERENCE_FIELDS = frozenset({"tone", "verbosity", "humor", "formality", "address_as"})
_STYLE_CONTROLS = {
    "tone": frozenset({
        "professional_precise", "casual_witty", "technical_depth", "creative_playful",
    }),
    "verbosity": frozenset({"concise", "normal", "detailed"}),
}
_WORDS = re.compile(r"[\w']+", re.UNICODE)
_STOPWORDS = frozenset(
    {"a", "about", "and", "at", "do", "for", "i", "in", "is", "me", "my", "of", "on", "the", "to", "was", "what", "with", "you"}
)
_WEAK_QUERY_TERMS = frozenset(
    {"details", "happened", "incident", "memory", "recall", "remember", "search", "story", "thing"}
)


def validate_style_control(field: str, control: object) -> str:
    """Validate a model-classified runtime control without interpreting raw prose."""
    allowed = _STYLE_CONTROLS.get(field)
    if not isinstance(control, str) or allowed is None or control not in allowed:
        raise ValueError("invalid style control for relationship field")
    return control


@dataclass(frozen=True)
class PersonMemoryContext:
    person_id: str | None
    conversation_id: str
    visibility: Literal["private", "group"] = "private"


@dataclass(frozen=True)
class RecalledEpisode:
    episode_id: str
    person_id: str | None
    conversation_id: str
    source_message_id: str
    content: str
    occurred_at: str
    recorded_at: str
    visibility: Literal["private", "group"]
    score: float
    status: Literal["active", "superseded"] = "active"
    superseded_by: str | None = None
    role: Literal["user", "assistant"] = "user"
    parent_episode_id: str | None = None
    delivery_state: str | None = None
    occurred_at_source: Literal["received_at", "source_event"] = "received_at"
    corrections: tuple[dict, ...] = ()


@dataclass(frozen=True)
class PersonalizedReply:
    text: str
    person_context: PersonMemoryContext
    source_episode_id: str


def resolve_person_memory_context(
    *,
    channel_id: str | None,
    peer_id: str | None,
    conversation_id: str,
    chat_type: str = "direct",
    identity_links: dict | None = None,
    api_authenticated: bool = False,
    origin: Literal["channel", "api"] = "channel",
) -> PersonMemoryContext | None:
    """Resolve only identities supplied by a trusted channel or authenticated API route."""
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        return None
    if origin == "api":
        if not api_authenticated:
            return None
        person_id = "local-api-owner"
        if identity_links:
            from sci_fi_dashboard.multiuser.identity_linker import resolve_linked_peer_id

            linked = resolve_linked_peer_id(person_id, "api", identity_links, "per-channel-peer")
            if linked:
                person_id = f"linked:{linked.lower().strip()}"
        return PersonMemoryContext(person_id, conversation_id)
    if origin != "channel" or not channel_id:
        return None
    channel = channel_id.strip().lower()
    if not channel:
        return None
    if chat_type in {"group", "channel"}:
        return PersonMemoryContext(None, conversation_id, "group")
    if chat_type != "direct" or not peer_id or not peer_id.strip():
        return None
    # Match the existing identityLinks format, independent of dmScope=main.
    from sci_fi_dashboard.multiuser.identity_linker import resolve_linked_peer_id

    peer = peer_id.strip().lower()
    linked = resolve_linked_peer_id(peer, channel, identity_links or {}, "per-channel-peer")
    person_id = f"linked:{linked.lower().strip()}" if linked else f"{channel}:{peer}"
    return PersonMemoryContext(person_id, conversation_id)


def scope_conversation_key(
    base_session_key: str,
    context: PersonMemoryContext | None,
    *,
    dm_scope: str = "per-channel-peer",
    agent_id: str = "the_creator",
) -> str:
    """Keep conversation history inside a verified person or group boundary."""
    if context is not None and context.visibility == "group":
        return base_session_key
    owner = _owner_key(context)
    if owner is None:
        return f"anonymous:{uuid.uuid4().hex}"
    digest = hashlib.sha256(context.person_id.encode("utf-8")).hexdigest()
    if dm_scope == "main":
        return f"agent:{agent_id}:person:{digest}:main"
    return f"{base_session_key}:person:{digest}"


def _owner_key(context: PersonMemoryContext | None) -> str | None:
    if context is None:
        return None
    if context.visibility == "group":
        return f"group:{context.conversation_id}" if context.conversation_id.strip() else None
    if context.visibility == "private" and context.person_id and context.person_id.strip():
        return f"person:{context.person_id}"
    return None


def _utc_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be an offset ISO-8601 date-time") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC).isoformat()


def _tokens(value: str) -> set[str]:
    return {word for word in _WORDS.findall(value.casefold()) if len(word) > 2 and word not in _STOPWORDS}


def _normalized_evidence(value: str) -> str:
    return " ".join(value.casefold().split())


class PersonalMemoryStore:
    """SQLite projection sharing the application's existing memory.db."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS personal_episodes (
                    episode_id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    person_id TEXT,
                    conversation_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    superseded_by TEXT,
                    embedding BLOB,
                    embedding_model TEXT,
                    embedding_dimensions INTEGER,
                    embedding_status TEXT NOT NULL DEFAULT 'pending',
                    embedding_attempts INTEGER NOT NULL DEFAULT 0,
                    embedding_next_attempt_at TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    parent_episode_id TEXT,
                    delivery_state TEXT,
                    occurred_at_source TEXT NOT NULL DEFAULT 'received_at',
                    UNIQUE(owner_key, source_message_id)
                );
                CREATE INDEX IF NOT EXISTS personal_episodes_scope
                    ON personal_episodes(owner_key, status, occurred_at);
                CREATE TABLE IF NOT EXISTS personal_relationship_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    explicit INTEGER NOT NULL,
                    confidence REAL,
                    source_episode_id TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    style_control TEXT,
                    UNIQUE(owner_key, field, value, explicit, source_episode_id)
                );
                CREATE INDEX IF NOT EXISTS personal_relationship_owner
                    ON personal_relationship_updates(owner_key, field, explicit);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(personal_episodes)")}
            for name, definition in {
                "role": "TEXT NOT NULL DEFAULT 'user'",
                "parent_episode_id": "TEXT",
                "delivery_state": "TEXT",
                "occurred_at_source": "TEXT NOT NULL DEFAULT 'received_at'",
                "embedding_attempts": "INTEGER NOT NULL DEFAULT 0",
                "embedding_next_attempt_at": "TEXT",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE personal_episodes ADD COLUMN {name} {definition}")
            relationship_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(personal_relationship_updates)")
            }
            if "style_control" not in relationship_columns:
                conn.execute(
                    "ALTER TABLE personal_relationship_updates ADD COLUMN style_control TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def capture_episode(
        self,
        context: PersonMemoryContext | None,
        *,
        source_message_id: str,
        content: str,
        occurred_at: datetime | str,
        recorded_at: datetime | str | None = None,
        occurred_at_source: Literal["received_at", "source_event"] = "received_at",
    ) -> str | None:
        owner = _owner_key(context)
        if owner is None or not content or not content.strip():
            return None
        if not source_message_id or not source_message_id.strip():
            raise ValueError("stable source_message_id is required")
        if occurred_at_source not in {"received_at", "source_event"}:
            raise ValueError("untrusted timestamp source")
        occurred = _utc_iso(occurred_at)
        recorded = _utc_iso(recorded_at or datetime.now(UTC))
        episode_id = hashlib.sha256(f"{owner}\0{source_message_id}".encode()).hexdigest()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM personal_episodes WHERE owner_key=? AND source_message_id=?",
                (owner, source_message_id),
            ).fetchone()
            if existing:
                if (
                    existing["content"] != content
                    or existing["conversation_id"] != context.conversation_id
                    or existing["person_id"] != context.person_id
                    or existing["visibility"] != context.visibility
                ):
                    raise ValueError("source_message_id conflicts with an existing episode")
                return str(existing["episode_id"])
            conn.execute(
                """INSERT INTO personal_episodes
                   (episode_id,owner_key,person_id,conversation_id,source_message_id,
                    content,occurred_at,recorded_at,visibility,occurred_at_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    episode_id, owner, context.person_id, context.conversation_id,
                    source_message_id, content, occurred, recorded, context.visibility,
                    occurred_at_source,
                ),
            )
        return episode_id

    def record_assistant_reply(
        self,
        context: PersonMemoryContext,
        *,
        source_episode_id: str,
        source_message_id: str,
        content: str,
        occurred_at: datetime | str,
        delivery_state: str = "pending",
    ) -> str:
        owner = _owner_key(context)
        if owner is None or not source_message_id or not content.strip():
            raise ValueError("assistant reply requires a scoped source and content")
        if delivery_state not in {"pending", "accepted", "returned"}:
            raise ValueError("invalid initial assistant delivery state")
        occurred = _utc_iso(occurred_at)
        with self._connect() as conn:
            parent = conn.execute(
                "SELECT role FROM personal_episodes WHERE owner_key=? AND episode_id=?",
                (owner, source_episode_id),
            ).fetchone()
            if parent is None or parent["role"] != "user":
                raise ValueError("assistant reply must link to a same-owner user turn")
            episode_id = hashlib.sha256(f"{owner}\0{source_message_id}".encode()).hexdigest()
            existing = conn.execute(
                "SELECT * FROM personal_episodes WHERE owner_key=? AND source_message_id=?",
                (owner, source_message_id),
            ).fetchone()
            if existing:
                if (
                    existing["role"] != "assistant"
                    or existing["parent_episode_id"] != source_episode_id
                    or existing["content"] != content
                    or existing["conversation_id"] != context.conversation_id
                ):
                    raise ValueError("assistant source key conflicts with existing episode")
                return str(existing["episode_id"])
            conn.execute(
                """INSERT INTO personal_episodes
                   (episode_id,owner_key,person_id,conversation_id,source_message_id,
                    content,occurred_at,recorded_at,visibility,role,parent_episode_id,
                    delivery_state,embedding_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending')""",
                (
                    episode_id, owner, context.person_id, context.conversation_id,
                    source_message_id, content, occurred, datetime.now(UTC).isoformat(),
                    context.visibility, "assistant", source_episode_id, delivery_state,
                ),
            )
        return episode_id

    def update_assistant_delivery(
        self,
        context: PersonMemoryContext,
        *,
        source_message_id: str,
        delivery_state: Literal["accepted", "cancelled", "failed"],
    ) -> None:
        owner = _owner_key(context)
        if owner is None or delivery_state not in {"accepted", "cancelled", "failed"}:
            raise ValueError("invalid assistant delivery update")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role,delivery_state FROM personal_episodes WHERE owner_key=? AND source_message_id=?",
                (owner, source_message_id),
            ).fetchone()
            if row is None or row["role"] != "assistant":
                raise ValueError("assistant source is missing or belongs to another owner")
            if row["delivery_state"] == "accepted" and delivery_state != "accepted":
                return
            conn.execute(
                "UPDATE personal_episodes SET delivery_state=? WHERE owner_key=? AND source_message_id=?",
                (delivery_state, owner, source_message_id),
            )

    def recall(
        self,
        context: PersonMemoryContext | None,
        query: str,
        *,
        limit: int = 3,
        include_history: bool = False,
        query_embedding: list[float] | None = None,
        embedding_model: str | None = None,
        exclude_episode_id: str | None = None,
    ) -> list[RecalledEpisode]:
        owner = _owner_key(context)
        query_words = _tokens(query)
        if owner is None or (not query_words and query_embedding is None) or limit <= 0:
            return []
        # SQL scope is mandatory before ranking. Legacy unowned rows are invisible.
        with self._connect() as conn:
            sql = (
                """SELECT e.*,p.status AS parent_status,p.superseded_by AS parent_superseded_by
                   FROM personal_episodes e LEFT JOIN personal_episodes p
                   ON p.episode_id=e.parent_episode_id AND p.owner_key=e.owner_key
                   WHERE e.owner_key=?
                   AND (e.role='user' OR e.delivery_state IN ('accepted','returned'))"""
            )
            params: list[str] = [owner]
            if exclude_episode_id is not None:
                sql += " AND e.episode_id!=?"
                params.append(exclude_episode_id)
            if not include_history:
                sql += " AND e.status='active' AND (e.parent_episode_id IS NULL OR p.status='active')"
            rows = conn.execute(
                sql, params,
            ).fetchall()
            corrections: dict[str, list[dict]] = {}
            if context.visibility == "private" and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_fact_support'"
            ).fetchone():
                supports = conn.execute(
                    """SELECT s.source_episode_id,s.kind,s.key,s.value,s.evidence,
                              f.value AS current_value,
                              f.source_episode_id AS current_source_episode_id,
                              current_episode.occurred_at AS current_occurred_at
                       FROM personal_fact_support s
                       JOIN user_memory_facts f ON f.user_id=? AND f.kind=s.kind AND f.key=s.key
                       JOIN personal_episodes current_episode
                         ON current_episode.episode_id=f.source_episode_id
                        AND current_episode.owner_key=s.owner_key
                       WHERE s.owner_key=? AND f.status='active'
                         AND s.source_episode_id!=f.source_episode_id
                       ORDER BY s.kind,s.key""",
                    (context.person_id, owner),
                ).fetchall()
                for support in supports:
                    if _normalized_claim(support["value"]) == _normalized_claim(
                        support["current_value"]
                    ):
                        continue
                    corrections.setdefault(support["source_episode_id"], []).append({
                        "kind": support["kind"],
                        "key": support["key"],
                        "obsolete_evidence": support["evidence"],
                        "current_value": support["current_value"],
                        "current_source_episode_id": support["current_source_episode_id"],
                        "current_occurred_at": support["current_occurred_at"],
                    })
        ranked: list[RecalledEpisode] = []
        weak_ranked: list[RecalledEpisode] = []
        for row in rows:
            words = _tokens(row["content"])
            overlap = len(query_words & words)
            lexical_score = (
                overlap / math.sqrt(len(query_words) * max(len(words), 1))
                if overlap and query_words else 0.0
            )
            semantic_score = 0.0
            blob = row["embedding"]
            if (
                query_embedding is not None
                and embedding_model is not None
                and row["embedding_model"] == embedding_model
                and row["embedding_dimensions"] == len(query_embedding)
                and blob is not None
                and len(blob) == 4 * len(query_embedding)
            ):
                vector = struct.unpack(f"<{len(query_embedding)}f", blob)
                norm = math.sqrt(sum(value * value for value in vector))
                if norm > 0 and math.isfinite(norm):
                    cosine = sum(a * b for a, b in zip(query_embedding, vector, strict=True)) / norm
                    if math.isfinite(cosine):
                        semantic_score = max(0.0, cosine)
            if lexical_score <= 0 and semantic_score < 0.62:
                continue
            score = max(lexical_score, semantic_score * 0.9)
            weak_match = overlap == 1 and len(query_words) > 2 and semantic_score < 0.62
            if weak_match and next(iter(query_words & words)) in _WEAK_QUERY_TERMS:
                continue
            (weak_ranked if weak_match else ranked).append(
                RecalledEpisode(
                    row["episode_id"], row["person_id"], row["conversation_id"],
                    row["source_message_id"], row["content"], row["occurred_at"],
                    row["recorded_at"], row["visibility"], score,
                    ("superseded" if row["parent_status"] == "superseded" else row["status"]),
                    (row["parent_superseded_by"] if row["parent_status"] == "superseded"
                     else row["superseded_by"]),
                    row["role"],
                    row["parent_episode_id"], row["delivery_state"],
                    row["occurred_at_source"],
                    tuple(corrections.get(row["parent_episode_id"] or row["episode_id"], ())),
                )
            )
        ranked.sort(key=lambda item: (item.score, item.occurred_at), reverse=True)
        selected = ranked[: min(limit, 8)]
        if len(selected) >= min(limit, 8) or not weak_ranked:
            return selected
        weak_ranked.sort(key=lambda item: (item.score, item.occurred_at), reverse=True)
        return [*selected, weak_ranked[0]]

    def get_scoped_facts(self, context: PersonMemoryContext | None) -> list[dict]:
        """Read only active, provenance-backed facts for a verified private owner."""
        owner = _owner_key(context)
        if context is None or context.visibility != "private" or owner is None:
            return []
        with self._connect() as conn:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_memory_facts'"
            ).fetchone() is None:
                return []
            rows = conn.execute(
                """SELECT f.kind,f.key,f.value,f.summary,f.confidence,f.evidence,
                          f.source_episode_id,f.status,e.occurred_at
                   FROM user_memory_facts f
                   JOIN personal_episodes e ON e.episode_id=f.source_episode_id
                   WHERE f.user_id=? AND e.owner_key=? AND e.person_id=?
                     AND e.role='user' AND e.visibility='private'
                     AND e.status='active' AND f.status='active'
                   ORDER BY e.occurred_at DESC,e.recorded_at DESC,f.id DESC LIMIT 32""",
                (context.person_id, owner, context.person_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _validated_update_source(
        self, context: PersonMemoryContext, source_episode_id: str, evidence: str,
        *, conn: sqlite3.Connection | None = None,
    ) -> tuple[str, sqlite3.Row]:
        owner = _owner_key(context)
        if context.visibility != "private" or owner is None:
            raise ValueError("relationship updates require a verified private owner")
        if conn is None:
            with self._connect() as owned:
                return self._validated_update_source(
                    context, source_episode_id, evidence, conn=owned
                )
        episode = conn.execute(
            "SELECT * FROM personal_episodes WHERE owner_key=? AND episode_id=?",
            (owner, source_episode_id),
        ).fetchone()
        if (
            episode is None
            or episode["role"] != "user"
            or not evidence
            or _normalized_evidence(evidence) not in _normalized_evidence(episode["content"])
        ):
            raise ValueError("relationship update lacks same-owner user evidence")
        return owner, episode

    def _relationship(self, owner: str, *, conn: sqlite3.Connection | None = None) -> dict:
        if conn is None:
            with self._connect() as owned:
                return self._relationship(owner, conn=owned)
        rows = conn.execute(
            """SELECT u.*, e.status AS episode_status
               FROM personal_relationship_updates u
               JOIN personal_episodes e ON e.episode_id=u.source_episode_id
               WHERE u.owner_key=? ORDER BY u.occurred_at,u.recorded_at,u.id""",
            (owner,),
        ).fetchall()
        explicit: dict[str, sqlite3.Row] = {}
        candidates: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            if row["episode_status"] != "active":
                continue
            if row["explicit"]:
                explicit[row["field"]] = row
            elif row["confidence"] is not None and row["confidence"] >= 0.7:
                agreement_key = row["style_control"] or row["value"]
                candidates.setdefault((row["field"], agreement_key), []).append(row)
        inferred: dict[str, dict] = {}
        for (field, agreement_key), supporting in candidates.items():
            if field in explicit or len({row["source_episode_id"] for row in supporting}) < 2:
                continue
            newest = supporting[-1]
            current = inferred.get(field)
            if current and current["updated_at"] >= newest["recorded_at"]:
                continue
            inferred[field] = {
                "value": newest["value"],
                "confidence": min(row["confidence"] for row in supporting[-2:]),
                "source_episode_ids": [row["source_episode_id"] for row in supporting],
                "updated_at": newest["recorded_at"],
            }
            if newest["style_control"]:
                inferred[field]["style_control"] = agreement_key
        runtime_style: dict[str, str] = {}
        for field in ("tone", "verbosity"):
            explicit_row = explicit.get(field)
            if explicit_row is not None:
                if explicit_row["style_control"]:
                    runtime_style[field] = explicit_row["style_control"]
                continue
            inferred_row = inferred.get(field)
            if inferred_row and inferred_row.get("style_control"):
                runtime_style[field] = inferred_row["style_control"]
        return {
            "preferences": {field: row["value"] for field, row in explicit.items()},
            "inferred": inferred,
            "runtime_style": runtime_style,
        }

    def get_relationship(self, context: PersonMemoryContext | None) -> dict:
        owner = _owner_key(context)
        if owner is None or context.visibility != "private":
            return {"version": 0, "preferences": {}, "inferred": {}, "runtime_style": {}}
        with self._connect() as conn:
            return self._get_relationship_in_tx(context, conn)

    def _get_relationship_in_tx(self, context: PersonMemoryContext, conn: sqlite3.Connection) -> dict:
        owner = _owner_key(context)
        self._ensure_versions_table(conn)
        row = conn.execute(
            "SELECT version FROM personal_relationship_versions WHERE owner_key=?", (owner,)
        ).fetchone()
        result = self._relationship(owner, conn=conn)
        return {"version": int(row["version"]) if row else 0, **result}

    @staticmethod
    def _has_versions_table(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_relationship_versions'"
        ).fetchone() is not None

    def _ensure_versions_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS personal_relationship_versions (owner_key TEXT PRIMARY KEY,version INTEGER NOT NULL)"
        )

    def _apply_update(
        self, context: PersonMemoryContext, updates: dict, *,
        source_episode_id: str, evidence: str, explicit: bool,
        conn: sqlite3.Connection | None = None,
    ) -> dict:
        if conn is None:
            with self._connect() as owned:
                return self._apply_update(
                    context, updates, source_episode_id=source_episode_id,
                    evidence=evidence, explicit=explicit, conn=owned,
                )
        owner, episode = self._validated_update_source(
            context, source_episode_id, evidence, conn=conn
        )
        if not isinstance(updates, dict):
            raise ValueError("updates must be a mapping")
        if not updates:
            return self._get_relationship_in_tx(context, conn)
        prepared = []
        for field, item in updates.items():
            if field not in _PREFERENCE_FIELDS:
                raise ValueError("unsupported relationship field")
            value = item.get("value") if isinstance(item, dict) else item
            confidence = None if explicit else item.get("confidence") if isinstance(item, dict) else None
            if not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise ValueError("relationship value must be 1-120 characters")
            if not explicit and (
                not isinstance(confidence, (float, int))
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("inference confidence must be finite and in [0,1]")
            style_control = None
            if isinstance(item, dict) and "style_control" in item:
                style_control = validate_style_control(field, item["style_control"])
            prepared.append((field, value.strip(), confidence, style_control))
        before = self._get_relationship_in_tx(context, conn)
        for field, value, confidence, style_control in prepared:
            existing = conn.execute(
                    """SELECT u.*,e.occurred_at AS source_time FROM personal_relationship_updates u
                       JOIN personal_episodes e ON e.episode_id=u.source_episode_id
                       WHERE u.owner_key=? AND u.field=? AND u.explicit=?
                       ORDER BY e.occurred_at DESC,e.recorded_at DESC,u.id DESC LIMIT 1""",
                    (owner, field, int(explicit)),
            ).fetchone()
            # A late old extraction may be stored as history, never override a newer source.
            conn.execute(
                """INSERT INTO personal_relationship_updates
                   (owner_key,field,value,explicit,confidence,source_episode_id,evidence,
                    occurred_at,recorded_at,style_control)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(owner_key,field,value,explicit,source_episode_id)
                   DO UPDATE SET style_control=excluded.style_control
                   WHERE personal_relationship_updates.style_control IS NULL
                     AND excluded.style_control IS NOT NULL""",
                (owner, field, value, int(explicit), confidence, source_episode_id,
                 evidence, episode["occurred_at"], episode["recorded_at"], style_control),
            )
            if (
                explicit
                and existing
                and existing["source_episode_id"] != source_episode_id
                and (episode["occurred_at"], episode["recorded_at"])
                > (existing["occurred_at"], existing["recorded_at"])
                and (existing["value"] != value or existing["style_control"] != style_control)
            ):
                conn.execute(
                    "UPDATE personal_episodes SET status='superseded',superseded_by=? WHERE episode_id=?",
                    (source_episode_id, existing["source_episode_id"]),
                )
        after = self._relationship(owner, conn=conn)
        if (
            before["preferences"], before["inferred"], before["runtime_style"]
        ) != (
            after["preferences"], after["inferred"], after["runtime_style"]
        ):
            conn.execute(
                """INSERT INTO personal_relationship_versions(owner_key,version) VALUES (?,1)
                   ON CONFLICT(owner_key) DO UPDATE SET version=version+1""",
                (owner,),
            )
        return self._get_relationship_in_tx(context, conn)

    def apply_relationship_update(
        self, context: PersonMemoryContext, updates: dict[str, str | dict], *,
        source_episode_id: str, evidence: str,
    ) -> dict:
        return self._apply_update(
            context, updates, source_episode_id=source_episode_id, evidence=evidence, explicit=True
        )

    def apply_inferred_relationship_update(
        self, context: PersonMemoryContext, updates: dict[str, dict], *,
        source_episode_id: str, evidence: str,
    ) -> dict:
        return self._apply_update(
            context, updates, source_episode_id=source_episode_id, evidence=evidence, explicit=False
        )


def __getattr__(name: str):
    if name == "PersonalMemoryService":
        from sci_fi_dashboard.personal_memory_service import PersonalMemoryService

        return PersonalMemoryService
    raise AttributeError(name)
