# Synapse — Complete Setup Guide

This guide takes you from a blank computer to a fully running Synapse instance.
No prior experience required. Every command is shown for **Windows**, **macOS**, and **Linux**.

---

## What You Are Setting Up

Synapse is a self-hosted AI assistant that lives in WhatsApp. It has persistent memory,
an evolving personality, and routes private conversations to a local model with zero
cloud exposure. Here is how the pieces fit together:

```
Your Phone (WhatsApp)
        ↓
  Baileys Bridge (internal)  ← spawned automatically by the gateway; bridges WhatsApp to your computer
        ↓
  Synapse API Gateway        ← the brain: memory, routing, persona
        ↓
  ┌──────────────────┬──────────────────────────────────────┐
  │  Gemini / Claude │  Ollama (nomic-embed-text)           │
  │  (cloud LLMs)    │  ← REQUIRED for memory & ingestion   │
  └──────────────────┴──────────────────────────────────────┘
        ↓
  Qdrant + SQLite            ← memory databases
```

**What runs on your machine:** Ollama, the Synapse API gateway, the Baileys WhatsApp bridge, and the databases.
**What lives in the cloud:** The LLM API you configure (Gemini, Claude, OpenRouter, etc.).

> **Why Ollama is required:** Every message you send and every fact Synapse learns is
> converted into a 768-dimensional embedding vector using Ollama's `nomic-embed-text` model.
> These vectors are what make memory retrieval semantic (meaning-aware) rather than just
> keyword matching. Without Ollama running, ingestion falls back to pure full-text search —
> Synapse will still chat but will have no real long-term memory.

---

## Time Required

| Stage | Time |
|-------|------|
| Installing prerequisites | 15–30 min (mostly downloads) |
| Pulling Ollama model (`nomic-embed-text`, ~900 MB) | 5–15 min depending on connection |
| First-time onboarding | 5–10 min |
| Scanning WhatsApp QR code | 2 min |
| **Total** | **~30–60 min** |

---

## Part 1 — Install Prerequisites

You need **four things** before you start. Install them in order.

---

### 1.1 — Git

**Check if you have it:**
```bash
git --version
```

**Install if missing:**

