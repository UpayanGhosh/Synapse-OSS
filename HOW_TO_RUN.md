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
*   **Vanilla OpenClaw:** You must have the [vanilla OpenClaw project](https://github.com/openclaw/openclaw) installed on your machine.
*   **Qdrant Vector Database:** Native installation or docker container running on port `6333`.
*   *(Highly Optional)* A local machine running **Ollama** for "The Vault" (Zero-cloud local inference). **If you do not have Ollama, the system will seamlessly run entirely on the cloud models.**

*Note: This architecture is cross-platform! Because it is built on Python and OpenClaw, it runs on macOS, Linux, and Windows (preferably via WSL).*

## 1. Installation: The Clean Integration

You do **not** need to blindly replace your existing `.openclaw` folder. The safest and recommended way to integrate this project is by configuring your vanilla OpenClaw to point to this repository as its workspace.

1. Clone this repository anywhere on your machine:
```bash
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS
```
2. Create and activate the Python environment:
```bash
python3 -m venv .venv
# Mac/Linux:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\Scripts\Activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```

## 2A. Getting Free API Keys

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
cp .env.example .env
```

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
source .venv/bin/activate
cd workspace/sci_fi_dashboard
python3 api_gateway.py
```
*(The gateway runs on localhost:8000 by default. If OPENCLAW_GATEWAY_TOKEN is not set, the server will fail to start.)*

**API Authentication:**
All sensitive endpoints (`/chat`, `/chat/the_creator`, `/chat/the_partner`, `/persona/rebuild`, `/ingest`, `/add`, `/query`) require authentication. Include the header `x-api-key: YOUR_OPENCLAW_GATEWAY_TOKEN` in requests.

**Terminal 2: Pointing OpenClaw to Your Workspace**
Now, run your vanilla OpenClaw CLI, but tell it to use this custom downloaded folder as its workspace, and point it to the proxy gateway!

```bash
openclaw start --workspace /path/to/where/you/cloned/Jarvis-OSS/workspace 
```
*(Alternatively, configure OpenClaw globally to hit your `localhost:8000` custom endpoint proxy instead of the default gateway).*

---
You now have a multi-model, RAG-enabled Digital Organism running locally. 
