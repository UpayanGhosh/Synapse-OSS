import random

NARRATIVE_MAP = {
    "POST /api/send_email": [
        ("📨 Crafting response to quarterly report inquiry...", "Analyzing recipient sentiment..."),
        ("⚡ Dispatching urgent communications...", "Routing through encrypted nodes..."),
    ],
    "SCRAPE: news_source": [
        ("🔍 Diving into archives...", "Hunting for AI breakthroughs and breakthroughs..."),
        ("🎯 Scanning global networks...", "Aggregating real-time data streams..."),
    ],
    "PROCESS: analytics": [
        ("🧠 Crunching performance numbers...", "Identifying latent patterns..."),
        ("📊 Synthesizing data points...", "Generating predictive models..."),
    ],
    "SYSTEM: backup": [
        ("🛡️ Securing digital assets...", "Fragmenting data for redundancy..."),
        ("💾 Initializing cloud backup...", "Verifying integrity of 3 repositories..."),
    ],
    "ERROR: timeout": [
        ("⚠️ Connection stumbled...", "Retrying with exponential backoff..."),
        ("🚫 Node unreachable...", "Rerouting traffic through secondary gateway..."),
    ],
    "MEMORY: search": [
        ("🧠 Deep searching context...", "Recalling relevant nodes and threads..."),
        ("🔍 Querying Vector DB...", "Filtering by semantic similarity..."),
    ],
    "SYSTEM: thinking": [
        ("💭 Agent in deep thought...", "Generating multi-step reasoning plan..."),
        ("⚡ High-entropy analysis...", "Optimizing decision tree..."),
    ],
    "sentiment_logs": [
        ("🧠 Analyzing emotional subtext...", "Updating relationship state..."),
        ("⚖️ Balancing logic vs empathy...", "Sentiment score calculated..."),
    ],
    "language_nuance": [
        ("🗣️ Refining Banglish dialect...", "Parsing slang and context..."),
        ("📖 Updating vocabulary...", "Nuance adjustment complete..."),
    ],
    "growth_log": [
        ("🌱 Distilling new insights...", "Internalizing human behavior..."),
        ("📈 Self-optimization sequence...", "Behavioral patterns updated..."),
    ],
}


def translate_log_to_narrative(technical_log: str):
    for key, options in NARRATIVE_MAP.items():
        if key in technical_log:
            narrative, sub = random.choice(options)
            return narrative, sub

    # Default fallbacks
    return f"⚙️ Executing: {technical_log}", "Monitoring system impact..."
