# 🧠 Persona Setup Guide

The architecture of this system uses "Few-Shot Examples" and dynamically constructed JSON profiles held in RAM. It doesn't use hardcoded system prompts; it uses an aggregated **"Relationship Context."**

Because you are going to use this, you need to change the system from answering to **primary_user** (the creator), to **You**.

---

## 📝 How to Edit Files (For Beginners)

To customize your Synapse, you'll need to edit text files. Here's how:

### Option 1: Notepad (Windows - Built-in)
1. Right-click any `.json` or `.py` file in File Explorer
2. Select **"Open with"** → **"Notepad"**
3. Edit the text and save (Ctrl+S)

### Option 2: VS Code (Recommended - Better Experience)
1. Download free from https://code.visualstudio.com/
  2. Install and open the Synapse-OSS folder
3. Click any file to edit - it has syntax highlighting and makes editing easier!
4. Save changes with Ctrl+S

### Tip: Finding Text in Files
To find a specific word (like `PHONE_MAP`) in a file:
- **VS Code:** Press `Ctrl+F` and type what you're looking for
- **Notepad:** Press `Ctrl+F` also works!

---

## 1. Edit the API Gateway Route Targets

In `workspace/sci_fi_dashboard/api_gateway.py`, search for the `PHONE_MAP` and the target keywords. You need to map your own phone number/name to a persona name.

```python
    # Strict Phone Mapping
    PHONE_MAP = {
        "9198XXXXXXXX": "your_girlfriend_or_friend",
        "858XXXXXXX": "your_name"
    }
```

## 2. Define Your Personas (SBS Architecture)

The system automatically generates its "soul" data when you first start the API Gateway (via `synapse_start.sh` / `synapse_start.ps1`). Instead of single files, it uses a layered architecture located in:

**File Location:**
- **macOS/Linux:** `workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`
- **Windows:** `workspace\sci_fi_dashboard\synapse_data\the_creator\profiles\current\`

### Key Files to Edit:
*   **core_identity.json**: Define your name, the bot's name, and personality "pillars".
*   **exemplars.json**: Replace the default `pairs` with your own (Few-Shot learning).
*   **linguistic.json**: Change the `banglish_ratio` (0.0 for pure English).

For example, to change who the bot thinks you are, edit `core_identity.json`:

```json
{
  "assistant_name": "Synapse",
  "user_name": "Your Name",
  "user_nickname": "Buddy",
  "relationship": "trusted_technical_companion",
  "personality_pillars": [
    "Sharp technical mind",
    "Casual humor",
    "Direct and honest"
  ]
}
```

_The bot creates these folders automatically on boot. If you don't see them yet, start the gateway once!_


## 3. The "Cold Start" Problem (Building the Soul)

When you first boot this system, the databases (`memory.db` and Qdrant) are completely empty. Because the bot relies on RAG (Retrieval-Augmented Generation) to simulate a "humanoid" long-term memory, **it will temporarily feel like a normal, amnesiac AI** during your first few conversations.

This is the "Cold Start" problem. To fix this and jump-start its "soul", you have two options:

### Option A: The "Genesis" Injection (Recommended)

You don't need to wait weeks for it to learn about you. You can manually inject core facts into its Knowledge Graph immediately using the `/ingest` endpoint or a simple script.

Example facts to inject on Day 1:

- `User` → `works_as` → `Backend Engineer`
- `User` → `hates` → `writing frontend CSS`
- `User` → `lives_in` → `New York`

Once these are injected, the very first time you text it "I'm tired of working", it will query the graph and reply: _"Tired of writing Backend code in New York? Tough. Drink coffee."_ Instant humanoid context!

### How to Inject Facts (The /ingest Endpoint)

Run this command in your terminal to inject facts:

**macOS/Linux:**
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"subject": "User", "relation": "works_as", "object": "Backend Engineer"}'
```

**Windows PowerShell:**
```powershell
curl.exe -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d "{\"subject\": \"User\", \"relation\": \"works_as\", \"object\": \"Backend Engineer\"}"
```

