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
To find a specific word (like `primary_language_ratio`) in a file:
- **VS Code:** Press `Ctrl+F` and type what you're looking for
- **Notepad:** Press `Ctrl+F` also works!

---

## 1. Map Your Phone Number to a Persona

Open `workspace/personas.yaml` — this is the single file that controls all personas and
their phone number / keyword mappings. No Python edits needed.

```yaml
personas:
  - id: the_creator
    display_name: "Your Name"
    description: "Chat as Synapse -> you"
    whatsapp_phones:
      - "15551234567"     # digits only, no + prefix
    whatsapp_keywords: [] # optional: route by keyword instead of number

  - id: the_partner
    display_name: "Partner"
    description: "Chat as Synapse -> partner"
    whatsapp_phones:
      - "15559876543"
    whatsapp_keywords: []

default_persona: the_creator  # fallback when no number/keyword matches
```

**Adding a new persona** — append another entry to the list and restart Synapse. A new
`/chat/<id>` API route is registered automatically. You can verify it appears at
`GET http://localhost:8000/openapi.json`.

## 2. Define Your Personas (SBS Architecture)

The system automatically generates its "soul" data when you first start the API Gateway (via `synapse_start.sh` on Mac/Linux or `synapse_start.bat` on Windows). Instead of single files, it uses a layered architecture located in:

**File Location:**
- **macOS/Linux:** `workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`
- **Windows:** `workspace\sci_fi_dashboard\synapse_data\the_creator\profiles\current\`

### Key Files to Edit:
*   **core_identity.json**: Define your name, the bot's name, and personality "pillars".
*   **exemplars.json**: Replace the default `pairs` with your own (Few-Shot learning).
*   **linguistic.json**: Set `preferred_language`, region/locality, local examples, and `language_mix_ratio` (0.0 for neutral default usage, 1.0 for maximum local-language mix).

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

When you first boot this system, the databases (`memory.db` and LanceDB) are completely empty. Because the bot relies on RAG (Retrieval-Augmented Generation) to simulate a "humanoid" long-term memory, **it will temporarily feel like a normal, amnesiac AI** during your first few conversations.

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

**Windows:**
```cmd
curl.exe -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d "{\"subject\": \"User\", \"relation\": \"works_as\", \"object\": \"Backend Engineer\"}"
```

> **Note:** Replace `http://localhost:8000` with your gateway URL if different. Also include `-H "x-api-key: YOUR_TOKEN"` if authentication is required.

### Option B: The Organic Growth (The Long Game)

Just start talking to it! Every time you chat, the `/add` endpoint uses LLMs to extract unstructured triples (Subject-Relation-Object) from your conversation and silently builds the Knowledge Graph in the background. After about 3-4 days of casual chatting, you will notice the bot suddenly recalling past context and acting significantly more "alive."

### Option C: The "Memory Dump" (Instant Hyper-Personalization)

> **Prerequisite:** The bot must already be fully running and connected to your channel (WhatsApp, Telegram, Discord, or Slack — complete the onboarding script first). Option C works by sending instructions to the live bot — it won't work before setup is complete.

If you want the bot to instantly understand your coding style, your humor, or your dynamic with a partner, **you do not need to manually ingest facts.**

Instead:

1. Export your data from another platform (e.g., export your ChatGPT data archive, export a WhatsApp chat history, or download a Discord log).
2. Simply upload the `.json` or `.txt` file directly to the bot via your configured channel (WhatsApp, Telegram, Discord, or Slack).
3. Tell the bot: _"Read this entire chat log file. Extract every relevant personal fact, preference, relationship dynamic, and recurring joke you can find, and ingest them into your Knowledge Graph."_

Because the bot has native file-reading tool capabilities and access to the `/add` memory ingestion logic, it will autonomously read your history, extract the triples, build the SQLite graph, and instantly become a hyper-personalized version of you without you writing a single line of code.

## 4. The Language Walkthrough (Customizing Dialects)

Synapse's default patterns are English-only. All feedback-detection phrases are defined in
a single YAML file — no code editing needed.

### Step 1 — Open the patterns file

```
workspace/sci_fi_dashboard/sbs/feedback/language_patterns.yaml
```

### Step 2 — Add your language's phrases

