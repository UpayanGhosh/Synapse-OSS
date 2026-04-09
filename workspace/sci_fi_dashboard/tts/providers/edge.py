"""EdgeTTSProvider — Microsoft Edge TTS synthesis via edge-tts library.

Produces MP3 bytes from text using Microsoft's neural TTS service.
Requires no API key — uses edge-tts which reverse-engineers the Edge browser TTS WebSocket.

Default voice: en-US-AriaNeural (400+ voices available via edge-tts voice list).
"""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("synapse.tts")

DEFAULT_VOICE = "en-US-AriaNeural"


class EdgeTTSProvider:
    """TTS provider using edge-tts (Microsoft Edge neural voices, zero credentials)."""

    async def synthesize(self, text: str, voice: str = DEFAULT_VOICE) -> bytes:
        """Synthesize text to MP3 bytes using edge-tts.

        Args:
            text: Text to synthesize.
            voice: Edge TTS voice name (e.g. "en-US-AriaNeural"). Falls back to
                   DEFAULT_VOICE if not provided.

        Returns:
            MP3 bytes on success; empty bytes on failure.
        """
        try:
            import edge_tts  # deferred import for graceful ImportError handling

            communicate = edge_tts.Communicate(text, voice or DEFAULT_VOICE)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            try:
                await communicate.save(tmp_path)
                return Path(tmp_path).read_bytes()
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except ImportError:
            logger.error(
                "edge-tts is not installed. Run: pip install edge-tts>=7.0.0"
            )
            return b""
        except Exception as exc:
            logger.error("EdgeTTSProvider.synthesize() failed: %s", exc)
            return b""
