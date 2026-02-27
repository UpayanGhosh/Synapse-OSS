import json
import os
import random


class PersonaManager:
    def __init__(self, workspace_root=None):
        if workspace_root is None:
            workspace_root = os.path.expanduser("~/.openclaw")
        self.root = workspace_root
        self.workspace = os.path.join(self.root, "workspace")
        self.dict_path = os.path.join(self.workspace, "skills/language/banglish_dict.json")

        # Identity Files Configuration (Order matters for context layering)
        self.files = {
            "instructions": os.path.join(self.workspace, "INSTRUCTIONS.MD"),
            "soul": os.path.join(self.workspace, "SOUL.md"),
            "core": os.path.join(self.workspace, "CORE.md"),
            "agents": os.path.join(self.workspace, "AGENTS.md"),
            "identity": os.path.join(self.workspace, "IDENTITY.md"),
            "user": os.path.join(self.workspace, "USER.md"),
        }

        self.banglish_data = self.load_dictionary()

    def load_dictionary(self):
        try:
            if os.path.exists(self.dict_path):
                with open(self.dict_path) as f:
                    return json.load(f)
        except Exception:
            # print(f"⚠️ Persona Error: Could not load Banglish dict: {e}")
            pass
        return {}

    def read_file(self, key):
        path = self.files.get(key)
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return f.read()
            except Exception as e:
                return f"<!-- Error reading {key}: {e} -->"
        return ""

    def get_random_words(self, count=5):
        if not self.banglish_data:
            return []
        return random.sample(list(self.banglish_data.keys()), min(count, len(self.banglish_data)))

    def get_system_prompt(self):
        """
        Constructs the high-context system prompt by aggregating identity files.
        """
        # 1. Read Core Files
        instructions = self.read_file("instructions")
        soul = self.read_file("soul")
        core = self.read_file("core")
        agents = self.read_file("agents")
        identity = self.read_file("identity")
        user = self.read_file("user")

        # 2. Dynamic Flavor (Banglish)
        flavor_words = self.get_random_words(8)
        flavor_text = ", ".join(flavor_words)

        # 3. Assemble Prompt
        # Concatenating in logical override order
        prompt = f"""
{instructions}

--- CONTEXT LOADING ---

<SOUL>
{soul}
</SOUL>

<CORE>
{core}
</CORE>

<USER_PROFILE>
{user}
</USER_PROFILE>

<WORKSPACE_GUIDELINES>
{agents}
</WORKSPACE_GUIDELINES>

<IDENTITY_METADATA>
{identity}
</IDENTITY_METADATA>

<DYNAMIC_VOCABULARY_INJECTION>
Required Bengali/Banglish Keywords to use naturally: {flavor_text}
</DYNAMIC_VOCABULARY_INJECTION>
"""
        return prompt