Each category maps to a specific behavior adjustment. Add regex patterns for your language
under the relevant category:

```yaml
correction_formal:
  - "why (are you|so) formal"
  - "stop being (formal|robotic)"
  # Spanish:
  # - "deja de ser tan formal"
  # Hindi/Urdu:
  # - "bahut formal mat bolo"

correction_length:
  - "too long"
  - "keep it short"
  # Hindi:
  # - "bahut lamba hai"

praise:
  - "good (boy|job)"
  - "perfect"
  # French:
  # - "parfait"
  # - "c'est bien"
```

Patterns are Python regexes, matched case-insensitively. Restart the gateway after saving.

### Step 3 — Teach Synapse your style with examples

In `core_identity.json` or `exemplars.json` (see Section 2), add a few example exchanges
in your local language. The LLM will pick up the dialect cadence from those samples and
start responding in kind — even without any system prompt changes.

### Step 4 — Update voice transcription language (optional)

If you send voice notes, open `workspace/do_transcribe.py` and check the `AudioProcessor`
initialisation. You can pass a `language` hint (e.g. `"es"` for Spanish, `"fr"` for French)
to improve Whisper/Groq accuracy for your dialect.

The system is model-agnostic: as long as you provide **patterns** and **examples**,
Synapse adapts to any human language.

---

## 5. Implicit Feedback Detection (Automatic Style Adaptation)

Synapse includes an `ImplicitFeedbackDetector` that continuously monitors your messages for style corrections. You don't need to explicitly configure anything — just talk naturally and Synapse will adapt.

### How It Works

When you say things like:
- **"Too long"** or **"keep it short"** → Synapse halves its preferred response length
- **"Stop being formal"** or **"sound like a robot"** → Synapse increases its casual/local-language ratio
- **"Be serious"** or **"professional"** → Synapse decreases casual language
- **"Elaborate"** or **"explain more"** → Synapse doubles its response length
- **"Good job"** or **"perfect"** → Synapse reinforces its current style

These adjustments happen **immediately** on the current conversation and are reinforced by the batch processor on its next cycle.

### Customizing Feedback Patterns

Detection phrases are defined in a YAML file — no Python edits needed:

```
workspace/sci_fi_dashboard/sbs/feedback/language_patterns.yaml
```

Open it, add your phrases under the relevant category, save, and restart. Example:

```yaml
correction_formal:
  - "why (are you|so) formal"
  - "stop being (formal|robotic)"
  - "bahut formal mat bolo"   # your language here

praise:
  - "good (boy|job)"
  - "perfect"
  - "ekdum sahi"              # your language here
```

Each category maps to a specific profile adjustment (see table below). Patterns are
Python regexes, matched case-insensitively. If the file is missing, Synapse falls back
to built-in English defaults automatically.

| Category | What it adjusts |
|---|---|
| `correction_formal` | Raises `primary_language_ratio` / `language_mix_ratio` (more casual/local-language) |
| `correction_casual` | Lowers `primary_language_ratio` (more formal) |
| `correction_length` | Halves `avg_response_length` |
| `correction_short` | Doubles `avg_response_length` |
| `praise` | Reinforces current style (logged for batch processor) |
| `rejection` | Logged for batch processor rollback consideration |

---

## 📖 Glossary

| Term | Meaning |
|------|---------|
| **JSON** | A text format for storing data (like a structured text file). Used for configuration. |
| **Few-Shot Examples** | Sample conversations you provide to teach the bot your style/tone. |
| **Knowledge Graph** | A database that stores facts as connections (Subject → Relation → Object). |
| **RAG** | Retrieval-Augmented Generation - looking up info before answering. |
| **Subject-Relation-Object** | The way facts are stored: "User works_as Backend Engineer". |
| **preferred_language** | The language or language mix Synapse should default to. |
| **region/locality** | Cultural and dialect context supplied by the user. |
| **local_language_examples** | User-taught phrases and corrections Synapse can imitate carefully. |
| **primary_language_ratio / language_mix_ratio** | Settings controlling how strongly Synapse leans toward your casual/local-language style (0.0 = neutral default usage, 1.0 = maximum local flavor). Adjusted automatically by feedback phrases. |

> **Tip:** For setup instructions and prerequisites, see [HOW_TO_RUN.md](HOW_TO_RUN.md).
