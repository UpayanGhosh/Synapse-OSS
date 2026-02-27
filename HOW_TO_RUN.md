# Synapse AI Assistant - Setup Guide

Get Synapse running in minutes with the automatic setup!

---

## Step 1: Install Required Tools

Make sure you have these installed on your computer before proceeding:

| Tool | How to Check | Where to Get It |
|------|--------------|--------------------|
| **Git** | `git --version` | [git-scm.com](https://git-scm.com) |
| **Python** | `python3 --version` (Mac/Linux) · `python --version` (Windows) | [python.org](https://www.python.org) |
| **Docker** | `docker --version` | [docker.com](https://docker.com) |
| **OpenClaw** | `openclaw --version` | [openclaw.ai](https://openclaw.ai) |

**Optional (enables local embedding + The Vault feature):**

| Tool | How to Check | Where to Get It |
|------|--------------|--------------------|
| **Ollama** | `ollama --version` | [ollama.com](https://ollama.com) |

> **Windows users:** After installing Python, make sure to check **"Add Python to PATH"** during installation.

---

## Step 2: Clone the Repository

```bash
git clone https://github.com/UpayanGhosh/Synapse-OSS.git
cd Synapse-OSS
```

---

## Step 3: Set Up Python Environment and Config

### Mac / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
crawl4ai-setup                 # Downloads browser for web browsing feature
cp .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY
```

### Windows

Open **Windows Terminal** (or Command Prompt) from inside the `Synapse-OSS` folder:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
REM Edit .env — add at minimum: GEMINI_API_KEY
```

> **Windows users:** `crawl4ai` is not supported on Windows — the onboarding script installs **Playwright** (the Windows browser backend) automatically. No manual browser setup step is needed.

### Required API Keys

Open `.env` and fill in your keys. **Only one key is required to start:**

| Key | Purpose | Where to Get |
|-----|---------|--------------|
| `GEMINI_API_KEY` | Primary LLM — app will not start without this | [aistudio.google.com](https://aistudio.google.com) |

**Optional** (app starts without these, but named features are disabled):

| Key | Disabled feature if missing | Where to Get |
|-----|----------------------------|--------------|
| `GROQ_API_KEY` | Voice message transcription | [console.groq.com](https://console.groq.com/keys) |
| `OPENROUTER_API_KEY` | Fallback model routing | [openrouter.ai](https://openrouter.ai) |
| `WHATSAPP_BRIDGE_TOKEN` | WhatsApp bridge authentication | Your OpenClaw dashboard |
| `OPENCLAW_GATEWAY_TOKEN` | OpenClaw OAuth proxy — leave blank to use Gemini directly | [openclaw.ai](https://openclaw.ai) |

> The app tells you exactly which features are disabled at startup — no silent failures.

---

## Step 4: Run the Onboarding Script

The onboarding script does everything else for you automatically.

### Mac / Linux

```bash
chmod +x synapse_onboard.sh  # Make executable (if needed)
./synapse_onboard.sh
```

### Windows

Simply double-click `synapse_onboard.bat` in the project folder. Or from a terminal:

```cmd
synapse_onboard.bat
```

That's it! The script will guide you through everything step by step.

> **Note:** Do NOT double-click the `.ps1` files — Windows opens them in Notepad by default. Always use the `.bat` launchers instead.

---

## What the Onboarding Script Does

When you run it, the script will:

1. Check that all required tools are installed (git, python, docker, openclaw) — Ollama is checked separately as optional
2. Ask if you want a **dedicated number** or **personal number** for WhatsApp
   - **Dedicated number** (recommended): Use a separate phone just for Synapse
   - **Personal number**: Use your own WhatsApp — chat via "Message yourself"
3. Collect your phone number (for permissions) — validates E.164 format
4. Show a QR code to link your WhatsApp
5. Save your phone number and configure the workspace
6. Start all Synapse services (Qdrant, API Gateway, WhatsApp bridge) — starts Ollama too if installed
7. **(Windows only)** Install Playwright browser binaries (Chromium) for the web browsing feature
8. Pull the Ollama embedding model (`nomic-embed-text`) in the background — skipped if Ollama is not installed
9. Verify services are running and tell you how to start chatting

> **Databases** (`memory.db`, `knowledge_graph.db`) are automatically created on first boot — no manual setup required.

> **The API Gateway** is automatically started by the onboarding and start scripts. You do not need to run it manually.

---

## Step 5: Chat with Synapse

After setup, message Synapse on WhatsApp:

| If You Used... | Where to Find Synapse |
|-----------------|---------------------|
| **Dedicated number** | Find "Synapse" or "WhatsApp Web" in your contacts |
| **Personal number** | Tap **"Message yourself"** at the top of your chat list |

Try sending: "Hello", "What's the weather?", or "Tell me a joke"

---

## Step 6: Running Synapse Later

Every time you want to use Synapse after the first setup:

### Mac / Linux

```bash
./synapse_start.sh
```

### Windows

Double-click `synapse_start.bat` or from a terminal:

```cmd
synapse_start.bat
```

Then message Synapse on WhatsApp!

---

## Custom Workspace Configuration

This repository uses a custom workspace folder at `workspace/` in the repository root. The onboarding script configures this automatically. For reference, the relevant commands are:

```bash
# Windows
openclaw config set agents.defaults.workspace "C:\Users\YourName\Synapse-OSS\workspace"

# Mac/Linux (use absolute path)
openclaw config set agents.defaults.workspace "/absolute/path/to/Synapse-OSS/workspace"

# Verify
openclaw config get agents.defaults.workspace
```

---

## Need Help?

- Open an issue: [github.com/UpayanGhosh/Synapse-OSS/issues](https://github.com/UpayanGhosh/Synapse-OSS/issues)
