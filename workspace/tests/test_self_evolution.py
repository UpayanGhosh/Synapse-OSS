from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_self_evolution_recommends_skill_after_repeated_workflow() -> None:
    from sci_fi_dashboard.self_evolution import SelfEvolutionTracker

    conn = sqlite3.connect(":memory:")
    try:
        tracker = SelfEvolutionTracker(conn, recommendation_threshold=3)
        for _ in range(3):
            tracker.record_workflow(
                user_id="agent:creator:test",
                workflow_key="daily_status_digest",
                summary="User repeatedly asks for a daily status digest.",
                suggested_skill="daily-status-digest",
                evidence="status digest please",
            )

        recs = tracker.recommend_pending(user_id="agent:creator:test")

        assert len(recs) == 1
        rec = recs[0]
        assert rec.workflow_key == "daily_status_digest"
        assert rec.suggested_skill == "daily-status-digest"
        assert rec.requires_approval is True

        row = conn.execute(
            """
            SELECT status, requires_approval, install_applied
            FROM self_evolution_recommendations
            WHERE user_id = ?
            """,
            ("agent:creator:test",),
        ).fetchone()
        assert row == ("pending_approval", 1, 0)
    finally:
        conn.close()


def test_self_evolution_does_not_duplicate_pending_recommendation() -> None:
    from sci_fi_dashboard.self_evolution import SelfEvolutionTracker

    conn = sqlite3.connect(":memory:")
    try:
        tracker = SelfEvolutionTracker(conn, recommendation_threshold=2)
        for _ in range(4):
            tracker.record_workflow(
                user_id="agent:creator:test",
                workflow_key="bug_triage_loop",
                summary="User repeatedly triages failing tests.",
                suggested_skill="bug-triage-loop",
                evidence="rerun tests and fix",
            )

        first = tracker.recommend_pending(user_id="agent:creator:test")
        second = tracker.recommend_pending(user_id="agent:creator:test")

        assert len(first) == 1
        assert second == []
        assert conn.execute(
            "SELECT COUNT(*) FROM self_evolution_recommendations"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_self_evolution_skips_duplicate_created_by_concurrent_recommender() -> None:
    from sci_fi_dashboard.self_evolution import SelfEvolutionTracker

    class RacingConnection:
        def __init__(self) -> None:
            self.conn = sqlite3.connect(":memory:")
            self.insert_calls = 0

        def executescript(self, sql):
            return self.conn.executescript(sql)

        def commit(self):
            return self.conn.commit()

        def execute(self, sql, params=()):
            if "INSERT" in sql and "self_evolution_recommendations" in sql:
                self.insert_calls += 1
                if self.insert_calls == 1:
                    self.conn.execute(
                        """
                        INSERT INTO self_evolution_recommendations
                            (user_id, workflow_key, summary, suggested_skill,
                             evidence_count, status, requires_approval, install_applied)
                        VALUES (?, ?, ?, ?, ?, 'pending_approval', 1, 0)
                        """,
                        (
                            "agent:creator:test",
                            "bug_triage_loop",
                            "Concurrent insert already won.",
                            "bug-triage-loop",
                            5,
                        ),
                    )
                    self.conn.commit()
            return self.conn.execute(sql, params)

        def close(self):
            return self.conn.close()

    conn = RacingConnection()
    try:
        tracker = SelfEvolutionTracker(conn, recommendation_threshold=2)
        for _ in range(3):
            tracker.record_workflow(
                user_id="agent:creator:test",
                workflow_key="bug_triage_loop",
                summary="User repeatedly triages failing tests.",
                suggested_skill="bug-triage-loop",
                evidence="rerun tests and fix",
            )

        recs = tracker.recommend_pending(user_id="agent:creator:test")

        assert recs == []
        assert conn.conn.execute(
            "SELECT COUNT(*) FROM self_evolution_recommendations"
        ).fetchone()[0] == 1
    finally:
        conn.close()
