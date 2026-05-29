# Knowledge Graph — performance & expressive limits

Synapse stores knowledge as subject-predicate-object (SPO) triples in SQLite via
`sqlite_graph.py`. This is a deliberate trade-off: zero infrastructure (no
Neo4j, no graph DB process), but multi-hop traversal degrades quickly as the
graph grows.

## Schema (current)

The graph lives in `~/.synapse/workspace/db/knowledge_graph.db` and is opened
in **WAL mode** with `synchronous=NORMAL` for low-latency writes from the
chat path.

Two tables:

**`nodes`**
- `name TEXT PRIMARY KEY` — the canonical entity string
- `type TEXT DEFAULT 'entity'`
- `properties TEXT DEFAULT '{}'` — JSON blob
- `created_at REAL`, `updated_at REAL` — Unix timestamps

**`edges`**
- `source TEXT NOT NULL` (FK -> `nodes.name`)
- `target TEXT NOT NULL` (FK -> `nodes.name`)
- `relation TEXT NOT NULL` — the predicate
- `weight REAL DEFAULT 1.0`
- `evidence TEXT DEFAULT ''` — appended on conflict (`evidence || ' | ' || ?`)
- `created_at REAL`
- Composite primary key: `(source, target, relation)`

**Indexes:** `idx_edges_source`, `idx_edges_target`, `idx_edges_relation`,
`idx_nodes_type`. Source, target, and relation are all individually indexed —
single-hop lookups in any direction hit an index.

## Queries that are fast (<10 ms on 100k triples)

- "What does X relate to?" — single-hop neighbors of subject S. The
  `get_entity_neighborhood()` helper does exactly this with `LIMIT 50` ordered
  by weight descending.
- "All triples about subject S" — direct lookup by source (indexed).
- "All triples with predicate P" — relation is indexed.
- "All outgoing edges from a node" — see `neighbors()`; indexed scan on
  `idx_edges_source`.
- Existence check (`has_node()`) — primary key lookup.

## Queries that get slow (>1 s on 100k triples)

- "Path from X to Y of length ≤4" — `find_connection_path()` uses a recursive
  CTE with `json_each` cycle-prevention. SQLite handles it correctly but the
  join cost compounds with depth and fan-out.
- "All subjects that share predicate P with at least 3 others" — would require
  a group-by over the full `edges` table (no helper currently ships).
- Any traversal that fans out to >10k intermediate nodes per level.
- Reverse-direction multi-hop (the recursive CTE in `find_connection_path()`
  walks `source -> target` only; bidirectional traversal would need a
  hand-rolled query).

## When to consider migrating

If your usage is dominated by:
- multi-hop traversal beyond depth 2
- pattern matching that resembles SPARQL / Cypher
- > 1M triples with a sub-second p95 traversal SLO

then plan a migration to **KuzuDB** (embedded, much closer to Synapse's
"zero infra" goal than Neo4j) or Neo4j.

For Synapse's current chat-grounded use case (entity recall, "who did I
mention in last week's conversation about X"), SPO-in-SQLite is sufficient.

## Operational tips

- **VACUUM**: `GentleWorker.heavy_task_db_optimize` runs `VACUUM` every
  30 minutes, gated on `power_plugged` + `cpu_percent <= 20%`. See
  `workspace/sci_fi_dashboard/gentle_worker.py`.
- **Stale-triple pruning**: `GentleWorker.heavy_task_graph_pruning` runs every
  10 minutes (same gating). Calls `prune_graph()` -> `prune_weak_edges(0.1)`,
  which deletes any edge with `weight < 0.1`.
- **Manual maintenance**: `cd workspace && python main.py vacuum` runs the
  same VACUUM unconditionally (no idle/power gate).
- **Persistent connection**: `SQLiteGraph` keeps a single `check_same_thread=False`
  connection alive for the process lifetime. Don't open ad-hoc connections to
  the same DB from new threads while the gateway is running.
