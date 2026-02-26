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
cd /path/to/Synapse-OSS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY=your_key_here
```

### Windows (Command Prompt)

Open **Command Prompt as Administrator**:

```batch
cd C:\path\to\Synapse-OSS
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
REM Edit .env — add at minimum: GEMINI_API_KEY=your_key_here
```

---

## Step 3: Set Up OpenClaw (First Time Only)

Before running the onboarding script, set up OpenClaw with WhatsApp:

```bash
# Mac/Linux
openclaw setup --wizard

# Windows
openclaw setup --wizard
```

Select **WhatsApp** when prompted and scan the QR code to link your WhatsApp account.

---

## Step 4: Run the Onboarding Script

### Mac / Linux

```bash
chmod +x synapse_onboard.sh  # Make executable (if needed)
./synapse_onboard.sh
```

### Windows (Batch)

```batch
synapse_onboard.bat
```

That's it! The script will guide you through everything.

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

### Windows (Batch)

```batch
synapse_start.bat
```

Then message Synapse on WhatsApp!

---

## Need Help?

- Open an issue: [github.com/UpayanGhosh/Synapse-OSS/issues](https://github.com/UpayanGhosh/Synapse-OSS/issues)
