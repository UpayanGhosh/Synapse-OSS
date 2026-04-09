"""TTS package — Text-to-speech synthesis engine for Synapse-OSS.

Provides OGG Opus audio bytes from text for WhatsApp PTT voice note delivery.

Quick start:
    from sci_fi_dashboard.tts import TTSEngine
    engine = TTSEngine()
    ogg_bytes = await engine.synthesize("Hello!")  # returns None or OGG Opus bytes

Providers:
    edge-tts    — Default. Zero credentials, 400+ Microsoft neural voices.
    elevenlabs  — Premium. Requires API key in synapse.json providers.elevenlabs.api_key.

Configuration (synapse.json):
    { "tts": { "enabled": true, "provider": "edge-tts", "voice": "en-US-AriaNeural" } }
"""

from .convert import mp3_to_ogg_opus
from .engine import TTSEngine

__all__ = ["TTSEngine", "mp3_to_ogg_opus"]
