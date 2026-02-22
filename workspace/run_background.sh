#!/bin/bash
# Run the Gentle Worker with lowest priority (nice -n 10)
# This ensures it yields CPU to everything else.

export PYTHONPATH=$PYTHONPATH:$(pwd)
echo "🚀 Launching Gentle Worker in background..."
nice -n 10 .venv/bin/python sci_fi_dashboard/gentle_worker.py
