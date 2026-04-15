"""ElevenLabsProvider — Premium TTS synthesis via ElevenLabs API.

Produces MP3 bytes from text using the ElevenLabs text-to-speech API.
Requires an API key passed explicitly (do not rely on os.environ).

Voice resolution: accepts human-readable names (Rachel, Josh, etc.) and resolves
them to ElevenLabs voice IDs via a hardcoded premade-voice dict.  If the name is
not in the dict it is passed through directly (allows raw voice_id usage).
"""

import logging

logger = logging.getLogger("synapse.tts")

# Hardcoded premade voices — avoid per-call /voices API lookups (adds 200ms+).
# Source: https://elevenlabs-sdk.mintlify.app/voices/premade-voices
_PREMADE_VOICES: dict[str, str] = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Josh": "TxGEqnHWrfWFTfGW9XjX",
    "Sam": "yoZ06aMxZJJ28mfd3POQ",
    "Bella": "EXAVITQu4vr4xnSDxMaL",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Elli": "MF3mGyEYCl7XYWbV9V6O",
    "Arnold": "VR6AewLTigWG4xSOukaG",
    "Domi": "AZnzlk1XvdvUeBnXmlld",
    "Antoni": "ErXwobaYiN019PkySvjV",
}

DEFAULT_VOICE = "Rachel"


def resolve_voice_id(name_or_id: str) -> str:
    """Resolve a human-readable voice name or direct voice ID to a ElevenLabs voice_id.

    Args:
        name_or_id: Either a premade voice name (e.g. "Rachel") or a raw voice_id.

    Returns:
        The corresponding voice_id from _PREMADE_VOICES, or name_or_id unchanged if
        not found in the dict (pass-through for direct ID usage).
    """
    return _PREMADE_VOICES.get(name_or_id, name_or_id)


class ElevenLabsProvider:
    """TTS provider using the official ElevenLabs Python SDK (premium, API key required)."""

    async def synthesize(self, text: str, voice: str, api_key: str) -> bytes:
        """Synthesize text to MP3 bytes using ElevenLabs.

        Args:
            text: Text to synthesize.
            voice: Voice name (e.g. "Rachel") or direct voice_id.
            api_key: ElevenLabs API key. Passed explicitly — not read from os.environ.

        Returns:
            MP3 bytes on success; empty bytes on failure or auth error.
        """
        try:
            from elevenlabs.client import AsyncElevenLabs  # deferred import

            voice_id = resolve_voice_id(voice or DEFAULT_VOICE)
            client = AsyncElevenLabs(api_key=api_key)

            audio_gen = await client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                output_format="mp3_44100_128",
            )

            chunks: list[bytes] = []
            async for chunk in audio_gen:
                if isinstance(chunk, bytes):
                    chunks.append(chunk)

            return b"".join(chunks)

        except ImportError:
            logger.error("elevenlabs SDK is not installed. Run: pip install elevenlabs>=1.0.0")
            return b""
        except Exception as exc:
            logger.error("ElevenLabsProvider.synthesize() failed: %s", exc)
            return b""
