#!/bin/bash
START=$(date +%s)
LOG=/d/Shreya/Synapse-OSS/.explainer_progress.json
while true; do
  NOW=$(date +%s)
  ELAPSED=$(( (NOW - START) / 60 ))
  HOURS=$(( ELAPSED / 60 ))
  MINS=$(( ELAPSED % 60 ))
  STATUS="running"
  WARNING=""
  if [ $ELAPSED -ge 240 ]; then
    STATUS="DANGER_5H_LIMIT_NEAR"
    WARNING="STOP DISPATCHING NEW AGENTS - 5h limit imminent"
  elif [ $ELAPSED -ge 200 ]; then
    STATUS="WARNING_APPROACHING_LIMIT"
    WARNING="Slow down - approaching 5h limit"
  fi
  echo "{\"start_epoch\": $START, \"elapsed_minutes\": $ELAPSED, \"elapsed_human\": \"${HOURS}h ${MINS}m\", \"status\": \"$STATUS\", \"warning\": \"$WARNING\", \"checked_at\": \"$(date)\"}" > $LOG
  sleep 120
done
