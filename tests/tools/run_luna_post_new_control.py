"""Exercise /new and transcript-free persistent recall against a finished run."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_luna_memory_simulation as sim  # noqa: E402


async def _run_controls(run_dir: Path, guard) -> None:
    from luna_file_relay import FileRelayRouter
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path
    from synapse_config import SynapseConfig

    if not (run_dir / "summary.json").is_file():
        raise AssertionError("summary-only stage must complete before post-new controls")
    initial = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if initial.get("turn_count") != 9 or initial.get("inference_request_count", 0) >= 40:
        raise AssertionError("persisted nine-turn run missing or inference cap too close")

    sim._configure_isolated_workspace(run_dir)
    cfg = SynapseConfig.load()
    router = FileRelayRouter(
        run_dir,
        timeout_seconds=180,
        poll_interval_seconds=0.05,
        max_requests=40 - initial["inference_request_count"],
    )
    channel = sim.FakeChannel()
    stack = None
    try:
        stack = await sim._new_worker_stack(cfg.data_root, router, channel, run_dir)
        _store, _service, inbox, flood, _queue, retry, _registry, _worker = stack
        context = sim._context_for_peer(cfg, "alice-peer")
        sessions = SessionStore(agent_id="the_creator", data_root=cfg.data_root)
        prior_request_names = {path.name for path in (run_dir / "requests").glob("*.json")}

        reset_id = "alice-new-control"
        reset_status = sim._inbox_status(inbox, reset_id)
        receipt = sim._outbox_row(retry, f"reply:{reset_id}:0")
        if not (reset_status and reset_status[1] == "completed" and receipt and receipt[0] == "accepted"):
            before = await sessions.get(context.conversation_id)
            if before is None:
                raise AssertionError("Alice's persisted pre-/new session was not found")
            old_transcript = transcript_path(before, cfg.data_root, "the_creator")
            old_messages = await load_messages(old_transcript)
            if len(old_messages) < 2:
                raise AssertionError("pre-/new transcript lacks the expected prior dialogue")
            sent_before = len(channel.sent)
            if not await flood.incoming(
                "alice-peer",
                "/new",
                {"message_id": reset_id, "channel_id": "whatsapp", "sender_name": "alice-peer"},
            ):
                raise AssertionError("/new inbound was unexpectedly deduplicated")
            await sim._wait_until(
                lambda: "completed"
                if sim._inbox_status(inbox, reset_id)
                and sim._inbox_status(inbox, reset_id)[1] == "completed"
                else None,
                label="/new durable completion",
            )
            receipt = await sim._wait_until(
                lambda: sim._outbox_row(retry, f"reply:{reset_id}:0")
                if (sim._outbox_row(retry, f"reply:{reset_id}:0") or (None,))[0] == "accepted"
                else None,
                label="/new accepted fake-channel receipt",
            )
            await sim._wait_until(
                lambda: True if len(channel.sent) > sent_before else None,
                label="/new fake send",
            )
            before_session_id = before.session_id
            old_count = len(old_messages)
            archive_candidates = list(old_transcript.parent.glob(old_transcript.name + ".deleted.*"))
            if not archive_candidates:
                raise AssertionError("/new did not archive the old transcript")
        else:
            # Resume after a prior attempt completed /new but stopped during
            # an assertion; never send the reset command twice.
            new_key_entry = await sessions.get(context.conversation_id)
            if new_key_entry is None:
                raise AssertionError("/new completed but the rotated session is missing")
            archived = list(
                (cfg.data_root / "state" / "agents" / "the_creator" / "sessions").glob(
                    "*.jsonl.deleted.*"
                )
            )
            if not archived:
                raise AssertionError("completed /new has no archived transcript evidence")
            archive_path = max(archived, key=lambda p: p.stat().st_mtime)
            before_session_id = archive_path.name.split(".jsonl.deleted.", 1)[0]
            old_count = len(archive_path.read_text(encoding="utf-8").splitlines())
            after = new_key_entry
        after = await sessions.get(context.conversation_id)
        if after is None or after.session_id == before_session_id:
            raise AssertionError("/new did not rotate the session identifier")
        new_transcript = transcript_path(after, cfg.data_root, "the_creator")
        new_messages = await load_messages(new_transcript)
        if new_messages:
            raise AssertionError("fresh transcript was not empty after /new")
        if not list(
            (cfg.data_root / "state" / "agents" / "the_creator" / "sessions").glob(
                f"{before_session_id}.jsonl.deleted.*"
            )
        ):
            raise AssertionError("old transcript was not archived by /new")

        query_id = "alice-new-recall"
        query_text = "Use query_memory to look up the umbrella incident, then tell me what happened."
        result = await sim._run_turn(
            run_dir, stack, channel, "alice-peer", query_id, query_text
        )
        all_request_files = sorted(
            (run_dir / "requests").glob("*.json"), key=lambda p: p.stat().st_mtime
        )
        request_files = [p for p in all_request_files if p.name not in prior_request_names]
        if len(request_files) > 40:
            raise AssertionError("agent-mediated inference cap exceeded")
        current_packets = [json.loads(path.read_text(encoding="utf-8")) for path in request_files]
        query_packet = next((
            packet for packet in current_packets
            if any(
                isinstance(message, dict)
                and message.get("role") == "user"
                and message.get("content") == query_text
                for message in packet.get("messages", [])
            )
        ), None)
        if query_packet is None:
            raise AssertionError("post-/new query was not present in an inference packet")
        roles = [m for m in query_packet.get("messages", []) if isinstance(m, dict)]
        transcript_users = {
            "What is 17 percent of 235?",
            "At Monday's meeting my tiny red umbrella flipped inside out as I walked in. You called it my CEO umbrella; that's our joke. Remember the umbrella incident.",
        }
        leaked = [
            m.get("content") for m in roles
            if m.get("role") == "user" and m.get("content") in transcript_users
        ]
        if leaked:
            raise AssertionError(f"old transcript user messages leaked after /new: {leaked!r}")
        tool_receipts = (run_dir / "memory_tool_receipts.jsonl").read_text(encoding="utf-8").splitlines()
        control = {
            "reset_message_id": reset_id,
            "old_session_id": before_session_id,
            "new_session_id": after.session_id,
            "old_transcript_message_count": old_count,
            "new_transcript_message_count": len(new_messages),
            "reset_reply": receipt[1],
            "query_message_id": query_id,
            "query": query_text,
            "query_reply": result["reply"],
            "post_new_prompt_user_turns": [
                m.get("content") for m in roles if m.get("role") == "user"
            ],
            "old_transcript_user_turns_leaked": leaked,
            "memory_tool_receipts_count": len(tool_receipts),
            "total_inference_requests": len(request_files),
            "accepted_sends_in_control_process": len(channel.sent),
            "outbound_attempts": guard.attempts,
        }
        (run_dir / "post-new-control.json").write_text(
            json.dumps(control, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(control, ensure_ascii=False), flush=True)
    finally:
        if stack is not None:
            await sim._finish_worker_stack(stack)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    from external_io_guard import ExternalIODenyGuard

    guard = ExternalIODenyGuard(run_dir / "outbound-attempts-controls.json")
    guard.install()
    try:
        asyncio.run(_run_controls(run_dir, guard))
    finally:
        guard.restore()
    if guard.attempts:
        raise RuntimeError("post-new control blocked an outbound network/process attempt")


if __name__ == "__main__":
    main()
