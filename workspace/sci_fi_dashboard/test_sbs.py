import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sbs.orchestrator import SBSOrchestrator

def test_sbs_integration():
    test_dir = Path("./test_sbs_data")
    
    # 1. Clean slate
    if test_dir.exists():
        shutil.rmtree(test_dir)
        
    print("🧪 Initializing SBS Orchestrator...")
    orchestrator = SBSOrchestrator(data_dir=str(test_dir))
    
    # 2. Ingestion & Realtime Perception
    print("🧪 Simulating conversation...")
    messages = [
        ("user", "hey jarvis, what's up?"),
        ("assistant", "Not much, just waiting for commands."),
        ("user", "khub pressure jacche ajke"), # Mood: stressed, Language: Mixed/Banglish
        ("assistant", "I understand. Let's take it easy. What can I help with?"),
        ("user", "why are you so formal"),     # Feedback: correction formal
        ("assistant", "My bad the_brother, ki obostha bol?"),
        ("user", "darun! tui code ta lekhto ebar"), # Praise + coding topic
        ("assistant", "Ekdom, writing the code now."),
    ]
    
    for role, content in messages:
        res = orchestrator.on_message(role, content)
        if role == "user":
            print(f"   [Realtime Insight] Mood: {res.get('rt_mood_signal')} | Lang: {res.get('rt_language')} | Sentiment: {res.get('rt_sentiment')}")
    
    # Check Profile Hot Update
    current_mood = orchestrator.get_profile_summary()["current_mood"]
    print(f"🧪 Profile Hot-Update check: Dominant mood is '{current_mood}'")
    assert current_mood in ["stressed", "playful", "neutral"]
    
    # 3. Batch Processing & Memory
    print("🧪 Forcing Batch Processing...")
    orchestrator.force_batch(full_rebuild=True)
    
    summary = orchestrator.get_profile_summary()
    print("🧪 Batch Summary:", summary)
    assert summary["total_messages"] == 8
    
    # 4. Injection Compilation
    print("🧪 Testing Prompt Compilation...")
    prompt = orchestrator.get_system_prompt("BASE INSTRUCTIONS")
    print("-" * 40)
    print(prompt[:500] + "\n...[truncated]...")
    print("-" * 40)
    
    # Ensure it combined properly
    assert "[IDENTITY]" in prompt
    assert "[EMOTIONAL CONTEXT]" in prompt
    
    print("✅ End-to-end integration test passed.")
    
    # Cleanup
    if test_dir.exists():
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_sbs_integration()
