"""Reclassify a backed-up synthetic profile, then exercise style and scoped recall."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_luna_memory_simulation as sim  # noqa: E402

SOURCE_DB = REPO_ROOT / ".tmp/synapse-luna-sim/run-definitive-20260925/synapse-home/workspace/db/memory.db"
TURN_PLAN = (
    ("alice", "style-neutral-1", "Can you help me draft a clear note asking my landlord to repair the kitchen tap?"),
    ("alice", "style-one-turn-override", "For this answer only, make it playful and keep it brief: remind the team to send project updates."),
    ("alice", "style-neutral-2", "What should I include when I ask to move a meeting to another day?"),
    ("bob", "bob-tool-recall", "Please use query_memory to look up my earlier lunch incident. What was taken?"),
    ("alice", "alice-post-new-recall", "Use query_memory to look up the umbrella incident, then tell me what happened."),
)


class ScriptedSmokeRouter:
    """Deterministic local plumbing probe; never a model-quality result."""

    model = "scripted-stub-smoke"

    def __init__(self) -> None:
        self._tool_call_id = 0

    async def call(self, _role: str, messages, **_kwargs) -> str:
        prompt = str(messages[-1].get("content", "")) if messages else ""
        if "Classify only the existing, source-backed" in prompt:
            return '{"style_control":"professional_precise"}' if '"field": "tone"' in prompt else '{"style_control":"concise"}'
        return '{"confirmed_facts":[],"relationship_updates":[]}'

    async def call_with_metadata(self, _role: str, _messages, **_kwargs):
        from sci_fi_dashboard.llm_router import LLMResult

        return LLMResult(
            text="Please state the issue, when it began, and what repair time works for you.",
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )

    async def call_with_tools(self, _role: str, messages, tools, **_kwargs):
        from sci_fi_dashboard.llm_router import LLMToolResult, ToolCall

        messages = [m for m in messages if isinstance(m, dict)]
        tool_message = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        query_user = next((
            str(m.get("content", "")) for m in reversed(messages)
            if m.get("role") == "user"
        ), "")
        tool_names = {
            item.get("function", {}).get("name")
            for item in tools if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
        calls = []
        text = "Please include the issue, its effect, and a suitable time for access."
        if tool_message is not None:
            text = "I found the earlier note in your saved memories."
        elif "query_memory" in tool_names and "query_memory" in query_user.casefold():
            query = "lunch sandwich pigeon CFO" if "lunch" in query_user.casefold() else "umbrella meeting CEO"
            self._tool_call_id += 1
            calls = [ToolCall(
                id=f"smoke-memory-{self._tool_call_id}",
                name="query_memory",
                arguments=json.dumps({"query": query}),
            )]
            text = ""
        return LLMToolResult(
            text=text,
            tool_calls=calls,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )


def _db_logical_digest(path: Path) -> str:
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        data = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = conn.execute(f"SELECT * FROM {quoted} ORDER BY rowid").fetchall()
            data.append((table, rows))
    return hashlib.sha256(repr(data).encode("utf-8", errors="replace")).hexdigest()


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"saved synthetic source database is unavailable: {source}")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite run database: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _instrument_style_resolution(run_dir: Path):
    from sci_fi_dashboard import chat_pipeline

    actual = chat_pipeline._apply_scoped_relationship_style

    def recording(policy, user_message, relationship):
        resolved = actual(policy, user_message, relationship)
        item = {
            "user_message": user_message,
            "tone": resolved.tone,
            "length": resolved.length,
            "source": resolved.source,
            "runtime_style": relationship.get("runtime_style", {}),
        }
        sim._write_jsonl(run_dir / "style-traces.jsonl", item)
        return resolved

    chat_pipeline._apply_scoped_relationship_style = recording


def _persistent_style_state(profile: dict) -> dict:
    state = {"runtime_style": profile.get("runtime_style", {})}
    for layer in ("preferences", "inferred"):
        values = profile.get(layer, {})
        state[layer] = {
            field: values.get(field)
            for field in ("tone", "verbosity")
            if isinstance(values, dict) and field in values
        }
    return state


def _raw_episode_snapshot(store, context) -> list[dict]:
    with store._connect() as conn:
        rows = conn.execute(
            """SELECT episode_id,source_message_id,content,occurred_at,recorded_at,role,status
               FROM personal_episodes WHERE owner_key=? ORDER BY episode_id""",
            (f"person:{context.person_id}",),
        ).fetchall()
    return [dict(row) for row in rows]


def _legacy_style_snapshot(store, context) -> list[dict]:
    with store._connect() as conn:
        rows = conn.execute(
            """SELECT u.id,u.owner_key,u.source_episode_id,u.field,u.value,u.evidence,
                      u.explicit,u.confidence,u.occurred_at,u.recorded_at,
                      u.style_control,e.status AS episode_status
               FROM personal_relationship_updates u
               JOIN personal_episodes e ON e.episode_id=u.source_episode_id
                 AND e.owner_key=u.owner_key
               WHERE u.owner_key=? AND u.field IN ('tone','verbosity') ORDER BY u.id""",
            (f"person:{context.person_id}",),
        ).fetchall()
    return [dict(row) for row in rows]


async def _reset_with_receipt(run_dir: Path, stack, channel, peer: str, message_id: str) -> dict:
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path
    from synapse_config import SynapseConfig

    _store, _service, inbox, flood, _queue, retry, _registry, _worker = stack
    cfg = SynapseConfig.load()
    context = sim._context_for_peer(cfg, peer.removesuffix("-peer") + "-peer")
    sessions = SessionStore(agent_id="the_creator", data_root=cfg.data_root)
    before = await sessions.get(context.conversation_id)
    if before is None:
        raise AssertionError("Alice's pre-/new session was not found")
    old_transcript = transcript_path(before, cfg.data_root, "the_creator")
    old_messages = await load_messages(old_transcript)
    if not old_messages:
        raise AssertionError("pre-/new transcript is empty")

    sends_before = len(channel.sent)
    if not await flood.incoming(
        peer,
        "/new",
        {"message_id": message_id, "channel_id": "whatsapp", "sender_name": peer},
    ):
        raise AssertionError("/new inbound was unexpectedly deduplicated")
    await sim._wait_until(
        lambda: "completed"
        if sim._inbox_status(inbox, message_id)
        and sim._inbox_status(inbox, message_id)[1] == "completed"
        else None,
        label="/new durable completion",
    )
    receipt = await sim._wait_until(
        lambda: sim._outbox_row(retry, f"reply:{message_id}:0")
        if (sim._outbox_row(retry, f"reply:{message_id}:0") or (None,))[0] == "accepted"
        else None,
        label="/new accepted fake-channel receipt",
    )
    await sim._wait_until(
        lambda: True if len(channel.sent) > sends_before else None,
        label="/new fake-channel send",
    )
    sim._write_jsonl(run_dir / "delivery-events.jsonl", {
        "message_id": message_id,
        "status": receipt[0],
        "channel_id": "whatsapp",
        "recipient": peer,
        "parent_episode_id": receipt[3],
    })
    after = await sessions.get(context.conversation_id)
    if after is None or after.session_id == before.session_id:
        raise AssertionError("/new did not rotate Alice's session")
    new_messages = await load_messages(transcript_path(after, cfg.data_root, "the_creator"))
    if new_messages:
        raise AssertionError("fresh transcript was not empty after /new")
    archived = list(old_transcript.parent.glob(old_transcript.name + ".deleted.*"))
    if not archived:
        raise AssertionError("/new did not archive Alice's old transcript")
    item = {
        "message_id": message_id,
        "old_session_id": before.session_id,
        "new_session_id": after.session_id,
        "old_transcript_messages": len(old_messages),
        "new_transcript_messages": len(new_messages),
        "reset_reply": receipt[1],
    }
    sim._write_jsonl(run_dir / "receipts.jsonl", {
        "message_id": message_id,
        "status": receipt[0],
        "channel_id": "whatsapp",
        "recipient": peer,
        "parent_episode_id": receipt[3],
    })
    sim._write_jsonl(run_dir / "turns.jsonl", {"user": "/new", **item, "accepted_send": True})
    return item


async def _run(run_dir: Path, source_db: Path, *, router=None) -> dict:
    from synapse_config import SynapseConfig

    original_digest = _db_logical_digest(source_db)
    home = sim._configure_isolated_workspace(run_dir)
    cfg = SynapseConfig.load()
    destination = cfg.db_dir / "memory.db"
    _sqlite_backup(source_db, destination)
    if _db_logical_digest(source_db) != original_digest:
        raise AssertionError("source database changed during read-only backup")
    if any((home / name).exists() for name in ("state", "sessions", "transcripts")):
        raise AssertionError("fresh simulation home unexpectedly contains prior transcript state")

    if router is None:
        from luna_file_relay import FileRelayRouter

        router = FileRelayRouter(
            run_dir,
            timeout_seconds=180,
            poll_interval_seconds=0.05,
            max_requests=40,
        )
    channel = sim.FakeChannel()
    stack = await sim._new_worker_stack(
        cfg.data_root,
        router,
        channel,
        run_dir,
        service_started=False,
        style_extract_timeout=300.0,
        style_lease_seconds=360.0,
    )
    store, service, _inbox, _flood, _queue, _retry, _registry, worker = stack
    alice_context = sim._context_for_peer(cfg, "alice-peer")
    bob_context = sim._context_for_peer(cfg, "bob-peer")
    before_profile = store.get_relationship(alice_context)
    before_snapshot = _raw_episode_snapshot(store, alice_context)
    before_style_rows = _legacy_style_snapshot(store, alice_context)
    queued = service.queue_missing_style_controls(alice_context, limit=32)
    if queued == 0:
        await sim._finish_worker_stack(stack)
        raise AssertionError("saved Alice profile had no eligible legacy tone/verbosity rows")

    backfill_counts = dict.fromkeys(service.style_reextract_status(alice_context), 0)
    try:
        while service.style_reextract_status(alice_context)["pending"]:
            outcome = await service.process_style_reextract_once(alice_context, limit=4)
            for key, value in outcome.items():
                backfill_counts[key] += value
            if not any(outcome.values()):
                break
        after_profile = store.get_relationship(alice_context)
        after_snapshot = _raw_episode_snapshot(store, alice_context)
        after_style_rows = _legacy_style_snapshot(store, alice_context)
        await service.start()
        _instrument_style_resolution(run_dir)

        results = []
        profile_checkpoints = {}
        for person, message_id, text in TURN_PLAN[:3]:
            results.append(await sim._run_turn(
                run_dir, stack, channel, f"{person}-peer", message_id, text
            ))
            profile_checkpoints[message_id] = store.get_relationship(alice_context)

        person, message_id, text = TURN_PLAN[3]
        results.append(
            await sim._run_turn(run_dir, stack, channel, f"{person}-peer", message_id, text)
        )
        reset = await _reset_with_receipt(
            run_dir, stack, channel, "alice-peer", "alice-session-new"
        )
        results.append(reset)
        person, message_id, text = TURN_PLAN[4]
        results.append(
            await sim._run_turn(run_dir, stack, channel, f"{person}-peer", message_id, text)
        )
    finally:
        await sim._finish_worker_stack(stack)

    alice_after = store.get_relationship(alice_context)
    bob_after = store.get_relationship(bob_context)
    traces = [
        json.loads(line)
        for line in (run_dir / "style-traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requests = sorted((run_dir / "requests").glob("*.json"))
    receipts = []
    receipt_file = run_dir / "receipts.jsonl"
    if receipt_file.is_file():
        receipts = [json.loads(line) for line in receipt_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    bob_lunch = store.recall(bob_context, "lunch sandwich pigeon CFO", limit=8)
    alice_umbrella = store.recall(alice_context, "umbrella incident meeting", limit=8)
    summary = {
        "simulation": "legacy style-control backfill + real Synapse worker/memory/prompt path",
        "model": (
            "scripted stub (plumbing smoke only; not Luna)"
            if getattr(router, "model", None) == "scripted-stub-smoke"
            else "GPT-6 Luna via constrained agent-mediated inference; not native provider auth"
        ),
        "source_database": str(source_db),
        "source_logical_digest_before": original_digest,
        "source_logical_digest_after": _db_logical_digest(source_db),
        "copied_database": str(destination),
        "short_term_history": "fresh isolated home; Alice /new verified session rotation and transcript archive",
        "embedding_mode": "lexical fallback; no embedding provider configured",
        "tools_exposed": ["query_memory"],
        "external_services": "fake WhatsApp channel; outbound network/process denied",
        "backfill": {
            "queued": queued,
            "counts": backfill_counts,
            "status": service.style_reextract_status(alice_context),
            "profile_before": before_profile,
            "profile_after": after_profile,
            "same_raw_episodes": before_snapshot == after_snapshot,
            "style_rows_before": before_style_rows,
            "style_rows_after": after_style_rows,
            "only_control_changed": (
                [{k: v for k, v in row.items() if k != "style_control"} for row in before_style_rows]
                == [{k: v for k, v in row.items() if k != "style_control"} for row in after_style_rows]
            ),
        },
        "alice_profile_checkpoints": profile_checkpoints,
        "turns": results,
        "effective_style_traces": traces,
        "inference_request_count": len(requests),
        "accepted_fake_channel_sends": sum(1 for row in receipts if row.get("status") == "accepted"),
        "query_memory_receipts": sim._query_memory_receipt_count(run_dir),
        "bob_lunch_recall": [r.content for r in bob_lunch],
        "alice_umbrella_recall": [r.content for r in alice_umbrella],
        "final_profiles": {"alice": alice_after, "bob": bob_after},
        "assertions": {
            "source_database_unchanged": original_digest == _db_logical_digest(source_db),
            "two_legacy_style_rows_classified": backfill_counts.get("classified", 0) == queued,
            "one_turn_override_did_not_change_persisted_style": (
                "style-one-turn-override" in profile_checkpoints
                and _persistent_style_state(profile_checkpoints["style-neutral-1"])
                == _persistent_style_state(profile_checkpoints["style-one-turn-override"])
            ),
            "raw_episode_identity_and_text_preserved": (
                before_snapshot == after_snapshot
            ),
            "backfill_only_filled_style_control": (
                [{k: v for k, v in row.items() if k != "style_control"} for row in before_style_rows]
                == [{k: v for k, v in row.items() if k != "style_control"} for row in after_style_rows]
                and all(
                    old["style_control"] is None
                    or old["style_control"] == new["style_control"]
                    for old, new in zip(before_style_rows, after_style_rows, strict=True)
                )
            ),
            "alice_session_reset_verified": reset["new_session_id"] != reset["old_session_id"] and reset["new_transcript_messages"] == 0,
            "cross_person_memory_scoped": all(r.person_id == bob_context.person_id for r in bob_lunch)
                and all(r.person_id == alice_context.person_id for r in alice_umbrella),
            "turns_all_have_accepted_receipts": len(receipts) == len(TURN_PLAN) + 1
                and all(r.get("status") == "accepted" for r in receipts),
        },
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "run_dir": str(run_dir),
        "backfill": summary["backfill"]["status"],
        "turns": len(results),
        "inferences": len(requests),
        "query_memory_receipts": summary["query_memory_receipts"],
        "assertions": summary["assertions"],
    }, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    parser.add_argument("--stub-smoke", action="store_true", help="run deterministic plumbing smoke, not Luna")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError("refusing to reuse a nonempty simulation run directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    from external_io_guard import ExternalIODenyGuard

    guard = ExternalIODenyGuard(run_dir / "outbound-attempts.json")
    guard.install()
    try:
        router = ScriptedSmokeRouter() if args.stub_smoke else None
        result = asyncio.run(_run(run_dir, args.source_db.resolve(), router=router))
    finally:
        guard.restore()
    if guard.attempts:
        raise RuntimeError("simulation blocked an outbound network/process attempt")
    (run_dir / "guard-summary.json").write_text(
        json.dumps({"blocked_attempt_count": guard.attempts}, indent=2), encoding="utf-8"
    )
    if not all(result["assertions"].values()):
        raise AssertionError("one or more deterministic simulation assertions failed")


if __name__ == "__main__":
    main()
