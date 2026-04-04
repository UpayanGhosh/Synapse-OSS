"""
Ollama Setup Script — run before the comparison tests.

Usage:
    python tests/reliability/setup_ollama.py

What it does:
1. Checks if Ollama binary is installed
2. Starts the Ollama server if not running
3. Pulls nomic-embed-text if not present
4. Verifies the Python ollama package is installed
5. Runs a quick smoke test (embed "hello world")
6. Prints a status report
"""

import subprocess
import sys
import time
import os
import json
import urllib.request
import urllib.error

OLLAMA_BINARY = r"C:\Users\Shorty0_0\AppData\Local\Programs\Ollama\ollama.exe"
OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL = "nomic-embed-text"

STEP = 0


def step(msg):
    global STEP
    STEP += 1
    print(f"\n[{STEP}] {msg}")


def ok(msg=""):
    print(f"    [OK] {msg}")


def fail(msg):
    print(f"    [FAIL] {msg}")
    sys.exit(1)


def warn(msg):
    print(f"    [WARN] {msg}")


# ---------------------------------------------------------------------------
# 1. Check binary
# ---------------------------------------------------------------------------
step("Checking Ollama binary")
if os.path.exists(OLLAMA_BINARY):
    ok(f"Found: {OLLAMA_BINARY}")
else:
    # Try PATH
    import shutil
    found = shutil.which("ollama")
    if found:
        OLLAMA_BINARY = found
        ok(f"Found on PATH: {OLLAMA_BINARY}")
    else:
        fail(
            "Ollama binary not found.\n"
            "  Install from: https://ollama.com/download\n"
            "  Windows: download OllamaSetup.exe and run it."
        )

# ---------------------------------------------------------------------------
# 2. Check / start server
# ---------------------------------------------------------------------------
step("Checking Ollama server")


def server_alive():
    try:
        req = urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3)
        return req.status == 200
    except Exception:
        return False


if server_alive():
    ok("Already running")
else:
    warn("Not running — starting server...")
    import subprocess

    subprocess.Popen(
        [OLLAMA_BINARY, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    for attempt in range(15):
        time.sleep(1)
        if server_alive():
            ok(f"Started (took {attempt + 1}s)")
            break
    else:
        fail("Server failed to start after 15s. Check Ollama logs.")

# ---------------------------------------------------------------------------
# 3. Check / pull model
# ---------------------------------------------------------------------------
step(f"Checking model: {MODEL}")
raw = urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5).read()
tags = json.loads(raw)
model_names = [m["name"] for m in tags.get("models", [])]

if any(MODEL in name for name in model_names):
    ok(f"Model already present: {MODEL}")
else:
    warn(f"Model not found. Pulling {MODEL}... (this downloads ~274 MB)")
    result = subprocess.run(
        [OLLAMA_BINARY, "pull", MODEL],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        ok(f"Pulled {MODEL}")
    else:
        fail(f"Failed to pull model:\n{result.stderr}")

# ---------------------------------------------------------------------------
# 4. Check Python package
# ---------------------------------------------------------------------------
step("Checking Python ollama package")
try:
    import ollama  # noqa: F401
    ok("ollama Python package installed")
except ImportError:
    warn("Not installed — installing now...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "ollama", "-q"])
    ok("Installed")

# ---------------------------------------------------------------------------
# 5. Smoke test
# ---------------------------------------------------------------------------
step("Smoke test — embedding 'hello world'")
try:
    import ollama

    client = ollama.Client(host=OLLAMA_HOST)
    r = client.embeddings(model=MODEL, prompt="hello world")
    dims = len(r.embedding)
    if dims == 768:
        ok(f"Got {dims}-dim vector")
    else:
        fail(f"Expected 768 dims, got {dims}")
except Exception as e:
    fail(f"Smoke test failed: {e}")

# ---------------------------------------------------------------------------
# 6. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("  Ollama is ready for comparative testing!")
print(f"  Server:  {OLLAMA_HOST}")
print(f"  Model:   {MODEL}")
print("=" * 60)
print("\nRun the comparison tests with:")
print("  cd workspace && pytest tests/reliability/test_phase4_provider_comparison.py -v --run-slow -s")
print()
