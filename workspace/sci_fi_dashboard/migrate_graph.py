import os
import sys

# Add workspace to path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(WORKSPACE_ROOT)

from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402

try:
    from synapse_config import SynapseConfig  # noqa: PLC0415
except ImportError:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
    from synapse_config import SynapseConfig

GRAPH_FILE = os.path.join(WORKSPACE_ROOT, "sci_fi_dashboard", "knowledge_graph.json.gz")
DB_PATH = str(SynapseConfig.load().db_dir / "knowledge_graph.db")

if __name__ == "__main__":
    if not os.path.exists(GRAPH_FILE):
        print(f"[ERROR] Source graph file not found at {GRAPH_FILE}")
        sys.exit(1)

    print(f"[INFO] Starting migration from {GRAPH_FILE}...")
    SQLiteGraph.migrate_from_networkx(GRAPH_FILE, DB_PATH)
    print("[SPARK] Migration complete!")
