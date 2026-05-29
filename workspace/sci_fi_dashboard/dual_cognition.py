"""
Dual-Stream Cognition Engine
Stream 1 (Present): What is the user saying RIGHT NOW?
Stream 2 (Memory):  What do I KNOW about this person and topic?
Merge:              Detect tension, alignment, or contradiction.
"""

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass, field

from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

logger = logging.getLogger("dual_cognition")


@dataclass
class PresentStream:
    """What the user is saying right now."""

    raw_message: str
    sentiment: str = "neutral"
    intent: str = "statement"
    topics: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    emotional_state: str = "calm"
    conversational_pattern: str = "single_turn"


@dataclass
class MemoryStream:
    """What I know from history."""

    relevant_facts: list = field(default_factory=list)
    relationship_context: str = ""
    graph_connections: str = ""
    affect_hints: str = ""
    contradictions: list = field(default_factory=list)


@dataclass
class CognitiveMerge:
    """The result of merging both streams."""

    thought: str = ""
    tension_level: float = 0.0
    tension_type: str = "none"
    response_strategy: str = "acknowledge"
    memory_insights: list = field(default_factory=list)
    suggested_tone: str = "warm"
    inner_monologue: str = ""
    contradictions: list = field(default_factory=list)


FAST_PHRASES = frozenset(
    [
        "hi",
        "hello",
        "hey",
        "ok",
        "thanks",
        "good morning",
        "good night",
        "bye",
        "hmm",
        "haha",
        "lol",
        "yes",
        "no",
        "yep",
        "nope",
        "sure",
        "cool",
        "nice",
        "wow",
        "damn",
    ]
)


