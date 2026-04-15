"""
media/audio_preflight.py — Pre-flight checks for audio files before transcription.

Validates file size and duration against configurable limits so that
oversized or excessively long recordings are rejected early, before being
sent to an external transcription API (e.g. Groq Whisper).
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class AudioPreflightResult:
    """Outcome of an audio preflight check."""

    ok: bool
    reason: str  # "" if ok, otherwise human-readable rejection reason
    duration_seconds: float | None
    file_size_bytes: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_audio_preflight(
    file_path: Path,
    max_size_bytes: int = 25 * 1024 * 1024,  # 25 MB (Groq/Whisper limit)
    max_duration_seconds: float = 7200,  # 2 hours
) -> AudioPreflightResult:
    """Run size and duration checks on an audio file.

    Parameters
    ----------
    file_path:
        Path to the audio file on disk.
    max_size_bytes:
        Maximum allowed file size in bytes (default 25 MB).
    max_duration_seconds:
        Maximum allowed duration in seconds (default 2 hours).

    Returns
    -------
    AudioPreflightResult
        ``ok=True`` when the file passes all checks, otherwise ``ok=False``
        with a human-readable ``reason``.
    """
    # --- file existence ---
    if not file_path.is_file():
        return AudioPreflightResult(
            ok=False,
            reason=f"File not found: {file_path}",
            duration_seconds=None,
            file_size_bytes=0,
        )

    # --- size check (cheap) ---
    file_size = file_path.stat().st_size
    if file_size > max_size_bytes:
        return AudioPreflightResult(
            ok=False,
            reason=(f"File size {file_size} bytes exceeds limit of " f"{max_size_bytes} bytes"),
            duration_seconds=None,
            file_size_bytes=file_size,
        )

    # --- duration check via ffprobe (if available) ---
    duration = await _probe_duration(file_path)

    if duration is not None and duration > max_duration_seconds:
        return AudioPreflightResult(
            ok=False,
            reason=(f"Duration {duration:.1f}s exceeds limit of " f"{max_duration_seconds:.0f}s"),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    return AudioPreflightResult(
        ok=True,
        reason="",
        duration_seconds=duration,
        file_size_bytes=file_size,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _probe_duration(file_path: Path) -> float | None:
    """Return the duration in seconds via ``ffprobe``, or *None* if unavailable."""
    if shutil.which("ffprobe") is None:
        logger.warning(
            "ffprobe not found on PATH — skipping duration check for %s",
            file_path,
        )
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            logger.debug("ffprobe exited with code %d for %s", proc.returncode, file_path)
            return None

        raw = stdout.decode().strip()
        if not raw:
            return None
        return float(raw)
    except (OSError, ValueError) as exc:
        logger.debug("ffprobe duration probe failed for %s: %s", file_path, exc)
        return None
