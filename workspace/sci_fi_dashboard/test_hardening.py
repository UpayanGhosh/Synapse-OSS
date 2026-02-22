import sys
import os
import time
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sci_fi_dashboard.knowledge_graph import TransparentBrain

def test_ram_circuit_breaker():
    print("🛡️ Testing RAM Circuit Breaker...")
    
    # 1. Initialize Brain with tiny limit
    test_file = "test_hardening_graph.json.gz"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    brain = TransparentBrain(graph_file=test_file, max_nodes=10) # Tiny limit
    
    # 2. Add 15 nodes (Limit 10)
    print("Adding 15 nodes (Limit: 10)...")
    for i in range(15):
        brain.add_node(f"Node_{i}")
        time.sleep(0.01) # Ensure timestamps differ

    # 3. Trigger Pruning
    brain.prune_graph()
    
    # 4. Verify
    count = brain.graph.number_of_nodes()
    print(f"Nodes remaining: {count}")
    
    if count <= 10:
        print("✅ PASSED: Graph successfully pruned.")
    else:
        print(f"❌ FAILED: Graph size {count} exceeds limit 10.")
        
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    test_ram_circuit_breaker()
    # Note: Full API test requires running Uvicorn separately, 
    # but unit testing the logic here is sufficient for the "Circuit Breaker".
