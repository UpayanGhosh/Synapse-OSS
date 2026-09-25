import asyncio
import uuid


class FloodGate:
    """Batches rapid-fire messages from the same user."""

    def __init__(self, batch_window_seconds: float = 3.0):
        self.window = batch_window_seconds
        self._buffers: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._callback = None
        self._failure_callback = None
        self._inbox_store = None

    @property
    def inbox_store(self):
        return self._inbox_store

    def set_inbox_store(self, store) -> None:
        self._inbox_store = store

    def set_callback(self, callback):
        self._callback = callback

    def set_failure_callback(self, callback):
        self._failure_callback = callback

    async def incoming(self, chat_id: str, message: str, metadata: dict) -> bool:
        """Persist first, then add to the short debounce buffer.

        Returns False for a provider duplicate that is already in the inbox.
        """
        details = dict(metadata)
        channel_id = str(details.get("channel_id") or "whatsapp")
        message_id = str(details.get("message_id") or uuid.uuid4())
        details["channel_id"] = channel_id
        details["message_id"] = message_id
        if self._inbox_store is not None:
            inbox_id, is_new = self._inbox_store.capture(
                channel_id, message_id, chat_id, message, details
            )
            if not is_new:
                return False
            details["inbox_ids"] = [inbox_id]
        self._buffer(chat_id, message, details)
        return True

    def replay(self, entry: dict) -> None:
        """Requeue a persisted envelope without merging it into a fresh turn."""
        details = dict(entry["metadata"])
        details["channel_id"] = entry["channel_id"]
        details["message_id"] = entry["message_id"]
        details["inbox_ids"] = [entry["id"]]
        details["inbox_claimed"] = bool(entry.get("inbox_claimed", False))
        self._buffer(entry["chat_id"], entry["text"], details, replay_key=entry["id"])

    def _buffer(
        self, chat_id: str, message: str, metadata: dict, replay_key: int | None = None
    ) -> None:
        key = (
            metadata.get("channel_id", "whatsapp"),
            metadata.get("person_origin", "channel"),
            chat_id,
            replay_key,
        )
        if key not in self._buffers:
            self._buffers[key] = {"messages": [message], "metadata": metadata}
            # Start the timeout task
            self._tasks[key] = asyncio.create_task(self._wait_and_flush(key))
        else:
            current = self._buffers[key]
            if metadata.get("inbox_ids") and set(metadata["inbox_ids"]) <= set(
                current["metadata"].get("inbox_ids", [])
            ):
                current["metadata"]["inbox_claimed"] = bool(
                    current["metadata"].get("inbox_claimed") or metadata.get("inbox_claimed")
                )
                return
            current["messages"].append(message)
            ids = [*current["metadata"].get("inbox_ids", []), *metadata.get("inbox_ids", [])]
            current["metadata"] = {**metadata, "inbox_ids": ids}

            # Cancel the existing timer and restart it to extend the debounce window
            if key in self._tasks:
                self._tasks[key].cancel()
            self._tasks[key] = asyncio.create_task(self._wait_and_flush(key))

    async def _wait_and_flush(self, key: tuple[str, str, int | None]):
        await asyncio.sleep(self.window)
        buffer_data = self._buffers.pop(key, None)
        self._tasks.pop(key, None)

        if buffer_data and self._callback:
            combined_message = "\n\n".join(buffer_data["messages"])
            try:
                await self._callback(key[2], combined_message, buffer_data["metadata"])
            except Exception as exc:
                if self._failure_callback is None:
                    raise
                self._failure_callback(buffer_data["metadata"], exc)
