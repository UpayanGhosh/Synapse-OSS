# Jarvis AI Assistant - Setup Guide

Get Jarvis running in minutes with the automatic setup!

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
cd /path/to/Jarvis-OSS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY=your_key_here
```

### Windows (PowerShell)

Open **PowerShell as Administrator** the first time and allow scripts to run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then:

```powershell
cd C:\path\to\Jarvis-OSS
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY=your_key_here
```

---

## Step 3: Run the Onboarding Script

### Mac / Linux

```bash
chmod +x jarvis_onboard.sh  # Make executable (if needed)
./jarvis_onboard.sh
```

### Windows (PowerShell)

```powershell
.\jarvis_onboard.ps1
```

That's it! The script will guide you through everything.

---

## What the Onboarding Script Does

When you run it, the script will:

1. Check that all required tools are installed
2. Ask if you want a **dedicated number** or **personal number** for WhatsApp
   - **Dedicated number** (recommended): Use a separate phone just for Jarvis
   - **Personal number**: Use your own WhatsApp — chat via "Message yourself"
3. Show a QR code to link your WhatsApp
4. Collect your phone number (for permissions) — validates E.164 format
5. Start all Jarvis services (Qdrant, Ollama, API Gateway, WhatsApp bridge)
6. Verify services are running
7. Tell you how to start chatting

The script also pulls the required Ollama embedding model (`nomic-embed-text`) and creates the Qdrant Docker container automatically.

---

## Step 4: Chat with Jarvis

After setup, message Jarvis on WhatsApp:

| If You Used... | Where to Find Jarvis |
|-----------------|---------------------|
| **Dedicated number** | Find "Jarvis" or "WhatsApp Web" in your contacts |
| **Personal number** | Tap **"Message yourself"** at the top of your chat list |

Try sending: "Hello", "What's the weather?", or "Tell me a joke"

---

## Running Jarvis Later

Every time you want to use Jarvis after the first setup:

### Mac / Linux

```bash
./jarvis_start.sh
```

### Windows (PowerShell)

```powershell
.\jarvis_start.ps1
```

Then message Jarvis on WhatsApp!

---

## Need Help?

- Open an issue: [github.com/UpayanGhosh/Jarvis-OSS/issues](https://github.com/UpayanGhosh/Jarvis-OSS/issues)
