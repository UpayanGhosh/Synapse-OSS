import time
from typing import Dict

class MessageDeduplicator:
    """Simple TTLCache to avoid reprocessing same messageid if webhook is retried."""
    def __init__(self, window_seconds: int = 300):
        self.window = window_seconds
        self.seen: Dict[str, float] = {}
        
    def is_duplicate(self, message_id: str) -> bool:
        if not message_id:
            return False
            
        now = time.time()
        
        # Clean up old entries
        expired = [k for k, v in self.seen.items() if now - v > self.window]
        for k in expired:
            del self.seen[k]
            
        if message_id in self.seen:
            return True
            
        self.seen[message_id] = now
        return False
