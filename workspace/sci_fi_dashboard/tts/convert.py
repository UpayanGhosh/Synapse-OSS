"""convert.py — MP3 to OGG Opus transcoding via ffmpeg subprocess.

WhatsApp PTT voice notes require OGG container with Opus codec.
Both edge-tts and ElevenLabs produce MP3; this module bridges the gap.

ffmpeg is a system binary (not a pip package).
Install: apt install ffmpeg / brew install ffmpeg / winget install Gyan.FFmpeg
"""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("synapse.tts")


async def mp3_to_ogg_opus(mp3_bytes: bytes) -> bytes:
    """Transcode MP3 bytes to OGG Opus bytes for WhatsApp PTT delivery.

    Uses asyncio.create_subprocess_exec to call ffmpeg without blocking the event loop.
    Output is mono 48kHz Opus @ 48kbps — optimised for voice and compatible with
    WhatsApp PTT (``ptt: true, mimetype: "audio/ogg; codecs=opus"``).

    Args:
        mp3_bytes: Raw MP3 audio bytes to transcode.

    Returns:
        OGG Opus bytes on success; empty bytes if ffmpeg is absent or fails.

    Raises:
        Nothing — all errors are caught and logged. Returns b"" on any failure.
    """
    in_path: str | None = None
    out_path: str | None = None

    try:
        # Write MP3 to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fin:
            fin.write(mp3_bytes)
            in_path = fin.name

        out_path = in_path.replace(".mp3", ".ogg")

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            "-ar",
            "48000",
            "-ac",
            "1",  # mono — reduces size, adequate for voice
            "-f",
            "ogg",
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited with code {proc.returncode}")

        return Path(out_path).read_bytes()

    except FileNotFoundError:
        logger.error(
            "ffmpeg not found. Voice notes disabled. "
            "Install ffmpeg to enable TTS: apt install ffmpeg / brew install ffmpeg / "
            "winget install Gyan.FFmpeg"
        )
        return b""
    except RuntimeError as exc:
        logger.error("ffmpeg conversion failed: %s", exc)
        return b""
    except Exception as exc:
        logger.error("mp3_to_ogg_opus() unexpected error: %s", exc)
        return b""
    finally:
        # Clean up temp files regardless of success/failure
        if in_path:
            Path(in_path).unlink(missing_ok=True)
        if out_path:
            Path(out_path).unlink(missing_ok=True)
