import os
import sys

# Add workspace to path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(WORKSPACE_ROOT)

from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402

GRAPH_FILE = os.path.join(WORKSPACE_ROOT, "sci_fi_dashboard", "knowledge_graph.json.gz")
DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/knowledge_graph.db")

if __name__ == "__main__":
    if not os.path.exists(GRAPH_FILE):
        print(f"❌ Source graph file not found at {GRAPH_FILE}")
        sys.exit(1)

    print(f"🚀 Starting migration from {GRAPH_FILE}...")
    SQLiteGraph.migrate_from_networkx(GRAPH_FILE, DB_PATH)
    print("✨ Migration complete!")
