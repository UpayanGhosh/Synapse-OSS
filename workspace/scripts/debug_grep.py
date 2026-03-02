import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
from synapse_config import SynapseConfig

import os

log_file = str(SynapseConfig.load().log_dir / "synapse-2026-02-13.log")
search_term = "Cloud Code"
search_term2 = "empty response"

try:
    with open(log_file, "r") as f:
        for i, line in enumerate(f, 1):
            if search_term.lower() in line.lower() or search_term2.lower() in line.lower():
                print(f"Line {i}: {line.strip()}")
except Exception as e:
    print(f"Error reading file: {e}")
