"""Background enrichment for owner-scoped personal episodes.

Raw capture is synchronous. Model/provider work runs only in the bounded pump,
using the existing V2 durable observation table and recoverable episode scan.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import sqlite3
import struct
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sci_fi_dashboard.personal_memory import (
    _PREFERENCE_FIELDS,
    PersonalMemoryStore,
    PersonMemoryContext,
    validate_style_control,
)
from sci_fi_dashboard.user_memory import (
    UserMemoryFact,
    ensure_user_memory_facts_table,
    upsert_user_memory_facts,
)
from sci_fi_dashboard.user_memory_distiller_v2 import (
    UserMemoryDistillerV2,
    build_router_extractor,
)

logger = logging.getLogger(__name__)
_STYLE_REEXTRACT_VERSION = "style-control-v1"
_STYLE_REEXTRACT_STATES = (
    "pending", "processing", "classified", "unclassified", "failed", "skipped"
)


class PersonalMemoryService:
    """Owns the durable personal enrichment pump and delivery projection."""

    def __init__(
        self,
        store: PersonalMemoryStore,
        *,
        retry_queue=None,
        extractor=None,
        embedding_provider=None,
        router=None,
        embedding_config: dict | None = None,
        poll_seconds: float = 5.0,
        style_extract_timeout: float = 15.0,
        style_lease_seconds: float = 60.0,
    ):
        if (
            not math.isfinite(style_extract_timeout)
            or not math.isfinite(style_lease_seconds)
            or style_extract_timeout <= 0
            or style_lease_seconds <= style_extract_timeout + 5
        ):
            raise ValueError("style lease must exceed positive extraction timeout by five seconds")
        self.store = store
        self.retry_queue = retry_queue
        self.extractor = extractor or (build_router_extractor(router) if router else None)
        self.embedding_provider = embedding_provider
        self.embedding_config = embedding_config
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.style_extract_timeout = float(style_extract_timeout)
        self.style_lease_seconds = float(style_lease_seconds)
        self._task: asyncio.Task | None = None
        with self.store._connect() as conn:
            UserMemoryDistillerV2(conn)
            conn.execute(
                "UPDATE user_memory_observations SET status='pending' "
                "WHERE status='processing' AND source_episode_id IS NOT NULL"
            )
            conn.executescript(
                """CREATE TABLE IF NOT EXISTS personal_style_reextract_jobs (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     relationship_update_id INTEGER NOT NULL,
                     extractor_version TEXT NOT NULL,
                     owner_key TEXT NOT NULL,
                     status TEXT NOT NULL DEFAULT 'pending',
                     attempt_count INTEGER NOT NULL DEFAULT 0,
                     next_attempt_at TEXT,
                     lease_token TEXT,
                     lease_until TEXT,
                     last_error TEXT,
                     created_at TEXT NOT NULL,
                     completed_at TEXT,
                     UNIQUE(relationship_update_id, extractor_version)
                   );
                   CREATE INDEX IF NOT EXISTS personal_style_reextract_due
                     ON personal_style_reextract_jobs(status,next_attempt_at,lease_until,id);
                """
            )

    def capture_user_turn(
        self,
        context: PersonMemoryContext | None,
        *,
        source_message_id: str,
        content: str,
        occurred_at: datetime | str,
    ) -> str | None:
        episode_id = self.store.capture_episode(
            context,
            source_message_id=source_message_id,
            content=content,
            occurred_at=occurred_at,
        )
        if episode_id and context is not None and context.visibility == "private":
            try:
                self._enqueue_missing_observations(limit=1, episode_id=episode_id)
                self.queue_missing_style_controls(context, limit=4)
            except sqlite3.Error:
                # The durable episode remains available if either queue is unavailable.
                logger.warning("Personal enrichment enqueue deferred; raw episode is durable")
        return episode_id

    @staticmethod
    def _style_owner(context: PersonMemoryContext | None) -> str | None:
        if (
            context is None or context.visibility != "private"
            or not context.person_id or not context.person_id.strip()
        ):
            return None
        return f"person:{context.person_id}"

    def queue_missing_style_controls(
        self, context: PersonMemoryContext | None, *, limit: int = 32
    ) -> int:
        """Queue one bounded page of this verified private owner's legacy style rows."""
        owner = self._style_owner(context)
        if owner is None or limit <= 0:
            return 0
        now = datetime.now(UTC).isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT u.id FROM personal_relationship_updates u
                   JOIN personal_episodes e ON e.episode_id=u.source_episode_id
                     AND e.owner_key=u.owner_key
                   WHERE u.owner_key=? AND e.person_id=? AND e.role='user'
                     AND e.visibility='private' AND e.status='active'
                     AND u.field IN ('tone','verbosity') AND u.style_control IS NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM personal_style_reextract_jobs j
                       WHERE j.relationship_update_id=u.id AND j.extractor_version=?
                     )
                   ORDER BY u.id LIMIT ?""",
                (owner, context.person_id, _STYLE_REEXTRACT_VERSION, min(limit, 32)),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """INSERT OR IGNORE INTO personal_style_reextract_jobs
                       (relationship_update_id,extractor_version,owner_key,created_at)
                       VALUES (?,?,?,?)""",
                    (row["id"], _STYLE_REEXTRACT_VERSION, owner, now),
                )
        return len(rows)

    def style_reextract_status(self, context: PersonMemoryContext | None) -> dict[str, int]:
        """Return counts only for the verified private owner and current version."""
        counts = dict.fromkeys(_STYLE_REEXTRACT_STATES, 0)
        owner = self._style_owner(context)
        if owner is None:
            return counts
        with self.store._connect() as conn:
            rows = conn.execute(
                """SELECT status,COUNT(*) AS total FROM personal_style_reextract_jobs
                   WHERE owner_key=? AND extractor_version=? GROUP BY status""",
                (owner, _STYLE_REEXTRACT_VERSION),
            ).fetchall()
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = int(row["total"])
        return counts

    def _claim_style_reextract(self, owner: str | None) -> dict | None:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT j.*,u.owner_key AS row_owner,u.field,u.value,u.evidence,
                          u.explicit,u.style_control,e.episode_id,e.owner_key AS episode_owner,
                          e.person_id,
                          e.conversation_id,e.content,e.role,e.visibility,e.status AS episode_status
                   FROM personal_style_reextract_jobs j
                   LEFT JOIN personal_relationship_updates u ON u.id=j.relationship_update_id
                   LEFT JOIN personal_episodes e ON e.episode_id=u.source_episode_id
                   WHERE j.extractor_version=? AND (? IS NULL OR j.owner_key=?)
                     AND ((j.status='pending' AND
                           (j.next_attempt_at IS NULL OR j.next_attempt_at<=?))
                       OR (j.status='processing' AND j.lease_until<=?))
                   ORDER BY j.id LIMIT 1""",
                (_STYLE_REEXTRACT_VERSION, owner, owner, now_iso, now_iso),
            ).fetchone()
            if row is None:
                return None
            job = dict(row)
            eligible = (
                job["row_owner"] == job["owner_key"]
                and job["episode_owner"] == job["owner_key"]
                and job["person_id"] is not None
                and job["owner_key"] == f"person:{job['person_id']}"
                and job["role"] == "user" and job["visibility"] == "private"
                and job["episode_status"] == "active"
                and job["field"] in {"tone", "verbosity"}
                and job["style_control"] is None
            )
            if not eligible:
                conn.execute(
                    """UPDATE personal_style_reextract_jobs
                       SET status='skipped',lease_token=NULL,lease_until=NULL,completed_at=?
                       WHERE id=?""",
                    (now_iso, job["id"]),
                )
                return {"skipped": True}
            token = uuid.uuid4().hex
            lease_until = (now + timedelta(seconds=self.style_lease_seconds)).isoformat()
            conn.execute(
                """UPDATE personal_style_reextract_jobs
                   SET status='processing',attempt_count=attempt_count+1,
                       lease_token=?,lease_until=?,last_error=NULL
                   WHERE id=?""",
                (token, lease_until, job["id"]),
            )
            job["lease_token"] = token
            return job

    @staticmethod
    def _style_observation(job: dict) -> dict:
        return {
            "text": job["content"],
            "source_episode_id": job["episode_id"],
            "owner_key": job["owner_key"],
            "person_context_json": json.dumps(asdict(PersonMemoryContext(
                job["person_id"], job["conversation_id"], "private"
            ))),
            "style_backfill_target": {
                "relationship_update_id": job["relationship_update_id"],
                "field": job["field"], "value": job["value"],
                "evidence": job["evidence"], "explicit": bool(job["explicit"]),
            },
        }

    def _finish_style_reextract(self, job: dict, control: str | None) -> str:
        now = datetime.now(UTC).isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """SELECT j.status,j.lease_token,j.lease_until,u.owner_key,u.style_control,
                          u.field,u.value,u.evidence,u.source_episode_id,
                          e.owner_key AS episode_owner,e.person_id,e.role,
                          e.visibility,e.status AS episode_status
                   FROM personal_style_reextract_jobs j
                   LEFT JOIN personal_relationship_updates u ON u.id=j.relationship_update_id
                   LEFT JOIN personal_episodes e ON e.episode_id=u.source_episode_id
                   WHERE j.id=?""",
                (job["id"],),
            ).fetchone()
            if (
                current is None or current["status"] != "processing"
                or current["lease_token"] != job["lease_token"]
                or not current["lease_until"] or current["lease_until"] <= now
            ):
                return "stale"
            eligible = (
                current["owner_key"] == job["owner_key"]
                and current["episode_owner"] == job["owner_key"]
                and current["person_id"] == job["person_id"]
                and current["role"] == "user" and current["visibility"] == "private"
                and current["episode_status"] == "active"
                and current["field"] == job["field"]
                and current["value"] == job["value"]
                and current["evidence"] == job["evidence"]
                and current["source_episode_id"] == job["episode_id"]
                and current["style_control"] is None
            )
            if not eligible:
                status = "skipped"
            elif control is None:
                status = "unclassified"
            else:
                updated = conn.execute(
                    """UPDATE personal_relationship_updates SET style_control=?
                       WHERE id=? AND owner_key=? AND field=? AND style_control IS NULL
                         AND EXISTS (
                           SELECT 1 FROM personal_episodes e
                           WHERE e.episode_id=personal_relationship_updates.source_episode_id
                             AND e.owner_key=? AND e.person_id=? AND e.role='user'
                             AND e.visibility='private' AND e.status='active'
                         )""",
                    (control, job["relationship_update_id"], job["owner_key"],
                     job["field"], job["owner_key"], job["person_id"]),
                ).rowcount
                status = "classified" if updated else "skipped"
                if updated:
                    conn.execute(
                        """INSERT INTO personal_relationship_versions(owner_key,version)
                           VALUES (?,1) ON CONFLICT(owner_key)
                           DO UPDATE SET version=version+1""",
                        (job["owner_key"],),
                    )
            conn.execute(
                """UPDATE personal_style_reextract_jobs
                   SET status=?,lease_token=NULL,lease_until=NULL,completed_at=?,last_error=NULL
                   WHERE id=? AND status='processing' AND lease_token=?""",
                (status, now, job["id"], job["lease_token"]),
            )
        return status

    def _fail_style_reextract(self, job: dict, error_type: str) -> None:
        now = datetime.now(UTC)
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT attempt_count FROM personal_style_reextract_jobs
                   WHERE id=? AND status='processing' AND lease_token=? AND lease_until>?""",
                (job["id"], job["lease_token"], now.isoformat()),
            ).fetchone()
            if row is None:
                return
            failed = row["attempt_count"] >= 3
            retry_at = None if failed else (
                now + timedelta(seconds=10 * 2 ** (row["attempt_count"] - 1))
            ).isoformat()
            conn.execute(
                """UPDATE personal_style_reextract_jobs
                   SET status=?,next_attempt_at=?,lease_token=NULL,lease_until=NULL,
                       last_error=?,completed_at=? WHERE id=? AND lease_token=?""",
                ("failed" if failed else "pending", retry_at, error_type,
                 now.isoformat() if failed else None, job["id"], job["lease_token"]),
            )

    async def _process_style_reextract_once(
        self, owner: str | None, *, limit: int = 4
    ) -> dict[str, int]:
        counts = dict.fromkeys(_STYLE_REEXTRACT_STATES, 0)
        if self.extractor is None or limit <= 0:
            return counts
        for _ in range(min(limit, 8)):
            job = self._claim_style_reextract(owner)
            if job is None:
                break
            if job.get("skipped"):
                counts["skipped"] += 1
                continue
            try:
                observation = self._style_observation(job)

                async def extract_style(observation=observation):
                    if inspect.iscoroutinefunction(self.extractor):
                        value = self.extractor(observation)
                    else:
                        value = await asyncio.to_thread(self.extractor, observation)
                    return await value if inspect.isawaitable(value) else value

                result = await asyncio.wait_for(
                    extract_style(), timeout=self.style_extract_timeout
                )
                payload = json.loads(result) if isinstance(result, str) else result
                if not isinstance(payload, dict) or set(payload) != {"style_control"}:
                    raise ValueError("style extractor must return only style_control")
                control = payload["style_control"]
                if control is not None:
                    control = validate_style_control(job["field"], control)
                outcome = self._finish_style_reextract(job, control)
                if outcome in counts:
                    counts[outcome] += 1
            except Exception as exc:
                self._fail_style_reextract(job, type(exc).__name__)
        return counts

    async def process_style_reextract_once(
        self, context: PersonMemoryContext | None, *, limit: int = 4
    ) -> dict[str, int]:
        """Run a bounded owner-scoped batch; the background pump uses queued jobs."""
        owner = self._style_owner(context)
        if owner is None:
            return dict.fromkeys(_STYLE_REEXTRACT_STATES, 0)
        return await self._process_style_reextract_once(owner, limit=limit)

    def _enqueue_missing_observations(
        self, *, limit: int = 8, episode_id: str | None = None
    ) -> int:
        with self.store._connect() as conn:
            distiller = UserMemoryDistillerV2(conn)
            rows = conn.execute(
                """SELECT e.* FROM personal_episodes e
                   WHERE e.role='user' AND e.visibility='private'
                   AND (? IS NULL OR e.episode_id=?)
                   AND NOT EXISTS (
                       SELECT 1 FROM user_memory_observations o
                       WHERE o.owner_key=e.owner_key AND o.source_episode_id=e.episode_id
                   ) ORDER BY e.recorded_at LIMIT ?""",
                (episode_id, episode_id, max(1, min(limit, 8))),
            ).fetchall()
            for row in rows:
                distiller.enqueue(
                    user_id=row["person_id"],
                    text=row["content"],
                    source_doc_id=None,
                    source_episode_id=row["episode_id"],
                    person_context=asdict(
                        PersonMemoryContext(
                            row["person_id"], row["conversation_id"], row["visibility"]
                        )
                    ),
                )
            return len(rows)

    async def process_pending_once(self, *, limit: int = 8) -> int:
        """Process at most one model extraction at a time; retry errors durably."""
        self._reconcile_outbox(limit=limit)
        self._enqueue_missing_observations(limit=limit)
        await self._embed_pending(limit=limit)
        if self.extractor is None:
            return 0
        processed = 0
        for _ in range(max(1, min(limit, 8))):
            row = self._claim_observation()
            if row is None:
                break
            try:
                result = self.extractor(row)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=15.0)
                payload = json.loads(result) if isinstance(result, str) else result
                if not isinstance(payload, dict):
                    raise ValueError("extractor output must be a JSON object")
                self._apply_payload(row, payload)
                processed += 1
            except Exception as exc:
                self._mark_extract_failure(row["id"], type(exc).__name__)
        return processed

    def _provider(self):
        if self.embedding_provider is not None:
            return self.embedding_provider
        if self.embedding_config is None:
            return None
        from sci_fi_dashboard.embedding.factory import create_provider

        config = dict(self.embedding_config)
        embedding = dict(config.get("embedding") or {})
        if not embedding.get("provider") or embedding.get("provider") == "auto":
            embedding["provider"] = "fastembed"
        config["embedding"] = embedding
        try:
            self.embedding_provider = create_provider(config)
        except (ImportError, RuntimeError):
            logger.warning("Personal embeddings unavailable; lexical recall remains active")
            self.embedding_config = None
        return self.embedding_provider

    @staticmethod
    def _valid_vector(vector, dimensions: int) -> list[float] | None:
        if not isinstance(vector, (list, tuple)) or len(vector) != dimensions:
            return None
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError):
            return None
        norm = math.sqrt(sum(value * value for value in values))
        if not norm or not math.isfinite(norm) or not all(math.isfinite(v) for v in values):
            return None
        return [value / norm for value in values]

    async def _embed_pending(self, *, limit: int = 8) -> None:
        provider = self._provider()
        if provider is None:
            return
        info = provider.info()
        dimensions = int(info.dimensions)
        fingerprint = f"{info.name}:{info.model}:{dimensions}"
        now = datetime.now(UTC).isoformat()
        with self.store._connect() as conn:
            rows = conn.execute(
                """SELECT episode_id,content FROM personal_episodes
                   WHERE status='active' AND (role='user' OR delivery_state IN ('accepted','returned'))
                   AND (embedding_status='pending'
                        OR (embedding_status='ready' AND embedding_model!=?)
                        OR (embedding_status='error' AND embedding_next_attempt_at<=?))
                   ORDER BY recorded_at,episode_id LIMIT ?""",
                (fingerprint, now, max(1, min(limit, 8))),
            ).fetchall()
        if not rows:
            return
        try:
            vectors = await asyncio.wait_for(
                asyncio.to_thread(provider.embed_documents, [row["content"] for row in rows]),
                timeout=15.0,
            )
            if len(vectors) != len(rows):
                raise ValueError("embedding provider returned an incomplete batch")
        except Exception:
            vectors = [None] * len(rows)
        with self.store._connect() as conn:
            for row, raw in zip(rows, vectors, strict=True):
                vector = self._valid_vector(raw, dimensions)
                if vector is None:
                    conn.execute(
                        """UPDATE personal_episodes SET embedding_status='error',
                           embedding_attempts=embedding_attempts+1,
                           embedding_next_attempt_at=? WHERE episode_id=?""",
                        ((datetime.now(UTC) + timedelta(minutes=5)).isoformat(), row["episode_id"]),
                    )
                    continue
                conn.execute(
                    """UPDATE personal_episodes SET embedding=?,embedding_model=?,
                       embedding_dimensions=?,embedding_status='ready',
                       embedding_next_attempt_at=NULL WHERE episode_id=?""",
                    (struct.pack(f"<{dimensions}f", *vector), fingerprint, dimensions, row["episode_id"]),
                )

    async def recall(
        self, context: PersonMemoryContext | None, query: str, *, limit: int = 3,
        exclude_episode_id: str | None = None,
    ):
        if context is None:
            return []
        provider = self._provider()
        vector = None
        fingerprint = None
        if provider is not None:
            try:
                info = provider.info()
                dimensions = int(info.dimensions)
                raw = await asyncio.wait_for(
                    asyncio.to_thread(provider.embed_query, query), timeout=2.0
                )
                vector = self._valid_vector(raw, dimensions)
                if vector is not None:
                    fingerprint = f"{info.name}:{info.model}:{dimensions}"
            except Exception:
                logger.warning("Personal query embedding unavailable; lexical recall used")
        return self.store.recall(
            context, query, limit=limit,
            query_embedding=vector, embedding_model=fingerprint,
            exclude_episode_id=exclude_episode_id,
        )

    def _claim_observation(self) -> dict | None:
        now = datetime.now(UTC).isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT o.*,e.occurred_at,e.recorded_at FROM user_memory_observations o
                   JOIN personal_episodes e ON e.episode_id=o.source_episode_id
                   AND e.owner_key=o.owner_key AND e.role='user'
                   WHERE o.source_episode_id IS NOT NULL AND o.status='pending'
                   AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=?)
                   ORDER BY o.id LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE user_memory_observations SET status='processing',attempt_count=attempt_count+1 WHERE id=?",
                (row["id"],),
            )
            result = dict(row)
            result["attempt_count"] += 1
            return result

    def _mark_extract_failure(self, observation_id: int, error_type: str) -> None:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT attempt_count FROM user_memory_observations WHERE id=?",
                (observation_id,),
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempt_count"])
            failed = attempts >= 3
            retry_at = None if failed else (
                datetime.now(UTC) + timedelta(seconds=10 * (2 ** (attempts - 1)))
            ).isoformat()
            conn.execute(
                """UPDATE user_memory_observations
                   SET status=?,next_attempt_at=?,last_error=? WHERE id=?""",
                ("failed" if failed else "pending", retry_at, error_type, observation_id),
            )

    def _apply_payload(self, observation: dict, payload: dict) -> None:
        context_data = json.loads(observation["person_context_json"])
        context = PersonMemoryContext(**context_data)
        source_id = observation["source_episode_id"]
        if context.visibility != "private" or observation["owner_key"] != f"person:{context.person_id}":
            raise ValueError("personal observation scope mismatch")
        updates = payload.get("relationship_updates", [])
        if not isinstance(updates, list):
            raise ValueError("relationship_updates must be a list")
        fact_items = payload.get("confirmed_facts", [])
        if not isinstance(fact_items, list):
            raise ValueError("confirmed_facts must be a list")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ensure_user_memory_facts_table(conn)
            source_owner, _source = self.store._validated_update_source(
                context, source_id, observation["text"], conn=conn
            )
            if source_owner != observation["owner_key"]:
                raise ValueError("personal observation owner mismatch")
            prepared = []
            for item in updates:
                if not isinstance(item, dict):
                    raise ValueError("invalid relationship update")
                field, value, evidence, mode = (
                    item.get("field"), item.get("value"), item.get("evidence"), item.get("mode")
                )
                if field not in _PREFERENCE_FIELDS or not isinstance(value, str) or not value.strip() or len(value) > 120:
                    raise ValueError("invalid relationship field or value")
                self.store._validated_update_source(context, source_id, evidence, conn=conn)
                style_control = (
                    validate_style_control(field, item["style_control"])
                    if "style_control" in item else None
                )
                if mode == "explicit":
                    prepared.append((True, field, value, evidence, None, style_control))
                elif mode == "inferred":
                    confidence = item.get("confidence")
                    if (
                        not isinstance(confidence, (float, int))
                        or not math.isfinite(confidence)
                        or not 0 <= confidence <= 1
                    ):
                        raise ValueError("invalid inference confidence")
                    prepared.append((False, field, value, evidence, confidence, style_control))
                else:
                    raise ValueError("unsupported relationship update mode")
            prepared_facts: list[UserMemoryFact] = []
            for item in fact_items:
                if not isinstance(item, dict):
                    raise ValueError("invalid confirmed fact")
                kind, key, value, summary, evidence = (
                    item.get("kind"), item.get("key"), item.get("value"),
                    item.get("summary"), item.get("evidence"),
                )
                if any(not isinstance(value_, str) or not value_.strip() for value_ in (
                    kind, key, value, summary, evidence
                )) or any(len(value_) > max_len for value_, max_len in (
                    (kind, 64), (key, 96), (value, 512), (summary, 512), (evidence, 512)
                )):
                    raise ValueError("invalid confirmed fact fields")
                confidence = item.get("confidence")
                if (
                    not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                ):
                    raise ValueError("invalid confirmed fact confidence")
                self.store._validated_update_source(context, source_id, evidence, conn=conn)
                prepared_facts.append(UserMemoryFact(
                    user_id=context.person_id,
                    kind=kind.strip(), key=key.strip(), value=value.strip(),
                    summary=summary.strip(), confidence=float(confidence),
                    source_doc_id=None, evidence=evidence.strip(),
                    source_episode_id=source_id,
                ))
            for explicit, field, value, evidence, confidence, style_control in prepared:
                update_value = {"value": value}
                if style_control is not None:
                    update_value["style_control"] = style_control
                if not explicit:
                    update_value["confidence"] = confidence
                update = {field: update_value}
                self.store._apply_update(
                    context, update, source_episode_id=source_id,
                    evidence=evidence, explicit=explicit, conn=conn,
                )
            for fact in prepared_facts:
                upsert_user_memory_facts(conn, [fact])
            conn.execute(
                """UPDATE user_memory_observations SET status='processed',
                   processed_at=?,last_error=NULL WHERE id=?""",
                (datetime.now(UTC).isoformat(), observation["id"]),
            )

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._pump(), name="personal-memory-enrichment")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _pump(self) -> None:
        while True:
            try:
                await self.process_pending_once(limit=8)
                await self._process_style_reextract_once(None, limit=2)
            except Exception:
                logger.exception("Personal memory enrichment cycle failed")
            await asyncio.sleep(self.poll_seconds)

    def record_assistant_reply(self, context: PersonMemoryContext, **kwargs) -> str:
        return self.store.record_assistant_reply(context, **kwargs)

    def mark_assistant_delivery(self, outbound: dict) -> None:
        """Project a committed terminal outbox receipt into conversational evidence."""
        context_json = outbound.get("personal_context_json")
        parent_id = outbound.get("parent_episode_id")
        if not context_json or not parent_id:
            return
        context = PersonMemoryContext(**json.loads(context_json))
        status = str(outbound.get("status") or "")
        if status not in {"accepted", "cancelled", "dead_letter"}:
            return
        created_at = datetime.fromisoformat(outbound["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        self.store.record_assistant_reply(
            context,
            source_episode_id=parent_id,
            source_message_id=outbound["message_key"],
            content=outbound["text"],
            occurred_at=created_at,
            delivery_state="pending",
        )
        self.store.update_assistant_delivery(
            context,
            source_message_id=outbound["message_key"],
            delivery_state="failed" if status == "dead_letter" else status,
        )
        if self.retry_queue is not None:
            with sqlite3.connect(self.retry_queue._db_path) as conn:
                conn.execute(
                    "UPDATE retry_queue SET personal_projected_at=? WHERE id=? AND status=?",
                    (datetime.now(UTC).isoformat(), outbound["id"], status),
                )

    def _reconcile_outbox(self, *, limit: int = 8) -> None:
        if self.retry_queue is None:
            return
        with sqlite3.connect(self.retry_queue._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM retry_queue WHERE personal_context_json IS NOT NULL
                   AND personal_projected_at IS NULL
                   AND status IN ('accepted','cancelled','dead_letter')
                   ORDER BY id LIMIT ?""",
                (max(1, min(limit, 8)),),
            ).fetchall()
        for row in rows:
            try:
                self.mark_assistant_delivery(dict(row))
            except Exception:
                logger.warning("Assistant memory projection deferred for outbox row")
