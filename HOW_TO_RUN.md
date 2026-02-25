# 🚀 How to Run Jarvis-OSS

This is a beginner-friendly guide to get Jarvis-OSS running on your machine.

> **Running on Windows?** This guide has Windows-specific instructions marked with 🪟.

---

## 📦 Step 1: Install Required Software

### 1. Git
- **What:** Downloads and updates the Jarvis code
- **Download:** [git-scm.com/downloads](https://git-scm.com/downloads)
- 🪟 Just click "Next" through the installer — defaults are fine

### 2. Python
- **What:** Runs all the Jarvis logic
- **Download:** [python.org/downloads](https://www.python.org/downloads/) (version 3.11+)
- 🪟 **CRITICAL:** Check "Add Python to PATH" on the first screen!

Verify:
```bash
python --version
```

### 3. Docker Desktop
- **What:** Runs Qdrant (vector memory database)
- **Download:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- 🪟 Enable WSL 2 or Hyper-V if prompted, restart if needed

---

## 📂 Step 2: Download & Set Up the Project

### 2a. Open a Terminal

| OS | How to open |
|---|---|
| 🪟 Windows | Press `Win + X` → **Windows PowerShell** or **Terminal** |
| 🍎 macOS | Press `Cmd + Space` → type **Terminal** → Enter |
| 🐧 Linux | Press `Ctrl + Alt + T` |

### 2b. Clone and Enter the Project

```bash
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
```

### 2c. Create a Virtual Environment

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

🪟 **Windows PowerShell:**
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
```

🪟 **Windows Error: "Script execution is disabled"?**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Success looks like:** Your prompt starts with `(.venv)`

### 2d. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🐚 Step 3: Install OpenClaw Base

Jarvis-OSS is built on OpenClaw. Install it via npm:

```bash
npm install -g npm@latest
npm i -g openclaw
```

Verify:
```bash
openclaw --version
```

---

## 🚀 Step 4: Start the Memory Database

1. **Open Docker Desktop** and wait for it to fully load (whale icon stops animating)
2. Run:
```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```
3. Verify:
```bash
docker ps
```

> **Note:** Only run step 2 once. After that, Qdrant starts automatically with Docker.

---

## 🔑 Step 5: Set Up Your API Key

### 5a. Create the `.env` File

🪟 **Windows:**
```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

### 5b. Get Your Free API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API Key"**
3. Copy the key

### 5c. Edit the `.env` File

Open in your preferred editor:
```bash
code .env          # VS Code (recommended)
notepad .env      # Windows Notepad
nano .env         # Linux terminal
```

**Add your key:**
```dotenv
GEMINI_API_KEY=AIzaSy...your_actual_key_here
```

**Leave everything else as-is or commented out** — only `GEMINI_API_KEY` is required.

### 5d. Important Rules

- ✅ No spaces around `=` → `KEY=value`
- ✅ No `#` at the start of required lines
- 🪟 **Windows:** Save as `.env`, NOT `.env.txt`

---

## 🖥️ Step 6: Run Jarvis

### Option A: Interactive Chat (Easiest)

```bash
cd workspace
python main.py chat
```

### Option B: Run Gateway Directly

```bash
cd workspace
python -m uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000
```

**Success looks like:**
```
🌍 Loading .env from /path/to/Jarvis-OSS/.env
🤖 LLM Architecture (OAuth):
   Casual: gemini-3-flash
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 📱 Step 7: WhatsApp (Optional)

Want to chat with Jarvis on WhatsApp?

```bash
openclaw onboard
```

This will walk you through connecting WhatsApp — no Meta Developer account needed on your end.

Then start Jarvis with:
```bash
openclaw start --workspace /path/to/Jarvis-OSS/workspace
```

---

## ✅ Final Checklist

Before running, confirm:

- [ ] Docker Desktop is open and running
- [ ] `.env` file exists in project root
- [ ] `GEMINI_API_KEY` is set in `.env`
- [ ] Virtual environment is activated (`(.venv)` in prompt)
- [ ] Dependencies installed (`pip install -r requirements.txt`)

---

## 🛑 Troubleshooting

### `python is not recognized`
🪟 Reinstall Python and check "Add to PATH"

### `ModuleNotFoundError`
Activate venv and reinstall:
```bash
pip install -r requirements.txt
```

### Docker/Qdrant won't start
```bash
docker start qdrant
```

### `GEMINI_API_KEY` error
Make sure you copied the full key from Google AI Studio — it starts with `AIza...`

---

**Still stuck?** Open an issue at [github.com/UpayanGhosh/Jarvis-OSS/issues](https://github.com/UpayanGhosh/Jarvis-OSS/issues)
