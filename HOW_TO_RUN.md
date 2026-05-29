# Synapse — Complete Setup Guide

This guide takes you from a blank computer to a fully running Synapse instance.
No prior experience required. Every command is shown for **Windows**, **macOS**, and **Linux**.

---

## What You Are Setting Up

Synapse is a self-hosted AI assistant you can use from the terminal or from chat
apps such as WhatsApp. It has persistent memory, persona-aware behavior, and
supports both local and cloud model routing. Here is how the pieces fit
together:

```
Terminal CLI or Your Phone (WhatsApp)
        ↓
  CLI chat or Baileys Bridge  ← WhatsApp bridge is optional and spawned by the gateway
        ↓
  Synapse API Gateway        ← the brain: memory, routing, persona
        ↓
  ┌──────────────────┬──────────────────────────────────────┐
  │  Gemini / Claude │  FastEmbed (local ONNX, default)     │
  │  (cloud LLMs)    │  or Gemini API (fallback) or Ollama  │
  └──────────────────┴──────────────────────────────────────┘
        ↓
  LanceDB + SQLite           ← memory databases (embedded, zero Docker)
```

**What runs on your machine:** the Synapse API gateway, the embedding provider (FastEmbed by default — local ONNX), the Baileys WhatsApp bridge, and the databases. Ollama is optional.
**What lives in the cloud:** The LLM API you configure (Gemini, Claude, OpenRouter, etc.).

## How embeddings work

Synapse picks an embedding provider in this order:

1. **FastEmbed** (default) — local ONNX, no external service, ~150 MB on first run.
2. **Gemini API** — fallback if FastEmbed isn't installed and `GEMINI_API_KEY` is set.

If neither is available, the embedding factory raises and the gateway logs an error
on startup — Synapse won't ingest new memory until you install one of the two.

