#!/bin/bash

# rollback.sh - Prune last N turns from OpenClaw session transcript
# Usage: ./rollback.sh -n 1

N=1
while getopts "n:" opt; do
  case $opt in
    n) N=$OPTARG ;;
    *) echo "Usage: $0 -n <number_of_turns>"; exit 1 ;;
  esac
done

# Find the most recent session file
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
SESSION_DIR="$OPENCLAW_HOME/agents/main/sessions"
SESSION_FILE=$(ls -t "$SESSION_DIR"/*.jsonl | head -n 1)

if [ -z "$SESSION_FILE" ]; then
    echo "Error: No session file found in $SESSION_DIR"
    exit 1
fi

echo "Targeting session: $(basename "$SESSION_FILE")"

# Find the line number of the N-th "user" role from the end
# Note: Transcript lines are JSON objects. User turns start with {"role":"user",...}
LINE_NUM=$(grep -n '"role":"user"' "$SESSION_FILE" | tail -n "$N" | head -n 1 | cut -d: -f1)

if [ -z "$LINE_NUM" ]; then
    echo "Error: Could not find $N turns to rollback."
    exit 1
fi

# Create a backup just in case
cp "$SESSION_FILE" "${SESSION_FILE}.bak"

# Delete from LINE_NUM to the end of the file
# Using sed -i '' for macOS compatibility
sed -i '' "${LINE_NUM},\$d" "$SESSION_FILE"

echo "Successfully rolled back $N turns. (Deleted from line $LINE_NUM onwards)"
echo "Backup created at ${SESSION_FILE}.bak"
