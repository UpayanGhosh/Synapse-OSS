import random

NARRATIVE_MAP = {
    "POST /api/send_email": [
        ("📨 Crafting response to quarterly report inquiry...", "Analyzing recipient sentiment..."),
        ("⚡ Dispatching urgent communications...", "Routing through encrypted nodes..."),
    ],
    "SCRAPE: news_source": [
        ("[SEARCH] Diving into archives...", "Hunting for AI breakthroughs and breakthroughs..."),
        ("🎯 Scanning global networks...", "Aggregating real-time data streams..."),
    ],
    "PROCESS: analytics": [
        ("[MEM] Crunching performance numbers...", "Identifying latent patterns..."),
        ("[STATS] Synthesizing data points...", "Generating predictive models..."),
    ],
    "SYSTEM: backup": [
        ("[GUARD] Securing digital assets...", "Fragmenting data for redundancy..."),
        ("💾 Initializing cloud backup...", "Verifying integrity of 3 repositories..."),
    ],
    "ERROR: timeout": [
        ("[WARN] Connection stumbled...", "Retrying with exponential backoff..."),
        ("🚫 Node unreachable...", "Rerouting traffic through secondary gateway..."),
    ],
    "MEMORY: search": [
        ("[MEM] Deep searching context...", "Recalling relevant nodes and threads..."),
        ("[SEARCH] Querying Vector DB...", "Filtering by semantic similarity..."),
    ],
    "SYSTEM: thinking": [
        ("💭 Agent in deep thought...", "Generating multi-step reasoning plan..."),
        ("⚡ High-entropy analysis...", "Optimizing decision tree..."),
    ],
    "sentiment_logs": [
        ("[MEM] Analyzing emotional subtext...", "Updating relationship state..."),
        ("⚖️ Balancing logic vs empathy...", "Sentiment score calculated..."),
    ],
    "language_nuance": [
        ("🗣️ Refining Banglish dialect...", "Parsing slang and context..."),
        ("[READ] Updating vocabulary...", "Nuance adjustment complete..."),
    ],
    "growth_log": [
        ("[NEW] Distilling new insights...", "Internalizing human behavior..."),
        ("[CHART] Self-optimization sequence...", "Behavioral patterns updated..."),
    ],
}


def translate_log_to_narrative(technical_log: str):
    for key, options in NARRATIVE_MAP.items():
        if key in technical_log:
            narrative, sub = random.choice(options)
            return narrative, sub

    # Default fallbacks
    return f"[EVAL] Executing: {technical_log}", "Monitoring system impact..."
