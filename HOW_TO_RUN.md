# 🤖 How to Set Up Your Jarvis AI Assistant

This guide will walk you through setting up Jarvis on your computer. We'll go step by step — take your time, read each part carefully.

**Estimated time:** 15-20 minutes

---

## 📥 Part 1: Install the Programs You Need

### 1.1 — Download Git (Step 1 of 3)

1. Open your browser and go to: **https://git-scm.com/downloads**
2. Click the button for your computer (Windows, Mac, or Linux)
3. A file will download — click to run it

**Windows Users:**
- Keep clicking **"Next"** until it says **"Finish"**
- All the default settings are fine!

**Mac Users:**
- A file will open — just follow the prompts
- If it says "can't verify developer," right-click the file and choose **"Open"**

---

### 1.2 — Download Python (Step 2 of 3)

1. Go to: **https://www.python.org/downloads/**
2. Click **"Download Python"**

**⚠️ CRITICAL FOR WINDOWS USERS — READ THIS!**

On the first screen, you will see a checkbox at the bottom that says **"Add Python to PATH"**.

**YOU MUST CHECK THIS BOX.** If you don't, nothing will work!

It should look like this (make sure the box is ticked):
```
☑ Add Python to PATH
```

Then click **"Install Now"**.

---

### 1.3 — Download Docker (Step 3 of 3)

1. Go to: **https://www.docker.com/products/docker-desktop/**
2. Click **"Download Docker Desktop"**
3. Run the installer

**Windows Users:**
- If it asks to install WSL or Hyper-V, click **"OK"** or **"Yes"**
- It may ask you to restart your computer — do it!

**Mac Users:**
- Just drag the Docker icon to your Applications folder

---

### ✅ Part 1 Complete — Checkpoint

Open a new terminal window and type these one at a time, pressing Enter after each:

```bash
git --version
python --version
docker --version
```

You should see version numbers appear (like 2.40.0, 3.11.0, etc.). If you see "not found" or an error, try the installation again or restart your computer.

---

## 💾 Part 2: Get the Jarvis Code

### 2.1 — Open Terminal

| Your Computer | Do This |
|---------------|---------|
| **Windows** | Press the Windows key → type "PowerShell" → press Enter |
| **Mac** | Press Command + Space → type "Terminal" → press Enter |
| **Linux** | Press Ctrl + Alt + T |

### 2.2 — Download the Code

Copy and paste this into your terminal (Ctrl+V or Cmd+V), then press Enter:

```bash
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
```

After it finishes, type:

```bash
cd Jarvis-OSS
```

### 2.3 — Set Up the Safe Environment

Copy and paste these commands one by one:

**For Mac/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**For Windows (PowerShell):**
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
```

**You know it worked** if your prompt now starts with `(.venv)`, like:
```
(.venv) C:\Users\YourName\Jarvis-OSS>
```

### 2.4 — Install the Dependencies

Copy and paste this and press Enter:

```bash
pip install -r requirements.txt
```

Wait for it to finish (could take 2-5 minutes). You'll know it's done when you see your prompt again.

---

## 🔑 Part 3: Get Your Free API Key

This is what lets Jarvis talk to AI. It's free and takes 1 minute.

### 3.1 — Go to Google AI Studio

Open your browser and go to:
**https://aistudio.google.com/app/apikey**

### 3.2 — Sign In

Use your Google account (Gmail) to sign in.

### 3.3 — Create API Key

1. Click **"Create API Key"**
2. Click **"Create API key in new project"**
3. A long string of letters and numbers will appear — copy it all
4. Don't share this with anyone!

### 3.4 — Save It

1. In your terminal, make sure you're in the Jarvis-OSS folder
2. Copy and paste this to create your settings file:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Mac/Linux:**
```bash
cp .env.example .env
```

3. Now open that file:

**All computers:**
```bash
notepad .env
```

4. Find the line that says `GEMINI_API_KEY=`
5. Delete `your_gemini_api_key_here` and paste your key there

It should look like:
```
GEMINI_API_KEY=AIzaSyDxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

6. Save the file and close it

---

## 📱 Part 4: Connect WhatsApp

### 4.1 — Link Your WhatsApp

In your terminal, copy and paste this and press Enter:

```bash
openclaw channels login
```

A QR code will appear on your screen!

### 4.2 — Scan with WhatsApp

1. Open **WhatsApp** on your phone
2. Tap the three dots (⋮) or **Settings**
3. Tap **Linked Devices**
4. Tap **Link a Device**
5. Point your phone at your screen to scan the QR code

**Wait** — it might take a few seconds to connect. You'll see "Linked" when it's done.

---

## 🚀 Part 5: Start Jarvis

### 5.1 — Make Sure Docker is Running

- **Windows:** Look for the Docker icon in your taskbar (bottom right). If it's not there, open Docker Desktop from your Start menu and wait for it to load.
- **Mac:** Look for the Docker icon in your menu bar (top right).

### 5.2 — Start the Gateway

In your terminal, copy and paste:

```bash
openclaw gateway
```

Wait a moment... You should see messages like:
```
🌍 Loading .env from /Users/.../Jarvis-OSS/.env
🤖 LLM Architecture: Casual: gemini-3-flash
INFO: Uvicorn running on http://127.0.0.1:8000
```

**🎉 Jarvis is now running!**

---

## 💬 Part 6: Chat with Jarvis

Here's the fun part!

1. Open **WhatsApp** on your phone
2. Find the new chat with **"Jarvis"** or **"WhatsApp Web"**
3. Send a message!

Try sending:
- "Hello"
- "What's the weather?"
- "Tell me a joke"

Jarvis will reply! 🎉

---

## 🛠️ If Something Goes Wrong

### "python is not found" or "python: command not found"

**Windows:** Python wasn't added to PATH. Uninstall Python, then reinstall it and make sure to check the "Add to PATH" box.

**Mac/Linux:** Try `python3` instead of `python`.

---

### "No module named 'xyz'"

You might not be in the virtual environment. Make sure your terminal shows `(.venv)` at the start. If not, run:

**Mac/Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```powershell
. .venv\Scripts\Activate.ps1
```

Then run `pip install -r requirements.txt` again.

---

### Docker won't start

1. Make sure Docker Desktop is open
2. Wait for it to fully load (the whale icon should be still, not moving)
3. Try closing other programs that might use ports (like Zoom, Skype, etc.)

---

### WhatsApp won't connect

Run this again:
```bash
openclaw channels login
```

A new QR code will appear — scan it again.

---

### Jarvis isn't responding

Check that your terminal shows:
- "Uvicorn running on http://127.0.0.1:8000"
- Your API key is saved in the .env file (no typos!)

---

## 🔄 How to Run Jarvis Again Later

Every time you want to use Jarvis:

1. Open **Docker Desktop** (if not already running)
2. Open your terminal
3. Go to the Jarvis folder:
   ```bash
   cd Jarvis-OSS
   ```
4. Activate the environment:
   
   **Mac/Linux:**
   ```bash
   source .venv/bin/activate
   ```
   
   **Windows:**
   ```powershell
   . .venv\Scripts\Activate.ps1
   ```
   
5. Start Jarvis:
   ```bash
   openclaw gateway
   ```

6. Message Jarvis on WhatsApp!

---

## 📞 Need Help?

If you get stuck:

1. Take a screenshot of the error
2. Note what step you're on
3. Open an issue at: **https://github.com/UpayanGhosh/Jarvis-OSS/issues**

We'll help you figure it out! 😊