class DualCognitionEngine:
    def __init__(self, memory_engine, graph, toxic_scorer=None, emotional_trajectory=None):
        self.memory = memory_engine
        self.graph = graph
        # toxic_scorer param kept for caller compatibility; unused in this module
        self.trajectory = emotional_trajectory

    def classify_complexity(self, message: str, history: list = None) -> str:
        """Zero-LLM complexity triage. Returns: 'fast' | 'standard' | 'deep'"""
        msg_lower = message.lower().strip()
        word_count = len(msg_lower.split())

        # FAST PATH: greetings, acknowledgments, single emojis, short phrases
        if msg_lower in FAST_PHRASES:
            return "fast"
        if word_count <= 3 and not re.search(r"[?!]", msg_lower):
            return "fast"

        # DEEP PATH: 2+ signals trigger deep reasoning
        deep_signals = 0

        if word_count > 60:
            deep_signals += 1
        sentence_count = len(re.split(r"[.!?]+", message.strip()))
        if sentence_count >= 3:
            deep_signals += 1

        contradiction_markers = [
            "but",
            "however",
            "actually",
            "didn't",
            "never",
            "that's not",
            "i don't think",
            "you're wrong",
        ]
        if any(m in msg_lower for m in contradiction_markers):
            deep_signals += 1

        emotional_markers = [
            # English
            "help",
            "stuck",
            "frustrated",
            "can't",
            "failed",
            "stressed",
            "scared",
            "angry",
            "depressed",
            "crying",
            "lonely",
            "hurt",
            "worried",
            "anxious",
            "miss",
            "confused",
            "upset",
            "sad",
            # Banglish — emotional states
            "miss korchi",
            "miss kori",
            "kharap",
            "dukkho",
            "kando",
            "ekla",
            "bhoy",
            "bhoy pacchi",
            "jhogra",
            "problem",
            "tension",
            "chinta",
            "kষti",
            "kষto",
            "tired",
            "please",
            "ki korbo",
            "ki korbi",
            "bujhte parchhi na",
            "mone hocche",
            "lagche",
            "kষমa",
            "sorry",
            "hurt korlo",
            "raga",
            "rag",
            "bhalobashi",
            "darkar",
            "dorkar",
            "thik nei",
            "thik nai",
            "valo nei",
            "bhalo nei",
            "valo na",
        ]
        if any(m in msg_lower for m in emotional_markers):
            deep_signals += 1

        ambiguity_markers = [
            # English
            "that thing",
            "what we",
            "you know",
            "remember when",
            # Banglish
            "mone ache",
            "mone achhe",
            "shei din",
            "shei ghotona",
            "oi kotha",
            "tui jantis",
            "tui janish",
            "bujhte parbi",
        ]
        if any(m in msg_lower for m in ambiguity_markers):
            deep_signals += 1

        if history and len(history) > 5:
            deep_signals += 1

        if deep_signals >= 2:
            return "deep"

        return "standard"

    async def think(
        self,
        user_message: str,
        chat_id: str,
        conversation_history: list = None,
        target: str = "the_creator",
        llm_fn=None,
        pre_cached_memory: dict = None,
        max_llm_calls: int | None = None,
    ) -> CognitiveMerge:
        """Main entry: routes through fast/standard/deep paths based on complexity."""

        try:
            complexity = self.classify_complexity(user_message, conversation_history)

            with contextlib.suppress(Exception):

                _get_emitter().emit(
                    "cognition.classify",
                    {
                        "complexity": complexity,
                        "word_count": len(user_message.split()),
                        "signals": [],
                    },
                )

            # FAST PATH: 0 LLM calls -- return minimal merge immediately
            if complexity == "fast":
                with contextlib.suppress(Exception):
                    _get_emitter().emit("cognition.fast_path", {"reason": "simple_message"})
                return CognitiveMerge(
                    tension_level=0.0,
                    tension_type="none",
                    response_strategy="acknowledge",
                    suggested_tone="warm",
                    inner_monologue="Simple message, no deep analysis needed.",
                )

            if max_llm_calls is not None and max_llm_calls <= 1:
                with contextlib.suppress(Exception):
                    _get_emitter().emit("cognition.single_call_mode", {"complexity": complexity})
                present = self._analyze_present_heuristic(user_message, conversation_history)
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "cognition.recall_start", {"from_cache": pre_cached_memory is not None}
                    )
                memory = await self._recall_memory(
                    user_message, chat_id, target, pre_cached_memory
                )
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "cognition.recall_done",
                        {
                            "fact_count": len(getattr(memory, "relevant_facts", [])),
                            "has_graph_context": bool(getattr(memory, "graph_connections", "")),
                        },
                    )
                merge = await self._merge_streams(
                    present,
                    memory,
                    target,
                    llm_fn,
                    use_cot=(complexity == "deep"),
                )
                if self.trajectory:
                    self.trajectory.record(merge, present.topics)
                return merge

            # STANDARD PATH: analyze + recall + merge (2 LLM calls)
            if complexity == "standard":
                with contextlib.suppress(Exception):
                    _get_emitter().emit("cognition.analyze_start", {})
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "cognition.recall_start", {"from_cache": pre_cached_memory is not None}
                    )
                present, memory = await asyncio.gather(
                    self._analyze_present(user_message, conversation_history, llm_fn),
                    self._recall_memory(user_message, chat_id, target, pre_cached_memory),
                )
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "cognition.analyze_done",
                        {
                            "sentiment": getattr(present, "sentiment", ""),
                            "intent": getattr(present, "intent", ""),
                            "emotional_state": getattr(present, "emotional_state", ""),
                            "topics": getattr(present, "topics", []),
                            "conversational_pattern": getattr(
                                present, "conversational_pattern", ""
                            ),
                        },
                    )
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "cognition.recall_done",
                        {
                            "fact_count": len(getattr(memory, "relevant_facts", [])),
                            "has_graph_context": bool(getattr(memory, "graph_connections", "")),
                        },
                    )
                with contextlib.suppress(Exception):
                    _get_emitter().emit("cognition.merge_start", {"use_cot": False})
                merge = await self._merge_streams(present, memory, target, llm_fn, use_cot=False)
                if self.trajectory:
                    self.trajectory.record(merge, present.topics)
                return merge

            # DEEP PATH: analysis + recall + CoT merge (2-3 LLM calls)
            # L-01: Removed _extract_search_intent — result was never used downstream.
            # Run both operations in parallel to save latency:
            # - present analysis (LLM call)
            # - memory recall using original message with pre-cached results (no LLM, fast)
            with contextlib.suppress(Exception):
                _get_emitter().emit("cognition.analyze_start", {})
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "cognition.recall_start", {"from_cache": pre_cached_memory is not None}
                )
            present, memory = await asyncio.gather(
                self._analyze_present(user_message, conversation_history, llm_fn),
                self._recall_memory(user_message, chat_id, target, pre_cached_memory),
            )
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "cognition.analyze_done",
                    {
                        "sentiment": getattr(present, "sentiment", ""),
                        "intent": getattr(present, "intent", ""),
                        "emotional_state": getattr(present, "emotional_state", ""),
                        "topics": getattr(present, "topics", []),
                        "conversational_pattern": getattr(present, "conversational_pattern", ""),
                    },
                )
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "cognition.recall_done",
                    {
                        "fact_count": len(getattr(memory, "relevant_facts", [])),
                        "has_graph_context": bool(getattr(memory, "graph_connections", "")),
                    },
                )

            # Step 3: CoT merge
            with contextlib.suppress(Exception):
                _get_emitter().emit("cognition.merge_start", {"use_cot": True})
            merge = await self._merge_streams(present, memory, target, llm_fn, use_cot=True)
            if self.trajectory:
                self.trajectory.record(merge, present.topics)
            return merge

        except Exception as e:
            logger.warning("Dual cognition failed: %s", e)
            return CognitiveMerge(
                inner_monologue="I'm having trouble thinking through this right now.",
                tension_level=0.0,
                response_strategy="acknowledge",
                suggested_tone="warm",
            )

    def _analyze_present_heuristic(
        self, message: str, history: list = None
    ) -> PresentStream:
        """Cheap foreground present-stream analysis used before a single merge call."""
        msg = str(message or "")
        msg_lower = msg.lower()
        present = PresentStream(raw_message=msg)

        negative_markers = (
            "annoyed",
            "angry",
            "pissed",
            "irritated",
            "frustrated",
            "anxious",
            "scared",
            "sad",
            "hurt",
            "stressed",
            "can't",
            "dumped",
            "unfair",
        )
        positive_markers = ("happy", "excited", "proud", "love", "great", "won", "finished")
        if any(marker in msg_lower for marker in negative_markers):
            present.sentiment = "negative"
        elif any(marker in msg_lower for marker in positive_markers):
            present.sentiment = "positive"

        if any(marker in msg_lower for marker in ("vent", "rant", "bitch", "pissed", "annoyed")):
            present.intent = "venting"
        elif "?" in msg:
            present.intent = "question"
        elif any(marker in msg_lower for marker in ("please", "help", "can you", "could you")):
            present.intent = "request"

        if any(marker in msg_lower for marker in ("anxious", "scared", "panic", "stressed")):
            present.emotional_state = "anxious"
        elif any(marker in msg_lower for marker in ("pissed", "angry", "irritated", "annoyed")):
            present.emotional_state = "angry"
        elif any(marker in msg_lower for marker in ("sad", "hurt", "lonely")):
            present.emotional_state = "vulnerable"
        elif any(marker in msg_lower for marker in ("happy", "excited", "proud")):
            present.emotional_state = "excited"

        topic_markers = {
            "work": ("work", "office", "demo", "boss", "cleanup", "project"),
            "relationships": ("crush", "date", "love", "mira", "relationship"),
            "sleep": ("sleep", "tired", "night"),
            "money": ("money", "budget", "shopping", "buy"),
        }
        for topic, markers in topic_markers.items():
            if any(marker in msg_lower for marker in markers):
                present.topics.append(topic)

        if history:
            present.conversational_pattern = "continuation"
        if any(marker in msg_lower for marker in ("but", "actually", "however", "even though")):
            present.conversational_pattern = "escalation"

        present.claims = [msg[:220]] if msg else []
        return present

    async def _analyze_present(
        self, message: str, history: list = None, llm_fn=None
    ) -> PresentStream:
        """Stream 1: Analyze current message with conversation context."""
        present = self._analyze_present_heuristic(message, history)

        if not llm_fn:
            return present

        # Inject last 3 messages as context for pattern detection
        recent_context = ""
        if history and len(history) > 0:
            last_3 = [
                m
                for m in (history or [])[-3:]
                if isinstance(m, dict) and "role" in m and "content" in m
            ]
            recent_context = "\n".join(f"{m['role']}: {m['content'][:100]}" for m in last_3)

        prompt = f"""Analyze this message IN CONTEXT. Return JSON only.

Recent conversation:
{recent_context if recent_context else "(no prior context)"}

Current message: "{message}"

Return:
{{
  "sentiment": "positive|negative|neutral",
  "intent": "question|statement|request|venting|bragging|deflecting",
  "claims": ["factual claims user is making"],
  "emotional_state": "calm|excited|defensive|vulnerable|evasive|guilty",
  "topics": ["key topics"],
  "conversational_pattern": "single_turn|continuation|topic_shift|callback|escalation"
}}

JSON only:"""

        try:
            result = await llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            text = result.strip()

            if "[THINKING]" in text:
                text = text.split("[/THINKING]")[-1].strip()

            if "```" in text:
                parts = text.split("```")
                if len(parts) > 1:
                    text = parts[1].replace("json", "").strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                present.sentiment = data.get("sentiment", "neutral")
                present.intent = data.get("intent", "statement")
                present.claims = data.get("claims", [])
                present.emotional_state = data.get("emotional_state", "calm")
                present.topics = data.get("topics", [])
                present.conversational_pattern = data.get("conversational_pattern", "single_turn")
        except Exception as e:
            logger.warning("Present stream analysis failed: %s", e)

        return present

    async def _recall_memory(
        self,
        message: str,
        chat_id: str,
        target: str,
        pre_cached_memory: dict = None,
    ) -> MemoryStream:
        """Stream 2: Query memory. Uses pre_cached_memory if available to avoid duplicate queries."""
        memory = MemoryStream()

        try:
            results = (
                pre_cached_memory
                if pre_cached_memory
                else self.memory.query(message, limit=5, with_graph=True)
            )
            memory.relevant_facts = [r["content"] for r in results.get("results", [])]
            memory.graph_connections = results.get("graph_context", "")
            memory.affect_hints = str(results.get("affect_hints", "") or "")
        except (KeyError, IndexError, ValueError) as e:
            logger.debug("Memory recall returned no results: %s", e)
        except Exception as e:
            logger.warning("Memory recall failed (database/connection error): %s", e)

        try:
            target_name = "primary_partner" if "the_partner" in target.lower() else "primary_user"
            memory.relationship_context = self.graph.get_entity_neighborhood(target_name)
        except Exception as e:
            # L-05: Log instead of silently dropping graph errors
            logger.debug("Graph neighborhood lookup failed: %s", e)

        return memory

    async def _merge_streams(
        self,
        present: PresentStream,
        memory: MemoryStream,
        target: str,
        llm_fn=None,
        use_cot: bool = False,
    ) -> CognitiveMerge:
        """Merge: compare present vs memory. CoT reasoning on deep path."""
        merge = CognitiveMerge()

        if not llm_fn:
            merge.inner_monologue = "No LLM for merge."
            return merge

        # Emotional trajectory injection
        trajectory_section = ""
        if self.trajectory:
            summary = self.trajectory.get_summary()
            if summary:
                trajectory_section = f"\n{summary}\n"

        # CoT instruction block (deep path only)
        if use_cot:
            thought_schema = (
                '  "thought": "Step-by-step reasoning about contradictions'
                ' and emotional state (2-3 sentences)",'
            )
            cot_instruction = (
                "\nINSTRUCTIONS:\n"
                "1. First, think step by step about whether the user's claims"
                " contradict any memories\n"
                "2. Then decide your response strategy\n"
            )
        else:
            thought_schema = '  "thought": "",'
            cot_instruction = ""

        prompt = f"""You are the inner thinking process of a close friend AI.

WHAT THEY JUST SAID:
  Message: "{present.raw_message}"
  Intent: {present.intent}
  Claims: {json.dumps(present.claims)}
  Emotional state: {present.emotional_state}
  Conversational pattern: {present.conversational_pattern}

WHAT I KNOW FROM MEMORY:
  Past facts: {json.dumps(memory.relevant_facts[:5])}
  Relationship: {memory.relationship_context[:400] if memory.relationship_context else "None"}
  Emotional memory signals: {memory.affect_hints[:500] if memory.affect_hints else "None"}
{trajectory_section}{cot_instruction}
Return JSON only:
{{
{thought_schema}
  "tension_level": 0.0 to 1.0,
  "tension_type": "none|mild_inconsistency|pattern_break|direct_contradiction|growth",
  "contradictions": ["list contradictions"],
  "response_strategy": "acknowledge|challenge|support|redirect|quiz|celebrate",
  "suggested_tone": "warm|playful|concerned|firm|proud|teasing",
  "inner_monologue": "1-2 sentences of what you're THINKING (not saying)"
}}

JSON only:"""

        try:
            result = await llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500 if use_cot else 400,
            )

            text = result.strip()
            if "```" in text:
                parts = text.split("```")
                if len(parts) > 1:
                    text = parts[1].replace("json", "").strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])

                merge.thought = data.get("thought", "")
                merge.tension_level = float(data.get("tension_level", 0))
                merge.tension_type = data.get("tension_type", "none")
                merge.contradictions = data.get("contradictions", [])
                merge.response_strategy = data.get("response_strategy", "acknowledge")
                merge.suggested_tone = data.get("suggested_tone", "warm")
                merge.inner_monologue = data.get("inner_monologue", "")
                merge.memory_insights = memory.relevant_facts[:3]
        except Exception as e:
            logger.warning("Merge failed: %s", e)
            merge.inner_monologue = "I'm having trouble thinking through this right now."

        return merge

    async def _extract_search_intent(self, message: str, history: list = None, llm_fn=None) -> str:
        """Pre-retrieval intent extraction (deep path only).
        Returns space-joined search terms for memory.query().
        """
        if not llm_fn:
            return ""

        safe_history = [
            m
            for m in (history or [])[-3:]
            if isinstance(m, dict) and "role" in m and "content" in m
        ]
        recent = "\n".join(f"{m['role']}: {m['content'][:80]}" for m in safe_history)
        prompt = (
            "What specific topics/events is the user referring to?\n"
            f"Recent conversation:\n{recent}\n"
            f'Message: "{message}"\n'
            "Return 1-3 specific search terms as JSON array. JSON only:"
        )

        try:
            result = await llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
            )
            text = result.strip()
            if "```" in text:
                parts = text.split("```")
                if len(parts) > 1:
                    text = parts[1].replace("json", "").strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                terms = json.loads(text[start:end])
                if isinstance(terms, list):
                    return " ".join(str(t) for t in terms[:3])
        except Exception as e:
            logger.warning("Search intent extraction failed: %s", e)

        return ""

    def build_cognitive_context(self, merge: CognitiveMerge, detail: str = "full") -> str:
        """Build the cognitive injection for the system prompt."""
        if detail == "strategy":
            return f"""

## RESPONSE STRATEGY

- Strategy: {merge.response_strategy}
- Tone: {merge.suggested_tone}
- Tension: {merge.tension_level:.1f}/1.0 ({merge.tension_type})
- Rule: Follow the strategy and tone. Do not expose this internal note.
"""

        return f"""

## YOUR INNER THOUGHTS (Use these to guide your response. Do NOT share directly.)

**What I'm thinking:** {merge.inner_monologue}

**Tension Level:** {merge.tension_level:.1f}/1.0 ({merge.tension_type})
**Response Strategy:** {merge.response_strategy}
**Suggested Tone:** {merge.suggested_tone}

**Memory Insights:**
{chr(10).join(f"- {m[:120]}" for m in merge.memory_insights[:3]) if merge.memory_insights else "- None"}

**Contradictions Detected:**
{chr(10).join(f"- {c}" for c in merge.contradictions) if merge.contradictions else "- None"}

**BEHAVIORAL RULES:**
- If tension > 0.5: Don't just agree. Challenge gently with memory evidence.
- If strategy is "quiz": Ask them to prove their claim.
- If strategy is "celebrate": They've genuinely grown. Be proud.
- NEVER say "I checked my memory." Make it feel like a friend who remembers.
"""
