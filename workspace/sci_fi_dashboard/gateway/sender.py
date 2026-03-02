import asyncio
import contextlib


class WhatsAppSender:
    """
    Sends messages via CLI subprocess.

    Wraps subprocess calls in asyncio for non-blocking execution.
    Phase 4 will replace this with a Baileys HTTP bridge client.
    """

    def __init__(self, cli_command: str = ""):
        """
        Args:
            cli_command: Base CLI command for WhatsApp send. Deprecated — will be replaced by
                Baileys HTTP bridge in Phase 4. Pass empty string to disable CLI send path.
        """
        self.cli = cli_command
        self._send_lock = asyncio.Lock()  # Serialize CLI calls

    async def send_text(self, target: str, message: str, quote_id: str = None) -> bool:
        """
        Send a text message via CLI subprocess.
        Uses asyncio.create_subprocess_exec so it doesn't block
        the event loop while the CLI runs.
        Phase 4 will replace this with a Baileys HTTP bridge call.
        """
        args = [
            self.cli,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            target,
            "--message",
            message,
            "--json",
        ]

        if quote_id:
            args.extend(["--quote", quote_id])

        return await self._run_cli(args, context=f"send to {target}")

    async def send_typing(self, target: str):
        """
        Send typing indicator if CLI supports it.
        """
        args = [
            self.cli,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            target,
            "--action",
            "typing_on",
        ]

        with contextlib.suppress(Exception):
            await self._run_cli(args, context=f"typing to {target}", timeout=5, silent=True)

    async def send_seen(self, target: str, message_id: str):
        """
        Mark message as read if the CLI supports it.
        """
        args = [
            self.cli,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            target,
            "--action",
            "mark_read",
            "--id",
            message_id,
        ]

        with contextlib.suppress(Exception):
            await self._run_cli(args, context=f"seen to {target}", timeout=5, silent=True)

    async def send_long_message(self, target: str, message: str, chunk_size: int = 4000) -> bool:
        """
        Handle messages that exceed WhatsApp's comfortable
        display length by splitting into chunks.
        """
        if len(message) <= chunk_size:
            return await self.send_text(target, message)

        chunks = self._split_message(message, chunk_size)

        for i, chunk in enumerate(chunks):
            success = await self.send_text(target, chunk)
            if not success:
                print(f"[SENDER] Failed on chunk {i+1}/{len(chunks)} " f"to {target}")
                return False
            if i < len(chunks) - 1:
                await asyncio.sleep(0.8)

        return True

    def _split_message(self, text: str, chunk_size: int) -> list:
        """Split a long message at natural break points."""
        chunks = []
        while text:
            if len(text) <= chunk_size:
                chunks.append(text)
                break

            break_point = text.rfind("\\n\\n", 0, chunk_size)
            if break_point == -1:
                break_point = text.rfind("\\n", 0, chunk_size)
            if break_point == -1:
                break_point = text.rfind(" ", 0, chunk_size)
            if break_point == -1:
                break_point = chunk_size

            chunks.append(text[:break_point])
            text = text[break_point:].lstrip()

        return chunks

    async def _run_cli(
        self, args: list, context: str = "", timeout: int = 30, silent: bool = False
    ) -> bool:
        """
        Execute a CLI command asynchronously.
        """
        async with self._send_lock:
            try:
                process = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

                if process.returncode == 0:
                    if not silent:
                        print(f"[SENDER] OK: {context}")
                    return True
                else:
                    error_text = stderr.decode().strip() if stderr else "unknown"
                    if not silent:
                        print(
                            f"[SENDER] CLI error ({context}): "
                            f"code={process.returncode}, err={error_text[:200]}"
                        )
                    return False

            except TimeoutError:
                if not silent:
                    print(f"[SENDER] CLI timeout ({context}): >{timeout}s")
                return False
            except FileNotFoundError:
                print(
                    f"[SENDER] FATAL: CLI command '{self.cli}' not found. "
                    f"Phase 4 will replace CLI send with Baileys HTTP bridge."
                )
                return False
            except Exception as e:
                if not silent:
                    print(f"[SENDER] CLI exception ({context}): {e}")
                return False
