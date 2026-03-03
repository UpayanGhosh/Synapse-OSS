"""
CLI utility to transcribe an audio file using the Groq Whisper backend.

Usage:
    python do_transcribe.py <path/to/audio.ogg>
"""
import sys
from pathlib import Path

# Resolve workspace root dynamically — works on Mac, Windows, Linux
WORKSPACE_ROOT = Path(__file__).resolve().parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from utils.env_loader import load_env_file

load_env_file(anchor=Path(__file__))

from db.audio_processor import AudioProcessor

if len(sys.argv) < 2:
    print("Usage: python do_transcribe.py <audio_file_path>")
    sys.exit(1)

file_path = Path(sys.argv[1])
if not file_path.exists():
    print(f"File not found: {file_path}")
    sys.exit(1)

processor = AudioProcessor()
result = processor.transcribe(str(file_path))
print(f"TRANSCRIPTION_START\n{result}\nTRANSCRIPTION_END")
