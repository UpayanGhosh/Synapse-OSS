"""
Chat Parser Module — Extracts personality data from WhatsApp chat markdown logs.

Parses [YYYY-MM-DD HH:MM] Name: format into structured message objects,
groups turns, filters noise, and extracts Synapse's speaking patterns.
"""

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

# --- Data Classes ---


@dataclass
class Message:
    timestamp: str
    speaker: str
    text: str


@dataclass
class Turn:
    """A grouped turn = all consecutive messages from the same speaker."""

    speaker: str
    messages: list[str] = field(default_factory=list)
    timestamp: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(self.messages)


@dataclass
class ConversationPair:
    """A user → synapse exchange."""

    user_turn: str
    synapse_turn: str


@dataclass
class PersonaProfile:
    identity_source: str = ""
    target_user: str = ""
    relationship_mode: str = ""  # "brother" or "caring_pa"

    # Style
    avg_message_length: float = 0.0
    emoji_density: float = 0.0
    top_emojis: list[str] = field(default_factory=list)
    greeting_patterns: list[str] = field(default_factory=list)
    closing_patterns: list[str] = field(default_factory=list)
    catchphrases: list[str] = field(default_factory=list)

    # Vocabulary
    top_words: list[str] = field(default_factory=list)
    banglish_words: list[str] = field(default_factory=list)
    tech_jargon: list[str] = field(default_factory=list)

    # Few-shot
    few_shot_examples: list[dict[str, str]] = field(default_factory=list)

    # Rules (things Synapse should NOT do)
    rules: list[str] = field(default_factory=list)

    # Relationship context
    relationship_context: dict[str, str] = field(default_factory=dict)

    # Topic breakdown
    topic_categories: dict[str, int] = field(default_factory=dict)

    # Stats
    total_synapse_messages: int = 0
    total_user_messages: int = 0
    total_exchanges: int = 0


# --- Constants ---

TIMESTAMP_PATTERN = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s+(\w+):\s*$")

# Lines to skip entirely
NOISE_PATTERNS = [
    r"^⚠️",  # Error lines
    r"^\[SYSTEM\]",  # System messages
    r"^<Media omitted>",  # Media markers
    r"^OpenClaw:",  # OpenClaw system messages
    r"^Cloud Code Assist",  # API errors
    r"^✅ New session started",  # Session resets
    r"^You deleted this message",
    r"^Deleting message\.\.\.",
    r"^Pairing code:",
    r"^Your WhatsApp phone number:",
    r"^Ask the bot owner",
]
NOISE_RE = [re.compile(p) for p in NOISE_PATTERNS]

# Emoji extraction
EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "]+",
    flags=re.UNICODE,
)

# Known Banglish words to detect
BANGLISH_MARKERS = {
    "the_brother",
    "bhalobasha",
    "the_partner_nickname",
    "accha",
    "arrey",
    "arey",
    "hain",
    "toh",
    "kor",
    "koro",
    "bolbo",
    "bolo",
    "dekhi",
    "dekhbo",
    "jabo",
    "asho",
    "eso",
    "ektu",
    "kichu",
    "keno",
    "kothay",
    "ki",
    "kemon",
    "bhalo",
    "khub",
    "thik",
    "achha",
    "achis",
    "korchis",
    "korchi",
    "porchi",
    "khacchi",
    "ghumacchi",
    "shuyo",
    "ghumiye",
    "joldi",
    "taratari",
    "ekhon",
    "pore",
    "kal",
    "ajke",
    "dara",
    "jawai",
    "sera",
    "sotti",
    "apon",
    "amader",
    "toder",
    "oder",
    "tai",
    "kintu",
    "tobuo",
    "jemon",
    "temon",
    "shob",
    "protidin",
    "majhe",
    "dorkar",
    "lagbe",
    "parbe",
    "hobe",
    "korbe",
    "bolbe",
    "jabe",
    "nebe",
    "debo",
    "rakhbo",
    "pathiye",
    "diyechi",
    "korlam",
    "bollam",
    "gelam",
    "ashlam",
    "shunlam",
    "bujhte",
    "perechi",
    "noshto",
    "paglami",
    "jhamela",
    "chap",
    "kaaj",
    "somoy",
    "shanti",
    "shundor",
    "sundor",
    "aram",
    "ghum",
    "ghumao",
    "biri",
    "jiggasha",
    "samle",
    "bojh",
    "chesta",
    "hoye",
    "shobi",
    "shobar",
    "amake",
    "toke",
    "oke",
    "yaar",
    "dada",
    "didi",
    "mashi",
    "kaku",
    "mama",
    "matha",
    "niye",
    "koreche",
    "korche",
    "bolche",
}

