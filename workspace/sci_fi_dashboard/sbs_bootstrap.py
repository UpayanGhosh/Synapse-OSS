import os
import sys
from pathlib import Path
from datetime import datetime

# Add workspace to path
CURRENT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = CURRENT_DIR.parent
sys.path.append(str(CURRENT_DIR))
sys.path.append(str(WORKSPACE_ROOT))

from chat_parser import parse_messages, group_into_turns
from sbs.orchestrator import SBSOrchestrator

def bootstrap_sbs():
    print("🚀 Starting SBS Bootstrap (Past-to-Brain Ingestion)...")
    
    # 1. Setup Orchestrators
    SBS_DATA_DIR = CURRENT_DIR / "jarvis_data"
    sbs_the_creator = SBSOrchestrator(str(SBS_DATA_DIR / "the_creator"))
    sbs_the_partner = SBSOrchestrator(str(SBS_DATA_DIR / "the_partner"))
    
    archive_dir = WORKSPACE_ROOT / "_archived_memories"
    
    files_to_process = [
        ("Chat_with_primary_user_LLM.md", sbs_the_creator, "primary_user"),
        ("Chat_with_partner_user_LLM.md", sbs_the_partner, "partner_user")
    ]
    
    for filename, orchestrator, user_name in files_to_process:
        fpath = archive_dir / filename
        if not fpath.exists():
            print(f"⚠️ Skipping {filename} (Not found in archive)")
            continue
            
        print(f"📖 Ingesting {filename}...")
        raw_messages = parse_messages(str(fpath))
        turns = group_into_turns(raw_messages)
        
        count = 0
        for turn in turns:
            role = "user" if turn.speaker == user_name else "assistant"
            # Normalize timestamp
            try:
                # Format: 2024-10-25 14:30
                dt = datetime.strptime(turn.timestamp, "%Y-%m-%d %H:%M")
            except:
                dt = datetime.now()
            
            # Directly log to avoid heavy realtime processing on thousands of messages
            # We want the batch processor to handle the heavy lifting later
            from sbs.ingestion.schema import RawMessage
            import re
            
            content = turn.full_text
            msg = RawMessage(
                role=role,
                content=content,
                timestamp=dt,
                char_count=len(content),
                word_count=len(content.split()),
                has_emoji=bool(re.search(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]", content)),
                is_question=content.strip().endswith("?"),
            )
            orchestrator.logger.log(msg)
            count += 1
            if count % 100 == 0:
                print(f"   Processed {count} turns...")
        
        print(f"✅ Ingested {count} turns for {user_name}. Triggering Full Rebuild...")
        orchestrator.force_batch(full_rebuild=True)

    print("\n🏁 SBS Bootstrap Complete. Jarvis is now fully 'Soul-Synced'.")

if __name__ == "__main__":
    bootstrap_sbs()
