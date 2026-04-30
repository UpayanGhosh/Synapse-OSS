"""Approval-gated self-evolution recommendations.

This layer notices repeated workflows and proposes new skills/config changes.
It never installs or mutates behavior by itself; recommendations require
explicit user approval.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SelfEvolutionRecommendation:
    user_id: str
    workflow_key: str
    summary: str
    suggested_skill: str
    evidence_count: int
    requires_approval: bool = True


def ensure_self_evolution_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS self_evolution_workflows (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            workflow_key    TEXT NOT NULL,
            summary         TEXT NOT NULL,
            suggested_skill TEXT NOT NULL,
            evidence_count  INTEGER NOT NULL DEFAULT 0,
            last_evidence   TEXT,
            first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, workflow_key)
        );
        CREATE INDEX IF NOT EXISTS idx_self_evolution_workflows_ready
            ON self_evolution_workflows(user_id, evidence_count);

        CREATE TABLE IF NOT EXISTS self_evolution_recommendations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            workflow_key    TEXT NOT NULL,
            summary         TEXT NOT NULL,
            suggested_skill TEXT NOT NULL,
            evidence_count  INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'pending_approval',
            requires_approval INTEGER NOT NULL DEFAULT 1,
            install_applied INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at     TIMESTAMP,
            UNIQUE(user_id, workflow_key, status)
        );
        CREATE INDEX IF NOT EXISTS idx_self_evolution_recommendations_status
            ON self_evolution_recommendations(user_id, status);
        """
    )


class SelfEvolutionTracker:
    def __init__(self, conn: sqlite3.Connection, *, recommendation_threshold: int = 3) -> None:
        self.conn = conn
        self.recommendation_threshold = int(recommendation_threshold)
        ensure_self_evolution_tables(conn)

    def record_workflow(
        self,
        *,
        user_id: str,
        workflow_key: str,
        summary: str,
        suggested_skill: str,
        evidence: str,
    ) -> None:
        clean = {
            "user_id": _required(user_id, "user_id"),
            "workflow_key": _required(workflow_key, "workflow_key"),
            "summary": _required(summary, "summary"),
            "suggested_skill": _required(suggested_skill, "suggested_skill"),
            "evidence": str(evidence or "").strip()[:500],
        }
        self.conn.execute(
            """
            INSERT INTO self_evolution_workflows
                (user_id, workflow_key, summary, suggested_skill, evidence_count, last_evidence)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, workflow_key) DO UPDATE SET
                summary = excluded.summary,
                suggested_skill = excluded.suggested_skill,
                evidence_count = self_evolution_workflows.evidence_count + 1,
                last_evidence = excluded.last_evidence,
                last_seen = CURRENT_TIMESTAMP
            """,
            (
                clean["user_id"],
                clean["workflow_key"],
                clean["summary"],
                clean["suggested_skill"],
                clean["evidence"],
            ),
        )
        self.conn.commit()

    def recommend_pending(self, *, user_id: str) -> list[SelfEvolutionRecommendation]:
        clean_user_id = _required(user_id, "user_id")
        rows = self.conn.execute(
            """
            SELECT user_id, workflow_key, summary, suggested_skill, evidence_count
            FROM self_evolution_workflows wf
            WHERE wf.user_id = ?
              AND wf.evidence_count >= ?
              AND NOT EXISTS (
                SELECT 1
                FROM self_evolution_recommendations rec
                WHERE rec.user_id = wf.user_id
                  AND rec.workflow_key = wf.workflow_key
                  AND rec.status IN ('pending_approval', 'approved')
              )
            ORDER BY wf.evidence_count DESC, wf.last_seen DESC
            """,
            (clean_user_id, self.recommendation_threshold),
        ).fetchall()

        recs: list[SelfEvolutionRecommendation] = []
        for row in rows:
            rec = SelfEvolutionRecommendation(
                user_id=row[0],
                workflow_key=row[1],
                summary=row[2],
                suggested_skill=row[3],
                evidence_count=int(row[4]),
            )
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO self_evolution_recommendations
                    (user_id, workflow_key, summary, suggested_skill,
                     evidence_count, status, requires_approval, install_applied)
                VALUES (?, ?, ?, ?, ?, 'pending_approval', 1, 0)
                """,
                (
                    rec.user_id,
                    rec.workflow_key,
                    rec.summary,
                    rec.suggested_skill,
                    rec.evidence_count,
                ),
            )
            if cursor.rowcount:
                recs.append(rec)
        self.conn.commit()
        return recs


def _required(value: str, name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean[:500]
