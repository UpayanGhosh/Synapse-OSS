# 🤖 Jarvis AI Assistant - Setup Guide

Get Jarvis running in minutes with the automatic setup!

---

## ⚡ Quick Setup (One Command)

Run this in your terminal:

```bash
./jarvis_onboard.sh
```

That's it! The script will guide you through everything.

---

## What You'll Need First

Make sure you have these installed on your computer:

| Tool | How to Check | Where to Get It |
|------|--------------|-----------------|
| **Git** | `git --version` | [git-scm.com](https://git-scm.com) |
| **Python** | `python3 --version` | [python.org](https://www.python.org) |
| **Docker** | `docker --version` | [docker.com](https://www.docker.com) |
| **OpenClaw** | `openclaw --version` | [openclaw.ai](https://openclaw.ai) |

---

## What the Setup Script Does

When you run `./jarvis_onboard.sh`, it will:

1. ✅ Check that all tools are installed
2. ✅ Ask if you want a **dedicated number** or **personal number** for WhatsApp
   - **Dedicated number** (recommended): Use a separate phone just for Jarvis
   - **Personal number**: Use your own WhatsApp — chat via "Message yourself"
3. ✅ Show a QR code to link your WhatsApp
4. ✅ Collect your phone number (for permissions)
5. ✅ Start Jarvis
6. ✅ Tell you how to start chatting

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

```bash
./jarvis_start.sh
```

Or manually:
```bash
openclaw gateway
```

Then message Jarvis on WhatsApp!

---

## Need Help?

- Open an issue: [github.com/UpayanGhosh/Jarvis-OSS/issues](https://github.com/UpayanGhosh/Jarvis-OSS/issues)