> **Note:** Replace `http://localhost:8000` with your gateway URL if different. Also include `-H "x-api-key: YOUR_TOKEN"` if authentication is required.

### Option B: The Organic Growth (The Long Game)

Just start talking to it! Every time you chat, the `/add` endpoint uses LLMs to extract unstructured triples (Subject-Relation-Object) from your conversation and silently builds the Knowledge Graph in the background. After about 3-4 days of casual chatting, you will notice the bot suddenly recalling past context and acting significantly more "alive."

### Option C: The "Memory Dump" (Instant Hyper-Personalization)

> **Prerequisite:** The bot must already be fully running and connected to WhatsApp (complete the onboarding script first). Option C works by sending instructions to the live bot — it won't work before setup is complete.

If you want the bot to instantly understand your coding style, your humor, or your dynamic with a partner, **you do not need to manually ingest facts.**

Instead:

1. Export your data from another platform (e.g., export your ChatGPT data archive, export a WhatsApp chat history, or download a Discord log).
2. Simply upload the `.json` or `.txt` file directly to the bot via the OpenClaw interface or your configured WhatsApp channel.
3. Tell the bot: _"Read this entire chat log file. Extract every relevant personal fact, preference, relationship dynamic, and recurring joke you can find, and ingest them into your Knowledge Graph."_

Because the bot has native file-reading tool capabilities (inherited from OpenClaw) and access to the `/add` memory ingestion logic, it will autonomously read your history, extract the triples, build the SQLite graph, and instantly become a hyper-personalized version of you without you writing a single line of code.

## 4. The Language Walkthrough (Customizing Dialects)

By default, the "soul" of this bot is programmed to speak in **Benglish** (a mix of Bengali and English) because that is how the creator communicates. If you want the bot to speak in plain English, or in your own local language (Hindi, Spanish, French, etc.), you need to update a few key files.

### To Switch to Plain English:
1.  **Open `workspace/CORE.md`**: Locate the language instructions and change to "Plain English".
2.  **Open `workspace/sci_fi_dashboard/api_gateway.py`**: Search for the function `route_traffic_cop` (the Traffic Cop intent classifier) and `translate_banglish` (the language post-processor). Update the `system` prompt strings inside those two functions to instruct the model to use English only. Tip: use Ctrl+F and search for `def route_traffic_cop` and `def translate_banglish` to jump directly to the right locations — there are many occurrences of the word "Banglish" in the file across unrelated sections.

### To Use Your Own Local Language:
If you want a "Spanglish" bot or a French-speaking Synapse:
1.  **Modify `CORE.md`**: Update the instructions to say: *"Speak in [Your Language] for casual conversation and English for technical explanations."*
2.  **Teach it Slang**: In your `core_identity.json` or `exemplars.json` (see Section 2), add several `few_shot_examples` using your local slang. The LLM will instantly pick up the cadence and dialect from those examples.
3.  **Update Transcription (Optional)**: If you use audio messages, check `workspace/scripts/transcribe_v2.py` and update the `language` code (e.g., `es` for Spanish, `fr` for French) to improve Whisper/Groq accuracy for your dialect.

The bot is model-agnostic, meaning as long as you update the **Instructions** and provide **Examples**, it will adapt to any human language you prefer.

---

## 📖 Glossary

| Term | Meaning |
|------|---------|
| **JSON** | A text format for storing data (like a structured text file). Used for configuration. |
| **Few-Shot Examples** | Sample conversations you provide to teach the bot your style/tone. |
| **Knowledge Graph** | A database that stores facts as connections (Subject → Relation → Object). |
| **RAG** | Retrieval-Augmented Generation - looking up info before answering. |
| **Subject-Relation-Object** | The way facts are stored: "User works_as Backend Engineer". |
| **banglish_ratio** | A setting controlling how much Bengali mix to use (0.0 = pure English). |

> **Tip:** For setup instructions and prerequisites, see [HOW_TO_RUN.md](HOW_TO_RUN.md).
