import asyncio
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional

class TaskStatus(Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"

@dataclass
class MessageTask:
    task_id: str
    chat_id: str
    user_message: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.QUEUED
    
    message_id: str = ""
    sender_name: str = ""
    is_group: bool = False
    
    response: Optional[str] = None
    error: Optional[str] = None
    processing_started: Optional[datetime] = None
    processing_finished: Optional[datetime] = None
    
    generation: int = 0
    processing_time_ms: int = 0

class TaskQueue:
    def __init__(self, max_size: int = 100, max_history: int = 500):
        self._queue = asyncio.Queue(maxsize=max_size)
        self._active_tasks = {}
        self._task_history = []
        self._max_history = max_history
    
    async def enqueue(self, task: MessageTask):
        self._active_tasks[task.task_id] = task
        await self._queue.put(task)
        
    async def dequeue(self) -> MessageTask:
        task = await self._queue.get()
        task.status = TaskStatus.PROCESSING
        task.processing_started = datetime.now()
        return task
        
    def complete(self, task: MessageTask, result: str = ""):
        task.status = TaskStatus.COMPLETED
        task.response = result
        task.processing_finished = datetime.now()
        self._archive(task)
        self._queue.task_done()
        
    def fail(self, task: MessageTask, error: str = ""):
        task.status = TaskStatus.FAILED
        task.error = error
        task.processing_finished = datetime.now()
        self._archive(task)
        self._queue.task_done()
        
    def supersede(self, task: MessageTask):
        """Mark a task as superseded by a newer one for the same chat."""
        task.status = TaskStatus.SUPERSEDED
        task.processing_finished = datetime.now()
        self._archive(task)
        self._queue.task_done()
        
    def _archive(self, task: MessageTask):
        self._active_tasks.pop(task.task_id, None)
        self._task_history.append(task)
        if len(self._task_history) > self._max_history:
            self._task_history = self._task_history[-self._max_history:]
        
    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
        
    def get_stats(self) -> dict:
        return {
            "pendingSize": self.pending_count,
        }
