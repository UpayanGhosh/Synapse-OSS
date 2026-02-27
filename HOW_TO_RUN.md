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

---

## Step 2: Set Up Python Environment and Config

### Mac / Linux

```bash
cd Synapse-OSS                 # Enter the cloned repo directory
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
crawl4ai-setup                 # Downloads browser for web browsing feature
cp .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY and GROQ_API_KEY (for voice messages)
```

### Windows

Open **Windows Terminal** (or Command Prompt):

```cmd
cd Synapse-OSS
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
crawl4ai-setup                 &REM Downloads browser for web browsing feature
copy .env.example .env
REM Edit .env — add at minimum: GEMINI_API_KEY and GROQ_API_KEY (for voice messages)
REM (If using Git Bash, use: source .venv/Scripts/activate)
```

---

## Step 3: Set Up OpenClaw (First Time Only)

Before running the onboarding script, set up OpenClaw with WhatsApp:

```bash
# Mac/Linux or Windows
openclaw setup --wizard
```

**Inside the wizard:**

1. Select your mode (recommended: `local`)
2. When asked about **channels**, select **WhatsApp**
3. A QR code will appear — scan it with your phone (WhatsApp → Settings → Linked Devices → Link a Device)
4. Continue through the wizard with default options
5. Done! WhatsApp is now linked.

---

## Step 4: Run the Onboarding Script

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

That's it! The script will guide you through everything.

> **Note:** Do NOT double-click the `.ps1` files — Windows opens them in Notepad by default. Always use the `.bat` launchers instead.

---

## Custom Workspace Configuration

This repository uses a custom workspace folder located at `workspace/` in the repository root. The onboarding script automatically configures this for you, but here are the commands for reference:

### Set Custom Workspace Path

```bash
# Windows
openclaw config set agents.defaults.workspace "C:\Users\YourName\Synapse-OSS\workspace"

# Mac/Linux (use absolute path)
openclaw config set agents.defaults.workspace "/absolute/path/to/Synapse-OSS/workspace"
```

### Verify Workspace Configuration

```bash
openclaw config get agents.defaults.workspace
```

### Restart Gateway After Changing Workspace

```bash
# Restart the gateway to apply changes
openclaw gateway restart

# Or stop and start manually
openclaw gateway stop
openclaw gateway
```

### What Happens During Onboarding

The `synapse_onboard.bat` script automatically:
1. Detects the project root (where the script is located)
2. Sets `SYNAPSE_WORKSPACE=%PROJECT_ROOT%\workspace`
3. Runs: `openclaw config set agents.defaults.workspace "%SYNAPSE_WORKSPACE%"`

This points OpenClaw to use `C:\Users\YourName\Synapse-OSS\workspace` instead of the default `~/.openclaw/workspace`.

---

## What the Onboarding Script Does

When you run it, the script will:

1. Check that all required tools are installed
2. Ask if you want a **dedicated number** or **personal number** for WhatsApp
   - **Dedicated number** (recommended): Use a separate phone just for Synapse
   - **Personal number**: Use your own WhatsApp — chat via "Message yourself"
3. Show a QR code to link your WhatsApp
4. Collect your phone number (for permissions) — validates E.164 format
5. Start all Synapse services (Qdrant, Ollama, API Gateway, WhatsApp bridge)
6. Verify services are running
7. Tell you how to start chatting
8. Configure OpenClaw workspace directory (maps workspace to `~/.openclaw/workspace/`)
9. Create required directories for databases and persona profiles

> **Note:** Databases (`memory.db`, `knowledge_graph.db`) are automatically created on first boot — no manual setup required.

> **Note:** The API Gateway (`api_gateway.py`) is automatically started by the onboarding and start scripts — you do NOT need to run it manually. Both `synapse_onboard.bat/.sh` and `synapse_start.bat/.sh` launch it as step 3 of 4.

The script also pulls the required Ollama embedding model (`nomic-embed-text`) and creates the Qdrant Docker container automatically.

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

## Need Help?

- Open an issue: [github.com/UpayanGhosh/Synapse-OSS/issues](https://github.com/UpayanGhosh/Synapse-OSS/issues)