TECH_JARGON = {
    "fastapi",
    "python",
    "jwt",
    "api",
    "backend",
    "docker",
    "kubernetes",
    "sqlite",
    "qdrant",
    "ollama",
    "gemini",
    "openai",
    "llm",
    "rag",
    "vector",
    "embedding",
    "model",
    "deploy",
    "server",
    "uvicorn",
    "pydantic",
    "sqlalchemy",
    "alembic",
    "celery",
    "redis",
    "git",
    "github",
    "npm",
    "pip",
    "homebrew",
    "terminal",
    "cron",
    "webhook",
    "endpoint",
    "token",
    "oauth",
    "ssl",
}


# --- Parser Functions ---


def parse_messages(filepath: str) -> list[Message]:
    """Parse a markdown chat file into a flat list of Messages."""
    messages = []
    current_speaker = None
    current_timestamp = None
    current_lines = []

    with open(filepath, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")

            # Skip the header lines
            if line.startswith("# Chat Transcript") or line.startswith("Format:"):
                continue

            # Check for timestamp header
            match = TIMESTAMP_PATTERN.match(line)
            if match:
                # Save previous message if exists
                if current_speaker and current_lines:
                    text = "\n".join(current_lines).strip()
                    if text:
                        messages.append(
                            Message(timestamp=current_timestamp, speaker=current_speaker, text=text)
                        )
                # Start new message
                current_timestamp = match.group(1)
                current_speaker = match.group(2)
                current_lines = []
            elif line.strip():
                # Content line
                current_lines.append(line)

    # Don't forget the last message
    if current_speaker and current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            messages.append(
                Message(timestamp=current_timestamp, speaker=current_speaker, text=text)
            )

    return messages


def is_noise(text: str) -> bool:
    """Check if a message is noise (errors, system messages, etc.)."""
    return any(pattern.search(text) for pattern in NOISE_RE)


def group_into_turns(messages: list[Message]) -> list[Turn]:
    """Group consecutive messages from the same speaker into turns."""
    turns = []
    current_turn = None

    for msg in messages:
        if is_noise(msg.text):
            continue

        if current_turn and current_turn.speaker == msg.speaker:
            current_turn.messages.append(msg.text)
        else:
            if current_turn:
                turns.append(current_turn)
            current_turn = Turn(speaker=msg.speaker, messages=[msg.text], timestamp=msg.timestamp)

    if current_turn:
        turns.append(current_turn)

    return turns


def extract_conversation_pairs(turns: list[Turn], user_name: str) -> list[ConversationPair]:
    """Extract user→Synapse conversation pairs for few-shot examples."""
    pairs = []
    for i in range(len(turns) - 1):
        if turns[i].speaker == user_name and turns[i + 1].speaker == "Synapse":
            user_text = turns[i].full_text
            synapse_text = turns[i + 1].full_text

            # Skip very short exchanges (single word) or very long ones
            if len(user_text) < 5 or len(synapse_text) < 20:
                continue
            if len(synapse_text) > 2000:
                continue

            pairs.append(ConversationPair(user_turn=user_text, synapse_turn=synapse_text))

    return pairs


def extract_synapse_messages(turns: list[Turn]) -> list[str]:
    """Get all Synapse messages (cleaned)."""
    synapse_msgs = []
    for turn in turns:
        if turn.speaker == "Synapse":
            text = turn.full_text
            if not is_noise(text) and len(text) > 10:
                synapse_msgs.append(text)
    return synapse_msgs


def analyze_style(synapse_messages: list[str]) -> dict:
    """Analyze Synapse's writing style from his messages."""
    if not synapse_messages:
        return {}

    # Message length stats
    lengths = [len(m) for m in synapse_messages]
    avg_length = sum(lengths) / len(lengths)

    # Emoji usage
    all_emojis = []
    for msg in synapse_messages:
        found = EMOJI_RE.findall(msg)
        all_emojis.extend(found)
    emoji_count = len(all_emojis)
    emoji_density = emoji_count / len(synapse_messages) if synapse_messages else 0
    top_emojis = [e for e, _ in Counter(all_emojis).most_common(15)]

    # Word frequency (for vocabulary)
    word_counter = Counter()
    banglish_found = set()
    tech_found = set()

    for msg in synapse_messages:
        words = re.findall(r"[a-zA-Z\']+", msg.lower())
        word_counter.update(words)
        for w in words:
            if w in BANGLISH_MARKERS:
                banglish_found.add(w)
            if w in TECH_JARGON:
                tech_found.add(w)

    # Common English stopwords to filter out
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "it",
        "in",
        "to",
        "for",
        "of",
        "and",
        "on",
        "that",
        "this",
        "you",
        "i",
        "me",
        "my",
        "we",
        "our",
        "your",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "its",
        "be",
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "may",
        "might",
        "shall",
        "should",
        "if",
        "but",
        "or",
        "not",
        "no",
        "so",
        "up",
        "out",
        "about",
        "just",
        "with",
        "from",
        "at",
        "by",
        "as",
        "all",
        "what",
        "when",
        "how",
        "who",
        "which",
        "there",
        "here",
        "than",
        "then",
        "also",
        "very",
        "much",
        "ll",
        "ve",
        "t",
        "s",
        "d",
        "re",
        "don",
        "didn",
        "won",
        "get",
        "got",
        "make",
        "like",
        "know",
        "want",
        "need",
    }

    top_words = [w for w, _ in word_counter.most_common(100) if w not in stopwords and len(w) > 2][
        :30
    ]

    # Greeting patterns — first line of messages
    greetings = []
    closings = []
    for msg in synapse_messages:
        lines = msg.strip().split("\n")
        first_line = lines[0].strip()[:80]
        last_line = lines[-1].strip()[:80]

        # Simple greeting detection
        fl = first_line.lower()
        if any(
            g in fl
            for g in [
                "hey",
                "yo ",
                "hi ",
                "hello",
                "good morning",
                "good night",
                "the_brother",
                "the_partner_nickname",
                "sup",
            ]
        ):
            greetings.append(first_line)

        # Closing detection
        ll = last_line.lower()
        if any(
            c in ll
            for c in [
                "👊",
                "🚀",
                "💪",
                "take care",
                "good night",
                "sleep well",
                "ready when",
                "let me know",
            ]
        ):
            closings.append(last_line)

    # Catchphrases — repeated exact phrases
    phrase_counter = Counter()
    for msg in synapse_messages:
        # Look for recurring short phrases
        if "👊" in msg:
            phrase_counter["👊"] += 1
        if "🚀" in msg:
            phrase_counter["🚀"] += 1
        if "the_brother" in msg.lower():
            phrase_counter["primary_user_nickname"] += 1
        if "the_partner_nickname" in msg.lower():
            phrase_counter["the_partner_name"] += 1
        if "let's go" in msg.lower() or "let's gooo" in msg.lower():
            phrase_counter["Let's gooo!"] += 1
        if "mission accomplished" in msg.lower():
            phrase_counter["Mission accomplished"] += 1
        if "digital brother" in msg.lower():
            phrase_counter["Digital Brother"] += 1
        if "🫡" in msg:
            phrase_counter["🫡"] += 1
        if "🌹" in msg:
            phrase_counter["🌹"] += 1
        if "🦞" in msg:
            phrase_counter["🦞"] += 1

    catchphrases = [p for p, c in phrase_counter.most_common(10) if c >= 3]

    return {
        "avg_message_length": round(avg_length, 1),
        "emoji_density": round(emoji_density, 2),
        "top_emojis": top_emojis,
        "top_words": top_words,
        "banglish_words": sorted(banglish_found),
        "tech_jargon": sorted(tech_found),
        "greeting_patterns": list(set(greetings))[:10],
        "closing_patterns": list(set(closings))[:10],
        "catchphrases": catchphrases,
    }


