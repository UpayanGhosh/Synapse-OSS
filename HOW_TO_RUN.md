# 🚀 How to Run Jarvis-OSS (WhatsApp Connected)

This guide gets you running Jarvis-OSS connected to WhatsApp — chat with your AI assistant from your phone!

> **Running on Windows?** Instructions marked with 🪟

---

## 📦 Step 1: Install Required Software

### 1. Git
- **Download:** [git-scm.com/downloads](https://git-scm.com/downloads)
- 🪟 Click "Next" through the installer — defaults are fine

### 2. Python
- **Download:** [python.org/downloads](https://www.python.org/downloads/) (version 3.11+)
- 🪟 **CRITICAL:** Check "Add Python to PATH" on the first screen!

Verify:
```bash
python --version
```

### 3. Docker Desktop
- **Download:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- 🪟 Enable WSL 2 or Hyper-V if prompted, restart if needed

---

## 📂 Step 2: Set Up the Project

### 2a. Open a Terminal

| OS | How to open |
|---|---|
| 🪟 Windows | Press `Win + X` → **Windows PowerShell** |
| 🍎 macOS | Press `Cmd + Space` → **Terminal** |
| 🐧 Linux | Press `Ctrl + Alt + T` |

### 2b. Clone the Project

```bash
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
```

### 2c. Create Virtual Environment

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

🪟 **Error: "Script execution is disabled"?**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Success:** Your prompt shows `(.venv)`

### 2d. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🔑 Step 3: Get Your API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API Key"**
3. Copy the key

---

## 📱 Step 4: Connect WhatsApp

### 4a. Create the `.env` File

🪟 **Windows:**
```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

### 4b. Add Your API Key

```bash
code .env          # Open in VS Code
```

Change this line:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

To:
```
GEMINI_API_KEY=AIzaSy...paste_your_key_here
```

Save and close.

### 4c. Link WhatsApp

Run this command and follow the prompts:

```bash
openclaw channels login
```

This will show a QR code — scan it with WhatsApp on your phone:

1. Open **WhatsApp** → **Settings** → **Linked Devices**
2. Scan the QR code

> **No Meta Developer account needed!** Just scan and go.

---

## 🚀 Step 5: Start Jarvis

Make sure **Docker Desktop is running**, then:

```bash
openclaw gateway
```

**Success looks like:**
```
🌍 Loading .env from /path/to/Jarvis-OSS/.env
🤖 LLM Architecture (OAuth):
   Casual: gemini-3-flash
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 💬 Step 6: Chat on WhatsApp

That's it! Open WhatsApp and message your Jarvis:

1. Open WhatsApp on your phone
2. Find the "Jarvis" device in **Linked Devices**
3. Start typing — Jarvis will respond!

---

## 🛑 Troubleshooting

### Docker/Qdrant won't start
```bash
docker start qdrant
```

### "No module named 'xyz'"
Activate venv and reinstall:
```bash
pip install -r requirements.txt
```

### Can't connect WhatsApp
Run `openclaw channels login` again to regenerate the QR code.

### Jarvis isn't responding
Check that:
- Docker Desktop is running
- The terminal shows "Uvicorn running"
- Your `GEMINI_API_KEY` is valid

---

## 🔧 Keeping Jarvis Updated

From time to time, update to the latest version:

```bash
git pull origin main
pip install -r requirements.txt
```

Then restart (Ctrl+C to stop, then `openclaw gateway` again).

---

**Need help?** Open an issue at [github.com/UpayanGhosh/Jarvis-OSS/issues](https://github.com/UpayanGhosh/Jarvis-OSS/issues)
