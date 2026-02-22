import json
import os
import time
import uuid

class ConflictManager:
    def __init__(self, conflicts_file="conflicts.json"):
        # Resolve path relative to this script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.conflicts_file = os.path.join(base_dir, conflicts_file)
        self.pending_conflicts = self.load_conflicts()

    def load_conflicts(self):
        if os.path.exists(self.conflicts_file):
            with open(self.conflicts_file, 'r') as f:
                return json.load(f)
        return []

    def save_conflicts(self):
        with open(self.conflicts_file, 'w') as f:
            json.dump(self.pending_conflicts, f, indent=2)

    def check_conflict(self, subject, new_fact, new_confidence, source, existing_fact=None, existing_confidence=0.0):
        """
        Checks if a new fact conflicts with an existing one.
        Returns: 
            - "OVERWRITE": If new confidence is high (>0.9) and old is low.
            - "CONFLICT": If both are similar/high.
            - "IGNORE": If new is low and old is high.
        """
        if not existing_fact:
            return "NEW"

        if new_fact == existing_fact:
            return "SAME"

        # User Logic: High Confidence determines the winner
        if new_confidence > 0.9 and existing_confidence < 0.5:
            # print(f"🚀 High confidence overwrite! ({new_confidence} vs {existing_confidence})")
            return "OVERWRITE"
        
        if existing_confidence > 0.9 and new_confidence < 0.5:
             # print(f"🛡️ Ignoring low confidence noise. ({new_confidence} vs {existing_confidence})")
             return "IGNORE"

        # If we are here, it's a real conflict
        self.register_conflict(subject, new_fact, source, existing_fact)
        return "CONFLICT"

    def register_conflict(self, subject, new_fact, source, existing_fact):
        conflict_id = str(uuid.uuid4())[:8]
        conflict_entry = {
            "id": conflict_id,
            "subject": subject,
            "timestamp": time.time(),
            "option_a": {
                "fact": existing_fact,
                "source": "Memory"
            },
            "option_b": {
                "fact": new_fact,
                "source": source
            },
            "status": "pending"
        }
        self.pending_conflicts.append(conflict_entry)
        self.prune_conflicts()
        self.save_conflicts()
        # print(f"🚩 Conflict Registered: {subject} -> '{new_fact}' vs '{existing_fact}'")

    def prune_conflicts(self, max_conflicts=20):
        """Auto-discards old conflicts if queue gets too large."""
        pending = [c for c in self.pending_conflicts if c["status"] == "pending"]
        if len(pending) > max_conflicts:
            # Sort by timestamp (newest first)
            pending.sort(key=lambda x: x["timestamp"], reverse=True)
            # Keep top N
            kept = pending[:max_conflicts]
            discarded_count = len(pending) - max_conflicts
            
            # Rebuild list: kept pending + already resolved
            resolved = [c for c in self.pending_conflicts if c["status"] != "pending"]
            self.pending_conflicts = kept + resolved
            print(f"✂️ Pruned {discarded_count} old conflicts to prevent overflow.")

    def get_morning_briefing_questions(self):
        questions = []
        for c in self.pending_conflicts:
            if c["status"] == "pending":
                q = (f"Conflict ID {c['id']}: Regarding '{c['subject']}', "
                     f"you previously said '{c['option_a']['fact']}', "
                     f"but recently (via {c['option_b']['source']}) I heard '{c['option_b']['fact']}'. "
                     "Which one is correct?")
                questions.append(q)
        return questions

    def resolve(self, conflict_id, choice):
        """
        Resolves a conflict. 
        choice: 'A' (keep old), 'B' (accept new)
        """
        for c in self.pending_conflicts:
            if c["id"] == conflict_id:
                c["status"] = "resolved"
                c["resolution"] = choice
                self.save_conflicts()
                return f"Resolved {conflict_id}: Kept {'Option A' if choice == 'A' else 'Option B'}"
        return "Conflict ID not found."

if __name__ == "__main__":
    # Test
    cm = ConflictManager("test_conflicts.json")
    
    # 1. New fact (No conflict)
    result = cm.check_conflict("Coffee", "I love match", 0.95, "Chat", None, 0.0)
    print(f"Test 1 (New): {result}")

    # 2. High Confidence Overwrite
    result = cm.check_conflict("Coffee", "I LOVE matcha", 0.95, "Chat", "I like matcha", 0.2)
    print(f"Test 2 (Overwrite): {result}")

    # 3. Real Conflict
    result = cm.check_conflict("Coffee", "I hate coffee", 0.8, "Chat", "I love coffee", 0.8)
    print(f"Test 3 (Conflict): {result}")
    
    # 4. Briefing
    print("\nMorning Briefing:")
    for q in cm.get_morning_briefing_questions():
        print(q)
