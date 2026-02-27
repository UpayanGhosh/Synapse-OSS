import asyncio
import contextlib
import time
import traceback

from .queue import MessageTask, TaskQueue
from .sender import WhatsAppSender


class MessageWorker:
    """
    Background worker pulling from the task queue.
    """

    def __init__(self, queue: TaskQueue, sender: WhatsAppSender, process_fn, num_workers: int = 2):
        self.queue = queue
        self.sender = sender
        self.process_fn = process_fn
        self.num_workers = num_workers
        self._workers: list[asyncio.Task] = []
        self._running = False

        # PER-CHAT GENERATION TRACKING
        self._chat_generations: dict[str, int] = {}
        self._gen_lock = asyncio.Lock()

    async def start(self):
        self._running = True
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"msg-worker-{i}")
            self._workers.append(task)
        print(f"[WORKER] Started {self.num_workers} workers.")

    async def stop(self):
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        print("[WORKER] All workers stopped.")

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                task = await self.queue.dequeue()
                await self._handle_task(task, worker_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WORKER-{worker_id}] Loop error: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def _handle_task(self, task: MessageTask, worker_id: int):
        chat_id = task.chat_id
        start_time = time.time()

        # INCREASE GENERATION TO INDICATE NEWEST LATEST TASK
        async with self._gen_lock:
            current = self._chat_generations.get(chat_id, 0)
            new_gen = current + 1
            self._chat_generations[chat_id] = new_gen
            task.generation = new_gen

        print(
            f"[WORKER-{worker_id}] gen={task.generation} Processing: "
            f'"{task.user_message[:60]}..." from {task.sender_name}'
        )

        try:
            # STEP 1: Blue ticks
            if task.message_id:
                await self.sender.send_seen(chat_id, task.message_id)

            # STEP 2: Typing indicator
            typing_task = asyncio.create_task(self._keep_typing(chat_id))

            # STEP 3: The actual pipeline (SBS + RAG + LLM)
            response = await self.process_fn(task.user_message, chat_id)

            # STEP 4: Stop typing
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task

            # STEP 5: Check if still the latest generation before sending
            async with self._gen_lock:
                latest_gen = self._chat_generations.get(chat_id, task.generation)

            if task.generation != latest_gen:
                self.queue.supersede(task)
                print(
                    f"[WORKER-{worker_id}] gen={task.generation} superseded by "
                    f"gen={latest_gen} for chat {chat_id}. Dropping response silently."
                )
                return

            # STEP 6: Send response via CLI
            if response and response.strip():
                success = await self.sender.send_long_message(target=chat_id, message=response)

                processing_time_ms = int((time.time() - start_time) * 1000)
                if success:
                    self.queue.complete(task, response)
                    print(
                        f"[WORKER-{worker_id}] gen={task.generation} Delivered in "
                        f"{processing_time_ms}ms"
                    )
                else:
                    self.queue.fail(task, "CLI send failed")
            else:
                self.queue.fail(task, "Empty LLM response")

        except Exception as e:
            error_msg = str(e)

            # Check if this task is already superseded
            async with self._gen_lock:
                latest_gen = self._chat_generations.get(chat_id, task.generation)

            if task.generation != latest_gen:
                self.queue.supersede(task)
                print(
                    f"[WORKER-{worker_id}] gen={task.generation} error after superseded by "
                    f"gen={latest_gen} for {chat_id}. Dropping silently."
                )
                return

            self.queue.fail(task, error_msg)
            print(f"[WORKER-{worker_id}] Task failed: {error_msg}")
            traceback.print_exc()

            # Tell the user something went wrong
            await self.sender.send_text(
                chat_id, "[WARN] A technical glitch occurred. Please try again. 🔧"
            )

    async def _keep_typing(self, chat_id: str):
        """Resend typing indicator every 4s to keep it alive."""
        try:
            while True:
                await self.sender.send_typing(chat_id)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
