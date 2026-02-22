# JARVIS Phoenix v3 — Mermaid Architecture Diagram

> **How to use this with Figma:**
> 1. Install the [Mermaid to Figma plugin](https://www.figma.com/community/plugin/1150536131435213601/mermaid).
> 2. Copy the entire code block below (excluding the triple backticks).
> 3. Paste it into the plugin and hit Generate.

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': 'transparent', 'primaryTextColor': '#ffffff', 'primaryBorderColor': '#ffffff', 'lineColor': '#ffffff', 'textColor': '#ffffff', 'nodeBorder': '#ffffff', 'mainBkg': 'transparent', 'clusterBkg': 'transparent', 'clusterBorder': '#aaaaaa'}}}%%
graph TD
    %% --- SECTION 1: INGRESS (LEFT) ---
    subgraph Inputs ["User Inputs"]
        U1["📱 WhatsApp Webhook<br/>Node Gateway"]:::user
        U2["💻 OpenClaw CLI<br/>Proxy Request"]:::user
    end

    %% --- SECTION 2: ASYNC PIPELINE (LEFT-CENTER) ---
    subgraph Async_Pipeline ["Async Gateway Pipeline"]
        FG{"🛡️ FloodGate<br/>Batch Window 3s"}:::async
        DD["🔁 MessageDeduplicator<br/>5-min window"]:::async
        Q["📦 TaskQueue<br/>max 100"]:::async
        W["⚙️ MessageWorker<br/>2 concurrent"]:::async
        
        FG --> DD
        DD --> Q
        Q --> W
    end

    %% --- SECTION 3: CORE GATEWAY (CENTER) ---
    G(("🚀 Core API Gateway<br/>FastAPI / Uvicorn<br/>:8000")):::gateway

    %% Connections into Gateway
    U1 -->|"HTTP POST /webhook"| FG
    U2 -->|"CLI Proxy"| G
    W --> G

    %% --- SECTION 4: CONTEXT & MEMORY (ABOVE GATEWAY) ---
    %% Placed above to show they are background services supporting the Gateway
    subgraph Brain_Context ["🤖 Context Engine"]
        subgraph SBS ["Soul-Brain Sync — Persona Engine"]
            SBS_O["🎭 SBS Orchestrator"]:::sbs
            SBS_P["📋 Profile Manager"]:::sbs
            SBS_L["📝 Conversation Logger"]:::sbs
            SBS_RT["⚡ Realtime Processor"]:::sbs
            SBS_B["🔄 Batch Processor"]:::sbs
            SBS_C["🖊️ Prompt Compiler"]:::sbs
            
            SBS_O --- SBS_P
            SBS_P --- SBS_L
            SBS_O --- SBS_RT
            SBS_RT --- SBS_B
            SBS_O --- SBS_C
        end

        subgraph Cognitive_Memory ["💾 Cognitive Memory"]
            ME["🧠 Memory Engine<br/>Hybrid Retrieval v3"]:::memory
            M1["🗃️ SQLite Graph DB"]:::memory
            M2["🔷 Qdrant Vector DB"]:::memory
            RE["🏅 FlashRank Reranker"]:::memory
            
            ME <--> M1
            ME <--> M2
            ME --> RE
        end

        subgraph Dual_Cognition ["🧩 Dual Cognition"]
            DC["🧩 DualCognitionEngine"]:::memory
            TS["☣️ LazyToxicScorer"]:::memory
            DC --- TS
        end
    end

    %% Connections from Gateway to Context
    G <-->|"Inject Persona Context"| SBS_O
    G <-->|"Semantic + Graph Query"| ME
    G -->|"Tension Check"| DC


    %% --- SECTION 5: MOA AGENTS (RIGHT) ---
    subgraph Mixture_of_Agents ["🚀 Mixture of Agents"]
        TC{"🚦 Traffic Cop<br/>Intent Classifier"}:::moa
        
        subgraph Agents ["LLM Agents"]
            LLM1["🟢 Gemini 3 Flash<br/>(CASUAL)"]:::moa
            LLM2["💻 The Hacker<br/>(CODING)"]:::moa
            LLM3["🏛️ The Architect<br/>(ANALYSIS)"]:::moa
            LLM4["🧐 The Philosopher<br/>(REVIEW)"]:::moa
            LLM5["🌶️ The Vault<br/>(SPICY)"]:::local
        end

        TC -->|"CASUAL"| LLM1
        TC -->|"CODING"| LLM2
        TC -->|"ANALYSIS"| LLM3
        TC -->|"REVIEW"| LLM4
        TC -->|"SPICY"| LLM5
    end

    %% --- SECTION 6: RETURN PATH (RIGHT) ---
    G -->|"Classify Intent"| TC
    
    LLM1 -->|"Response + Stats"| G
    LLM2 -->|"Response + Stats"| G
    LLM3 -->|"Response + Stats"| G
    LLM4 -->|"Response + Stats"| G
    LLM5 -->|"Response + Stats"| G

    G -->|"Auto-Continue if cut-off"| AC["✂️ Auto-Continue"]:::async
    G -->|"Final Output"| Out["📨 Output"]:::user

    %% Link Output back to Inputs conceptually (or just show direction)
    AC -.->|"continues..."| G
````
