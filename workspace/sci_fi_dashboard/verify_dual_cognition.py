import asyncio
import sys

# Add workspace to path
sys.path.insert(0, "/path/to/openclaw/workspace/sci_fi_dashboard")
sys.path.insert(0, "/path/to/openclaw/workspace")

from dual_cognition import DualCognitionEngine


# Mock dependencies
class MockMemory:
    def query(self, text, limit=5, with_graph=True):
        return {
            "results": [
                {"content": "primary_user likes spicy food.", "source": "past_chat"},
                {
                    "content": "primary_user is working on an AI project called OpenClaw.",
                    "source": "knowledge_base",
                },
            ],
            "graph_context": "primary_user -> building -> OpenClaw",
        }


class MockGraph:
    def get_entity_neighborhood(self, entity):
        return f"Connections for {entity}: Friend of partner_user, Creator of Synapse."


async def mock_llm(messages, temperature=0.7, max_tokens=500):
    prompt = messages[-1]["content"]
    print(f"\n🤖 [Mock LLM] Processing prompt: {prompt[:100]}...")

    if "Analyze this message" in prompt:
        return """
        {
          "sentiment": "positive",
          "intent": "statement",
          "claims": ["I love spicy food"],
          "emotional_state": "excited",
          "topics": ["food", "preference"]
        }
        """
    elif "You are the inner thinking process" in prompt:
        return """
        {
          "tension_level": 0.2,
          "tension_type": "none",
          "contradictions": [],
          "response_strategy": "support",
          "suggested_tone": "warm",
          "inner_monologue": "He's expressing a consistent preference for spicy food. I should keep the conversation light and friendly."
        }
        """
    return "{}"


async def main():
    print("🚀 Starting Dual Cognition Isolation Test...")

    memory = MockMemory()
    graph = MockGraph()
    engine = DualCognitionEngine(memory_engine=memory, graph=graph)

    user_msg = "I really love spicy food, it's the best!"

    print(f"\n👤 [User]: {user_msg}")

    result = await engine.think(user_message=user_msg, chat_id="test_user", llm_fn=mock_llm)

    print("\n🧠 [Cognitive Merge Results]:")
    print(f"   - Tension Level: {result.tension_level}")
    print(f"   - Tension Type: {result.tension_type}")
    print(f"   - Strategy: {result.response_strategy}")
    print(f"   - Tone: {result.suggested_tone}")
    print(f"   - Inner Monologue: {result.inner_monologue}")

    context = engine.build_cognitive_context(result)
    print("\n📝 [Injected Context]:")
    print(context)

    print("\n✅ Isolation test completed.")


if __name__ == "__main__":
    asyncio.run(main())
