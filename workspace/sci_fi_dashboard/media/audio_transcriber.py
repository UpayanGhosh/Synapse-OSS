"""
media/audio_transcriber.py — Groq Whisper Large v3 transcription via httpx.

Calls the pre-flight check first, then sends the audio file to Groq's
OpenAI-compatible Whisper endpoint as multipart/form-data.

Usage:
    from sci_fi_dashboard.media.audio_transcriber import transcribe_audio
    text = await transcribe_audio(Path("/tmp/voice.ogg"))
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from .audio_preflight import check_audio_preflight

logger = logging.getLogger(__name__)

_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_GROQ_WHISPER_MODEL = "whisper-large-v3"
_REQUEST_TIMEOUT = 60.0  # seconds — large files can take a while


async def transcribe_audio(
    file_path: Path,
    language: str = "auto",
) -> str:
    """Transcribe an audio file using Groq Whisper Large v3.

    Parameters
    ----------
    file_path:
        Path to the audio file on disk (OGG, MP3, WAV, M4A, etc.).
    language:
        ISO-639-1 language code (e.g. ``"en"``, ``"bn"``).  ``"auto"``
        lets Whisper auto-detect.

    Returns
    -------
    str
        The transcribed text, or ``""`` on any failure.
    """
    # --- API key check ---
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "[Transcribe] GROQ_API_KEY not set — audio transcription disabled"
        )
        return ""

    # --- Pre-flight validation ---
    preflight = await check_audio_preflight(file_path)
    if not preflight.ok:
        logger.warning(
            "[Transcribe] Pre-flight rejected %s: %s", file_path, preflight.reason
        )
        return ""

    # --- Build multipart form data ---
    try:
        audio_bytes = file_path.read_bytes()
    except OSError as exc:
        logger.error("[Transcribe] Failed to read %s: %s", file_path, exc)
        return ""

    # Determine a reasonable filename with extension for MIME detection on
    # the server side.
    filename = file_path.name or "audio.ogg"

    form_data: dict[str, object] = {
        "model": (None, _GROQ_WHISPER_MODEL),
        "file": (filename, audio_bytes),
        "response_format": (None, "text"),
    }
    if language != "auto":
        form_data["language"] = (None, language)

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    # --- Call Groq Whisper API ---
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                _GROQ_WHISPER_URL,
                headers=headers,
                files=form_data,
            )

        if resp.status_code != 200:
            logger.error(
                "[Transcribe] Groq API returned %d for %s: %s",
                resp.status_code,
                file_path.name,
                resp.text[:300],
            )
            return ""

        transcript = resp.text.strip()
        logger.info(
            "[Transcribe] OK — %s (%d bytes) → %d chars",
            file_path.name,
            preflight.file_size_bytes,
            len(transcript),
        )
        return transcript

    except httpx.TimeoutException:
        logger.error(
            "[Transcribe] Timeout after %.0fs for %s", _REQUEST_TIMEOUT, file_path.name
        )
        return ""
    except httpx.HTTPError as exc:
        logger.error("[Transcribe] HTTP error for %s: %s", file_path.name, exc)
        return ""
    except Exception as exc:
        logger.error("[Transcribe] Unexpected error for %s: %s", file_path.name, exc)
        return ""
