import os
import sys
import time

# Add current directory to path so we can import modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.knowledge_graph import TransparentBrain
from sci_fi_dashboard.smart_entity import EntityGate


def run_soul_test():
    print("[MAGIC] Initiating Soul Verification Protocol...\n")

    # 1. Initialize Components
    # EntityGate resolves paths relative to itself, so we just need the filename if it's in the same dir
    gate = EntityGate(entities_file="entities.json")
    brain = TransparentBrain(graph_file="soul_graph.json.gz")

    # 2. Simulate "The Gentle Worker" indexing a specific fact
    print("[WORKER] Gentle Worker: Indexing secret strategy...")
    subject = "Malenia"
    brain.add_node(subject, "Boss")
    brain.add_node("Freezing Pot", "Item")
    brain.add_relation(subject, "is weak to", "Freezing Pot")
    brain.save_graph()
    time.sleep(1)  # Dramatic pause
    print("[OK] Indexing Complete.\n")

    # 3. User Query with Slang
    user_query = "Yo, how do I cheese the Rot Goddess?"
    print(f"[PERSON] User: '{user_query}'")

    # 4. Flash Gate Extraction
    entities = gate.extract_entities(user_query)
    print(f"[FLASH] Flash Gate: Detected Entities -> {entities}")

    if not entities:
        print("[ERROR] FAILED: Could not detect entity.")
        return

    # 5. Connect to Transparent Brain
    focus_entity = entities[0]  # Should be "Malenia"
    print(f"[MEM] Transparent Brain: Recalling knowledge for '{focus_entity}'...")

    context = brain.get_context(focus_entity)
    connections = []

    if brain.graph.has_node(focus_entity):
        for neighbor in context:
            edge_data = brain.graph.get_edge_data(focus_entity, neighbor)
            relation = edge_data["relation"]
            connections.append(f"{focus_entity} --[{relation}]--> {neighbor}")

    if connections:
        print("\n[SPARK] SOUL RESURRECTED [SPARK]")
        print("The system successfully connected the slang term to the graph data.")
        print("Knowledge Retrieved:")
        for c in connections:
            print(f"  > {c}")
    else:
        print("[ERROR] FAILED: Entity found but no knowledge retrieved.")


if __name__ == "__main__":
    run_soul_test()
