# 🧠 Persona Setup Guide

The architecture of this system uses "Few-Shot Examples" and dynamically constructed JSON profiles held in RAM. It doesn't use hardcoded system prompts; it uses an aggregated **"Relationship Context."**

Because you are going to use this, you need to change the system from answering to **primary_user** (the creator), to **You**.

## 1. Edit the API Gateway Route Targets

In `workspace/sci_fi_dashboard/api_gateway.py`, search for the `PHONE_MAP` and the target keywords. You need to map your own phone number/name to a persona name.

```python
    # Strict Phone Mapping
    PHONE_MAP = {
        "9198XXXXXXXX": "your_girlfriend_or_friend",
        "858XXXXXXX": "your_name"
    }
```

## 2. Define Your Personas

Create or edit your own persona JSON files in `workspace/sci_fi_dashboard/personas/`.

For example, `your_name_profile.json`:

```json
{
  "target_user": "Your Name",
  "relationship_mode": "brother",
  "relationship_context": {
    "role": "You are a pragmatic, direct digital assistant who speaks plainly.",
    "rules": "Never apologize. Be concise. Push me to finish my features."
  },
  "few_shot_examples": [
    {
      "user": "I am too tired to code today.",
      "jarvis": "Excuses don't ship products. Drink coffee and open the terminal."
    }
  ]
}
```

_The system will dynamically read this JSON, convert it into an Anthropic-style `System Prompt`, and append the latest Memories to it before hitting the Gemini/Claude/Ollama routers._

## 3. The "Cold Start" Problem (Building the Soul)

When you first boot this system, the databases (`memory.db` and Qdrant) are completely empty. Because the bot relies on RAG (Retrieval-Augmented Generation) to simulate a "humanoid" long-term memory, **it will temporarily feel like a normal, amnesiac AI** during your first few conversations.

This is the "Cold Start" problem. To fix this and jump-start its "soul", you have two options:

### Option A: The "Genesis" Injection (Recommended)

You don't need to wait weeks for it to learn about you. You can manually inject core facts into its Knowledge Graph immediately using the `/ingest` endpoint or a simple script.

Example facts to inject on Day 1:

- `User` $\to$ `works_as` $\to$ `Backend Engineer`
- `User` $\to$ `hates` $\to$ `writing frontend CSS`
- `User` $\to$ `lives_in` $\to$ `New York`

Once these are injected, the very first time you text it "I'm tired of working", it will query the graph and reply: _"Tired of writing Backend code in New York? Tough. Drink coffee."_ Instant humanoid context!

### Option B: The Organic Growth (The Long Game)

Just start talking to it! Every time you chat, the `/add` endpoint uses LLMs to extract unstructured triples (Subject-Relation-Object) from your conversation and silently builds the Knowledge Graph in the background. After about 3-4 days of casual chatting, you will notice the bot suddenly recalling past context and acting significantly more "alive."

### Option C: The "Memory Dump" (Instant Hyper-Personalization)

If you want the bot to instantly understand your coding style, your humor, or your dynamic with a partner, **you do not need to manually ingest facts.**

Instead:

1. Export your data from another platform (e.g., export your ChatGPT data archive, export a WhatsApp chat history, or download a Discord log).
2. Simply upload the `.json` or `.txt` file directly to the bot via the OpenClaw interface or your configured Telegram/WhatsApp channel.
3. Tell the bot: _"Read this entire chat log file. Extract every relevant personal fact, preference, relationship dynamic, and recurring joke you can find, and ingest them into your Knowledge Graph."_

Because the bot has native file-reading tool capabilities (inherited from OpenClaw) and access to the `/add` memory ingestion logic, it will autonomously read your history, extract the triples, build the SQLite graph, and instantly become a hyper-personalized version of you without you writing a single line of code.

## 4. The Language Walkthrough (Customizing Dialects)

By default, the "soul" of this bot is programmed to speak in **Benglish** (a mix of Bengali and English) because that is how the creator communicates. If you want the bot to speak in plain English, or in your own local language (Hindi, Spanish, French, etc.), you need to update a few key files.

### To Switch to Plain English:
1.  **Open `workspace/CORE.md`**: Locate the `Language` section and change "Benglish" to "Plain English".
2.  **Open `workspace/INSTRUCTIONS.MD`**: Under `Personality Traits`, change the `Language` and `Style` notes to "Native English".
3.  **Open `workspace/sci_fi_dashboard/api_gateway.py`**: Search for the word `Banglish` and update the `system` prompts inside functions like `route_traffic_cop` or `translate_banglish` to instruct the model to use English only.

### To Use Your Own Local Language:
If you want a "Spanglish" bot or a French-speaking Jarvis:
1.  **Modify `CORE.md`**: Update the instructions to say: *"Speak in [Your Language] for casual conversation and English for technical explanations."*
2.  **Teach it Slang**: In your `your_name_profile.json` (see Section 2), add several `few_shot_examples` using your local slang. The LLM will instantly pick up the cadence and dialect from those examples.
3.  **Update Transcription (Optional)**: If you use audio messages, check `workspace/scripts/transcribe_v2.py` and update the `language` code (e.g., `es` for Spanish, `fr` for French) to improve Whisper/Groq accuracy for your dialect.

The bot is model-agnostic, meaning as long as you update the **Instructions** and provide **Examples**, it will adapt to any human language you prefer.
