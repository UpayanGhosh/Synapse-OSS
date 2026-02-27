import json
import os
import shutil
import time
from datetime import datetime, timedelta

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
SESSION_FILE = os.path.join(OPENCLAW_HOME, "agents", "main", "sessions", "sessions.json")
MAX_AGE_DAYS = 7


def prune_sessions():
    if not os.path.exists(SESSION_FILE):
        print("Session file not found.")
        return

    print(f"Reading sessions from {SESSION_FILE}...")
    try:
        with open(SESSION_FILE, "r") as f:
            sessions = json.load(f)
    except json.JSONDecodeError:
        print("Error decoding JSON.")
        return

    print(f"Total sessions: {len(sessions)}")

    cutoff_time = time.time() - (MAX_AGE_DAYS * 86400)
    new_sessions = {}
    pruned_count = 0

    for key, session in sessions.items():
        # Check 'updatedAt' primarily
        last_active = (
            session.get("updatedAt") or session.get("lastMessageAt") or session.get("createdAt")
        )

        keep = True
        if last_active:
            # Handle ISO string vs Timestamp
            try:
                if isinstance(last_active, str):
                    dt = datetime.fromisoformat(last_active.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                else:
                    ts = float(last_active) / 1000.0  # JS ms to seconds

                if ts < cutoff_time:
                    keep = False
                    # Optional: Print what we are deleting
                    # print(f"Pruning {key} (Age: {(time.time() - ts)/86400:.1f} days)")
            except:
                # If we can't parse, keep it to be safe
                pass

        if keep:
            new_sessions[key] = session
        else:
            pruned_count += 1

    if pruned_count > 0:
        print(f"Pruning {pruned_count} sessions...")
        # Backup first
        shutil.copy2(SESSION_FILE, f"{SESSION_FILE}.bak")

        with open(SESSION_FILE, "w") as f:
            json.dump(new_sessions, f, indent=2)
        print("[OK] Pruning complete.")
    else:
        print("No sessions to prune.")


if __name__ == "__main__":
    prune_sessions()
