"""
Dual-Stream Cognition Engine
Stream 1 (Present): What is the user saying RIGHT NOW?
Stream 2 (Memory):  What do I KNOW about this person and topic?
Merge:              Detect tension, alignment, or contradiction.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class PresentStream:
    """What the user is saying right now."""
    raw_message: str
    sentiment: str = "neutral"
    intent: str = "statement"
    topics: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    emotional_state: str = "calm"


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
    tension_level: float = 0.0
    tension_type: str = "none"
    response_strategy: str = "acknowledge"
    memory_insights: list = field(default_factory=list)
    suggested_tone: str = "warm"
    inner_monologue: str = ""
    contradictions: list = field(default_factory=list)


class DualCognitionEngine:
    def __init__(self, memory_engine, graph, toxic_scorer=None):
        self.memory = memory_engine
        self.graph = graph
        self.toxic_scorer = toxic_scorer

    async def think(
        self,
        user_message: str,
        chat_id: str,
        conversation_history: list = None,
        target: str = "the_creator",
        llm_fn=None,
    ) -> CognitiveMerge:
        """Main entry: runs both streams, merges them."""
        
        # Run in parallel
        present, memory = await asyncio.gather(
            self._analyze_present(user_message, conversation_history, llm_fn),
            self._recall_memory(user_message, chat_id, target),
        )

        merge = await self._merge_streams(present, memory, target, llm_fn)
        return merge

    async def _analyze_present(
        self, message: str, history: list = None, llm_fn=None
    ) -> PresentStream:
        """Stream 1: Analyze current message."""
        present = PresentStream(raw_message=message)

        if not llm_fn:
            return present

        prompt = f"""Analyze this message. Return JSON only.

Message: "{message}"

Return:
{{
  "sentiment": "positive|negative|neutral",
  "intent": "question|statement|request|venting|bragging|deflecting",
  "claims": ["factual claims user is making"],
  "emotional_state": "calm|excited|defensive|vulnerable|evasive|guilty",
  "topics": ["key topics"]
}}

JSON only:"""

        try:
            result = await llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            # Parse JSON - strip thinking blocks if present
            text = result.strip()
            
            # Remove thinking blocks if prepended
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
        except Exception as e:
            print(f"⚠️ Present stream failed: {e}")

        return present

    async def _recall_memory(
        self, message: str, chat_id: str, target: str
    ) -> MemoryStream:
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
        self, present: PresentStream, memory: MemoryStream, target: str, llm_fn=None
    ) -> CognitiveMerge:
        """Merge: compare present vs memory."""
        merge = CognitiveMerge()

        if not llm_fn:
            merge.inner_monologue = "No LLM for merge."
            return merge

        prompt = f"""You are the inner thinking process of a close friend AI.

WHAT THEY JUST SAID:
  Message: "{present.raw_message}"
  Intent: {present.intent}
  Claims: {json.dumps(present.claims)}
  Emotional state: {present.emotional_state}

WHAT I KNOW FROM MEMORY:
  Past facts: {json.dumps(memory.relevant_facts[:5])}
  Relationship: {memory.relationship_context[:400] if memory.relationship_context else "None"}

Think: does their message align with or contradict what you know?

Return JSON only:
{{
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
                max_tokens=400,
            )

            text = result.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])

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

    def build_cognitive_context(self, merge: CognitiveMerge) -> str:
        """Build the cognitive injection for the system prompt."""
        return f"""

## YOUR INNER THOUGHTS (Use these to guide your response. Do NOT share directly.)

**What I'm thinking:** {merge.inner_monologue}

**Tension Level:** {merge.tension_level:.1f}/1.0 ({merge.tension_type})
**Response Strategy:** {merge.response_strategy}
**Suggested Tone:** {merge.suggested_tone}

**Memory Insights:**
{chr(10).join(f'- {m[:120]}' for m in merge.memory_insights[:3]) if merge.memory_insights else '- None'}

**Contradictions Detected:**
{chr(10).join(f'- {c}' for c in merge.contradictions) if merge.contradictions else '- None'}

**BEHAVIORAL RULES:**
- If tension > 0.5: Don't just agree. Challenge gently with memory evidence.
- If strategy is "quiz": Ask them to prove their claim.
- If strategy is "celebrate": They've genuinely grown. Be proud.
- NEVER say "I checked my memory." Make it feel like a friend who remembers.
"""
