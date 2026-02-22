from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid

class RawMessage(BaseModel):
    """Atomic unit of conversation capture."""
    
    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    role: Literal["user", "assistant", "system"]
    content: str
    
    # Metadata extracted at ingestion time (cheap operations only)
    char_count: int = 0
    word_count: int = 0
    has_emoji: bool = False
    has_media: bool = False              # image/audio/file reference
    is_question: bool = False            # ends with ?
    
    # Session context
    session_id: str = ""                 # groups messages in one conversation
    response_to: Optional[str] = None    # links assistant reply to user message
    
    # Populated by realtime processor (not at ingestion)
    rt_sentiment: Optional[float] = None       # -1.0 to 1.0
    rt_language: Optional[str] = None          # "en", "bn", "banglish", "mixed"
    rt_mood_signal: Optional[str] = None       # "stressed", "playful", etc.
