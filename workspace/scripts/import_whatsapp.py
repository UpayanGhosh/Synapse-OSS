#!/usr/bin/env python3
"""
WhatsApp Export Importer — seeds memory from real conversation history.

Parses WhatsApp .txt chat exports and ingests them into Synapse's
memory pipeline as conversation chunks.

WhatsApp export format:
  [MM/DD/YY, HH:MM:SS AM/PM] Name: message text
  or
  [DD/MM/YYYY, HH:MM:SS] Name: message text

Usage:
    cd workspace
    python scripts/import_whatsapp.py chat_export.txt --speaker "YourName" --hemisphere safe
    python scripts/import_whatsapp.py chat_export.txt --speaker "FriendName" --hemisphere spicy --dry-run
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))

# WhatsApp date format patterns
WA_PATTERNS = [
    # [MM/DD/YY, HH:MM:SS AM/PM] Name: message
    re.compile(
        r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\]\s*([^:]+):\s*(.+)$"
    ),
    # MM/DD/YY, HH:MM - Name: message (no brackets)
    re.compile(
        r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?:\s*[AP]M)?)\s*-\s*([^:]+):\s*(.+)$"
    ),
]

SKIP_MESSAGES = [
    "Messages and calls are end-to-end encrypted",
    "<Media omitted>",
    "image omitted",
    "audio omitted",
    "video omitted",
    "sticker omitted",
    "document omitted",
    "This message was deleted",
    "You deleted this message",
]

CHUNK_SIZE = 10  # messages per chunk
MIN_WORDS = 3  # skip messages with fewer words


def parse_export(filepath: Path) -> list[dict]:
    """Parse a WhatsApp .txt export into a list of messages."""
    messages = []
    current_msg = None

    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            matched = False
            for pattern in WA_PATTERNS:
                m = pattern.match(line)
                if m:
                    if current_msg:
                        messages.append(current_msg)
                    date_str, time_str, sender, content = m.groups()
                    current_msg = {
                        "date": date_str.strip(),
                        "time": time_str.strip(),
                        "sender": sender.strip(),
                        "content": content.strip(),
                    }
                    matched = True
                    break

            if not matched and current_msg and line.strip():
                # Continuation of previous message
                current_msg["content"] += " " + line.strip()

    if current_msg:
        messages.append(current_msg)

    return messages


def filter_messages(messages: list[dict], speaker: str = None) -> list[dict]:
    """Filter out media/system messages. Optionally filter by speaker."""
    filtered = []
    for msg in messages:
        content = msg["content"]
        if any(skip in content for skip in SKIP_MESSAGES):
            continue
        if len(content.split()) < MIN_WORDS:
            continue
        if speaker and msg["sender"].lower() != speaker.lower():
            continue
        filtered.append(msg)
    return filtered


def chunk_messages(messages: list[dict], chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Group messages into chunks of N for more meaningful context."""
    chunks = []
    for i in range(0, len(messages), chunk_size):
        group = messages[i : i + chunk_size]
        lines = []
        for msg in group:
            lines.append(f"[{msg['date']}] {msg['sender']}: {msg['content']}")
        chunks.append("\n".join(lines))
    return chunks


def ingest_chunks(chunks: list[str], hemisphere: str, dry_run: bool) -> int:
    """Insert chunks into Synapse documents table."""
    if dry_run:
        print(f"  [dry] Would insert {len(chunks)} chunks (hemisphere={hemisphere})")
        return 0

    from sci_fi_dashboard.db import DatabaseManager

    conn = DatabaseManager.get_connection()
    inserted = 0
    for chunk in chunks:
        try:
            conn.execute(
                "INSERT INTO documents (filename, content, hemisphere_tag, processed) "
                "VALUES (?,?,?,0)",
                ("whatsapp_import", chunk, hemisphere),
            )
            inserted += 1
        except Exception as e:
            print(f"  [warn] Insert failed: {e}")
    conn.commit()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Import WhatsApp export into Synapse memory")
    parser.add_argument("file", help="Path to WhatsApp .txt export file")
    parser.add_argument(
        "--speaker", default=None, help="Filter to only import messages from this speaker name"
    )
    parser.add_argument(
        "--hemisphere",
        choices=["safe", "spicy"],
        default="safe",
        help="Hemisphere tag for imported messages (default: safe)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Messages per chunk (default: {CHUNK_SIZE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview only — no writes to database"
    )
    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"[ERROR] File not found: {filepath}")
        sys.exit(1)

    print(f"\nWhatsApp Export Importer")
    print(f"File: {filepath}")
    print(f"Speaker filter: {args.speaker or '(all senders)'}")
    print(f"Hemisphere: {args.hemisphere}")
    print(f"Chunk size: {args.chunk_size} messages")
    print("=" * 50)

    # Parse
    all_messages = parse_export(filepath)
    print(f"Parsed: {len(all_messages)} total messages")

    # Filter
    filtered = filter_messages(all_messages, args.speaker)
    print(f"After filtering: {len(filtered)} messages")

    if not filtered:
        print("[WARN] No messages after filtering. Check --speaker name.")
        sys.exit(0)

    # Sample
    print(f"\nSample (first 3 messages):")
    for msg in filtered[:3]:
        print(f"  [{msg['date']}] {msg['sender']}: {msg['content'][:80]}")

    # Chunk
    chunks = chunk_messages(filtered, args.chunk_size)
    print(f"\nChunked into: {len(chunks)} context blocks")

    # Ingest
    if args.dry_run:
        print("\n[DRY RUN] No data written.")
        print(f"  Would insert {len(chunks)} chunks into documents table")
        print(f"  hemisphere_tag = '{args.hemisphere}'")
        print("\nRe-run without --dry-run to import.")
    else:
        inserted = ingest_chunks(chunks, args.hemisphere, dry_run=False)
        print(f"\n[OK] Inserted {inserted} chunks into memory")
        print("\nNext steps:")
        print("  1. Re-embed into LanceDB: python scripts/re_embed_lancedb.py")
        print("  2. Test retrieval: curl -X POST http://localhost:8000/chat/the_creator ...")


if __name__ == "__main__":
    main()
