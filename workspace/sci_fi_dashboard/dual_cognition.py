"""
Dual-Stream Cognition Engine
Stream 1 (Present): What is the user saying RIGHT NOW?
Stream 2 (Memory):  What do I KNOW about this person and topic?
Merge:              Detect tension, alignment, or contradiction.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field


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
        self.toxic_scorer = toxic_scorer
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
        ]
        if any(m in msg_lower for m in emotional_markers):
            deep_signals += 1

        ambiguity_markers = [
            "that thing",
            "what we",
            "you know",
            "remember when",
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
    ) -> CognitiveMerge:
        """Main entry: routes through fast/standard/deep paths based on complexity."""

        try:
            complexity = self.classify_complexity(user_message, conversation_history)

            # FAST PATH: 0 LLM calls — return minimal merge immediately
            if complexity == "fast":
                return CognitiveMerge(
                    tension_level=0.0,
                    tension_type="none",
                    response_strategy="acknowledge",
                    suggested_tone="warm",
                    inner_monologue="Simple message, no deep analysis needed.",
                )

            # STANDARD PATH: analyze + recall + merge (2 LLM calls)
            if complexity == "standard":
                present, memory = await asyncio.gather(
                    self._analyze_present(user_message, conversation_history, llm_fn),
                    self._recall_memory(user_message, chat_id, target),
                )
                merge = await self._merge_streams(present, memory, target, llm_fn, use_cot=False)
                if self.trajectory:
                    self.trajectory.record(merge, present.topics)
                return merge

            # DEEP PATH: intent extraction + targeted recall + CoT merge (3-4 LLM calls)
            # Step 1: Extract search intent
            search_query = await self._extract_search_intent(
                user_message, conversation_history, llm_fn
            )
            recall_query = search_query if search_query else user_message

            # Step 2: Run analysis + targeted recall in parallel
            present, memory = await asyncio.gather(
                self._analyze_present(user_message, conversation_history, llm_fn),
                self._recall_memory(recall_query, chat_id, target),
            )

            # Step 3: CoT merge
            merge = await self._merge_streams(present, memory, target, llm_fn, use_cot=True)
            if self.trajectory:
                self.trajectory.record(merge, present.topics)
            return merge

        except Exception as e:
            print(f"⚠️ Dual cognition failed: {e}")
            return CognitiveMerge(
                inner_monologue="I'm having trouble thinking through this right now.",
                tension_level=0.0,
                response_strategy="acknowledge",
                suggested_tone="warm",
            )

    async def _analyze_present(
        self, message: str, history: list = None, llm_fn=None
    ) -> PresentStream:
        """Stream 1: Analyze current message with conversation context."""
        present = PresentStream(raw_message=message)

        if not llm_fn:
            return present

        # Inject last 3 messages as context for pattern detection
        recent_context = ""
        if history and len(history) > 0:
            last_3 = history[-3:]
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
                text = text.split("```")[1].replace("json", "").strip()
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
            print(f"⚠️ Present stream failed: {e}")

        return present

    async def _recall_memory(self, message: str, chat_id: str, target: str) -> MemoryStream:
        """Stream 2: Query memory."""
        memory = MemoryStream()

        try:
            results = self.memory.query(message, limit=5, with_graph=True)
            memory.relevant_facts = [r["content"] for r in results.get("results", [])]
            memory.graph_connections = results.get("graph_context", "")
        except Exception as e:
            print(f"⚠️ Memory recall failed: {e}")

        try:
            target_name = "primary_partner" if "the_partner" in target.lower() else "primary_user"
            memory.relationship_context = self.graph.get_entity_neighborhood(target_name)
        except Exception:
            pass

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
                text = text.split("```")[1].replace("json", "").strip()
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
            print(f"⚠️ Merge failed: {e}")

        return merge

    async def _extract_search_intent(self, message: str, history: list = None, llm_fn=None) -> str:
        """Pre-retrieval intent extraction (deep path only).
        Returns space-joined search terms for memory.query().
        """
        if not llm_fn:
            return ""

        recent = "\n".join(f"{m['role']}: {m['content'][:80]}" for m in (history or [])[-3:])
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
                text = text.split("```")[1].replace("json", "").strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                terms = json.loads(text[start:end])
                if isinstance(terms, list):
                    return " ".join(str(t) for t in terms[:3])
        except Exception as e:
            print(f"⚠️ Search intent extraction failed: {e}")

        return ""

    def build_cognitive_context(self, merge: CognitiveMerge) -> str:
        """Build the cognitive injection for the system prompt."""
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
