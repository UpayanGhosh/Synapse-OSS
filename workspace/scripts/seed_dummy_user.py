"""
seed_dummy_user.py — Seed a dummy virtual user (Alex Chen) into all memory stores.

This script populates:
  1. memory.db + LanceDB  — 35 episodic memories via MemoryEngine.add_memory()
  2. knowledge_graph.db   — 15 nodes, 25 edges via SQLiteGraph
  3. SBS profile          — 60 synthetic turns -> force_batch(full_rebuild=True)

Purpose: end-to-end brain validation on the Pipeline Dashboard.
Run manually ONLY — not auto-seeded on startup.

Usage:
    cd workspace
    python scripts/seed_dummy_user.py
    python scripts/seed_dummy_user.py --force       # wipe and re-seed
    python scripts/seed_dummy_user.py --skip-sbs    # skip SBS profile seeding
    python scripts/seed_dummy_user.py --dry-run     # print counts, write nothing
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
SCI_FI_DIR = WORKSPACE_ROOT / "sci_fi_dashboard"

sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(SCI_FI_DIR))

# ── dummy data ─────────────────────────────────────────────────────────────────

# Each entry: (content, category, days_ago)
# days_ago used to backdate unix_timestamp so temporal scoring is realistic
DUMMY_MEMORIES = [
    # --- daily life (10) ---
    ("had coffee with Jordan this morning before the standup", "daily_life", 1),
    ("Pixel knocked over my rubber plant again, third time this week", "daily_life", 2),
    ("went grocery shopping after work, Jordan wanted paneer", "daily_life", 3),
    ("cooked dinner together — Jordan made dal, I handled the rice", "daily_life", 4),
    ("watched Severance episode 3 with Jordan, both of us stressed now", "daily_life", 5),
    ("Pixel was sick this morning, took him to Dr. Mehta at the vet clinic", "daily_life", 8),
    ("Jordan woke up early to call their parents in the UK", "daily_life", 10),
    ("our apartment AC broke again, sweating through the afternoon", "daily_life", 12),
    ("morning jog along the lake — it rained halfway through", "daily_life", 15),
    ("finally fixed the wobbly shelf in the bedroom", "daily_life", 20),

    # --- work (10) ---
    ("shipped the payment reconciliation fix — 3 days of debugging, one line change", "work", 1),
    ("standup ran 45 minutes today because of the infra incident, completely draining", "work", 3),
    ("got positive feedback from Priya (CTO) on the Q1 reconciliation work", "work", 5),
    ("got promoted to senior engineer — Q1 performance cycle, effective from next month", "work", 7),
    ("first round interview with Razorpay went well, they want a system design round", "work", 10),
    ("system design round with Razorpay — designed a distributed rate limiter, felt solid", "work", 14),
    ("on-call this week, got paged at 2am for a payment timeout spike", "work", 18),
    ("sprint retrospective was tense — the feature delay is blamed on our team", "work", 22),
    ("wrote a design doc for the new transaction audit trail feature", "work", 25),
    ("parents are visiting next month, need to request WFH days from Arjun (manager)", "work", 30),

    # --- relationships (8) ---
    ("Jordan surprised me with new climbing shoes — La Sportiva Katanas, exactly what I wanted", "relationships", 2),
    ("Jordan and I had a small argument about moving back to Kolkata — I'm not ready", "relationships", 6),
    ("called mom and dad, they're excited about the Bangalore visit, asked about Jordan", "relationships", 9),
    ("Jordan cooked my favourite biryani for our two-year anniversary of moving in together", "relationships", 13),
    ("mom asked when we're getting married — changed the topic quickly", "relationships", 16),
    ("Jordan is stressed about their PhD viva prep, I've been making extra tea", "relationships", 19),
    ("had a long conversation with dad about the promotion — he was genuinely proud", "relationships", 24),
    ("Jordan and I went to a rooftop bar with Mihir and his girlfriend, rare social event", "relationships", 35),

    # --- hobbies / interests (7) ---
    ("finished Stories of Your Life and Others by Ted Chiang — mind completely blown", "hobbies", 4),
    ("built a new mechanical keyboard — Bakeneko 60, holy pandas, GMK Umbra keycaps", "hobbies", 11),
    ("went bouldering at Boulder Box — finally solved the V4 overhang that beat me for 3 weeks", "hobbies", 6),
    ("started reading Exhalation by Ted Chiang — the second story is already wrecking me", "hobbies", 17),
    ("bouldering session with Mihir on Saturday, he's got better footwork than me now", "hobbies", 21),
    ("ordered a Keychron Q1 for work desk — lubed Boba U4 switches, quieter office setup", "hobbies", 28),
    ("picked up a used copy of Blindsight by Peter Watts — someone at the gym recommended it", "hobbies", 40),
]

# Graph: (name, node_type, properties_dict)
DUMMY_NODES = [
    ("Alex Chen", "person", {"age": 28, "occupation": "software engineer", "city": "Bangalore"}),
    ("Jordan", "person", {"relationship": "partner", "origin": "UK", "studying": "PhD"}),
    ("Pixel", "animal", {"species": "cat", "breed": "grey tabby", "age": 3}),
    ("parents", "person_group", {"location": "Kolkata", "visiting": "next month"}),
    ("Bangalore", "location", {"country": "India", "state": "Karnataka"}),
    ("fintech startup", "organization", {"type": "startup", "domain": "fintech"}),
    ("Razorpay", "organization", {"type": "company", "domain": "payments"}),
    ("rock climbing", "activity", {"type": "sport", "frequency": "2x per week", "style": "bouldering"}),
    ("Boulder Box", "location", {"type": "climbing gym", "city": "Bangalore"}),
    ("Ted Chiang", "person", {"type": "author", "genre": "sci-fi"}),
    ("mechanical keyboards", "hobby", {"type": "hobby", "current_build": "Bakeneko 60"}),
    ("promotion", "event", {"level": "senior engineer", "quarter": "Q1"}),
    ("Razorpay interview", "event", {"stage": "system design", "outcome": "pending"}),
    ("Mihir", "person", {"relationship": "friend", "shared_hobby": "bouldering"}),
    ("Priya", "person", {"role": "CTO", "company": "fintech startup"}),
]

# Graph edges: (source, target, relation, weight, evidence)
DUMMY_EDGES = [
    ("Alex Chen", "Jordan", "partner_of", 1.0, "lives together 2 years"),
    ("Alex Chen", "Pixel", "owns", 0.9, "grey tabby, 3yo"),
    ("Alex Chen", "parents", "child_of", 0.9, "parents in Kolkata"),
    ("Alex Chen", "Bangalore", "lives_in", 1.0, "current city"),
    ("Alex Chen", "fintech startup", "works_at", 1.0, "current employer"),
    ("Alex Chen", "rock climbing", "hobby", 0.9, "2x per week bouldering"),
    ("Alex Chen", "mechanical keyboards", "hobby", 0.8, "enthusiast, multiple builds"),
    ("Alex Chen", "Ted Chiang", "reads", 0.9, "Stories of Your Life, Exhalation"),
    ("Alex Chen", "Mihir", "friend_of", 0.7, "climbing partner"),
    ("promotion", "Alex Chen", "happened_to", 1.0, "Q1 senior engineer"),
    ("promotion", "Priya", "approved_by", 0.8, "CTO positive feedback"),
    ("Priya", "fintech startup", "works_at", 0.9, "CTO role"),
    ("Alex Chen", "Razorpay", "interviewing_at", 0.9, "system design round"),
    ("Razorpay interview", "Alex Chen", "involves", 1.0, "distributed rate limiter"),
    ("Jordan", "Bangalore", "lives_in", 0.9, "moved in with Alex"),
    ("Pixel", "Bangalore", "lives_in", 0.8, "lives in apartment"),
    ("Alex Chen", "Boulder Box", "trains_at", 0.9, "regular climbing gym"),
    ("Boulder Box", "Bangalore", "located_in", 1.0, "climbing gym in Bangalore"),
    ("parents", "Bangalore", "visiting", 0.7, "visiting next month"),
    ("Jordan", "parents", "met", 0.6, "Jordan knows Alex's parents"),
    ("Alex Chen", "Razorpay", "considering_joining", 0.8, "career move"),
    ("Alex Chen", "fintech startup", "getting_promoted_at", 1.0, "Q1 promotion"),
    ("Mihir", "rock climbing", "hobby", 0.7, "climbing partner"),
    ("Mihir", "Boulder Box", "trains_at", 0.7, "same gym"),
    ("Jordan", "rock climbing", "supports", 0.7, "gifted climbing shoes"),
]

# SBS turns: (role, content)
# 60 turns covering linguistic style, emotional state, domain, interaction preferences
DUMMY_TURNS = [
    # casual daily exchanges
    ("user", "hey"),
    ("assistant", "hey, what's up"),
    ("user", "nothing just tired. standup ran forever again"),
    ("assistant", "the 45-minute ones are the worst. what happened?"),
    ("user", "infra thing. whatever. Pixel knocked over my plant again"),
    ("assistant", "classic Pixel. is the plant okay"),
    ("user", "barely. Jordan found it funnier than I did"),
    ("assistant", "fair. how's the on-call week going"),
    ("user", "got paged at 2am. payment timeout spike. fixed it in 20min but couldn't sleep after"),
    ("assistant", "that's rough. what was the root cause"),
    ("user", "misconfigured retry interval in the reconciliation service. one line"),
    ("assistant", "three days of debugging for one line. the classic"),
    ("user", "exactly. anyway. promoted btw"),
    ("assistant", "wait seriously? congrats, that's huge"),
    ("user", "yeah. Priya said the reconciliation work was the deciding factor. senior engineer from next month"),
    ("assistant", "well earned. how does it feel"),
    ("user", "good I guess. also terrifying. more responsibility"),
    ("assistant", "you'll handle it. what's the Razorpay situation"),
    ("user", "system design round went well I think. designed a distributed rate limiter"),
    ("assistant", "token bucket or sliding window?"),
    ("user", "sliding window with redis sorted sets. they seemed happy with it"),
    ("assistant", "solid choice. when do you hear back"),
    ("user", "next week probably. not sure I even want to leave tbh"),
    ("assistant", "complicated. what does Jordan think"),
    ("user", "jordan says follow the money but also says it's my call"),
    ("assistant", "that's a good partner move"),
    # work-focused
    ("user", "wrote a design doc for the audit trail feature today. took 4 hours"),
    ("assistant", "what's the architecture"),
    ("user", "event sourcing. append-only ledger, Kafka in the middle"),
    ("assistant", "clean. any pushback from the team"),
    ("user", "Vikram wants to use a message queue directly without kafka. says it's overengineered"),
    ("assistant", "is it"),
    ("user", "maybe for MVP. but audit trails need replay. kafka makes that trivial"),
    ("assistant", "agreed. write that into the doc"),
    # hobbies
    ("user", "finally finished the bakeneko build. holy pandas feel incredible"),
    ("assistant", "linear or tactile person"),
    ("user", "tactile. can't do linears for long sessions. clicky is too loud for the office"),
    ("assistant", "what keycaps"),
    ("user", "GMK Umbra. dark theme. Jordan hates the sound"),
    ("assistant", "Jordan has opinions about keyboards?"),
    ("user", "Jordan has opinions about everything in our apartment"),
    ("assistant", "sounds about right"),
    ("user", "finished Stories of Your Life. that last story broke me a little"),
    ("assistant", "Story of Your Life or Exhalation?"),
    ("user", "Story of Your Life. the one with the heptapods. free will vs determinism"),
    ("assistant", "Chiang is doing something different with that story. the grief structure"),
    ("user", "yeah. starts reading Exhalation tonight"),
    ("assistant", "the second story is disorienting in the best way"),
    # relationships and personal
    ("user", "mom asked about wedding plans again"),
    ("assistant", "classic timing. what did you say"),
    ("user", "changed the subject. not ready for that conversation"),
    ("assistant", "probably wise"),
    ("user", "Jordan and I argued about moving back to Kolkata. I don't want to"),
    ("assistant", "what's the draw for Jordan"),
    ("user", "they think Bangalore is exhausting. it kind of is. but the work is here"),
    ("assistant", "classic bangalore dilemma"),
    ("user", "parents are visiting next month. need to ask Arjun for WFH days"),
    ("assistant", "how many days do you need"),
    ("user", "probably 5. they're here for 10 days but I can't WFH the whole time"),
    ("assistant", "5 days is reasonable, Arjun should be fine with that"),
    ("user", "solved the V4 overhang at Boulder Box today"),
    ("assistant", "the one that's been beating you?"),
    ("user", "three weeks. finally got the foot position right"),
    ("assistant", "Mihir must be insufferable about it now"),
    ("user", "he solved it two weeks ago and hasn't shut up"),
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _days_ago_to_ts(days: float) -> int:
    return int(time.time() - days * 86400)


def already_seeded(graph) -> bool:
    """Check if Alex Chen node exists in the knowledge graph."""
    conn = graph._conn()
    row = conn.execute(
        "SELECT name FROM nodes WHERE name = ?", ("Alex Chen",)
    ).fetchone()
    return row is not None


def seed_memories(engine, dry_run: bool = False) -> int:
    """Seed DUMMY_MEMORIES into memory.db + LanceDB, then backdate timestamps."""
    if dry_run:
        print(f"[DRY RUN] Would seed {len(DUMMY_MEMORIES)} memories")
        return len(DUMMY_MEMORIES)

    from sci_fi_dashboard.db import get_db_connection

    seeded = 0
    for content, category, days_ago in DUMMY_MEMORIES:
        result = engine.add_memory(content, category=category, hemisphere="safe")
        if "error" in result:
            print(f"[WARN] Failed to seed memory: {result['error']!r} — {content[:60]}")
            continue

        doc_id = result.get("id")
        target_ts = _days_ago_to_ts(days_ago)

        # Backdate in memory.db
        conn = get_db_connection()
        conn.execute(
            "UPDATE documents SET unix_timestamp = ? WHERE id = ?",
            (target_ts, doc_id),
        )
        conn.commit()
        conn.close()

        # Backdate in LanceDB via upsert with corrected metadata
        # The embedding is already in LanceDB; we upsert to overwrite metadata.
        try:
            vec = list(engine.get_embedding(content))
            engine.vector_store.upsert_facts([{
                "id": doc_id,
                "vector": vec,
                "metadata": {
                    "text": content,
                    "hemisphere_tag": "safe",
                    "unix_timestamp": target_ts,
                    "importance": engine._score_importance_heuristic(content),
                },
            }])
        except Exception as e:
            print(f"[WARN] LanceDB backdate failed for doc {doc_id}: {e}")

        seeded += 1

    return seeded


def seed_graph(graph, dry_run: bool = False) -> tuple[int, int]:
    """Seed DUMMY_NODES and DUMMY_EDGES into knowledge_graph.db."""
    if dry_run:
        print(f"[DRY RUN] Would seed {len(DUMMY_NODES)} nodes, {len(DUMMY_EDGES)} edges")
        return len(DUMMY_NODES), len(DUMMY_EDGES)

    for name, node_type, props in DUMMY_NODES:
        graph.add_node(name, node_type=node_type, **props)

    for source, target, relation, weight, evidence in DUMMY_EDGES:
        graph.add_edge(source, target, relation=relation, weight=weight, evidence=evidence)

    return len(DUMMY_NODES), len(DUMMY_EDGES)


def seed_sbs(sbs, dry_run: bool = False) -> int:
    """Log 60 synthetic turns into SBS and trigger a full batch rebuild."""
    if dry_run:
        print(f"[DRY RUN] Would seed {len(DUMMY_TURNS)} SBS turns + force_batch")
        return len(DUMMY_TURNS)

    from sci_fi_dashboard.sbs.ingestion.schema import RawMessage

    session_id = "alex_chen_seed"
    base_dt = datetime.now() - timedelta(days=30)
    interval_minutes = 45

    for i, (role, content) in enumerate(DUMMY_TURNS):
        ts = base_dt + timedelta(minutes=i * interval_minutes)
        msg = RawMessage(
            role=role,
            content=content,
            timestamp=ts,
            session_id=session_id,
            char_count=len(content),
            word_count=len(content.split()),
            has_emoji=bool(re.search(r"[\U0001F600-\U0001F64F]", content)),
            is_question=content.strip().endswith("?"),
        )
        sbs.logger.log(msg)

    sbs.force_batch(full_rebuild=True)
    return len(DUMMY_TURNS)


def wipe_seed_data(graph) -> None:
    """Remove Alex Chen node and all connected edges from graph (for --force re-seed)."""
    conn = graph._conn()
    conn.execute("DELETE FROM edges WHERE source = 'Alex Chen' OR target = 'Alex Chen'")
    conn.execute("DELETE FROM nodes WHERE name = 'Alex Chen'")
    # Also wipe other seeded nodes not connected back
    seeded_names = [n for n, _, _ in DUMMY_NODES]
    placeholders = ",".join("?" * len(seeded_names))
    conn.execute(f"DELETE FROM edges WHERE source IN ({placeholders})", seeded_names)
    conn.execute(f"DELETE FROM nodes WHERE name IN ({placeholders})", seeded_names)
    conn.commit()
    print("[OK] Wiped previous Alex Chen seed data from graph")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seed dummy user (Alex Chen) into Synapse memory stores for brain validation"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-seed even if Alex Chen is already seeded (wipes graph first)"
    )
    parser.add_argument(
        "--skip-sbs", action="store_true",
        help="Skip SBS profile seeding (faster, memories+graph only)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be seeded without writing anything"
    )
    args = parser.parse_args()

    print("[seed_dummy_user] Starting seed for Alex Chen...")
    print(f"  force={args.force}  skip_sbs={args.skip_sbs}  dry_run={args.dry_run}")

    # ── imports (deferred to avoid startup side-effects) ──────────────────────
    from sci_fi_dashboard.memory_engine import MemoryEngine
    from sci_fi_dashboard.sqlite_graph import SQLiteGraph
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    print(f"[INFO] db_dir  : {cfg.db_dir}")
    print(f"[INFO] sbs_dir : {cfg.sbs_dir}")

    # ── init stores ──────────────────────────────────────────────────────────
    graph = SQLiteGraph()
    engine = MemoryEngine(graph_store=graph)

    # ── idempotency check ────────────────────────────────────────────────────
    if already_seeded(graph):
        if args.force:
            print("[INFO] Alex Chen already seeded — wiping for re-seed (--force)")
            if not args.dry_run:
                wipe_seed_data(graph)
        else:
            print("[SKIP] Alex Chen is already seeded. Use --force to re-seed.")
            return

    # ── seed memories ────────────────────────────────────────────────────────
    print(f"\n[1/3] Seeding {len(DUMMY_MEMORIES)} memories (memory.db + LanceDB)...")
    t0 = time.time()
    n_mem = seed_memories(engine, dry_run=args.dry_run)
    print(f"[OK]  Seeded {n_mem} memories in {time.time()-t0:.1f}s")

    # ── seed graph ───────────────────────────────────────────────────────────
    print(f"\n[2/3] Seeding {len(DUMMY_NODES)} nodes, {len(DUMMY_EDGES)} edges (knowledge_graph.db)...")
    t0 = time.time()
    n_nodes, n_edges = seed_graph(graph, dry_run=args.dry_run)
    print(f"[OK]  Seeded {n_nodes} nodes, {n_edges} edges in {time.time()-t0:.1f}s")

    # ── seed SBS ─────────────────────────────────────────────────────────────
    if not args.skip_sbs:
        sbs_data_dir = str(cfg.sbs_dir / "the_creator")
        print(f"\n[3/3] Seeding {len(DUMMY_TURNS)} SBS turns -> {sbs_data_dir}")
        print("      Running force_batch(full_rebuild=True) — may take 30-60s...")

        if not args.dry_run:
            from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator
            sbs = SBSOrchestrator(data_dir=sbs_data_dir)

        t0 = time.time()
        n_turns = seed_sbs(sbs if not args.dry_run else None, dry_run=args.dry_run)
        print(f"[OK]  Seeded {n_turns} SBS turns + batch rebuild in {time.time()-t0:.1f}s")
    else:
        print("\n[3/3] Skipping SBS seeding (--skip-sbs)")

    # ── summary ──────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  SEED COMPLETE — Alex Chen is ready for brain validation")
    print("="*60)
    print(f"  Memories  : {n_mem}")
    print(f"  Graph     : {n_nodes} nodes, {n_edges} edges")
    if not args.skip_sbs:
        print(f"  SBS turns : {n_turns}")
    print()
    print("  Next steps:")
    print("  1. Start server: cd workspace && uv run --no-project uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000")
    print("  2. Open: http://localhost:8000/dashboard")
    print('  3. Send: "What did I do at work today?"')
    print('           "Tell me about Jordan"')
    print('           "What book am I reading?"')
    print()
    if args.dry_run:
        print("  (DRY RUN — nothing was actually written)")


if __name__ == "__main__":
    main()