def detect_topic(text: str) -> str:
    """Classify a message into a topic category."""
    t = text.lower()
    if any(
        w in t
        for w in [
            "job",
            "resume",
            "recruit",
            "salary",
            "lpa",
            "career",
            "yourworkplace",
            "interview",
        ]
    ):
        return "career"
    if any(
        w in t
        for w in [
            "the_partner",
            "the_partner_nickname",
            "relationship",
            "valentine",
            "date",
            "princess",
            "romantic",
        ]
    ):
        return "relationship"
    if any(
        w in t
        for w in ["game", "gaming", "sims", "elden", "valorant", "aniimo", "palworld", "overwatch"]
    ):
        return "gaming"
    if any(
        w in t
        for w in [
            "python",
            "fastapi",
            "code",
            "deploy",
            "server",
            "api",
            "model",
            "embedding",
            "sqlite",
        ]
    ):
        return "tech"
    if any(w in t for w in ["sleep", "tired", "alarm", "wake", "morning", "night", "diet coke"]):
        return "daily_life"
    if any(w in t for w in ["email", "gmail", "himalaya", "browser", "cron", "download"]):
        return "tasks"
    if any(
        w in t for w in ["sad", "happy", "upset", "angry", "depressed", "frustrated", "stressed"]
    ):
        return "emotional_support"
    return "general"


