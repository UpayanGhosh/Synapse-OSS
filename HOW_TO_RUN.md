# 🤖 Jarvis AI Assistant - Setup Guide

Get Jarvis running in minutes with the automatic setup!

---

## ⚡ Quick Setup (One Command)

Run this in your terminal:

```bash
./jarvis_onboard.sh   # Mac/Linux
.\jarvis_onboard.ps1  # Windows
```

That's it! The script will guide you through everything.

---

## 🖥️ Running Scripts on Different Operating Systems

### Mac / Linux

Open **Terminal** and run:

```bash
cd /path/to/Jarvis-OSS
chmod +x jarvis_onboard.sh  # Make executable (if needed)
./jarvis_onboard.sh
```

### Windows

Open **PowerShell as Administrator** the first time and allow scripts to run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then run:

```powershell
cd C:\path\to\Jarvis-OSS
.\jarvis_onboard.ps1
```

---

## What You'll Need First

Make sure you have these installed on your computer:

| Tool | How to Check | Where to Get It |
|------|--------------|-----------------|
| **Git** | `git --version` | [git-scm.com](https://git-scm.com) |
| **Python** | `python3 --version` (Mac/Linux) · `python --version` (Windows) | [python.org](https://www.python.org) |
| **Docker** | `docker --version` | [docker.com](https://docker.com) |
| **OpenClaw** | `openclaw --version` | [openclaw.ai](https://openclaw.ai) |

Before running the onboard script, also set up your Python environment and config:

```bash
# macOS/Linux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY=your_key_here

# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env — add at minimum: GEMINI_API_KEY=your_key_here
```

The onboard script will also pull the required Ollama embedding model (`nomic-embed-text`) and create the Qdrant Docker container automatically.

---

## What the Setup Script Does

When you run the onboarding script, it will:

1. ✅ Check that all tools are installed
2. ✅ Ask if you want a **dedicated number** or **personal number** for WhatsApp
   - **Dedicated number** (recommended): Use a separate phone just for Jarvis
   - **Personal number**: Use your own WhatsApp — chat via "Message yourself"
3. ✅ Show a QR code to link your WhatsApp
4. ✅ Collect your phone number (for permissions) - validates E.164 format
5. ✅ Start all Jarvis services (Qdrant, Ollama, API Gateway, WhatsApp bridge)
6. ✅ Verify services are running
7. ✅ Tell you how to start chatting

---

## How to Chat with Jarvis

After setup, message Jarvis on WhatsApp:

| If You Used... | Where to Find Jarvis |
|-----------------|---------------------|
| **Dedicated number** | Find "Jarvis" or "WhatsApp Web" in your contacts |
| **Personal number** | Tap **"Message yourself"** at the top of your chat list |

Try sending: "Hello", "What's the weather?", or "Tell me a joke"

---

## Running Jarvis Later

Every time you want to use Jarvis:

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
