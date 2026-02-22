import json
import os
from flashtext import KeywordProcessor

class EntityGate:
    def __init__(self, entities_file="entities.json"):
        self.keyword_processor = KeywordProcessor()
        # Resolve path relative to this script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.entities_file = os.path.join(base_dir, entities_file)
        self.load_entities()

    def load_entities(self):
        """Loads entities from a JSON file in the format {StandardName: [Variation1, Variation2]}"""
        if os.path.exists(self.entities_file):
            with open(self.entities_file, 'r') as f:
                entities_dict = json.load(f)
                self.keyword_processor.add_keywords_from_dict(entities_dict)
                print(f"✅ Loaded {len(entities_dict)} entity groups from {self.entities_file}")
        else:
            print(f"⚠️ Warning: Entities file {self.entities_file} not found. Starting empty.")

    def extract_entities(self, text):
        """
        Extracts entities from text. 
        Returns a list of 'Standard Names' regardless of which variation was found.
        Example: 'I love SOTE' -> ['Elden Ring']
        """
        return self.keyword_processor.extract_keywords(text)

    def extract_keywords(self, text):
        """
        Alias for extract_entities() - provides compatibility with code 
        that expects a keyword_processor with extract_keywords method.
        """
        return self.extract_entities(text)

    def add_entity(self, standard_name, variations):
        """Adds a new entity or updates existing one with new variations at runtime."""
        if isinstance(variations, str):
            variations = [variations]
        
        self.keyword_processor.add_keyword(standard_name, variations)
        
        # In a real app, we might want to persist this back to the JSON file
        # self.save_entities() 

if __name__ == "__main__":
    # Quick Test
    gate = EntityGate()
    
    test_sentences = [
        "I need to fix the py script for openclaw.",
        "Is SOTE worth playing?",
        "Configure the vector db for me."
    ]
    
    print("\n--- Flash Gate Test ---")
    for sentence in test_sentences:
        extracted = gate.extract_entities(sentence)
        print(f"Input: '{sentence}'")
        print(f"Entities: {extracted}\n")
