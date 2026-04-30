"""Request/response schemas for the Antigravity Gateway."""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    history: list = []
    user_id: str | None = None
    channel_id: str | None = None
    session_type: str | None = None  # safe or spicy override
    session_key: str | None = None  # explicit session isolation key (e.g. cron jobs)


class MemoryItem(BaseModel):
    content: str
    category: str = "general"


class QueryItem(BaseModel):
    text: str


class WhatsAppEnqueueRequest(BaseModel):
    message_id: str
    from_phone: str
    to_phone: str | None = None
    conversation_id: str | None = None
    text: str
    timestamp: str | None = None
    channel: str = "whatsapp"


class WhatsAppLoopTestRequest(BaseModel):
    target: str = "+10000000000"
    message: str = "local-loop-test"
    dry_run: bool = True
    timeout_sec: float = 20.0


class OpenAIRequest(BaseModel):
    model: str = "default"
    messages: list[dict]
    temperature: float | None = 0.7
    max_tokens: int | None = 500
    user: str | None = "the_creator"
