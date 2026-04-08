import json
import os

from flashtext import KeywordProcessor


class EntityGate:
    def __init__(self, graph_store=None, entities_file="entities.json"):
        self.keyword_processor = KeywordProcessor()
        # Resolve path relative to this script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.entities_file = os.path.join(base_dir, entities_file)
        self._load_from_graph(graph_store)
        self._load_aliases(self.entities_file)

    def _load_from_graph(self, graph_store) -> None:
        """Loads entity names from a SQLiteGraph (or duck-typed equivalent) into FlashText."""
        if graph_store is None:
            print("[WARN] EntityGate: no graph_store provided — skipping KG load")
            return
        names = graph_store.get_all_node_names()
        for name in names:
            self.keyword_processor.add_keyword(name)
        print(f"[OK] EntityGate: loaded {len(names)} entities from knowledge graph")

    def _load_aliases(self, entities_file: str) -> None:
        """Merges optional alias overrides from a JSON file on top of KG-loaded names."""
        if not os.path.exists(entities_file):
            print(f"[WARN] EntityGate: alias file {entities_file} not found — skipping")
            return
        with open(entities_file, encoding="utf-8") as f:
            raw = json.load(f)
        if not raw:
            # Empty dict is normal for OSS repo — skip silently
            return
        # Normalize: values may be lists (variations) or ints (counts from bulk extractor)
        aliases_dict = {
            k: v if isinstance(v, list) else [k]
            for k, v in raw.items()
        }
        self.keyword_processor.add_keywords_from_dict(aliases_dict)
        print(f"[OK] EntityGate: merged {len(aliases_dict)} alias groups from {entities_file}")

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
    gate = EntityGate()   # no graph, no aliases — still runnable standalone

    test_sentences = [
        "I need to fix the py script for synapse.",
        "Is SOTE worth playing?",
        "Configure the vector db for me.",
    ]

    print("\n--- Flash Gate Test ---")
    for sentence in test_sentences:
        extracted = gate.extract_entities(sentence)
        print(f"Input: '{sentence}'")
        print(f"Entities: {extracted}\n")