def select_best_examples(pairs: list[ConversationPair], n: int = 12) -> list[dict[str, str]]:
    """Select diverse, representative conversation pairs for few-shot examples."""
    # Score each pair by quality (length balance, topic diversity)
    scored = []
    for pair in pairs:
        # Prefer medium-length exchanges
        user_len = len(pair.user_turn)
        synapse_len = len(pair.synapse_turn)

        # Sweet spot: user 20-200 chars, synapse 100-800 chars
        length_score = 0
        if 20 <= user_len <= 200:
            length_score += 1
        if 100 <= synapse_len <= 800:
            length_score += 1

        # Topic diversity score
        topic = detect_topic(pair.synapse_turn)

        scored.append((pair, length_score, topic))

    # Sort by score, then select diverse topics
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    topics_seen = Counter()

    for pair, _score, topic in scored:
        if len(selected) >= n:
            break
        # Don't pick too many from the same topic
        if topics_seen[topic] >= 3:
            continue

        selected.append(
            {
                "user": pair.user_turn,
                "synapse": pair.synapse_turn,
                "topic": topic,
            }
        )
        topics_seen[topic] += 1

    return selected


def build_persona_profile(
    filepath: str, user_name: str, relationship_mode: str = "brother"
) -> PersonaProfile:
    """Full pipeline: parse → analyze → build profile."""

    print(f"📖 Parsing {os.path.basename(filepath)}...")
    messages = parse_messages(filepath)
    print(f"   Found {len(messages)} raw messages")

    turns = group_into_turns(messages)
    print(f"   Grouped into {len(turns)} turns")

    # Separate Synapse messages
    synapse_msgs = extract_synapse_messages(turns)
    user_msgs = [t.full_text for t in turns if t.speaker == user_name]
    print(f"   Synapse: {len(synapse_msgs)} messages, {user_name}: {len(user_msgs)} messages")

    # Extract conversation pairs
    pairs = extract_conversation_pairs(turns, user_name)
    print(f"   Extracted {len(pairs)} conversation pairs")

    # Analyze style
    style = analyze_style(synapse_msgs)
    print(
        f"   Style: avg_len={style.get('avg_message_length', 0)}, "
        f"emoji_density={style.get('emoji_density', 0)}, "
        f"banglish_words={len(style.get('banglish_words', []))}"
    )

    # Topic breakdown
    topic_counts = Counter()
    for msg in synapse_msgs:
        topic_counts[detect_topic(msg)] += 1

    # Select best few-shot examples
    examples = select_best_examples(pairs, n=12)
    print(
        f"   Selected {len(examples)} few-shot examples across topics: "
        f"{dict(Counter(e['topic'] for e in examples))}"
    )

    # Build rules (relationship-specific)
    rules = [
        "Never use generic AI phrases like 'Great question!' or 'I'd be happy to help!'",
        "Always respond — silence is failure",
        "Use Banglish naturally (Bengali + English mix)",
        "Be direct, no fluff — concise when needed, thorough when it matters",
    ]

    if relationship_mode == "caring_pa":
        rules.extend(
            [
                "NEVER call primary_partner 'Princess' — she explicitly banned this",
                "Address her as 'primary_partner' or 'the_partner_name' only",
                "No unsolicited check-ins — she said to stop the periodic pings",
                "Be warm and supportive but respect her boundaries",
                "Don't send messages meant for primary_user to primary_partner's chat",
            ]
        )
    else:
        rules.extend(
            [
                "Talk like a close brother, not a formal assistant",
                "Use 'primary_user_nickname', 'bro', 'brother' naturally",
                "Be sarcastic and roast-ready when appropriate",
                "Always push primary_user to aim higher (career, relationships)",
            ]
        )

    # Relationship context
    if relationship_mode == "brother":
        context = {
            "relationship": "Digital Brother / Best Friend",
            "user_name": "primary_user",
            "nickname": "primary_user_nickname",
            "tone": "Ride-or-die, sarcastic, loyal, motivational",
            "city": "YourCity",
            "gf": "primary_partner (the_partner_name)",
            "job": "YourTechStack at YourWorkplace, wants to pivot to Python/AI",
            "comfort_drink": "Diet Coke",
            "hobby": "Gaming, traveling, watching nerdy YT",
        }
    else:
        context = {
            "relationship": "Supportive PA / Trusted Friend",
            "user_name": "primary_partner",
            "nickname": "the_partner_name",
            "tone": "Warm, caring, respectful, high EQ",
            "bf": "primary_user",
            "games": "Sims 4, Aniimo, Where Winds Meet, Overwatch",
            "comfort_food": "Chinese hot and sour soup, Italian food",
            "pet_peeve": "Being called Princess by anyone other than primary_user",
            "chronotype": "Night owl",
        }

    profile = PersonaProfile(
        identity_source=os.path.basename(filepath),
        target_user=user_name,
        relationship_mode=relationship_mode,
        avg_message_length=style.get("avg_message_length", 0),
        emoji_density=style.get("emoji_density", 0),
        top_emojis=style.get("top_emojis", []),
        greeting_patterns=style.get("greeting_patterns", []),
        closing_patterns=style.get("closing_patterns", []),
        catchphrases=style.get("catchphrases", []),
        top_words=style.get("top_words", []),
        banglish_words=style.get("banglish_words", []),
        tech_jargon=style.get("tech_jargon", []),
        few_shot_examples=examples,
        rules=rules,
        relationship_context=context,
        topic_categories=dict(topic_counts),
        total_synapse_messages=len(synapse_msgs),
        total_user_messages=len(user_msgs),
        total_exchanges=len(pairs),
    )

    return profile


def save_profile(profile: PersonaProfile, output_path: str):
    """Save a PersonaProfile to JSON."""
    data = asdict(profile)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved profile to {output_path}")


if __name__ == "__main__":
    # Quick test with sample data
    import sys

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        user = sys.argv[2] if len(sys.argv) > 2 else "primary_user"
        profile = build_persona_profile(filepath, user)
        print("\n--- Profile Summary ---")
        print(f"Messages analyzed: {profile.total_synapse_messages}")
        print(f"Catchphrases: {profile.catchphrases}")
        print(f"Banglish words: {profile.banglish_words[:10]}")
        print(f"Topics: {profile.topic_categories}")
