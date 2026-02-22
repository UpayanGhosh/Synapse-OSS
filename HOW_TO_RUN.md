# 🚀 How to Run the Digital Organism (Jarvis-OSS)

This repository is a deeply customized, modular RAG system built on top of the incredible **OpenClaw** platform. Before diving in, please read the [Manifesto (README.md)](README.md) to understand what this system does and why it was built.

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
git clone https://github.com/YOUR_GIT_HUB_NAME/Jarvis-OSS.git
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
# Make sure to install FastAPI, uvicorn, httpx, and any other dependencies listed in the main scripts.
```

## 2. API Keys & The "Budget" MoA

Copy the environment template:
```bash
cp .env.example .env
```

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

## 4. Booting the Core Gateway

This project intercepts and routes OpenClaw traffic through a custom FastAPI gateway.

**Terminal 1: The Core API Gateway (FastAPI)**
Start the custom gateway/router:
```bash
source .venv/bin/activate
cd workspace/sci_fi_dashboard
python3 api_gateway.py
```
*(The gateway normally runs on localhost:8000)*

**Terminal 2: Pointing OpenClaw to Your Workspace**
Now, run your vanilla OpenClaw CLI, but tell it to use this custom downloaded folder as its workspace, and point it to the proxy gateway!

```bash
openclaw start --workspace /path/to/where/you/cloned/Jarvis-OSS/workspace 
```
*(Alternatively, configure OpenClaw globally to hit your `localhost:8000` custom endpoint proxy instead of the default gateway).*

---
You now have a multi-model, RAG-enabled Digital Organism running locally. 
