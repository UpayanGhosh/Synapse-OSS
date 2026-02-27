import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone
import requests

# Set up logging to the same file monitor.py reads
LOG_DIR = "/tmp/openclaw"
LOG_FILE = os.path.join(LOG_DIR, f"openclaw-{datetime.now().strftime('%Y-%m-%d')}.log")


def log_event(message, level="INFO"):
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    log_entry = {
        "0": json.dumps({"subsystem": "transcriber"}),
        "1": message,
        "2": "",
        "_meta": {"logLevelName": level, "date": timestamp},
        "time": timestamp,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Logging error: {e}")


def get_audio_duration(file_path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout)


def transcribe_audio(file_path):
    # Try multiple common environment variables for Gemini API Key
    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
    )

    # Fallback: Try to read from openclaw.json if still not found
    if not api_key:
        try:
            config_path = os.path.join(os.path.expanduser("~/.openclaw"), "openclaw.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                    # Try to find a key in skills.entries (found AIza... key here previously)
                    skills_entries = config.get("skills", {}).get("entries", {})
                    for entry in skills_entries.values():
                        if "apiKey" in entry and entry["apiKey"].startswith("AIza"):
                            api_key = entry["apiKey"]
                            break
        except Exception:
            pass

    if not api_key:
        log_event("GEMINI_API_KEY not found", "ERROR")
        return "Error: No Google API Key found. Please set GEMINI_API_KEY in your environment."

    filename = os.path.basename(file_path)
    log_event(f"Starting legacy-free transcription for: {filename}")

    try:
        duration = get_audio_duration(file_path)
        duration_mins = duration / 60
        log_event(f"Audio duration: {duration_mins:.2f} minutes")

        # 3 minute chunks (180 seconds)
        chunk_size = 180
        num_chunks = int(duration // chunk_size) + (1 if duration % chunk_size > 0 else 0)

        log_event(f"Splitting into {num_chunks} chunks using ffmpeg")
        full_transcript = []

        for i in range(num_chunks):
            start_time = i * chunk_size
            log_event(f"Processing chunk {i+1}/{num_chunks} (starts at {start_time}s)...")
            temp_chunk = f"temp_chunk_{i}.ogg"

            # Extract chunk using ffmpeg
            res = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(start_time),
                    "-t",
                    str(chunk_size),
                    "-i",
                    file_path,
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    temp_chunk,
                ],
                capture_output=True,
                text=True,
            )

            if not os.path.exists(temp_chunk) or os.path.getsize(temp_chunk) == 0:
                log_event(f"Chunk {i+1} ffmpeg failed: {res.stderr}", "ERROR")
                continue

            with open(temp_chunk, "rb") as f:
                import base64

                audio_data = base64.b64encode(f.read()).decode("utf-8")

            # Use Groq Whisper API (whisper-large-v3) for fast, multilingual transcription
            # User specifically requested Bengali support
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                log_event("GROQ_API_KEY not found", "ERROR")
                continue

            url = "https://api.groq.com/openai/v1/audio/transcriptions"

            # Prepare file for upload
            # Note: We need to send the actual file bytes, requests handles multipart/form-data
            with open(temp_chunk, "rb") as f:
                files = {"file": (temp_chunk, f, "audio/ogg")}
                data = {
                    "model": "whisper-large-v3",
                    "language": "bn",  # Force Bengali as requested, though model is good at auto-detect
                    "response_format": "json",
                    "temperature": 0.0,
                }

                try:
                    resp = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        files=files,
                        data=data,
                        timeout=60,  # Groq is fast, but give it time
                    )

                    if resp.status_code == 200:
                        text = resp.json().get("text", "")
                        full_transcript.append(text)
                        log_event(f"Chunk {i+1} success: {len(text)} chars")
                    else:
                        error_msg = resp.text
                        log_event(
                            f"Chunk {i+1} failed ({resp.status_code}): {error_msg[:100]}", "ERROR"
                        )

                except Exception as e:
                    log_event(f"Chunk {i+1} exception: {str(e)}", "ERROR")

            if os.path.exists(temp_chunk):
                os.remove(temp_chunk)

        final_text = "\n".join(full_transcript)
        log_event(f"Transcription complete. Total length: {len(final_text)} chars")

        # Save the final transcription to a .txt file next to the original audio
        txt_output = os.path.splitext(file_path)[0] + ".txt"
        with open(txt_output, "w") as f:
            f.write(final_text)
        log_event(f"Saved transcript to: {os.path.basename(txt_output)}")

        return final_text

    except Exception as e:
        log_event(f"Critical error: {str(e)}", "ERROR")
        return f"Error: {str(e)}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe_v2.py <path_to_audio>")
        sys.exit(1)

    result = transcribe_audio(sys.argv[1])
    print(result)