| Platform | Command / Link |
|----------|---------------|
| macOS | `brew install git` (if Homebrew is installed) or download from [git-scm.com](https://git-scm.com/download/mac) |
| Linux (Debian/Ubuntu) | `sudo apt update && sudo apt install -y git` |
| Linux (Fedora/RHEL) | `sudo dnf install -y git` |
| Windows | Download from [git-scm.com](https://git-scm.com/download/win) — install with default options |

---

### 1.2 — Python 3.11 or higher

**Check if you have it:**

```bash
# macOS / Linux
python3 --version

# Windows
python --version
```

You need version **3.11 or higher**. 3.12 and 3.13 also work.

**Install if missing:**

| Platform | How |
|----------|-----|
| macOS | `brew install python@3.11` or download from [python.org](https://www.python.org/downloads/) |
| Linux (Debian/Ubuntu) | `sudo apt install -y python3.11 python3.11-venv python3.11-dev` |
| Linux (Fedora) | `sudo dnf install -y python3.11` |
| Windows | Download from [python.org](https://www.python.org/downloads/) |

> **Windows:** During installation, check **"Add Python to PATH"** — this is unchecked by default and you will get errors without it.

> **Windows — C++ Build Tools:** The `sqlite-vec` package (vector memory) requires a C++ compiler on Windows. If `pip install` fails with a build error later, install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and select the **"Desktop development with C++"** workload. Then retry.

---

### 1.3 — Docker Desktop

Docker runs the Qdrant vector database (long-term memory storage).

**Check if you have it:**
```bash
docker --version
docker info   # Should say "Server: Docker Engine" — if this fails, Docker isn't running
```

**Install:**
- **macOS:** [docs.docker.com/desktop/install/mac-install](https://docs.docker.com/desktop/install/mac-install/)
- **Windows:** [docs.docker.com/desktop/install/windows-install](https://docs.docker.com/desktop/install/windows-install/)
- **Linux:** [docs.docker.com/desktop/install/linux-install](https://docs.docker.com/desktop/install/linux-install/) — or use Docker Engine without Desktop

> **After installing Docker Desktop on Windows or Mac:** Launch the application and wait for the whale icon in the system tray to stop animating. Docker must be *running* before you start Synapse.

---

### 1.4 — Ollama (Required — powers memory and ingestion)

Ollama runs the `nomic-embed-text` embedding model locally. This model converts every
message and memory into a 768-dimensional vector — the foundation of Synapse's semantic
memory system. **Without it, memory ingestion does not work.**

Ollama also unlocks **The Vault**: a private conversation mode where responses are generated
by a local LLM with zero cloud exposure.

#### Install Ollama

> **The onboarding script (`synapse_onboard.sh` / `.bat`) installs Ollama
> automatically if it is not found.** You can skip the manual install below and let the
> script handle it — or pre-install now if you prefer.

| Platform | Manual install |
|----------|----------------|
| macOS | Download from [ollama.com/download](https://ollama.com/download) and run the `.dmg` |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Windows | Download the installer from [ollama.com/download](https://ollama.com/download) and run it |

**Verify the install:**
```bash
ollama --version
```

#### Pull the required embedding model

> **The onboarding script pulls `nomic-embed-text` automatically and waits for it to
> complete before continuing.** If you pre-installed Ollama, you can optionally pull now:

```bash
ollama pull nomic-embed-text
```

You can check download progress:
```bash
ollama list
# When done, you'll see:
# NAME                    ID              SIZE      MODIFIED
# nomic-embed-text:latest 0a109f422b47    274 MB    ...
```

> **Why this specific model?** The memory database schema uses 768-dimensional vectors,
> which is exactly what `nomic-embed-text` produces. The sentence-transformers fallback
> (`all-MiniLM-L6-v2`) produces 384-dimensional vectors — the wrong size — which means
> embeddings silently fail to store. Always use `nomic-embed-text`.

#### Verify Ollama is serving and the model works

```bash
# Start Ollama (if not already running as a background service)
ollama serve &    # macOS / Linux — runs in background
# On Windows: Ollama runs as a system service after install, no manual start needed

# Test embedding generation
ollama embeddings nomic-embed-text "hello world"
# Expected: a long JSON array of 768 numbers — {"embedding": [0.12, -0.34, ...]}
```

If you see the embedding array, Ollama is working correctly.

---

## Part 2 — Get the Code

Clone the Synapse-OSS repository to your computer:

```bash
# macOS / Linux
cd ~
git clone https://github.com/UpayanGhosh/Synapse-OSS.git
cd Synapse-OSS

# Windows (Command Prompt or PowerShell)
cd %USERPROFILE%
git clone https://github.com/UpayanGhosh/Synapse-OSS.git
cd Synapse-OSS
```

> You can clone it anywhere. The scripts resolve their own location automatically.

---

## Part 3 — Get Your API Keys

Synapse needs at least **one LLM API key** to work. Get it before continuing.

**Google Gemini API Key** — Free tier available, no credit card required.

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with a Google account
3. Click **"Get API key"** → **"Create API key"**
4. Copy the key — it looks like `AIzaSy...`

> **Free tier limits:** Gemini Flash is very generous on the free tier (15 requests/minute,
> 1 million tokens/day as of early 2026). You can run Synapse at full speed for personal
> use without spending anything.

### Optional (adds features, app works without them)

| Key | What it unlocks | Where to get it |
|-----|----------------|-----------------|
| `GROQ_API_KEY` | Voice message transcription (send voice notes to Synapse) | [console.groq.com/keys](https://console.groq.com/keys) — free tier |
| `OPENROUTER_API_KEY` | Fallback routing when primary LLM fails | [openrouter.ai](https://openrouter.ai) |
| `OPENAI_API_KEY` | Specific tool overrides | [platform.openai.com](https://platform.openai.com) |

> Synapse tells you at startup which features are disabled based on what keys are missing.
> No silent failures.

---

## Part 4 — Configure Your Environment

Copy the template and fill in your keys:

### macOS / Linux

```bash
# From inside the Synapse-OSS directory
cp .env.example .env
nano .env          # or: code .env (VS Code), vim .env, etc.
```

### Windows

```cmd
copy .env.example .env
notepad .env
```

**What to fill in (minimum required):**

```bash
# --- Required ---
GEMINI_API_KEY="AIzaSy..."          # Your Gemini key from Part 3

ADMIN_PHONE="+15551234567"          # Your WhatsApp number in E.164 format
                                    # Format: + country code + number, no spaces or dashes
                                    # US example: +15551234567
                                    # India example: +919876543210
                                    # UK example: +447912345678

# --- Optional (leave blank to disable the feature) ---
GROQ_API_KEY=""                     # For voice message transcription
OPENROUTER_API_KEY=""               # For fallback model routing
WHATSAPP_BRIDGE_TOKEN=""            # Leave blank — set automatically during onboarding
```

> **ADMIN_PHONE** is the WhatsApp number you will use to chat with Synapse. It tells Synapse
> who has admin-level access. Without it, Synapse starts but ignores all incoming messages.

Save the file and close it.

---

## Part 5 — Set Up Python Environment

Install Python dependencies into an isolated virtual environment.

### macOS / Linux

```bash
# From inside the Synapse-OSS directory
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Install browser for web browsing feature (Mac/Linux only)
crawl4ai-setup
```

### Windows

```cmd
python -m venv .venv
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

> **Windows web browsing:** The onboarding script installs Playwright (the Windows browser
> backend) automatically. You do not need to run any browser setup command manually.

**Verify the install:**

```bash
python -c "import fastapi, sqlite_vec; print('Dependencies OK')"
```

If you see `Dependencies OK`, you're good. If you see an error about `sqlite_vec`, see
the [Troubleshooting](#troubleshooting) section.

---

## Part 5.5 — Configure LLM Routing (`synapse.json`)

This step is **required** for Synapse to make LLM calls. Without it, the gateway starts
but every chat reply fails with "0 roles configured".

Copy the template and fill in your API keys:

### macOS / Linux

```bash
mkdir -p ~/.synapse
cp synapse.json.example ~/.synapse/synapse.json
chmod 600 ~/.synapse/synapse.json   # keep your keys private
nano ~/.synapse/synapse.json        # or: code ~/.synapse/synapse.json
```

### Windows

```cmd
mkdir "%USERPROFILE%\.synapse"
copy synapse.json.example "%USERPROFILE%\.synapse\synapse.json"
notepad "%USERPROFILE%\.synapse\synapse.json"
```

**What to fill in (minimum required):**

```json
{
  "providers": {
    "gemini": {"api_key": "AIzaSy..."}
  },
  "model_mappings": {
    "casual":   {"model": "gemini/gemini-2.0-flash", "fallback": null},
    "code":     {"model": "gemini/gemini-2.0-flash", "fallback": null},
    "analysis": {"model": "gemini/gemini-2.0-flash", "fallback": null},
    "review":   {"model": "gemini/gemini-2.0-flash", "fallback": null},
    "vault":    {"model": "ollama_chat/llama3.2:3b",  "fallback": null},
    "translate":{"model": "gemini/gemini-2.0-flash", "fallback": null}
  }
}
```

> **Why is this separate from `.env`?**
> `synapse.json` controls per-role model routing (which model handles casual chat,
> code, deep analysis, etc.) while `.env` contains infrastructure config. Keeping them
> separate lets you swap models without touching environment variables.

> **File location:** `~/.synapse/synapse.json` (Mac/Linux) or
> `%USERPROFILE%\.synapse\synapse.json` (Windows).
> The onboarding script creates this file automatically from the example — you just
> need to open it and replace the placeholder API keys.

---

## Part 6 — Run the Onboarding Script (One Time Only)

The onboarding script does everything else: creates required directories, configures the
workspace, guides you through WhatsApp setup, and starts all services. **Run it once on
first setup. Never run it again after that** — use the start script for daily use instead.

### macOS / Linux

```bash
chmod +x synapse_onboard.sh   # Make executable (only needed once)
./synapse_onboard.sh
```

### Windows

Double-click `synapse_onboard.bat` in File Explorer. Or from a terminal:

```cmd
.\synapse_onboard.bat
```

> **Do NOT double-click the `.ps1` files** — Windows opens them in Notepad by default.
> Always use the `.bat` launchers on Windows.

---

### What the onboarding script does — step by step

**Step 1: Checks your tools**
Verifies Git, Python, Docker, and Ollama are installed and working. If Ollama is missing,
it installs it automatically (via Homebrew on macOS, the official installer on Linux).
Fails with a clear message if anything else is missing.

**Step 2: Creates your `.env`**
Auto-creates `.env` from `.env.example` if it does not already exist. No manual file copy needed.

**Step 3: Asks your WhatsApp setup preference**

```
[1] Dedicated Number (recommended)
    Use a separate phone number just for Synapse
    (like an old Android phone or spare SIM)

[2] Personal Number
    Use your own WhatsApp number
    Chat with Synapse by "messaging yourself"
```

Enter `1` or `2`. Either works — personal number is the simplest way to get started.

**Step 4: Takes your phone number**
Enter your WhatsApp number in E.164 format (same as `ADMIN_PHONE` in `.env`). This is
saved so Synapse only responds to you.

**Step 5: Shows the WhatsApp QR code**
A QR code appears in your terminal, served by the Baileys bridge that is spawned by the
gateway. On your phone:
1. Open **WhatsApp**
2. Go to **Settings** → **Linked Devices**
3. Tap **Link a Device**
4. Scan the QR code

You have about 60 seconds. If it expires, you can retrieve a fresh QR code at any time
by visiting `GET http://localhost:8000/qr` while Synapse is running.

**Step 6: Configures the workspace**
Creates the required directory structure under `~/.synapse/`:
- `~/.synapse/logs/` — service log files
- `~/.synapse/workspace/db/` — SQLite databases
- Profile directories for each persona

**Step 7: Configures LLM access**
Checks for a `GEMINI_API_KEY` in `.env`. If none is found, it prints a warning (does not
abort) so you can add a key later without re-running the full onboard.

**Step 8: Starts all services**

| Service | Purpose |
|---------|---------|
| Qdrant (Docker) | Vector database for semantic memory |
| Ollama | Embedding model (`nomic-embed-text`) — required for memory ingestion |
| Synapse API Gateway | The brain — handles memory, routing, persona |

The Baileys WhatsApp bridge is spawned automatically by the API gateway on startup —
it is an internal subprocess and does not need to be managed separately.

**Step 9: Waits for startup and verifies**
Polls the health endpoints for up to 15 seconds. Reports which services are running.

---

## Part 7 — Say Hello

After onboarding completes, send Synapse a message on WhatsApp:

| Setup | Where to find Synapse |
|-------|-----------------------|
| **Dedicated number** | Look in your contacts for the number you linked — it is now "Synapse" |
| **Personal number** | Tap **"Message yourself"** at the top of your chat list (your own name) |

Try:
- `Hello`
- `What can you do?`
- `Search the web for today's weather in London`
- `Remember that I work as a software engineer`

Synapse should reply within 2–5 seconds. The first reply may take up to 15 seconds while
the gateway warms up.

> **If Synapse doesn't reply:** Check the logs. See [Troubleshooting](#troubleshooting).

---

## Part 8 — Daily Use

After the first setup, you never run the onboarding script again.

### Starting Synapse

#### macOS / Linux

```bash
cd /path/to/Synapse-OSS
./synapse_start.sh
```

#### Windows

Double-click `synapse_start.bat` in the Synapse-OSS folder. Or:

```cmd
synapse_start.bat
```

The start script automatically:
- Starts Docker / Qdrant if not already running
- Starts Ollama (required for memory embedding)
- Starts the Synapse API Gateway (which in turn spawns the Baileys WhatsApp bridge)

Then message Synapse on WhatsApp — it's live.

---

### Stopping Synapse

#### macOS / Linux

```bash
./synapse_stop.sh
```

#### Windows

```cmd
synapse_stop.bat
```

---

### Checking if everything is running

#### macOS / Linux

```bash
./synapse_health.sh
```

Expected output:
```
[OK] Gateway    (8000)
[OK] Qdrant     (6333)
[OK] Ollama     (11434)
```

All three must show green for Synapse to function fully. If Ollama is red, memory ingestion
is disabled — see the [Troubleshooting](#troubleshooting) section.

#### Windows

```cmd
curl.exe http://localhost:8000/health
curl.exe http://localhost:11434
netstat -ano | findstr ":8000 :6333 :11434"
```

---

### Service ports at a glance

| Service | Port | Required | What it does |
|---------|------|----------|--------------|
| Synapse API Gateway | 8000 | Yes | Main brain — memory, routing, persona |
| Qdrant | 6333 | Yes | Vector memory database |
| Ollama | 11434 | Yes | Embedding model (`nomic-embed-text`) for ingestion |
| Baileys Bridge | 5010 | Internal | WhatsApp bridge — managed by the gateway, not user-facing |

---

## Part 9 — Make Synapse Yours

Out of the box, Synapse is configured with the creator's personality (Upayan's Bengali/English
mix). Here is how to make it respond to you in your own style.

### 9.1 — Map your phone number to a persona

Open `workspace/personas.yaml` and fill in your phone numbers under the persona you want
to reach when WhatsApp messages come in from that number:

```yaml
personas:
  - id: the_creator
    display_name: "Your Name"
    description: "Chat as Synapse -> you"
    whatsapp_phones:
      - "15551234567"   # digits only, no + prefix
    whatsapp_keywords: []

  - id: the_partner
    display_name: "Partner"
    description: "Chat as Synapse -> your partner"
    whatsapp_phones:
      - "15559876543"
    whatsapp_keywords: []

default_persona: the_creator
```

**Adding a third persona** (e.g. a family member or work context): add a new entry to the
`personas` list, fill in their phone number, and restart Synapse. The `/chat/<id>` route
is registered automatically — no code changes needed.

### 9.2 — Set your language and feedback phrases

**Default detection phrases** (what triggers style adaptation) are defined in:

```
workspace/sci_fi_dashboard/sbs/feedback/language_patterns.yaml
```

Open it and add phrases for your own language under the relevant category:

```yaml
correction_formal:
  - "why (are you|so) formal"
  - "stop being (formal|robotic)"
  # Add your language here:
  # - "beshi formal hoyona"        # Bengali example
  # - "deja de ser tan formal"     # Spanish example

correction_length:
  - "too long"
  - "keep it short"
  # - "mukhtasar karo"             # Urdu example

praise:
  - "good (boy|job)"
  - "perfect"
  # - "shabaash"                   # Hindi/Urdu example
```

Each pattern is a Python regex (case-insensitive). Restart Synapse after saving. Changes
take effect immediately on the next boot — no code edits needed.

### 9.3 — Define who you are (persona profile)

After booting Synapse for the first time, these files are auto-created at:

```
workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/
```

Edit `core_identity.json` to set your name and personality:

```json
{
  "assistant_name": "Synapse",
  "user_name": "Your Name",
  "user_nickname": "Hey",
  "relationship": "trusted_technical_companion",
  "personality_pillars": [
    "Sharp technical mind",
    "Casual and direct",
    "Honest feedback"
  ]
}
```

Edit `linguistic.json` to control how strongly Synapse leans toward your primary language:

```json
{
  "primary_language_ratio": 0.0,
  "formality": "casual"
}
```

Set `primary_language_ratio` to `0.0` for neutral/formal tone, `1.0` for maximum
casual/local-language mix. Synapse also adjusts this automatically when you send phrases
defined in `language_patterns.yaml` (e.g. "stop being formal" raises it; "be professional"
lowers it).

### 9.4 — Inject your background (jump-start memory)

On a fresh install, Synapse has no memory of you. You can inject facts immediately:

```bash
# macOS / Linux
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"subject": "User", "relation": "works_as", "object": "Software Engineer"}'

curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"subject": "User", "relation": "lives_in", "object": "New York"}'

# Windows
curl.exe -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d "{\"subject\": \"User\", \"relation\": \"works_as\", \"object\": \"Software Engineer\"}"
```

Or just start chatting — Synapse extracts facts from every conversation automatically
and builds its memory over time. After 3–4 days of use, it will feel noticeably more
personalized without any manual input.

### 9.5 — Teach it your style with examples

Edit `workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/exemplars.json`
to add sample conversations that show the tone you want:

```json
{
  "pairs": [
    {
      "user": "Summarize this article for me",
      "assistant": "Key points: [1] ... [2] ... [3] ... Bottom line: ..."
    },
    {
      "user": "I'm getting a 404 on this API call",
      "assistant": "Check your base URL first. Then verify the auth header. Paste the full error if those look right."
    }
  ]
}
```

> For the full persona customization guide (language switching, implicit feedback,
> memory dump strategies), see [SETUP_PERSONA.md](SETUP_PERSONA.md).

---

## Troubleshooting

### Synapse doesn't reply to my WhatsApp messages

**1. Check the API gateway is running:**
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"} or any JSON response
```

**2. Check the gateway log for errors:**

```bash
# macOS / Linux
tail -50 ~/.synapse/logs/gateway.log

# Windows
type "%USERPROFILE%\.synapse\logs\gateway.log"
```

**3. Check the WhatsApp bridge status:**

The Baileys bridge is managed internally by the gateway. Check its status via:
```bash
curl http://localhost:8000/channels/whatsapp/health
```

**4. Get a fresh WhatsApp QR code (if WhatsApp is not linked):**
```bash
curl http://localhost:8000/qr
```
Or open `http://localhost:8000/qr` in your browser. Scan the returned QR code with
WhatsApp → Settings → Linked Devices → Link a Device.

**5. Make sure your phone number is set in `.env`:**

Open your `.env` file and confirm `ADMIN_PHONE` is set to your number in E.164 format
(e.g. `+15551234567`). If it was blank, add it and restart Synapse.

**6. Re-run the start script:**
```bash
./synapse_start.sh    # Mac/Linux
synapse_start.bat     # Windows
```

---

### WhatsApp QR code expired or login failed during onboarding

This is normal if you took too long to scan. Get a fresh QR code at any time while
Synapse is running:

```bash
curl http://localhost:8000/qr
```

Or open `http://localhost:8000/qr` in your browser. Scan it with WhatsApp → Settings →
Linked Devices → Link a Device.

---

### `pip install -r requirements.txt` fails on Windows (build error)

The `sqlite-vec` package needs a C++ compiler. Install:
[Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
→ select **"Desktop development with C++"** workload → then retry `pip install`.

---

### `pip install -r requirements.txt` fails on Linux (missing headers)

```bash
sudo apt install -y python3-dev build-essential gcc g++
pip install -r requirements.txt
```

---

### Docker errors — "Cannot connect to Docker daemon"

Docker Desktop is not running. Launch Docker Desktop and wait for it to fully start
(the whale icon stops animating). Then run the start script again.

---

### Qdrant fails to start

```bash
# Remove and recreate the container
docker rm -f antigravity_qdrant
docker run -d --name antigravity_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

---

### Port 8000 is already in use

Another process is using port 8000. Find and stop it:

```bash
# macOS / Linux
lsof -i :8000
kill -9 <PID>

# Windows
netstat -ano | findstr ":8000"
taskkill /PID <PID> /F
```

Or change the gateway port by adding `SERVER_PORT=8001` to your `.env`.

---

### Ollama is not running or `nomic-embed-text` is missing

Ollama must be running and `nomic-embed-text` must be pulled for memory ingestion to work.

**Check if Ollama is running:**
```bash
curl http://localhost:11434
# Expected: "Ollama is running"
```

**Start Ollama if it's not running:**
```bash
# macOS / Linux
ollama serve &

# Windows — Ollama installs as a system service; restart it from the system tray icon
# or run in a terminal:
ollama serve
```

**Check if the model is pulled:**
```bash
ollama list
# You should see: nomic-embed-text:latest
```

**Pull it if missing (this is ~900 MB):**
```bash
ollama pull nomic-embed-text
```

**Verify the model produces embeddings:**
```bash
ollama embeddings nomic-embed-text "test"
# Expected: {"embedding": [0.12, -0.34, 0.56, ...]} — 768 numbers
```

**Check which embedding mode the gateway is using:**

Look at the gateway startup log:
```bash
# macOS / Linux
grep -i "retriever\|embed\|ollama" ~/.synapse/logs/gateway.log | head -5

# Windows
findstr /i "retriever embed ollama" "%USERPROFILE%\.synapse\logs\gateway.log"
```

You want to see:
```
[OK] Retriever: Using Ollama (nomic-embed-text) -- exact DB match
```

If you see `sentence-transformers` or `fts_only` instead, Ollama is not reachable.
Fix Ollama first, then restart the gateway.

---

### Gateway starts but crashes immediately

Check the log for the actual error:
```bash
# macOS / Linux
tail -100 ~/.synapse/logs/gateway.log

# Windows
type "%USERPROFILE%\.synapse\logs\gateway.log"
```

Common causes:
- **`GEMINI_API_KEY` missing or invalid** — double-check your `.env`
- **Import error** — virtual environment not activated or `pip install` failed
- **Database error** — directory permissions issue (run the start script as your normal user, not root/Administrator)

---

### Node.js not found (Baileys bridge fails to start)

The Baileys WhatsApp bridge requires **Node.js 18 or higher**. The gateway logs a clear
error if Node.js is missing or outdated.

**Check:**
```bash
node --version
# Expected: v18.x.x or higher
```

**Install if missing:** Download from [nodejs.org](https://nodejs.org) — choose the **LTS** version (18 or higher).

After installing, restart Synapse. The bridge starts automatically.

---

## Advanced Topics

### Run the API gateway directly (for development)

```bash
cd workspace
source ../.venv/bin/activate   # Mac/Linux
# ..\.venv\Scripts\activate.bat  ← Windows

uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --reload
```

`--reload` auto-restarts on code changes. Remove it in production.

---

### CLI interface

```bash
cd workspace
source ../.venv/bin/activate

python main.py chat      # Interactive chat in terminal (bypasses WhatsApp)
python main.py ingest    # Ingest facts into knowledge graph
python main.py vacuum    # Prune and optimize databases
python main.py verify    # Run 3-point inspection (health, air-gap, latency)
```

---

### Run with Docker Compose (alternative deployment)

If you prefer running the entire stack in Docker instead of natively:

```bash
# Copy your .env first
cp .env.example .env
# Edit .env and add your keys

# Build and start
docker compose up --build

# Stop
docker compose down
```

This starts Qdrant and the Synapse API Gateway in containers.

---

### Useful API endpoints

All endpoints are at `http://localhost:8000`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/health` | Check if gateway is alive |
| `GET` | `/qr` | Get WhatsApp QR code for (re)linking |
| `GET` | `/channels/whatsapp/health` | Check Baileys bridge status |
| `POST` | `/chat/<persona_id>` | Send a message to a specific persona (e.g. `/chat/the_creator`) |
| `POST` | `/whatsapp/enqueue` | Enqueue a WhatsApp message (async) |
| `POST` | `/ingest` | Add a fact to the knowledge graph |
| `POST` | `/add` | Store unstructured memory |
| `POST` | `/query` | Search memory |
| `POST` | `/persona/rebuild` | Rebuild all persona profiles from logs |
| `GET` | `/persona/status` | View all persona profile statistics |
| `GET` | `/sbs/status` | Live SBS stats (mood, sentiment, language ratio) |

> **Persona routes are dynamic.** Every `id` entry in `personas.yaml` automatically gets
> a `/chat/<id>` endpoint. Add a new persona to the YAML, restart, and it appears in
> `GET /openapi.json` with no code changes.

> **Authentication:** All `/chat/*`, `/ingest`, `/add`, `/query`, and `/persona/*`
> endpoints require an `x-api-key` header containing your `GEMINI_API_KEY` value.
> `/health`, `/qr`, and `/sbs/status` are unauthenticated.

```bash
# Example: check health (no auth needed)
curl http://localhost:8000/health

# Example: chat directly (requires x-api-key header)
curl -X POST http://localhost:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_GEMINI_API_KEY" \
  -d '{"message": "What do you know about me?"}'

# Windows equivalent
curl.exe -X POST http://localhost:8000/chat/the_creator -H "Content-Type: application/json" -H "x-api-key: YOUR_GEMINI_API_KEY" -d "{\"message\": \"What do you know about me?\"}"
```

---

### Custom data root

By default Synapse stores all data in `~/.synapse/`. To use a different location, set the
`SYNAPSE_HOME` environment variable before starting:

```bash
# macOS / Linux
export SYNAPSE_HOME="/data/synapse"
./synapse_start.sh

# Windows
set SYNAPSE_HOME=D:\synapse
synapse_start.bat
```

All log files, databases, and persona profiles will be placed under that directory.

---

## Quick Reference Card

| Task | Mac/Linux | Windows |
|------|-----------|---------|
| First-time setup | `./synapse_onboard.sh` | `synapse_onboard.bat` |
| Start Synapse | `./synapse_start.sh` | `synapse_start.bat` |
| Stop Synapse | `./synapse_stop.sh` | `synapse_stop.bat` |
| Health check | `./synapse_health.sh` | `curl.exe http://localhost:8000/health` |
| Check Ollama | `curl http://localhost:11434` | `curl.exe http://localhost:11434` |
| Pull embedding model | `ollama pull nomic-embed-text` | same |
| Verify embeddings work | `ollama embeddings nomic-embed-text "test"` | same |
| View gateway log | `tail -f ~/.synapse/logs/gateway.log` | `type "%USERPROFILE%\.synapse\logs\gateway.log"` |
| Get WhatsApp QR code | `curl http://localhost:8000/qr` | `curl.exe http://localhost:8000/qr` |
| Check bridge status | `curl http://localhost:8000/channels/whatsapp/health` | same |

---

## Getting Help

- **GitHub Issues:** [github.com/UpayanGhosh/Synapse-OSS/issues](https://github.com/UpayanGhosh/Synapse-OSS/issues)
- **Persona Setup:** [SETUP_PERSONA.md](SETUP_PERSONA.md)
- **Architecture Deep-Dive:** [ARCHITECTURE.md](ARCHITECTURE.md)
- **Engineering Philosophy:** [MANIFESTO.md](MANIFESTO.md)