You **do not** need Ollama for embeddings. Ollama is only used if you point a chat
role at a local model (e.g. the `vault` role for private conversations, or the
[no-cloud profile](#no-cloud-profile) below). See `workspace/sci_fi_dashboard/embedding/factory.py`
for the exact cascade.

---

## Time Required

| Stage | Time |
|-------|------|
| Installing prerequisites | 15–30 min (mostly downloads) |
| First-time onboarding (downloads FastEmbed model on first ingest, ~150 MB) | 5–10 min |
| Optional WhatsApp QR code | 2 min |
| Optional Ollama install + model pull (only if you want a local LLM role) | 5–15 min |
| **Total** | **~25–50 min** |

---

## Part 1 — Install Prerequisites

You need **two things** before you start: **Git** and **Python 3.11+**. Ollama is optional —
only install it if you want a fully-local LLM path (see [How embeddings work](#how-embeddings-work)).
(Docker is no longer required — LanceDB is embedded.)

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

### 1.3 — Ollama (Optional — only for local LLM roles)

Ollama is **not** required for embeddings — Synapse uses FastEmbed (local ONNX) by
default and falls back to the Gemini API. See [How embeddings work](#how-embeddings-work).

You only need Ollama if you want a fully-local response path (e.g. the `vault` role
for private conversations, or the [no-cloud profile](#no-cloud-profile)). If you're
fine with a cloud LLM (Gemini / Claude / OpenRouter), you can skip this section.

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

#### Pull a local LLM model (optional)

If you decided to use Ollama for a local LLM role, pull a chat model. Common picks:

```bash
ollama pull llama3.2:3b      # ~2 GB — used by the vault role in the default config
ollama pull mistral          # ~4 GB — bigger, better reasoning
```

You can check what's installed:

```bash
ollama list
```

For the [no-cloud profile](#no-cloud-profile), pull the specific models referenced
by `synapse.local-only.json` (see [docs/local-only-benchmark.md](docs/local-only-benchmark.md)).

#### Verify Ollama is serving

```bash
# Start Ollama (if not already running as a background service)
ollama serve &    # macOS / Linux — runs in background
# On Windows: Ollama runs as a system service after install, no manual start needed

# Smoke test
curl http://localhost:11434
# Expected: "Ollama is running"
```

---

## Part 2 — Install Synapse

Normal users do not need the GitHub repo. Install the standalone CLI from npm:

```bash
npm install -g synapse-oss
```

Then install the product runtime into your Synapse home:

```bash
synapse install
```

Run onboarding from the installed CLI:

```bash
synapse onboard
```

Synapse stores app data, logs, config, runtime files, and local workspace state in
`.synapse` (`~/.synapse` on macOS/Linux, `%USERPROFILE%\.synapse` on Windows).
That product home is the normal place to inspect or back up your install.

Developer-only setup: clone the repo only if you plan to edit Synapse source or
contribute patches.

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

`synapse install` creates the local product-home files. `synapse onboard` opens
the guided setup and writes config under `.synapse`.

If you want to edit keys manually before onboarding:

### macOS / Linux

```bash
nano ~/.synapse/.env          # or: code ~/.synapse/.env
```

### Windows

```cmd
notepad "%USERPROFILE%\.synapse\.env"
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

### .env file — minimal vs advanced

The default [.env.example](.env.example) is minimal — one required key
(`GEMINI_API_KEY`) and a few common optional ones. If you want the full set of
12 supported providers and every flag Synapse honors, see
[.env.example.advanced](.env.example.advanced).

Quick start:

```bash
cp .env.example .env
$EDITOR .env   # fill in GEMINI_API_KEY
```

---

## Part 5 — Install the Runtime

Run the product installer:

```bash
synapse install
```

The installer creates the managed virtual environment and runtime assets inside
`.synapse`. Normal users do not need to create a repo-local virtual environment.

**Verify the install:**

```bash
synapse doctor
```

---

## Part 5.5 — Configure LLM Routing (`synapse.json`)

This step is **required** for Synapse to make LLM calls. Without it, the gateway starts
but every chat reply fails with "0 roles configured".

Let onboarding create the config, then fill in your API keys if needed:

### macOS / Linux

```bash
synapse onboard
chmod 600 ~/.synapse/synapse.json   # keep your keys private
nano ~/.synapse/synapse.json        # or: code ~/.synapse/synapse.json
```

### Windows

```cmd
synapse onboard
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

### 5.5.1 - OpenAI Codex subscription onboarding (OAuth)

`openai_codex/*` models are subscription-backed and use OAuth device flow, not an API key.

1. Run onboarding and select `openai_codex` in provider selection.
2. Complete the device flow at `https://auth.openai.com/codex/device` when prompted.
3. Verify OAuth state file exists:
   - macOS / Linux: `~/.synapse/state/openai-codex-oauth.json`
   - Windows: `%USERPROFILE%\.synapse\state\openai-codex-oauth.json`

Sample config using both OpenAI API-key and OpenAI Codex subscription providers:

```json
{
  "providers": {
    "openai_codex": {
      "oauth_email": "me@example.com",
      "profile_name": "me@example.com",
      "account_id": "acct-123"
    },
    "openai": {"api_key": "sk-proj-..."}
  },
  "model_mappings": {
    "code": {"model": "openai_codex/gpt-5-codex", "fallback": "openai/gpt-4o-mini"},
    "casual": {"model": "openai/gpt-4o-mini", "fallback": null}
  }
}
```

Auth split summary:
- `openai_codex/*` -> ChatGPT subscription OAuth
- `openai/*` -> OpenAI API key (`providers.openai.api_key`)

> **Why is this separate from `.env`?**
> `synapse.json` controls per-role model routing (which model handles casual chat,
> code, deep analysis, etc.) while `.env` contains infrastructure config. Keeping them
> separate lets you swap models without touching environment variables.

> **File location:** `~/.synapse/synapse.json` (Mac/Linux) or
> `%USERPROFILE%\.synapse\synapse.json` (Windows).
> The onboarding command creates this file automatically from the example — you just
> need to open it and replace the placeholder API keys.

---

## Part 6 — Run Onboarding (One Time Only)

The onboarding command does everything else: creates required directories, configures the
workspace, optionally guides you through WhatsApp setup, and starts all services. **Run it once on
first setup. Never run it again after that** — use `synapse start` for daily use instead.

### macOS / Linux

```bash
synapse onboard
```

### Windows

```cmd
synapse onboard
```

The repository launchers (`synapse_onboard.bat`, `synapse_onboard.sh`) are
developer conveniences. They delegate to the npm-installed CLI.

---

### What the onboarding script does — step by step

**Step 1: Checks your tools**
Verifies Node, Python, and Ollama are installed and working. If Ollama is missing,
it installs it automatically (via Homebrew on macOS, the official installer on Linux).
Fails with a clear message if anything else is missing.

**Step 2: Creates your `.env`**
Auto-creates `.env` from `.env.example` if it does not already exist. No manual file copy needed.

**Step 3: Choose whether to configure WhatsApp**

You can skip WhatsApp and use the terminal CLI chat instead. If you configure
WhatsApp now, choose one of these modes:

```
[1] Dedicated Number (recommended)
    Use a separate phone number just for Synapse
    (like an old Android phone or spare SIM)

[2] Personal Number
    Use your own WhatsApp number
    Chat with Synapse by "messaging yourself"
```

Enter `1` or `2` only if you chose to configure WhatsApp. Either works —
personal number is the simplest way to get started.

**Step 4: Takes your phone number (WhatsApp only)**
Enter your WhatsApp number in E.164 format (same as `ADMIN_PHONE` in `.env`). This is
saved so Synapse only responds to you.

**Step 5: Shows the WhatsApp QR code (WhatsApp only)**
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

Agent workspace reference:
- [workspace/README.md](workspace/README.md)
- [docs/agent-workspace.md](docs/agent-workspace.md)

Canonical context files:
- `CORE.md`
- `CODE.md`
- `MEMORY.md`

Non-overwrite policy:
- Workspace seeding/repair creates missing required files only.
- Existing workspace markdown files are not overwritten.

Existing-install migration note:
- If you already have a Synapse install, keep your current workspace.
- Run repair first:

```bash
synapse doctor --fix
```

**Step 7: Configures LLM access**
Checks for a `GEMINI_API_KEY` in `.env`. If none is found, it prints a warning (does not
abort) so you can add a key later without re-running the full onboard.

**Step 8: Starts all services**

| Service | Purpose |
|---------|---------|
| LanceDB (embedded) | Vector database for semantic memory |
| FastEmbed (in-process) | Local ONNX embedding provider (default) — no separate service |
| Ollama (optional) | Started only if a chat role points at a local model |
| Synapse API Gateway | The brain — handles memory, routing, persona |

The Baileys WhatsApp bridge is spawned automatically by the API gateway on startup —
it is an internal subprocess and does not need to be managed separately.

**Step 9: Waits for startup and verifies**
Polls the health endpoints for up to 15 seconds. Reports which services are running.

---

### CLI-only mode

If you do not want a third-party chat app, run:

```bash
synapse chat
```

Use `/safe`, `/spicy`, and `/quit` inside the CLI chat.

---

## Part 7 — Say Hello

After onboarding completes, either use CLI chat:

```bash
synapse chat
```

Or send Synapse a message on WhatsApp if you configured it:

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
- Initializes LanceDB vector store (embedded, no Docker needed)
- Starts Ollama if it is installed and any chat role uses a local model (otherwise skipped)
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
[OK] LanceDB    (embedded)
[OK] Ollama     (11434)   ← only shown if Ollama is installed/used
```

The Gateway and LanceDB rows must show green for Synapse to function. The Ollama row
only appears when you've configured a local LLM role (it is not used for embeddings —
see [How embeddings work](#how-embeddings-work)).

#### Windows

```cmd
curl.exe http://localhost:8000/health
curl.exe http://localhost:11434
netstat -ano | findstr ":8000 :11434"
```

---

### Service ports at a glance

| Service | Port | Required | What it does |
|---------|------|----------|--------------|
| Synapse API Gateway | 8000 | Yes | Main brain — memory, routing, persona |
| LanceDB | embedded | Yes | Vector memory database (`~/.synapse/workspace/db/lancedb/`) |
| FastEmbed | in-process | Yes (default) | Local ONNX embedding provider — no port, no daemon |
| Ollama | 11434 | Optional | Only used when a chat role points at a local model, or for the [no-cloud profile](#no-cloud-profile) |
| Baileys Bridge | 5010 | Internal | WhatsApp bridge — managed by the gateway, not user-facing |

---

## Part 9 — Make Synapse Yours

Out of the box, Synapse uses neutral English and asks for your region, locality, and
preferred language during onboarding. It should only use regional language, dialect, or
code-switching after you choose it, write that way, import examples, or teach it phrases.

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
  # - "deja de ser tan formal"     # Spanish example
  # - "bahut formal mat bolo"      # Hindi/Urdu example

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

Edit `linguistic.json` to control Synapse's language and regional style:

```json
{
  "preferred_language": "English",
  "region": "",
  "locality": "",
  "primary_language_ratio": 0.0,
  "language_mix_ratio": 0.0,
  "ask_user_to_teach": true,
  "local_language_examples": []
}
```

Set `preferred_language` to the language or language mix you want by default. Set
`language_mix_ratio` / `primary_language_ratio` to `0.0` for neutral default usage, or
closer to `1.0` when Synapse should lean heavily into the local language. If
`ask_user_to_teach` is true and Synapse is unsure, it should ask you for a phrase,
correction, or example instead of guessing.

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

## No-cloud profile

Synapse can run with zero cloud egress. A starter profile is checked into the
repo:

```bash
mkdir -p ~/.synapse
cp synapse.local-only.json ~/.synapse/synapse.json
```

This requires Ollama running locally with the models referenced in the file
pre-pulled. See [docs/local-only-benchmark.md](docs/local-only-benchmark.md) for
the methodology / known regressions versus the cloud default. Note that dual
cognition timeout is bumped to 10s because local models are slower; you can
tune this via `session.dual_cognition_timeout` in `synapse.json`.

---

## Production deployment

For production-style deployments (rather than the demo compose), see
[deploy/README.md](deploy/README.md), which covers:

- a multi-stage Dockerfile (root of repo)
- a hardened systemd unit (`deploy/synapse.service`)
- environment-file conventions (`/etc/synapse/synapse.env`)

For the fastest demo path (single command, no production hardening), use:

```bash
docker compose -f docker-compose.demo.yml up
```

---

## Scaling notes

Synapse today is **single-user-per-instance**. The `multiuser/` layer (see
[docs/multiuser.md](docs/multiuser.md)) adds per-user keying, but the underlying
store is SQLite — concurrent writers from many users will hit lock contention
regardless of WAL. A Postgres backend for multi-user is on the roadmap; track
it via PRODUCT_ISSUES.md issue 7.1.

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

### LanceDB fails to initialize

LanceDB is embedded and requires no external service. If it fails, check that
`~/.synapse/workspace/db/lancedb/` is writable:

```bash
ls -la ~/.synapse/workspace/db/
```

If the directory is missing, it will be created automatically on first run.

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

### Ollama is not running (only relevant if you configured a local LLM role)

Ollama is **not** required for embeddings — that path is FastEmbed by default. You
only need Ollama if you pointed a chat role (e.g. `vault`) at a local model, or if
you're running the [no-cloud profile](#no-cloud-profile).

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

**Check what models are pulled:**
```bash
ollama list
```

**Check which embedding provider the gateway picked at startup:**

```bash
# macOS / Linux
grep -i "embedding.*selected\|embedding.*provider" ~/.synapse/logs/gateway.log | head -5

# Windows
findstr /i "embedding" "%USERPROFILE%\.synapse\logs\gateway.log"
```

You want to see one of:
```
[Embedding] Selected provider: FastEmbed (ONNX, local)
[Embedding] Selected provider: Gemini API
```

If you see neither and the gateway logs `No embedding provider available`,
install fastembed (`pip install fastembed`) or set `GEMINI_API_KEY`.

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

The Baileys WhatsApp bridge requires **Node.js 20+** (Baileys 7.x requirement — Phase 15). The gateway logs a clear
error if Node.js is missing or outdated.

**Check:**
```bash
node --version
# Expected: v20.x.x or higher
```

**Install if missing:** Download from [nodejs.org](https://nodejs.org) — choose the **LTS** version (20 or higher).

After installing, restart Synapse. The bridge starts automatically.

---

## Advanced Topics

### Run the API gateway directly (for development)

```bash
# Mac/Linux
( cd workspace && source ../.venv/bin/activate && uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000 --reload )

# Windows (cmd)
pushd workspace && ..\.venv\Scripts\activate.bat && uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000 --reload & popd
```

`--reload` auto-restarts on code changes. Remove it in production. The
parenthesised subshell on Mac/Linux means the `cd` doesn't pollute your current
shell — you stay in the repo root after the gateway exits.

---

### CLI interface

```bash
# Mac/Linux — subshell form keeps your current shell's cwd intact
( cd workspace && source ../.venv/bin/activate && python main.py chat )      # Interactive chat (bypasses WhatsApp)
( cd workspace && source ../.venv/bin/activate && python main.py ingest )    # Ingest facts into knowledge graph
( cd workspace && source ../.venv/bin/activate && python main.py vacuum )    # Prune and optimize databases
( cd workspace && source ../.venv/bin/activate && python main.py verify )    # 3-point inspection (health, air-gap, latency)
```

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
| Install Synapse | `npm install -g synapse-oss && synapse install` | `npm install -g synapse-oss && synapse install` |
| First-time setup | `synapse onboard` | `synapse onboard` |
| Start Synapse | `synapse start` | `synapse start` |
| Stop Synapse | `synapse stop` | `synapse stop` |
| Reset for re-onboarding | `synapse reset --scope config --reonboard` | same |
| Health check | `synapse doctor` | `synapse doctor` |
| Check Ollama (only if you use a local LLM role) | `curl http://localhost:11434` | `curl.exe http://localhost:11434` |
| Pull a local LLM model | `ollama pull llama3.2:3b` | same |
| Verify Ollama serves a chat model | `ollama run llama3.2:3b "hi"` | same |
| View gateway log | `tail -f ~/.synapse/logs/gateway.log` | `type "%USERPROFILE%\.synapse\logs\gateway.log"` |
| Get WhatsApp QR code | `curl http://localhost:8000/qr` | `curl.exe http://localhost:8000/qr` |
| Check bridge status | `curl http://localhost:8000/channels/whatsapp/health` | same |

### Targeted Test Commands (Workspace/Doctor)

Run from repo root (subshell keeps your shell cwd intact):

```bash
( cd workspace && pytest tests/test_doctor.py -v )
( cd workspace && pytest tests/test_onboard.py -k ensure_agent_workspace -v )
( cd workspace && pytest tests/test_agent_workspace_prefix.py -v )
( cd workspace && pytest tests/test_multiuser.py -k bootstrap -v )
```

Provider compatibility checks:

```bash
( cd workspace && pytest tests/providers/test_provider_contracts.py -q )
( cd workspace && pytest tests/providers/test_provider_live.py --run-live-providers --live-provider gemini -q )
```

Contract tests do not spend quota. Live provider tests are opt-in and skip providers whose
credentials are not present. See [docs/provider-testing.md](docs/provider-testing.md).

---

### Reset and re-onboard

Use this when you are testing onboarding repeatedly, switching accounts/providers, or want a
fresh setup without manually deleting `~/.synapse`.

```bash
synapse reset --scope config --reonboard
```

Reset scopes:

| Scope | What it backs up before resetting |
|---|---|
| `config` | `synapse.json` only |
| `config+creds+sessions` | config plus saved credentials and sessions |
| `full` | all Synapse home contents except existing backups |

All reset scopes move data into `~/.synapse/backups/<timestamp>/`; they do not delete it
directly. Add `--yes` to skip the confirmation prompt:

```bash
synapse reset --scope full --yes --reonboard
```

The older hidden form still works for automation:

```bash
synapse onboard --reset config
```

---

## Getting Help

- **GitHub Issues:** [github.com/UpayanGhosh/Synapse-OSS/issues](https://github.com/UpayanGhosh/Synapse-OSS/issues)
- **Persona Setup:** [SETUP_PERSONA.md](SETUP_PERSONA.md)
- **Architecture Deep-Dive:** [ARCHITECTURE.md](ARCHITECTURE.md)
- **Engineering Philosophy:** [MANIFESTO.md](MANIFESTO.md)
