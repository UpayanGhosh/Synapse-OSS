# 🚀 How to Run Jarvis-OSS

This repository is a deeply customized, modular RAG system built on top of the incredible **OpenClaw** platform. For a high-level overview of the system, see the [README](README.md). For the full design philosophy, see [MANIFESTO.md](MANIFESTO.md).

> **🙏 Immense Gratitude & Respect**
> This entire project exists because of **[OpenClaw](https://github.com/openclaw/openclaw)**. OpenClaw provides the foundational shell, tool-use capabilities, and gateway architecture that allowed me to build this hyper-personalized "brain." To the creator(s) and maintainers of OpenClaw: thank you for giving us a platform to dream and engineer on. 

---

## 🏗️ Architecture Overview

*(For a visual diagram of exactly how the Mixture of Agents and RAG systems interact, view the **[System Architecture Diagram (Mermaid)](ARCHITECTURE.md)**).*

Features you are deploying:
*   **MoA (Mixture of Agents) Routing:** Dynamically routes Chat to Gemini Flash, Coding to Claude/Gemini, and NSFW/Private tasks to local Ollama nodes based on intention extraction.
*   **Hybrid Memory:** SQLite Knowledge Base (Graph DB) + Vector Embeddings for perfect long-term context recall.

## 📊 Why Choose This Over Vanilla OpenClaw?

Vanilla OpenClaw is a brilliant, generalized framework. But out-of-the-box, it lacks a personalized soul and can become expensive or slow if every chat is routed to a premium model. I built this architectural layer on top of OpenClaw to solve those exact problems.

**1. Token Optimization & Cost Reduction**
Instead of dumping your entire chat history into every single API call (which eats tokens and burns money), this system uses a **Hybrid RAG Retriever**. It intercepts the message, queries the local SQLite Graph, and only injects the *mathematically relevant* memories into the `System Prompt`. The result? Turn total tokens stay low, meaning you can chat for hours for pennies.

**2. Mixture of Agents (MoA) Speed**
Vanilla setups usually rely on one model (e.g., Claude 3.5 Sonnet). This architecture acts as a "Traffic Cop". If you say "Hello", it routes it to Gemini 3 Flash (yielding sub-second, cheap responses). If you say "Write a python script", it routes to Claude 4.5. You get the speed of small models and the power of massive models automatically.

**3. The Infinite Context Window (Zero Hallucination)**
Because memories are stored as rigid Subject-Relation-Object Triples in an SQLite Graph Database—married to Qdrant Vector embeddings—the bot can remember a detail you told it 6 months ago *without* needing a 2-million token context window. It pulls the exact fact, eliminating the hallucination that happens when LLMs try to summarize old conversations. 

**4. True Humanoid Roleplay**
Instead of static System Prompts, this uses dynamic JSON injected "Relationship Contexts." It changes its behavior entirely based on the phone number or chat ID talking to it, making it feel less like a tool and more like an entity.

## 🛠️ Prerequisites

*   **Python 3.10+**
*   **Vanilla OpenClaw:** You must have the [vanilla OpenClaw project](https://github.com/openclaw/openclaw) installed on your machine. (See section below)
*   **Qdrant Vector Database:** Native installation or docker container running on port `6333`. (See section below)
*   *(Highly Optional)* A local machine running **Ollama** for "The Vault" (Zero-cloud local inference). **If you do not have Ollama, the system will seamlessly run entirely on the cloud models.**

*Note: This architecture is cross-platform! Because it is built on Python and OpenClaw, it runs on macOS, Linux, and Windows (preferably via WSL).*

---

## 📦 Installing Required Software (Step-by-Step)

Don't worry if you're new to this! Here's what each tool does and how to install it.

### Minimum System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| **RAM** | 8 GB | 16 GB |
| **Storage** | 10 GB free | 20 GB free |
| **OS** | macOS 10.15+, Windows 10+, Ubuntu 18.04+ | macOS 12+, Windows 11, Ubuntu 22.04+ |
| **Internet** | Required for API keys | Required for API keys |

> **Note:** The system was designed to run on an 8GB MacBook Air. If you have less than 8GB RAM, you may experience slowdowns.

### What You'll Need

| Tool | What It Does | How to Get It |
|------|-------------|---------------|
| **Git** | Downloads the project code from the internet | [Download Git](https://git-scm.com/downloads) |
| **Python** | Runs the program (the brain) | [Download Python](https://www.python.org/downloads/) |
| **Docker** | Runs Qdrant (the memory system) in a container | [Download Docker Desktop](https://www.docker.com/products/docker-desktop/) |

> **💡 Tip:** During Python installation on Windows, **check the box "Add Python to PATH"** - this is crucial!

### Quick Checklist

- [ ] Download and install **Git**
- [ ] Download and install **Python 3.10+** (check "Add to PATH" on Windows)
- [ ] Download and install **Docker Desktop**
- [ ] Create a free **GitHub account** (to clone the project)
- [ ] Get at least one **API key** (see Section 2A for free options)

---

### Verify Your Installation

After installing, open a terminal and type:

```bash
# macOS/Linux
git --version
python3 --version
docker --version

# Windows PowerShell
git --version
python --version
docker --version
```

If each command shows a version number (like `git version 2.40.0`), you're good to go!

---

## 📖 Glossary (In Plain English)

Don't understand a term? Here's what they mean:

| Term | Plain English Explanation |
|------|--------------------------|
| **Terminal/Command Line** | A text-based way to talk to your computer. Instead of clicking icons, you type commands. |
| **Python** | The programming language the system is written in. Think of it as the "brain." |
| **Virtual Environment (.venv)** | A separate space for this project so it doesn't mess up other Python projects on your computer. |
| **Qdrant** | A database that stores "embeddings" (numerical representations of text). Helps the bot remember things semantically. Think of it as "long-term memory." |
| **memory.db** | A SQLite database file that stores facts and conversations. Auto-created on first run - you don't need to create it! |
| **Docker** | A way to run software in an isolated container. Makes it easy to run Qdrant without installation headaches. |
| **API Key** | A secret password that lets your program talk to AI services (like Google Gemini, Claude, etc.). |
| **Vector Embeddings** | A way to convert text into numbers so computers can find "similar" things (like finding all messages about "food" even without the word "food"). |
| **OpenClaw** | The base platform this project builds on top of. Provides WhatsApp integration and tool-use capabilities. |
| **RAG** | Retrieval-Augmented Generation - looking up info before answering. |
| **MoA** | Mixture of Agents - routing messages to different AI models based on what they're best at. |
| **ngrok** | A tool that creates a public URL for your local computer (useful for testing webhooks locally). |

---

## ❓ Frequently Asked Questions

**Q: Do I need to know programming?**
> A: No! You just need to know how to use a terminal/command line and follow the steps. Programming knowledge is not required to run the system.

**Q: How much does this cost?**
> A: The software is free. You'll need to pay for API keys if you use cloud AI models, but this guide shows how to get free keys to start.

**Q: Can I run this on a regular laptop?**
> A: Yes! The project was designed to run on an 8GB RAM MacBook Air. Any modern computer with 8GB+ RAM should work.

**Q: How long does setup take?**
> A: About 30-60 minutes for first-time setup, including installing software and getting API keys.

**Q: What if something goes wrong?**
> A: Check the Troubleshooting sections in this guide. Most common issues have solutions listed.

---

## 💻 Windows Setup Guide

This project runs best on Windows via **WSL2 (Windows Subsystem for Linux)**. Native Windows support is experimental.

### Option A: WSL2 (Recommended)

1. **Install WSL2:**
   ```powershell
   # Run PowerShell as Administrator
   wsl --install
   ```
   - Restart your computer when prompted
   - Create a Ubuntu user account when prompted

2. **Install Docker Desktop:**
   - Download from https://www.docker.com/products/docker-desktop/
   - Enable WSL2 backend in Docker Desktop Settings → General

3. **Open Ubuntu terminal** and run the macOS/Linux commands from this guide:
   ```bash
   # Clone and setup
   git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
   cd Jarvis-OSS
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Start Qdrant (in Ubuntu terminal):**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
   ```

5. **Run the gateway:**
   ```bash
   cd workspace/sci_fi_dashboard
   python3 api_gateway.py
   ```

### Option B: Native Windows (Experimental)

If you prefer not to use WSL2:

1. **Install Python 3.10+** from https://www.python.org/downloads/
   - **Important:** Check "Add Python to PATH" during installation

2. **Install Docker Desktop** from https://www.docker.com/products/docker-desktop/

3. **Open PowerShell** (not Command Prompt) and run:
   > **Note:** If you get an error about running scripts, run this command first:
   > ```powershell
   > Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   > ```
   
   ```powershell
   # Clone the repo
   git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
   cd Jarvis-OSS

   # Create virtual environment
   python -m venv .venv
   .venv\Scripts\Activate.ps1

   # Install dependencies
   pip install -r requirements.txt

   # Start Qdrant (in separate terminal or background)
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant

   # Run the gateway
   cd workspace\sci_fi_dashboard
   python api_gateway.py
   ```

### Common Windows Issues

| Error | Solution |
| ----- | ---------- |
| `python is not recognized` | Add Python to PATH, or use `py` instead of `python` |
| `pip is not recognized` | Reinstall Python with "Add to PATH" checked |
| `docker: command not found` | Install Docker Desktop and restart terminal |
| `Permission denied` | Run PowerShell as Administrator |
| `Port 6333 in use` | Stop other Qdrant instances or change port |

### Quick Reference: Windows ↔ Unix Commands

| macOS/Linux | Windows PowerShell |
| ------------ | ------------------- |
| `python3` | `python` |
| `pip install` | `pip install` |
| `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| `cp file1 file2` | `copy file1 file2` |
| `/path/to/file` | `C:\path\to\file` |
| `curl http://localhost:8000` | `curl.exe http://localhost:8000` |
| `ls -la` | `dir` |

---

## 🚀 Setting Up Qdrant (Vector Database)

Qdrant is required for the vector embeddings memory. Choose one method below:

### Option A: Docker (Recommended)

1. **Install Docker** from https://www.docker.com/products/docker-desktop/

2. **Run Qdrant container:**
   ```bash
   # macOS/Linux terminal:
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
   
   # Windows PowerShell:
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
   ```

3. **Verify it's running:**
   ```bash
   docker ps
   # macOS/Linux:
   curl http://localhost:6333
   # Windows (may need curl.exe):
   curl.exe http://localhost:6333
   ```

4. **To stop/start later:**
   ```bash
   docker stop qdrant
   docker start qdrant
   ```

### Option B: Native Installation (Linux/macOS)

1. **Download Qdrant:**
   ```bash
   # macOS (download binary from GitHub)
   curl -LO https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-apple-darwin.tar.gz
   tar -xzf qdrant-x86_64-apple-darwin.tar.gz
   
   # Linux
   curl -LO https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
   tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
   ```

2. **Run Qdrant:**
   ```bash
   ./qdrant
   ```

3. Qdrant will start on `http://localhost:6333`

### Option C: Windows (Without Docker)

**Option 1: Use WSL2**
Install Windows Subsystem for Linux, then follow Linux instructions above.

**Option 2: Use Docker Desktop**
Enable WSL2 backend in Docker Desktop settings, then follow Docker instructions.

---

### Troubleshooting Qdrant

- **"Connection refused"**: Ensure Qdrant is running (`docker ps` or check process manager)
- **Port 6333 in use**: Stop other Qdrant instances or change port with `-p 6335:6333`
- **Memory issues**: Ensure your system has at least 4GB RAM available

If Qdrant is unavailable, the system will show a warning but may continue with limited functionality (the `MemoryEngine` will initialize with "no duplication" mode).

### About entities.json

The warning "Entities file not found" is **optional** and can be safely ignored. This file only enhances entity extraction (e.g., mapping slang to formal names). The system will work without it.

---

## 🐚 Setting Up OpenClaw (Required)

This project extends OpenClaw. You need the base installation:

### Option A: From Source

1. **Clone OpenClaw:**
   ```bash
   # macOS/Linux
   git clone https://github.com/openclaw/openclaw.git ~/openclaw
   cd ~/openclaw

   # Windows (in WSL2 or PowerShell with Git)
   git clone https://github.com/openclaw/openclaw.git $env:USERPROFILE\openclaw
   cd $env:USERPROFILE\openclaw
   ```

2. **Create environment and install:**
   ```bash
   # macOS/Linux
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .

   # Windows PowerShell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e .
   ```

3. **Verify installation:**
   ```bash
   openclaw --version
   ```

### Option B: Using pip

```bash
pip install openclaw
```

### Configure OpenClaw to Use This Workspace

After installing OpenClaw, point it to this Jarvis-OSS workspace:

```bash
# The gateway runs on localhost:8000
# Point OpenClaw to use our custom gateway
# (See OpenClaw docs for workspace configuration)

# Quick start - tell OpenClaw to use this workspace:
openclaw start --workspace /path/to/Jarvis-OSS/workspace

# Windows (PowerShell):
openclaw start --workspace C:\path\to\Jarvis-OSS\workspace
```

---

## 📱 Setting Up WhatsApp (Optional)

To chat with Jarvis via WhatsApp, you have two options:

### Option A: Use OpenClaw + Custom Gateway (Recommended)

This requires careful setup to avoid port conflicts:

1. **First, start your Jarvis gateway (Terminal 1):**
   ```bash
   cd Jarvis-OSS/workspace/sci_fi_dashboard
   python3 api_gateway.py  # Runs on port 8000
   ```

2. **Run onboard BUT skip the gateway (Terminal 2):**
   ```bash
   openclaw onboard
   ```
   - When asked about starting gateway: **Choose NO**
   - When asked about daemon: **Choose NO**
   - Just configure the WhatsApp channel credentials

3. **Start OpenClaw pointing to YOUR gateway:**
   ```bash
   openclaw start --workspace /path/to/Jarvis-OSS/workspace
   ```
   This tells OpenClaw to forward messages to your custom gateway instead of starting its own.

### Option B: Test Without WhatsApp First (Easier!)

Start with just curl commands to test everything works:

```bash
# Terminal 1: Start Jarvis
cd Jarvis-OSS/workspace/sci_fi_dashboard
python3 api_gateway.py

# Terminal 2: Test with curl
curl -X POST http://localhost:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

Once confirmed working, then add WhatsApp later with `openclaw onboard`.

---

### ⚠️ Port Conflict Warning

| Port | What Uses It |
|------|-------------|
| 8000 | Jarvis-OSS api_gateway.py (YOUR custom gateway) |
| 8000 | OpenClaw default gateway |

**Never run both gateways on the same port!** Always make sure only ONE is running on 8000.

---

## 1. Installation: The Clean Integration

This section provides step-by-step instructions for obtaining free API keys from various AI providers. Each platform has different registration processes, rate limits, and capabilities.

---

### Google Gemini (AI Studio) — Recommended Starting Point

**Best for:** General chat, quick responses, multimodal tasks

1. **Navigate to Google AI Studio:**
   Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

2. **Sign in with your Google account** (Gmail or any Google account)

3. **Click "Get API Key"** — you may need to create a new project first

4. **Select "Create API key in new project"** (recommended) or select an existing project

5. **Copy your API key** — it will start with `AIza...`

6. **Add to your `.env` file:**
   ```
   GEMINI_API_KEY=AIza...
   ```

**Free Tier Limits:**
- 15 RPM (requests per minute)
- 1,500 TPM (tokens per minute)
- No credit card required
- Models available: Gemini 2.0 Flash, Gemini 1.5 Flash, Gemini 1.5 Pro

**Note:** Google provides generous free limits that reset continuously. This is the easiest free key to obtain and works well for casual chat routing.

---

### Groq — Fastest Free Inference

**Best for:** High-speed inference, Llama/Mixtral models

1. **Navigate to Groq Console:**
   Go to [https://console.groq.com](https://console.groq.com)

2. **Sign up** using one of these methods:
   - Email + password
   - GitHub account
   - Google account

3. **Verify your email** if signing up with email

4. **Navigate to API Keys** section in the left sidebar

5. **Click "Create API Key"**

6. **Name your key** (e.g., "Jarvis-OSS")

7. **Copy your API key** — it will start with `gsk_...`

8. **Add to your `.env` file:**
   ```
   GROQ_API_KEY=gsk_...
   ```

**Free Tier Limits:**
- Thousands of tokens per minute, refreshed daily
- No credit card required
- Models available: Llama 3.3 70B, Mixtral 8x7B, Gemma 2 9B, and more
- Extremely fast inference (Groq's specialty)

**Note:** Groq is known for industry-leading inference speed. Excellent for the "casual chat" routing in the MoA architecture.

---

### Hugging Face — Open Source Models

**Best for:** Open-source models, embeddings, no-cost experimentation

1. **Navigate to Hugging Face:**
   Go to [https://huggingface.co](https://huggingface.co)

2. **Sign up** (free account)

3. **Navigate to Settings → Access Tokens**

4. **Click "Create new token"**

5. **Select permissions:** "Read" is sufficient for API access

6. **Copy your token**

7. **Add to your `.env` file:**
   ```
   HF_TOKEN=hf_...
   ```

**Free Tier Limits:**
- Free Inference API: Limited daily usage
- Spaces: 2vCPU hours/month
- No credit card required
- Models available: Llama variants, Mistral, Qwen, CodeLlama, and thousands of others

**Note:** For production API usage beyond free limits, consider upgrading to Pro ($9/month). The free tier is excellent for testing.

---

### DeepSeek — Advanced Reasoning

**Best for:** Complex reasoning tasks, coding, math

1. **Navigate to DeepSeek Platform:**
   Go to [https://platform.deepseek.com](https://platform.deepseek.com)

2. **Sign up** with email or OAuth (GitHub/Google)

3. **Verify your email** if applicable

4. **Go to API Keys** section

5. **Create a new API key**

6. **Copy your key**

7. **Add to your `.env` file:**
   ```
   DEEPSEEK_API_KEY=sk-...
   ```

**Free Tier Limits:**
- Offers free credits for new accounts (amount varies)
- Competitive pricing after credits
- Models available: DeepSeek V3, DeepSeek R1

**Note:** DeepSeek R1 is particularly notable for reasoning capabilities comparable to OpenAI o1, at much lower cost.

---

### OpenAI — Limited Free Access

**Best for:** GPT-3.5 access, legacy support

1. **Navigate to OpenAI Platform:**
   Go to [https://platform.openai.com](https://platform.openai.com)

2. **Sign up** with email, or use GitHub/Google/Microsoft account

3. **Complete account verification**

4. **Navigate to API Keys** section

5. **Click "Create new secret key"**

6. **Copy your key** — it will start with `sk-...`

7. **Add to your `.env` file:**
   ```
   OPENAI_API_KEY=sk-...
   ```

**Free Tier Limits (2026):**
- Extremely limited: 3 requests per minute
- Restricted to GPT-3.5 Turbo only
- **Note:** Free trial credits were discontinued in mid-2025. New accounts receive no automatic free credits.
- To unlock full API access, you must add a payment method (minimum $5 credit purchase)

**Recommendation:** If you need OpenAI access, the $5 minimum credit is the most cost-effective entry point. Otherwise, use Google Gemini or Groq for free access.

---

### Anthropic (Claude) — No Free Tier

**Best for:** High-quality coding, complex reasoning

1. **Navigate to Anthropic Console:**
   Go to [https://console.anthropic.com](https://console.anthropic.com)

2. **Sign up** with email

3. **Wait for account approval** (may be required depending on region)

4. **Add payment method** — Anthropic does not offer a free tier as of 2026

5. **Create API key** once account is active

6. **Add to your `.env` file:**
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

**Note:** Anthropic does not provide a free tier. You must add a credit card. However, new accounts often receive $5-10 in free credits to start.

---

### Ollama — 100% Local & Free

**Best for:** Complete privacy, offline use, no API costs

Ollama runs models entirely on your local machine — no API keys or internet required.

1. **Download Ollama:**
   Go to [https://ollama.com](https://ollama.com) and install for your OS

2. **Run a model:**
   ```bash
   ollama run llama3
   # or
   ollama run mistral
   # or
   ollama run codellama
   ```

3. **Configure in `.env`:**
   ```
   OLLAMA_BASE_URL=http://localhost:11434
   WINDOWS_PC_IP=127.0.0.1
   ```

**Models Available:**
- Llama 3, 3.1, 3.2
- Mistral
- CodeLlama
- Phi3
- Gemma 2
- And many others

**Note:** No API costs, complete privacy. However, requires local GPU/CPU resources.

---

### Summary: Recommended Free Setup

For a complete free MoA setup without spending any money:

| Task Type | Provider | Model | Env Variable |
|-----------|----------|-------|--------------|
| Casual Chat | Groq | Llama 3.3 70B | `GROQ_API_KEY` |
| Coding | Groq | Llama 3.3 70B | `GROQ_API_KEY` |
| Analysis | Google Gemini | Gemini 2.0 Flash | `GEMINI_API_KEY` |
| Privacy/Offline | Ollama | Llama3/Mistral | `OLLAMA_BASE_URL` |

Set all three keys in your `.env` file for full MoA functionality at zero cost.

---

### Troubleshooting API Key Issues

- **"401 Unauthorized"**: Double-check your API key is correct and properly set in `.env`. Restart the gateway after modifying `.env`.
- **"429 Too Many Requests"**: You've hit rate limits. Wait a minute or switch to a different provider.
- **"Quota Exceeded"**: You've used your free allocation. Wait for reset or switch providers.
- **Key not loading**: Ensure no spaces around `=` in your `.env` file. Use quotes if values contain special characters.

---

*Last updated: February 2026. API limits and offerings change frequently. Verify current limits on each provider's documentation.*
---

## 2. API Keys & The "Budget" MoA

Copy the environment template:
```bash
# macOS/Linux:
cp .env.example .env

# Windows PowerShell:
copy .env.example .env
```

### Understanding Your .env File

The `.env` file contains all the settings for your Jarvis. Here's what you need to know:

**Required:**
```bash
# Get a free key from https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIza...  

# Any random string (e.g., "my-secret-token-12345")
OPENCLAW_GATEWAY_TOKEN=your-random-string
```

**Optional (but recommended):**
```bash
# Get a free key from https://console.groq.com
GROQ_API_KEY=gsk_...
```

> **💡 Important:** After editing `.env`, you must restart the gateway for changes to take effect.

**Required Environment Variables:**
- `OPENCLAW_GATEWAY_TOKEN` — **Required.** Set a strong random string for API authentication.
- `OPENCLAW_ENV_PATH` — Path to your `.env` file (auto-detected by default)
- `API_BIND_HOST` — Server bind address (default: `127.0.0.1` for localhost)
- `CORS_ORIGINS` — Comma-separated list of allowed origins (default: `http://localhost:3000`)
- `LLM_SAFETY_LEVEL` — Safety threshold for LLM content filtering (default: `BLOCK_NONE`)

**How many API keys do you need?**
The full "Mixture of Agents" (MoA) architecture is designed to route requests to the best available models (e.g., Anthropic Claude for coding, Gemini Pro for analysis, Gemini Flash for casual chat).

*   **The Single-Key Route:** Don't want to manage multiple keys? You only *need* one! Simply provide a single API key (like `GEMINI_API_KEY` or `OPENAI_API_KEY`) and set the rest to empty. The router will gracefully fall back to your available model for all tasks.
*   **The Free MoA Route:** If you want true Mixture of Agents without burning money, leverage OpenClaw's free credits! You can use the `google-antigravity` provider to route tasks across premium models for free (e.g. `google-antigravity/gemini-3-flash`, `google-antigravity/claude-opus-4-6-thinking`).

**100% Private / Local Deployment (The Vault)**
If you are deeply concerned about privacy and want zero cloud leakage, this architecture is fully ready to run completely offline using Ollama:
1. Don't set any Cloud API keys in your `.env`.
2. Ensure you have [Ollama](https://ollama.com/) running locally (e.g., `ollama run llama3`).
3. Set your `WINDOWS_PC_IP` in `.env` to your Ollama server IP (use `127.0.0.1` if it's on the same machine).
4. Open `workspace/sci_fi_dashboard/api_gateway.py`. Scroll down to the routing block (the `if/elif` statements) and simply replace the cloud function calls like `await call_gemini_flash(...)` with your local function: `await call_local_spicy(full_prompt)`. The gateway will now push *every single thought* through your private local node!

*Edit `.env` and configure accordingly.*

## 3. Customizing the Persona (CRITICAL)

The routing logic checks for usernames to trigger specific personas like `brother` or `caring PA`. You must alter this to serve you.
**Read [SETUP_PERSONA.md](SETUP_PERSONA.md) to correctly adapt Jarvis's soul to your life.**

## 4. Google OAuth Token Migration

If you previously used Gmail/Calendar integration, delete your old `.pickle` token files. The system now uses JSON for secure serialization. Re-run `python workspace/scripts/setup_native_auth.py` to generate new tokens.

## 5. Booting the Core Gateway

This project intercepts and routes OpenClaw traffic through a custom FastAPI gateway.

**Terminal 1: The Core API Gateway (FastAPI)**
Start the custom gateway/router:
```bash
# macOS/Linux:
source .venv/bin/activate
cd workspace/sci_fi_dashboard
python3 api_gateway.py

# Windows PowerShell:
.venv\Scripts\Activate.ps1
cd workspace\sci_fi_dashboard
python api_gateway.py
```
*(The gateway runs on localhost:8000 by default. If OPENCLAW_GATEWAY_TOKEN is not set, the server will fail to start.)*

**API Authentication:**
All sensitive endpoints (`/chat`, `/chat/the_creator`, `/chat/the_partner`, `/persona/rebuild`, `/ingest`, `/add`, `/query`) require authentication. Include the header `x-api-key: YOUR_OPENCLAW_GATEWAY_TOKEN` in requests.

**Example with authentication (macOS/Linux):**
```bash
curl -X POST http://localhost:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_OPENCLAW_GATEWAY_TOKEN" \
  -d '{"message": "Hello!"}'
```

**Example with authentication (Windows PowerShell):**
```powershell
curl.exe -X POST http://localhost:8000/chat/the_creator -H "Content-Type: application/json" -H "x-api-key: YOUR_OPENCLAW_GATEWAY_TOKEN" -d "{\"message\": \"Hello!\"}"
```

**Terminal 2: Pointing OpenClaw to Your Workspace**
Now, run your vanilla OpenClaw CLI, but tell it to use this custom downloaded folder as its workspace, and point it to the proxy gateway!

```bash
openclaw start --workspace /path/to/where/you/cloned/Jarvis-OSS/workspace 
```
*(Alternatively, configure OpenClaw globally to hit your `localhost:8000` custom endpoint proxy instead of the default gateway).*
---

## ✅ First Run Checklist

Before starting, make sure you've completed these steps:

- [ ] **Git** installed and working
- [ ] **Python** installed (version 3.10+)  
- [ ] **Docker Desktop** installed and running (the Docker icon in your taskbar should be green)
- [ ] **Cloned** the Jarvis-OSS repository
- [ ] **Created** the `.env` file from `.env.example`
- [ ] **Added** at least one API key to `.env`
- [ ] **Set** `OPENCLAW_GATEWAY_TOKEN` in `.env`
- [ ] **Installed** Python dependencies (`pip install -r requirements.txt`)
- [ ] **Started** Qdrant (`docker run -d --name qdrant -p 6333:6333 qdrant/qdrant`)
- [ ] **Optional:** Ran `openclaw onboard` for WhatsApp/advanced features

> **Note:** The `memory.db` database file will be created automatically when you first run the gateway. You don't need to create it manually!

### Starting the System

**Terminal 1 - Start the Gateway:**
```bash
cd Jarvis-OSS
source .venv/bin/activate  # macOS/Linux
# or: .venv\Scripts\Activate.ps1  # Windows PowerShell
cd workspace/sci_fi_dashboard
python3 api_gateway.py  # or: python api_gateway.py (Windows)
```

If successful, you should see:
```
✅ MemoryEngine initialized
✅ Gateway running on http://localhost:8000
```

**Terminal 2 - Start OpenClaw:**
```bash
openclaw start --workspace /path/to/Jarvis-OSS/workspace
```

### How to Test It

Once everything is running, test the system:

```bash
# Test health endpoint
curl http://localhost:8000/health

# Send a test message (macOS/Linux)
curl -X POST http://localhost:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! This is a test."}'

# Send a test message (Windows PowerShell - single line)
curl.exe -X POST http://localhost:8000/chat/the_creator -H "Content-Type: application/json" -d "{\"message\": \"Hello! This is a test.\"}"
```

### What If It Doesn't Work?

1. **Check Docker is running** - Look for the Docker icon in your taskbar/menubar
2. **Check Qdrant** - Run `docker ps` and make sure qdrant is listed
3. **Check your .env file** - Make sure API keys are correct and saved
4. **Check the error messages** - Read what's printed in the terminal

---

### Need Help?

- **GitHub Issues:** https://github.com/UpayanGhosh/Jarvis-OSS/issues
- **Check logs:** Look at what the terminal outputs for error messages
- **Common fixes:** Restart Docker, restart the gateway, check your .env file

---

You now have a multi-model, RAG-enabled Digital Organism running locally. 

**Happy chatting! 🤖**
