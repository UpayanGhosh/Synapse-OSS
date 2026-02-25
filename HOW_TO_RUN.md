# 🚀 How to Run Jarvis-OSS

This repository is a deeply customized, modular RAG system built on top of the **OpenClaw** platform. For a high-level overview, see [README.md](README.md).

---

## 📦 Step 1: Install Required Software

Don't worry if you're new to this! Here's what you need.

### System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| **RAM** | 8 GB | 16 GB |
| **Storage** | 10 GB free | 20 GB free |
| **OS** | macOS 10.15+, Windows 10+, Ubuntu 18.04+ | macOS 12+, Windows 11, Ubuntu 22.04+ |

### What You'll Need

| Tool | What It Does | How to Get It |
|------|-------------|---------------|
| **Git** | Downloads the project code | [Download](https://git-scm.com/downloads) |
| **Python** | Runs the program | [Download](https://www.python.org/downloads/) |
| **Docker** | Runs Qdrant (memory) | [Download](https://www.docker.com/products/docker-desktop/) |

> **💡 Windows Tip:** During Python installation, **check "Add Python to PATH"**!

### Verify Installation

```bash
# macOS/Linux
git --version && python3 --version && docker --version

# Windows PowerShell
git --version; python --version; docker --version
```

---

## 📂 Step 2: Clone & Set Up Jarvis-OSS

```bash
# macOS/Linux
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Windows PowerShell
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> **⚠️ Windows:** If you get a script error on `Activate.ps1`, run this first:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

## 🐚 Step 3: Install OpenClaw

Jarvis-OSS extends OpenClaw. You need the base installation:

### Option A: Using pip (Easiest)

```bash
pip install openclaw
```

### Option B: From Source

```bash
# macOS/Linux
git clone https://github.com/openclaw/openclaw.git ~/openclaw
cd ~/openclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Windows PowerShell
git clone https://github.com/openclaw/openclaw.git $env:USERPROFILE\openclaw
cd $env:USERPROFILE\openclaw
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

### Verify

```bash
openclaw --version
```

---

## 🚀 Step 4: Set Up Qdrant (Vector Database)

Qdrant stores the "long-term memory" for your Jarvis.

### Option A: Docker (Recommended)

```bash
# macOS/Linux & Windows
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

Verify: `docker ps` should show qdrant running.

### Option B: Native (Linux/macOS)

```bash
# macOS (Apple Silicon - M1/M2/M3/M4)
curl -LO https://github.com/qdrant/qdrant/releases/latest/download/qdrant-aarch64-apple-darwin.tar.gz
tar -xzf qdrant-aarch64-apple-darwin.tar.gz
./qdrant

# macOS (Intel)
curl -LO https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-apple-darwin.tar.gz
tar -xzf qdrant-x86_64-apple-darwin.tar.gz
./qdrant

# Linux
curl -LO https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
./qdrant
```

> **Note:** If Qdrant isn't running, you'll see a warning but the system will still work (with limited features).

---

## 🔑 Step 5: Get API Keys & Configure

You need at least one AI API key. Here are free options:

### Google Gemini (Recommended - Easiest Free Key)

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click "Get API Key" → Create new project
3. Copy the key (starts with `AIza...`)
4. Free: 15 requests/min, 1,500 tokens/min

### Groq (Fastest Free)

1. Go to [https://console.groq.com](https://console.groq.com)
2. Sign up → API Keys → Create Key
3. Copy the key (starts with `gsk_...`)
4. Free: Very high limits, extremely fast

### Configure Your .env File

Make sure you're inside the Jarvis-OSS folder, then:

```bash
# macOS/Linux
cp .env.example .env

# Windows PowerShell
copy .env.example .env
```

Edit `.env` and add your key:

```bash
GEMINI_API_KEY=AIza...   # Your Google key
# OR
GROQ_API_KEY=gsk_...    # Your Groq key

# Required: Set any random string for authentication
OPENCLAW_GATEWAY_TOKEN=my-secret-token-12345
```

> **💡 Important:** After editing `.env`, you must restart the gateway for changes to take effect.

---

## 🖥️ Step 6: Start Jarvis Gateway

```bash
# macOS/Linux
cd Jarvis-OSS
source .venv/bin/activate
cd workspace/sci_fi_dashboard
python3 api_gateway.py

# Windows PowerShell
cd Jarvis-OSS
.venv\Scripts\Activate.ps1
cd workspace\sci_fi_dashboard
python api_gateway.py
```

If successful, you'll see:
```
✅ MemoryEngine initialized
✅ Gateway running on http://localhost:8000
```

---

## 📱 Step 7: WhatsApp Setup

To chat with Jarvis via WhatsApp, you need to configure it.

### 1. Run the Onboard Wizard (FIRST!)

```bash
openclaw onboard
```

This will guide you through:
- Setting up your OpenClaw account
- Configuring WhatsApp (you'll need Meta Developer credentials)
- Setting up channels

### 2. What You'll Need from Meta

During onboard, you'll be asked for WhatsApp credentials. Get them here:

1. Go to https://developers.facebook.com/
2. Create an app → select "WhatsApp"
3. Get from the dashboard:
   - Phone Number ID
   - WhatsApp Business Account ID
   - App Secret
   - Access Token

### 3. Important: Skip the Gateway!

When running `openclaw onboard`:
- When asked about starting gateway: **Choose NO** ⭐
- When asked about daemon: **Choose NO**

Why? Because your Jarvis gateway already runs on port 8000!

### 4. Start OpenClaw (AFTER onboard)

```bash
# macOS/Linux
openclaw start --workspace ~/Jarvis-OSS/workspace

# Windows PowerShell
openclaw start --workspace C:\Users\YourName\Jarvis-OSS\workspace
```

### 5. Connect Your Phone

1. Add a test phone number in Meta Developer Portal
2. You'll get a message on WhatsApp - reply "join" to authorize
3. Start chatting!

---

## ⚠️ Port Conflict Warning

| Port | What Uses It |
|------|-------------|
| 8000 | Jarvis-OSS api_gateway.py (YOUR gateway) |
| 8000 | OpenClaw default gateway |

**Never run both on the same port!**

---

## 📖 Glossary

| Term | Meaning |
|------|---------|
| **Terminal** | Text-based way to talk to your computer |
| **.venv** | Isolated space for this project (won't mess up other Python projects) |
| **Qdrant** | Database for long-term memory (vector embeddings) |
| **memory.db** | Auto-created database file - you don't need to create it! |
| **API Key** | Secret password to talk to AI services (Gemini, Claude, etc.) |

---

## 💻 Windows-Specific Notes

### Common Issues

| Error | Solution |
|-------|----------|
| `python not recognized` | Add Python to PATH or use `py` |
| `docker not found` | Install Docker Desktop |
| `Permission denied` | Run PowerShell as Administrator |

### Command Reference

| macOS/Linux | Windows |
|-------------|---------|
| `python3` | `python` |
| `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| `cp a b` | `copy a b` |
| `curl` | `curl.exe` |

---

## ✅ Quick Checklist

**In order:**

1. [ ] Git, Python, Docker installed
2. [ ] Jarvis-OSS cloned
3. [ ] Virtual environment created and dependencies installed
4. [ ] OpenClaw installed (`pip install openclaw`)
5. [ ] `.env` file created with API key
6. [ ] `OPENCLAW_GATEWAY_TOKEN` set in `.env`
7. [ ] Qdrant running (`docker ps` shows qdrant)
8. [ ] Jarvis gateway started (`python3 api_gateway.py`)
9. [ ] `openclaw onboard` completed (configures WhatsApp)
10. [ ] `openclaw start --workspace ...` started

---

## ❓ FAQ

**Q: Do I need to know programming?**
> A: No! Just follow the steps. Programming knowledge not required.

**Q: How much does it cost?**
> A: Software is free. API keys may cost money, but this guide shows free options.

**Q: How long to set up?**
> A: About 30-60 minutes first time.

**Q: What if something goes wrong?**
> 1. Check Docker is running (green icon in taskbar)
> 2. Check Qdrant: `docker ps`
> 3. Check .env has correct API keys
> 4. Check error messages in terminal

---

## Need Help?

- **GitHub Issues:** https://github.com/UpayanGhosh/Jarvis-OSS/issues
- **Check logs:** Look at terminal output for error messages
- **Restart:** Often fixes issues: restart Docker, restart gateway

---

**Happy chatting! 🤖**
