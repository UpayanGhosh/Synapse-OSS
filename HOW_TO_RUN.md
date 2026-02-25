# 🚀 How to Run Jarvis-OSS

This repository is a deeply customized, modular RAG system built on top of the **OpenClaw** platform. This guide is designed to be beginner-friendly, even if you've never used a terminal before.

> **Running on Windows?** This guide has Windows-specific instructions at every step. Look for the 🪟 icon.

---

## 📦 Step 1: Install Required Software

You need **three** programs installed before anything else.

### 1. Git (Code Downloader)
*   **What it does:** Downloads and updates the Jarvis-OSS code.
*   **Get it:** [Download for Windows/Mac/Linux](https://git-scm.com/downloads)
*   🪟 **Windows Tip:** During installation, just keep clicking "Next" — the default settings are fine.

### 2. Python (The Engine)
*   **What it does:** Runs all the Jarvis logic.
*   **Get it:** [Download Python 3.11+](https://www.python.org/downloads/)
*   🪟 **⚠️ CRITICAL WINDOWS STEP:** During installation, you **MUST** check the box that says **"Add Python to PATH"** on the very first screen. If you miss this, nothing else in this guide will work.
    
    ![Python PATH checkbox](https://docs.python.org/3/_images/win_installer.png)

*   **Verify installation:** After installation, open a new terminal and type:
    ```bash
    python --version
    ```
    You should see something like `Python 3.11.x` or higher. If you see an error, Python was not added to PATH — uninstall and reinstall with the checkbox checked.

### 3. Docker (Memory Storage)
*   **What it does:** Runs Qdrant, which is Jarvis's "long-term memory" database.
*   **Get it:** [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
*   Once installed, **open Docker Desktop** and wait for it to fully start (the whale icon in your taskbar will stop animating when ready).
*   🪟 **Windows Note:** Docker Desktop may ask you to enable WSL 2 or Hyper-V. Follow the prompts and restart your computer if asked.

---

## 📂 Step 2: Download & Set Up the Project

### 2a. Open a Terminal

| OS | How to open |
|---|---|
| 🪟 **Windows** | Press `Win + X`, then click **"Windows PowerShell"** or **"Terminal"** |
| 🍎 **macOS** | Press `Cmd + Space`, type **Terminal**, press Enter |
| 🐧 **Linux** | Press `Ctrl + Alt + T` |

### 2b. Clone the Code

Type these commands one at a time, pressing **Enter** after each:

```bash
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
```

### 2c. Create a Virtual Environment

A virtual environment is like a clean sandbox so Jarvis's libraries don't conflict with anything else on your computer.

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

🪟 **Windows PowerShell:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 🪟 **Windows Error: "Script execution is disabled"?**  
> This is a common Windows security setting. Run this command **once** to fix it, then try the activate command again:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Alternatively, use the `.bat` version instead:
> ```cmd
> .\.venv\Scripts\activate.bat
> ```

**How to know it worked:** Your terminal prompt will now start with `(.venv)` — for example:
```
(.venv) C:\Users\YourName\Jarvis-OSS>
```

### 2d. Install Dependencies

```bash
pip install -r requirements.txt
```

This may take 2–5 minutes. Wait for it to finish completely.

---

## 🐚 Step 3: Install OpenClaw Base

Jarvis-OSS extends OpenClaw and is a "supercharged" version, so you need the base tool first:

### Option A: Using npm (Easiest)
```bash
npm install -g npm@latest
npm i -g openclaw
```

Verify it works:
```bash
openclaw --version
```

You should see a version number. If you see an error, make sure your virtual environment is activated (see Step 2c).

---

## 🚀 Step 4: Start the Memory Database (Qdrant)

1.  Make sure **Docker Desktop** is open and running.
2.  In your terminal, run:

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

3.  Verify it's running:
```bash
docker ps
```
You should see a row with `qdrant/qdrant` in the output. If you don't, Docker may not be fully started — wait a moment and try again.

> **Note:** You only need to run the `docker run` command once. After that, Qdrant will start automatically when Docker Desktop opens. If it doesn't, run: `docker start qdrant`

---

## 🔑 Step 5: Set Up the `.env` File (Secret Keys)

> **⚠️ This is the #1 place where people get stuck.** Read every line carefully.

The `.env` file tells Jarvis your API keys and security tokens. Without it, the gateway **will crash** with an error like:
```
EnvironmentError: OPENCLAW_GATEWAY_TOKEN environment variable is required
```

### 5a. Create the `.env` file

You need to copy the example template to create your actual `.env` file.

🪟 **Windows PowerShell:**
```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

### 5b. Open and edit the `.env` file

Open the `.env` file in any text editor:

| Editor | How to open |
|---|---|
| **VS Code** (recommended) | Type `code .env` in the terminal |
| 🪟 **Notepad** (Windows) | Type `notepad .env` in PowerShell |
| 🍎 **TextEdit** (macOS) | Type `open -a TextEdit .env` in terminal |
| **nano** (Linux/macOS) | Type `nano .env` in terminal |

### 5c. Fill in the **required** values

At minimum, you **must** set these two values. Everything else is optional.

| Variable | Required? | What it is | Where to get it |
|---|---|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | ✅ **Yes** | A password that protects the API. **You make this up yourself.** | Invent any string, e.g. `my-jarvis-secret-2024` |
| `GEMINI_API_KEY` | ✅ **Yes** | The key that lets Jarvis talk to Google's AI models. | Free from [Google AI Studio](https://aistudio.google.com/app/apikey) — click "Create API Key" |

**Here is what your `.env` file should look like after editing (minimum required):**

```dotenv
# --- Required ---
GEMINI_API_KEY=AIzaSyD_YOUR_ACTUAL_KEY_FROM_GOOGLE
OPENCLAW_GATEWAY_TOKEN=my-jarvis-secret-2024

# --- Optional (leave as-is if unsure) ---
OPENROUTER_API_KEY="your_openrouter_api_key_here"
OPENAI_API_KEY="your_openai_api_key_here"
GROQ_API_KEY="your_groq_api_key_here"
WINDOWS_PC_IP="192.168.1.xxx"
WHATSAPP_BRIDGE_TOKEN="your_whatsapp_bridge_secret"
WHATSAPP_CHAT_URL="http://127.0.0.1:8000/chat"
MAC_APP_SESSION_TYPE="safe"
```

### 5d. Important rules for the `.env` file

1.  **No spaces around the `=` sign.**  
    ✅ `OPENCLAW_GATEWAY_TOKEN=my-secret`  
    ❌ `OPENCLAW_GATEWAY_TOKEN = my-secret`

2.  **No `#` at the start of the line** — that makes it a comment (ignored).  
    ✅ `OPENCLAW_GATEWAY_TOKEN=my-secret`  
    ❌ `# OPENCLAW_GATEWAY_TOKEN=my-secret`

3.  **Quotes are optional.** Both of these work:  
    ✅ `OPENCLAW_GATEWAY_TOKEN=my-secret`  
    ✅ `OPENCLAW_GATEWAY_TOKEN="my-secret"`

4.  🪟 **Windows Notepad warning:** Make sure the file is saved as `.env` and NOT `.env.txt`. Notepad sometimes adds `.txt` automatically. To avoid this:
    - In the "Save As" dialog, change "Save as type" to **"All Files (\*.\*)"**
    - Or use VS Code instead (recommended)

### 5e. Where should `.env` live?

The `.env` file should be placed in the **root of the project** (the `Jarvis-OSS` folder):

```
Jarvis-OSS/               ← .env goes HERE
├── .env                   ← ✅ This file
├── .env.example
├── workspace/
│   ├── main.py
│   └── sci_fi_dashboard/
│       └── api_gateway.py
└── ...
```

The system automatically searches for it in the project root first, then in the `workspace/` folder. You do **not** need to be in any specific directory for it to be found.

---

## 🖥️ Step 6: Start the Jarvis Gateway

The Gateway is the "Brain" server that processes all messages.

### Option A: Run via the CLI (Recommended)

From the **project root** (`Jarvis-OSS/` folder):

**macOS / Linux:**
```bash
cd workspace
python3 -m uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000
```

🪟 **Windows PowerShell:**
```powershell
cd workspace
python -m uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000
```

### Option B: Run the interactive chat directly

**macOS / Linux:**
```bash
cd workspace
python3 main.py chat
```

🪟 **Windows PowerShell:**
```powershell
cd workspace
python main.py chat
```

This will start the gateway server in the background and open an interactive chat prompt.

### What "success" looks like

When the server starts correctly, you'll see output like:
```
🌍 Loading .env from /path/to/Jarvis-OSS/.env
🤖 LLM Architecture (OAuth): 
   Casual: gemini-3-flash
   ...
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 🛑 Troubleshooting

### ❌ Error: `OPENCLAW_GATEWAY_TOKEN environment variable is required`

This is the most common error. It means the gateway cannot find or read your token. Here's how to fix it step by step:

**1. Check that `.env` exists in the right place:**

🪟 Windows PowerShell:
```powershell
# From the Jarvis-OSS root folder:
Test-Path .env
```

macOS / Linux:
```bash
# From the Jarvis-OSS root folder:
ls -la .env
```

If the file doesn't exist, go back to **Step 5a**.

**2. Check that the token is actually set inside the file:**

🪟 Windows PowerShell:
```powershell
Select-String "OPENCLAW_GATEWAY_TOKEN" .env
```

macOS / Linux:
```bash
grep "OPENCLAW_GATEWAY_TOKEN" .env
```

You should see a line like `OPENCLAW_GATEWAY_TOKEN=my-jarvis-secret-2024`. If the line starts with `#`, it's commented out — remove the `#`.

**3. Check that the file isn't secretly named `.env.txt`:**

🪟 Windows PowerShell:
```powershell
Get-ChildItem -Force | Where-Object { $_.Name -like ".env*" }
```

If you see `.env.txt`, rename it:
```powershell
Rename-Item .env.txt .env
```

**4. Last resort — set the variable manually in your terminal session:**

This bypasses the `.env` file entirely. Useful for quick testing.

🪟 Windows PowerShell:
```powershell
$env:OPENCLAW_GATEWAY_TOKEN = "my-jarvis-secret-2024"
$env:GEMINI_API_KEY = "AIzaSy_YOUR_KEY"
```

macOS / Linux:
```bash
export OPENCLAW_GATEWAY_TOKEN="my-jarvis-secret-2024"
export GEMINI_API_KEY="AIzaSy_YOUR_KEY"
```

Then re-run the gateway command from Step 6.

---

### ❌ Error: `ModuleNotFoundError: No module named 'xyz'`

You forgot to activate the virtual environment or install dependencies. Run:
```bash
# Activate venv first (see Step 2c), then:
pip install -r requirements.txt
```

### ❌ Error: `python is not recognized`

🪟 **Windows:** You forgot to check "Add Python to PATH" during installation. Uninstall Python and reinstall with that checkbox checked. See Step 1.

### ❌ Error: `Script execution is disabled`

🪟 **Windows PowerShell only.** Run this once:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### ❌ Docker/Qdrant won't start

1.  Make sure **Docker Desktop** is open and fully loaded (whale icon is stable).
2.  If you've run `docker run` before and get a "name already in use" error:
    ```bash
    docker start qdrant
    ```

---

## 📱 Step 7: WhatsApp Setup (Optional)

To talk to Jarvis on WhatsApp:

1.  **Configure WhatsApp:** Run `openclaw onboard` and follow the prompts. You'll need a [Meta Developer](https://developers.facebook.com/) account.
2.  **Start the link:**
    
    macOS / Linux:
    ```bash
    openclaw start --workspace /path/to/your/Jarvis-OSS/workspace
    ```
    
    🪟 Windows PowerShell:
    ```powershell
    openclaw start --workspace C:\Users\YourName\Jarvis-OSS\workspace
    ```

---

## ✅ Final Checklist

Before running the gateway, confirm all of these:

- [ ] **Docker Desktop** is open and running (whale icon is stable).
- [ ] Your **`.env`** file exists in the root `Jarvis-OSS/` folder.
- [ ] **`OPENCLAW_GATEWAY_TOKEN`** is set inside `.env` (not commented out with `#`).
- [ ] **`GEMINI_API_KEY`** is set inside `.env` with a valid key from Google AI Studio.
- [ ] Your **virtual environment** is activated (you see `(.venv)` in your terminal prompt).
- [ ] You ran **`pip install -r requirements.txt`** successfully.

---

## 📊 Project Folder Structure (Quick Reference)

```
Jarvis-OSS/
├── .env                   ← Your secret keys (Step 5)
├── .env.example           ← Template for .env
├── requirements.txt       ← Python dependencies
├── HOW_TO_RUN.md          ← You are here!
├── README.md              ← Project overview
├── workspace/
│   ├── main.py            ← CLI entry point (python main.py chat)
│   ├── utils/
│   │   └── env_loader.py  ← Shared .env file loader
│   └── sci_fi_dashboard/
│       ├── api_gateway.py ← The main Gateway server
│       ├── memory_engine.py
│       └── ...
└── ...
```

---

**Still stuck?** Open an issue on [GitHub](https://github.com/UpayanGhosh/Jarvis-OSS/issues) with:
1. The **full error message** (copy-paste from terminal)
2. Your **OS** (Windows 10/11, macOS, Linux)
3. Your **Python version** (`python --version`)
