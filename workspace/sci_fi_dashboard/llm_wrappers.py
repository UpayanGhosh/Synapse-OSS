"""LLM call wrappers and traffic cop routing."""
import logging
import os
import re

from sci_fi_dashboard import _deps as deps

logger = logging.getLogger(__name__)

WINDOWS_PC_IP = os.environ.get("WINDOWS_PC_IP", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def call_local_spicy(prompt: str) -> str:
    """LOCAL_SPICY (The Vault): routes to 'vault' role in model_mappings."""
    print("[HOT] Calling LOCAL_SPICY (The Vault) via SynapseLLMRouter 'vault' role...")
    messages = [{"role": "user", "content": prompt}]
    return await deps.synapse_llm_router.call("vault", messages, temperature=0.8, max_tokens=2000)


async def call_or_fallback(prompt: str) -> str:
    """OR_FALLBACK: casual role via SynapseLLMRouter (openrouter fallback handled by Router)."""
    print("[REFRESH] Calling OR_FALLBACK via SynapseLLMRouter...")
    messages = [{"role": "user", "content": prompt}]
    return await deps.synapse_llm_router.call("casual", messages)


async def call_gemini_flash(
    input_messages: list, temperature: float = 0.7, max_tokens: int = 500
) -> str:
    """AG_CASUAL / TRAFFIC COP: routes to 'casual' role in model_mappings."""
    return await deps.synapse_llm_router.call("casual", input_messages, temperature, max_tokens)


async def call_ag_code(messages: list) -> str:
    """AG_CODE (The Hacker): routes to 'code' role in model_mappings."""
    print("[CMD] Routing to THE HACKER (code role)...")
    return await deps.synapse_llm_router.call("code", messages, temperature=0.2, max_tokens=1000)


async def call_ag_oracle(messages: list) -> str:
    """AG_ORACLE (The Architect): routes to 'analysis' role in model_mappings."""
    print("[BLDG] Calling The Architect (analysis role)...")
    return await deps.synapse_llm_router.call(
        "analysis", messages, temperature=0.7, max_tokens=1500
    )


async def call_ag_review(messages: list) -> str:
    """AG_REVIEW (The Philosopher): routes to 'review' role in model_mappings."""
    print("[THINK] Calling The Philosopher (review role)...")
    return await deps.synapse_llm_router.call(
        "review", messages, temperature=0.7, max_tokens=1500
    )


async def translate_banglish(text: str) -> str:
    """Translate Banglish -> English via SynapseLLMRouter (translate role)."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a translator. Translate Romanized Bengali (Banglish) "
                "to English. OUTPUT ONLY ENGLISH."
            ),
        },
        {"role": "user", "content": text},
    ]
    try:
        return await deps.synapse_llm_router.call("translate", messages)
    except Exception as e:
        print(f"[WARN] Translation failed: {e}")
        return text


# --- Routing Logic ---

# Maps dual-cognition response_strategy -> traffic-cop classification.
# When a match exists we skip the traffic-cop LLM call (~50 % of messages).
STRATEGY_TO_ROLE: dict[str, str] = {
    "acknowledge": "CASUAL",
    "support": "CASUAL",
    "celebrate": "CASUAL",
    "redirect": "CASUAL",
    "challenge": "ANALYSIS",
    "quiz": "ANALYSIS",
}


async def route_traffic_cop(user_message: str) -> str:
    """TRAFFIC COP: Classifies message as CASUAL, CODING, ANALYSIS, or REVIEW."""
    system = (
        "Classify this message. Reply with EXACTLY ONE WORD: "
        "CASUAL, CODING, ANALYSIS, or REVIEW.\n\n"
        "- CODING: Write code, debug, script, API, python.\n"
        "- ANALYSIS (Synthesis/Data): Summarize logs, explain history, "
        "deep dive, data aggregation. (Use Gemini Pro Context).\n"
        "- REVIEW (Critique/Judgment): Grade this, find flaws, audit, "
        "critique logic, opinion. (Use Claude Opus nuance).\n"
        "- CASUAL: Chat, greetings, daily life, simple questions."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]
    try:
        # Use Flash for speed; Increase tokens for thinking
        resp = await call_gemini_flash(messages, temperature=0.0, max_tokens=100)
        decision = resp.strip().upper()
        # Clean up punctuation
        decision = re.sub(r"[^A-Z]", "", decision)
        print(f"[SIGNAL] Traffic Cop: {decision}")
        return decision
    except Exception:
        return "CASUAL"
