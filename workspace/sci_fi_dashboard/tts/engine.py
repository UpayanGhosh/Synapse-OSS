"""TTSEngine — TTS synthesis engine with dual provider support.

Dispatches to edge-tts (default, zero credentials) or ElevenLabs (premium opt-in)
based on ``tts.provider`` in synapse.json.  Produces OGG Opus bytes suitable for
WhatsApp PTT delivery.

Configuration (synapse.json):
    {
        "tts": {
            "enabled": true,
            "provider": "edge-tts",       // or "elevenlabs"
            "voice": "en-US-AriaNeural"   // voice name or ID
        },
        "providers": {
            "elevenlabs": {"api_key": "YOUR_KEY"}  // only for elevenlabs provider
        }
    }
"""

import logging
from typing import Optional

from .convert import mp3_to_ogg_opus
from .providers.edge import EdgeTTSProvider
from .providers.elevenlabs import ElevenLabsProvider

logger = logging.getLogger("synapse.tts")

MAX_TTS_CHARS = 400  # Messages longer than this are skipped — too long for voice UX


class TTSEngine:
    """Synthesize text to OGG Opus bytes for WhatsApp PTT delivery.

    Provider dispatch:
        - "edge-tts" (default): Uses EdgeTTSProvider (no credentials needed).
        - "elevenlabs": Uses ElevenLabsProvider (requires API key in providers config).

    Returns None when synthesis is skipped (disabled, too long, no key, ffmpeg absent).
    Returns OGG Opus bytes when synthesis succeeds.
    """

    async def synthesize(self, text: str) -> Optional[bytes]:
        """Synthesize text to OGG Opus bytes.

        Args:
            text: Text to synthesize into speech.

        Returns:
            OGG Opus bytes on success; None if skipped or failed at any stage.
        """
        # Guard: skip very long messages
        if len(text) > MAX_TTS_CHARS:
            logger.debug(
                "TTS skipped: text length %d exceeds MAX_TTS_CHARS (%d)",
                len(text),
                MAX_TTS_CHARS,
            )
            return None

        # Load config lazily to avoid import-time side effects
        from synapse_config import SynapseConfig  # deferred import

        cfg = SynapseConfig.load()
        tts_cfg: dict = cfg.tts

        # Respect global enabled flag (defaults to True when key is absent)
        if not tts_cfg.get("enabled", True):
            return None

        provider_name: str = tts_cfg.get("provider", "edge-tts")
        voice: str = tts_cfg.get("voice", "en-US-AriaNeural")

        # --- Provider dispatch ---
        mp3_bytes: bytes

        if provider_name == "elevenlabs":
            api_key = cfg.providers.get("elevenlabs", {}).get("api_key", "")
            if not api_key:
                logger.warning(
                    "TTS provider is 'elevenlabs' but no API key found in "
                    "providers.elevenlabs.api_key — skipping TTS."
                )
                return None
            mp3_bytes = await ElevenLabsProvider().synthesize(text, voice, api_key)

        else:
            # Default: edge-tts (covers "edge-tts" and any unknown provider name)
            if provider_name not in ("edge-tts",):
                logger.warning(
                    "Unknown TTS provider '%s'; falling back to edge-tts.", provider_name
                )
            mp3_bytes = await EdgeTTSProvider().synthesize(text, voice)

        # Provider returned empty bytes — synthesis failed
        if not mp3_bytes:
            return None

        # Transcode MP3 → OGG Opus for WhatsApp PTT
        ogg_bytes = await mp3_to_ogg_opus(mp3_bytes)

        # ffmpeg absent or conversion failed
        if not ogg_bytes:
            return None

        return ogg_bytes
