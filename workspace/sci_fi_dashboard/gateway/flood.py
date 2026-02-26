import asyncio


class FloodGate:
    """Batches rapid-fire messages from the same user."""

    def __init__(self, batch_window_seconds: float = 3.0):
        self.window = batch_window_seconds
        self._buffers: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._callback = None

    def set_callback(self, callback):
        self._callback = callback

    async def incoming(self, chat_id: str, message: str, metadata: dict):
        if chat_id not in self._buffers:
            self._buffers[chat_id] = {"messages": [message], "metadata": metadata}
            # Start the timeout task
            self._tasks[chat_id] = asyncio.create_task(self._wait_and_flush(chat_id))
        else:
            self._buffers[chat_id]["messages"].append(message)
            self._buffers[chat_id]["metadata"] = metadata

            # Cancel the existing timer and restart it to extend the debounce window
            if chat_id in self._tasks:
                self._tasks[chat_id].cancel()
            self._tasks[chat_id] = asyncio.create_task(self._wait_and_flush(chat_id))

    async def _wait_and_flush(self, chat_id: str):
        await asyncio.sleep(self.window)
        buffer_data = self._buffers.pop(chat_id, None)
        self._tasks.pop(chat_id, None)

        if buffer_data and self._callback:
            combined_message = "\\n\\n".join(buffer_data["messages"])
            await self._callback(chat_id, combined_message, buffer_data["metadata"])
