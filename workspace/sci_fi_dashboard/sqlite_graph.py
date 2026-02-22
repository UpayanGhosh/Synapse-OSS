"""
SQLite-backed Knowledge Graph — replaces NetworkX.
Memory: ~150MB → ~1MB (only query results in RAM).
"""

import sqlite3
import json
import os
import gzip
import time
from typing import Optional, List, Dict


DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/knowledge_graph.db")


class SQLiteGraph:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self):
        conn = self._conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    name TEXT PRIMARY KEY,
                    type TEXT DEFAULT 'entity',
                    properties TEXT DEFAULT '{}',
                    created_at REAL,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    evidence TEXT DEFAULT '',
                    created_at REAL,
                    PRIMARY KEY (source, target, relation),
                    FOREIGN KEY (source) REFERENCES nodes(name),
                    FOREIGN KEY (target) REFERENCES nodes(name)
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            """)
            conn.commit()
        finally:
            conn.close()

    def add_node(self, name: str, node_type: str = "entity", **properties):
        now = time.time()
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO nodes (name, type, properties, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       properties = ?, updated_at = ?""",
                (name, node_type, json.dumps(properties), now, now,
                 json.dumps(properties), now),
            )
            conn.commit()
        finally:
            conn.close()

    def add_edge(self, source: str, target: str, relation: str,
                 weight: float = 1.0, evidence: str = ""):
        now = time.time()
        conn = self._conn()
        try:
            for node in (source, target):
                conn.execute(
                    "INSERT OR IGNORE INTO nodes (name, created_at, updated_at) VALUES (?, ?, ?)",
                    (node, now, now),
                )
            conn.execute(
                """INSERT INTO edges (source, target, relation, weight, evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, target, relation) DO UPDATE SET
                       weight = ?, evidence = evidence || ' | ' || ?""",
                (source, target, relation, weight, evidence, now, weight, evidence),
            )
            conn.commit()
        finally:
            conn.close()

    def get_entity_neighborhood(self, entity: str, hops: int = 1) -> str:
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT source, relation, target, weight
                   FROM edges
                   WHERE source = ? OR target = ?
                   ORDER BY weight DESC LIMIT 20""",
                (entity, entity),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return ""
        lines = []
        for r in rows:
            lines.append(f"  {r['source']} --[{r['relation']}]--> {r['target']} (w={r['weight']:.2f})")
        return f"Knowledge about {entity}:\n" + "\n".join(lines)

    def find_connection_path(self, start: str, end: str, max_depth: int = 4) -> list:
        conn = self._conn()
        try:
            visited = {start}
            queue = [(start, [start])]
            for _ in range(max_depth):
                next_queue = []
                for current, path in queue:
                    rows = conn.execute(
                        "SELECT target FROM edges WHERE source = ?", (current,),
                    ).fetchall()
                    for row in rows:
                        neighbor = row["target"]
                        if neighbor == end:
                            return path + [neighbor]
                        if neighbor not in visited:
                            visited.add(neighbor)
                            next_queue.append((neighbor, path + [neighbor]))
                queue = next_queue
                if not queue:
                    break
        finally:
            conn.close()
        return []

    def get_all_node_names(self) -> List[str]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT name FROM nodes").fetchall()
            return [r["name"] for r in rows]
        finally:
            conn.close()

    def number_of_nodes(self) -> int:
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        finally:
            conn.close()

    def number_of_edges(self) -> int:
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        finally:
            conn.close()


    # ── NetworkX Compatibility Layer ──
    # These methods allow drop-in replacement in api_gateway.py

    def add_relation(self, source: str, relation: str, target: str, 
                     weight: float = 1.0, evidence: str = ""):
        """Alias for add_edge — matches TransparentBrain API."""
        self.add_edge(source, target, relation=relation, weight=weight, evidence=evidence)

    def has_node(self, name: str) -> bool:
        """Check if a node exists."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM nodes WHERE name = ? LIMIT 1", (name,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def neighbors(self, node: str) -> List[str]:
        """Get all nodes connected to this node (outgoing edges)."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT target FROM edges WHERE source = ?", (node,)
            ).fetchall()
            return [r["target"] for r in rows]
        finally:
            conn.close()

    @property
    def graph(self):
        """Self-reference so brain.graph.has_node() works without changes."""
        return self

    def prune_weak_edges(self, min_weight: float = 0.1):
        conn = self._conn()
        try:
            deleted = conn.execute(
                "DELETE FROM edges WHERE weight < ?", (min_weight,)
            ).rowcount
            conn.commit()
            if deleted:
                print(f"✂️ Pruned {deleted} weak edges")
        finally:
            conn.close()

    def prune_graph(self):
        """Drop-in for TransparentBrain.prune_graph()"""
        self.prune_weak_edges(0.1)

    def save_graph(self):
        """No-op — SQLite auto-persists. Keeps interface compatible."""
        pass

    @classmethod
    def migrate_from_networkx_file(cls, graph_file: str, db_path: str = DB_PATH):
        """One-time migration from knowledge_graph.json.gz to SQLite."""
        import networkx as nx

        print(f"📦 Migrating {graph_file} → {db_path}")

        if graph_file.endswith(".gz"):
            with gzip.open(graph_file, "rt") as f:
                data = json.load(f)
        else:
            with open(graph_file) as f:
                data = json.load(f)

        G = nx.node_link_graph(data)
        db = cls(db_path)

        node_count = 0
        for node, attrs in G.nodes(data=True):
            db.add_node(str(node), node_type=attrs.get("type", "entity"))
            node_count += 1

        edge_count = 0
        for src, tgt, attrs in G.edges(data=True):
            db.add_edge(
                str(src), str(tgt),
                relation=attrs.get("relation", attrs.get("label", "related_to")),
                weight=attrs.get("weight", 1.0),
            )
            edge_count += 1

        print(f"✅ Migrated {node_count} nodes, {edge_count} edges")
        return db
