import sys
import os
import time
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sci_fi_dashboard.conflict_resolver import ConflictManager

def test_pruning():
    print("✂️ Testing Conflict Pruning Logic...")
    
    # Use a temp file
    test_file = "test_pruning_conflicts.json"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    cm = ConflictManager(test_file)
    
    # Add 25 conflicts (limit is 20)
    print("Generating 25 conflicts...")
    for i in range(25):
        cm.check_conflict(
            subject=f"Topic {i}", 
            new_fact=f"Fact A{i}", 
            new_confidence=0.5, 
            source="Test", 
            existing_fact=f"Fact B{i}", 
            existing_confidence=0.5
        )
        time.sleep(0.01) # Ensure timestamps differ slightly

    # Verify count
    pending_count = len([c for c in cm.pending_conflicts if c["status"] == "pending"])
    print(f"Pending Conflicts: {pending_count}")
    
    if pending_count <= 20:
        print("✅ PASSED: Conflicts pruned to limit.")
    else:
        print(f"❌ FAILED: Found {pending_count} conflicts (Expected <= 20).")

    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    test_pruning()
