import asyncio
from pathlib import Path
from datetime import datetime

from .ingestion.logger import ConversationLogger
from .ingestion.schema import RawMessage
from .profile.manager import ProfileManager
from .injection.compiler import PromptCompiler

class SBSOrchestrator:
    """
    Soul-Brain Sync Orchestrator (Phase 1 Skeleton).
    """
    
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        
        # Initialize all components
        self.profile_mgr = ProfileManager(self.data_dir / "profiles")
        self.logger = ConversationLogger(self.data_dir)
        from .processing.realtime import RealtimeProcessor
        self.realtime = RealtimeProcessor(self.profile_mgr)
        from .processing.batch import BatchProcessor
        self.batch = BatchProcessor(self.logger.db_path, self.profile_mgr)
        from .feedback.implicit import ImplicitFeedbackDetector
        self.feedback = ImplicitFeedbackDetector(self.profile_mgr)
        self.compiler = PromptCompiler(self.profile_mgr)
        
        # Track unbatched messages
        self._unbatched_count = 0
        self.BATCH_THRESHOLD = 50
        
        # Startup batch trigger (if > 6 hours)
        self._check_startup_batch()

    def _check_startup_batch(self):
        meta = self.profile_mgr.load_layer("meta")
        last_run_str = meta.get("last_batch_run")
        if not last_run_str:
            return
        
        from datetime import datetime, timedelta
        try:
            last_run = datetime.fromisoformat(last_run_str)
            if datetime.now() - last_run > timedelta(hours=6):
                print(f"[SBS] Startup trigger: >6 hrs since last batch. Running now.")
                import threading
                threading.Thread(target=self.batch.run).start()
        except ValueError:
            pass
        
    def on_message(self, role: str, content: str, session_id: str = "default", response_to: str = None) -> dict:
        """
        Called for every message in the conversation.
        """
        import re
        message = RawMessage(
            role=role,
            content=content,
            session_id=session_id,
            response_to=response_to,
            char_count=len(content),
            word_count=len(content.split()),
            has_emoji=bool(re.search(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]", content)),
            is_question=content.strip().endswith("?"),
        )
        
        # Run realtime processing
        rt_results = self.realtime.process(message)
        message.rt_sentiment = rt_results["rt_sentiment"]
        message.rt_language = rt_results["rt_language"]
        message.rt_mood_signal = rt_results["rt_mood_signal"]
        
        # Log the message
        self.logger.log(message)
        
        rt_results["msg_id"] = message.msg_id
        
        # Check for implicit feedback (user messages only)
        if role == "user":
            # Simple retrieval of last assistant message for context 
            # (In production, you'd fetch this from the actual chat history/DB)
            last_asst_msg = getattr(self, "_last_assistant_message", "")
            feedback_signal = self.feedback.analyze(content, last_asst_msg)
            
            if feedback_signal:
                self.feedback.apply_feedback(feedback_signal)
                print(f"[FEEDBACK] Detected: {feedback_signal['type']}")
                
        elif role == "assistant":
            # Keep track of last assistant message for feedback context
            self._last_assistant_message = content
        
        # Trigger batch processing logic
        self._unbatched_count += 1
        if self._unbatched_count >= self.BATCH_THRESHOLD:
            # We would normally trigger this entirely asynchronously.
            # For this MVP we will trigger it in line, however you'd want a 
            # Celery/Background task here.
            import threading
            threading.Thread(target=self.batch.run).start()
            self._unbatched_count = 0
            
        return rt_results
    
    def get_system_prompt(self, base_instructions: str = "") -> str:
        """
        Returns the complete system prompt with injected persona profile.
        """
        persona_block = self.compiler.compile()
        
        if base_instructions:
            return f"{base_instructions}\n\n---\n\n{persona_block}"
        return persona_block
    
    def force_batch(self, full_rebuild: bool = False):
        self.batch.run(full_rebuild=full_rebuild)
        self._unbatched_count = 0
    
    def rollback(self, version: int):
        self.profile_mgr.rollback_to(version)
    
    def get_profile_summary(self) -> dict:
        profile = self.profile_mgr.load_full_profile()
        return {
            "current_mood": profile["emotional_state"]["current_dominant_mood"],
            "sentiment": profile["emotional_state"]["current_sentiment_avg"],
            "banglish_ratio": profile["linguistic"].get("current_style", {}).get("banglish_ratio"),
            "vocab_size": profile["vocabulary"].get("total_unique_words", 0),
            "profile_version": profile["meta"].get("current_version", 0),
            "total_messages": profile["meta"].get("total_messages_processed", 0),
        }
