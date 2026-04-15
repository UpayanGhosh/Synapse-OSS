"""TTS providers package — EdgeTTSProvider and ElevenLabsProvider."""

from .edge import EdgeTTSProvider
from .elevenlabs import ElevenLabsProvider

__all__ = ["EdgeTTSProvider", "ElevenLabsProvider"]
