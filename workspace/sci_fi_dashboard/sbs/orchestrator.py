import asyncio
import contextlib
import logging
import re
from datetime import datetime
from pathlib import Path

from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

from .ingestion.logger import ConversationLogger
from .ingestion.schema import RawMessage
from .injection.compiler import PromptCompiler
from .profile.manager import ProfileManager


class SBSOrchestrator:
    """
    Soul-Brain Sync Orchestrator (Phase 1 Skeleton).
    """

    def __init__(self, data_dir: str = "./data", sbs_config=None):
        self.data_dir = Path(data_dir)

        # Resolve SBS configuration (use defaults if none provided)
        if sbs_config is None:
            from synapse_config import SBSConfig

            sbs_config = SBSConfig()
        self._sbs_config = sbs_config

        # Initialize all components
        self.profile_mgr = ProfileManager(
            self.data_dir / "profiles",
            max_versions=sbs_config.max_profile_versions,
        )
        self.logger = ConversationLogger(self.data_dir)
        from .processing.realtime import RealtimeProcessor

        self.realtime = RealtimeProcessor(self.profile_mgr)
        from .processing.batch import BatchProcessor

        self.batch = BatchProcessor(
            self.logger.db_path,
            self.profile_mgr,
            vocabulary_decay=sbs_config.vocabulary_decay,
            exemplar_pairs=sbs_config.exemplar_pairs,
        )
        from .feedback.implicit import ImplicitFeedbackDetector

        self.feedback = ImplicitFeedbackDetector(self.profile_mgr)
        self.compiler = PromptCompiler(
            self.profile_mgr,
            max_chars=sbs_config.prompt_max_chars,
        )

        # Track unbatched messages
        self._unbatched_count = 0
        self.BATCH_THRESHOLD = sbs_config.batch_threshold

        # Startup batch trigger (configurable window)
        self._check_startup_batch()

    def _run_batch_safe(self):
        """Wrapper around batch.run() with error handling for fire-and-forget execution."""
        try:
            self.batch.run()
        except Exception as e:
            logging.getLogger("sbs").error(f"Batch processing failed: {e}", exc_info=True)

    def _schedule_batch(self):
        """Schedule batch processing on a background thread safely.

        Attempts to use the running asyncio loop's executor to avoid
        unsynchronized threading issues. Falls back to a daemon thread
        if no loop is available.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._run_batch_safe)
        except RuntimeError:
            # No running event loop — fall back to a daemon thread
            import threading

            threading.Thread(target=self._run_batch_safe, daemon=True).start()

    def _check_startup_batch(self):
        meta = self.profile_mgr.load_layer("meta")
        last_run_str = meta.get("last_batch_run")
        if not last_run_str:
            return

        from datetime import timedelta

        try:
            last_run = datetime.fromisoformat(last_run_str)
            window_hours = self._sbs_config.batch_window_hours
            if datetime.now() - last_run > timedelta(hours=window_hours):
                print(f"[SBS] Startup trigger: >{window_hours} hrs since last batch. Running now.")
                self._schedule_batch()
        except ValueError:
            pass

    def on_message(
        self, role: str, content: str, session_id: str = "default", response_to: str = None
    ) -> dict:
        """
        Called for every message in the conversation.
        """
        message = RawMessage(
            role=role,
            content=content,
            session_id=session_id,
            response_to=response_to,
            char_count=len(content),
            word_count=len(content.split()),
        )

        # M4: Compute metadata fields defined in schema but previously unset
        message.has_emoji = bool(
            re.search(
                r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
                r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF]",
                content,
            )
        )
        message.is_question = content.rstrip().endswith("?")

        # C4+M5: Run realtime processing FIRST, copy results into message, THEN log
        rt_results = self.realtime.process(message)
        with contextlib.suppress(Exception):
            _get_emitter().emit(
                "sbs.layer_read",
                {
                    "layer_name": "emotional_state",
                    "mood": rt_results.get("rt_mood_signal", ""),
                    "sentiment": rt_results.get("rt_sentiment", ""),
                    "language": rt_results.get("rt_language", ""),
                },
            )
        message.rt_sentiment = rt_results.get("rt_sentiment")
        message.rt_language = rt_results.get("rt_language")
        message.rt_mood_signal = rt_results.get("rt_mood_signal")

        self.logger.log(message)
        if role == "user" and rt_results.get("rt_mood_signal"):
            try:
                self.realtime.flush()
            except Exception:
                logging.getLogger("sbs").warning(
                    "Realtime flush failed; continuing message flow.",
                    exc_info=True,
                )

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

        # M1: Trigger batch processing with error handling
        self._unbatched_count += 1
        if self._unbatched_count >= self.BATCH_THRESHOLD:
            self._schedule_batch()
            self._unbatched_count = 0

        return rt_results

    def get_system_prompt(self, base_instructions: str = "", proactive_context: str = "") -> str:
        """
        Returns the complete system prompt with injected persona profile.
        Optionally appends a proactive awareness block from the ProactiveAwarenessEngine.
        """
        with contextlib.suppress(Exception):
            _get_emitter().emit("sbs.read_start", {"target": getattr(self, "_target", "unknown")})
        persona_block = self.compiler.compile()
        with contextlib.suppress(Exception):
            _get_emitter().emit(
                "sbs.compile_done",
                {
                    "total_chars": len(persona_block),
                    "token_estimate": len(persona_block) // 4,
                    "layers_included": 7,
                },
            )
        parts = []
        if base_instructions:
            parts.append(base_instructions)
        parts.append(persona_block)
        if proactive_context:
            parts.append(proactive_context)
        return "\n\n---\n\n".join(parts)

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
