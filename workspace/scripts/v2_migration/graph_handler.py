import networkx as nx
import json
import gzip
import sqlite3
import os

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")
GRAPH_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "knowledge_graph.json.gz")


class GraphStore:
    def __init__(self):
        self.G = nx.DiGraph()
        self.load_from_db()

    def load_from_db(self):
        print("Loading Graph from SQLite...")
        if not os.path.exists(DB_PATH):
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Load links
        cursor.execute("SELECT subject, relation, object FROM entity_links")
        rows = cursor.fetchall()

        for sub, rel, obj in rows:
            self.G.add_edge(sub, obj, relation=rel)

        conn.close()
        print(
            f"Graph loaded with {self.G.number_of_nodes()} nodes and {self.G.number_of_edges()} edges."
        )
        self.save_to_disk()

    def save_to_disk(self):
        data = nx.node_link_data(self.G)
        with gzip.open(GRAPH_PATH, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"Graph persisted to {GRAPH_PATH}")

    # --- Phase 3: Graph Explorer Tools ---

    def get_entity_neighborhood(self, entity: str, depth: int = 1) -> str:
        """Returns immediate connections for context injection."""
        if entity not in self.G:
            return ""

        subgraph = nx.ego_graph(self.G, entity, radius=depth)
        facts = []
        for u, v, data in subgraph.edges(data=True):
            relation = data.get("relation", "related_to")
            facts.append(f"- {u} {relation} {v}")
        return "\n".join(facts)

    def find_connection_path(self, start_entity: str, end_entity: str) -> str:
        """Traces the path between two entities to find causal links."""
        try:
            path = nx.shortest_path(self.G, source=start_entity, target=end_entity)
            narrative = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edge_data = self.G.get_edge_data(u, v)
                relation = edge_data.get("relation", "connected_to")
                narrative.append(f"{u} [{relation}] -> {v}")
            return " -> ".join(narrative)
        except nx.NetworkXNoPath:
            return f"No direct path found between {start_entity} and {end_entity}."
        except nx.NodeNotFound:
            return "One of the entities is missing from the graph."


if __name__ == "__main__":
    store = GraphStore()
    # Test
    # print(store.find_connection("primary_user", "YourWorkplace"))
