#!/usr/bin/env python3
"""
Project Sentinel (v1.0) - The Autonomy Layer
Author: Antigravity Engineer
Description: Monitors Brain (FastAPI), Body (Node), and Vitality (Disk/Swap).
             Auto-heals services and alerts on critical failures.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime

from synapse_config import SynapseConfig

# --- CONFIGURATION ---
MEMORY_SERVER_URL = "http://127.0.0.1:8989/health"
SYNAPSE_PROCESS_NAME = "synapse gateway"  # TODO Phase 4: update to Synapse bridge process name
_cfg = SynapseConfig.load()
STATE_FILE = str(_cfg.data_root / "sentinel_state.json")
LOG_FILE = str(_cfg.log_dir / "sentinel.log")
MAX_RETRIES = 3
SWAP_LIMIT_MB = 4096  # 4GB
DISK_LIMIT_PERCENT = 90


# --- UTILS ---
def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    print(entry)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except Exception as e:
        print(f"Failed to write log: {e}")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"brain_strikes": 0, "body_strikes": 0}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        log(f"State save failed: {e}", "ERROR")


def alert_macos(title, message):
    """Sends a native notification to the Mac (Fallback Voice)."""
    script = f'display notification "{message}" with title "{title}" subtitle "Sentinel Alert" sound name "Submarine"'
    subprocess.run(["osascript", "-e", script])


# --- CHECKS ---
def check_brain():
    """Checks FastAPI Health Endpoint."""
    try:
        with urllib.request.urlopen(MEMORY_SERVER_URL, timeout=5) as response:
            if response.getcode() == 200:
                return True
    except:
        return False
    return False


def check_body():
    """Checks if Synapse gateway process is running."""
    try:
        # TODO Phase 4: update process name for Synapse bridge
        # pgrep returns 0 if process found, 1 if not
        subprocess.check_call(["/usr/bin/pgrep", "-f", "synapse"], stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def check_vitals(state):
    """Checks Disk and RAM pressure."""
    dirty = False
    # 1. Disk Check
    total, used, free = shutil.disk_usage("/")
    percent_used = (used / total) * 100

    if percent_used > DISK_LIMIT_PERCENT:
        msg = f"Disk Critical: {percent_used:.1f}% used. Purging logs."
        log(msg, "CRITICAL")
        alert_macos("Disk Critical", "Disk > 90%. Purging logs.")
        log_files = glob.glob(str(SynapseConfig.load().log_dir / "*.log"))
        for f in log_files:
            try:
                os.remove(f)
            except Exception as e:
                log(f"Failed to remove {f}: {e}", "ERROR")

    # 2. Swap Check (macOS specific)
    try:
        result = subprocess.check_output(["/usr/sbin/sysctl", "vm.swapusage"]).decode("utf-8")
        match = re.search(r"used\s*=\s*(\d+\.\d+)M", result)
        if match:
            swap_used = float(match.group(1))
            if swap_used > SWAP_LIMIT_MB:
                log(f"High Swap Usage: {swap_used}MB", "WARNING")
                alert_macos("High Swap", "Memory Pressure High. Recommend Reboot.")
    except Exception as e:
        log(f"Vital check failed: {e}", "ERROR")

    # 3. RAM Pressure Check (The "Lifeboat" Protocol - Senior Advice)
    try:
        page_size = int(subprocess.check_output(["pagesize"]).decode("utf-8").strip())
        vm_stat = subprocess.check_output(["vm_stat"]).decode("utf-8")

        def get_stat(key):
            match = re.search(f"{key}:\\s+(\\d+)", vm_stat)
            return int(match.group(1)) if match else 0

        available_pages = (
            get_stat("Pages free") + get_stat("Pages inactive") + get_stat("Pages speculative")
        )
        available_ram_mb = (available_pages * page_size) / 1024 / 1024

        # --- KILL LOGIC ---
        if available_ram_mb < 500:
            log(
                f"CRITICAL RAM LOW: {available_ram_mb:.2f}MB Available. Executing Lifeboat.",
                "CRITICAL",
            )
            # Check if Ollama is running
            if (
                subprocess.run(
                    ["pgrep", "-f", "Ollama.app"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                log("Killing Ollama to save Gateway...", "WARN")
                subprocess.run(["pkill", "-9", "-f", "Ollama"], check=False)
                state["ollama_auto_killed"] = True
                alert_macos(
                    "Low Memory",
                    f"Killed AI to save Gateway. Available: {available_ram_mb:.1f}MB",
                )
                dirty = True

        # --- REVIVE LOGIC ---
        elif available_ram_mb > 1500 and state.get("ollama_auto_killed", False):
            log(
                f"RAM Stable: {available_ram_mb:.2f}MB Available. Reviving Ollama.",
                "SUCCESS",
            )
            subprocess.Popen(["open", "-g", "-a", "Ollama"])
            state["ollama_auto_killed"] = False
            alert_macos("Memory Stable", "Ollama revived by Sentinel.")
            dirty = True

    except Exception as e:
        log(f"Lifeboat/Revive check failed: {e}", "ERROR")

    return dirty


# --- REPAIR LOGIC ---
def run_sentinel():
    log("Sentinel scan started...", "DEBUG")
    state = load_state()
    dirty = False

    # 1. BRAIN CHECK
    # ... (rest of the logic)
    if not check_brain():
        state["brain_strikes"] = state.get("brain_strikes", 0) + 1
        log(f"Brain Dead (Strike {state['brain_strikes']})", "ERROR")

        if state["brain_strikes"] <= MAX_RETRIES:
            log("Attempting Brain Transplant (Restarting Service)...", "WARN")
            # Restart via LaunchAgent
            uid = subprocess.check_output(["id", "-u"]).decode().strip()
            # TODO Phase 4: update launchctl service ID for Synapse
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/ai.synapse.memory"],
                check=False,
            )
            alert_macos("Sentinel Action", "Restarted Memory Server.")
        else:
            log("Brain Critical Failure. Max retries exceeded.", "CRITICAL")
            alert_macos("CRITICAL FAILURE", "Memory Server is dead and refuses to restart.")
        dirty = True
    else:
        if state.get("brain_strikes", 0) > 0:
            log("Brain functions restored.", "SUCCESS")
            state["brain_strikes"] = 0
            dirty = True

    # 2. BODY CHECK
    if not check_body():
        state["body_strikes"] = state.get("body_strikes", 0) + 1
        log(f"Body Dead (Strike {state['body_strikes']})", "ERROR")

        if state["body_strikes"] <= MAX_RETRIES:
            log("Attempting CPR (Restarting Synapse Gateway)...", "WARN")
            # TODO Phase 4: replace with Synapse bridge start command
            subprocess.run([shutil.which("synapse_start.sh") or "./synapse_start.sh"], check=False)
            alert_macos("Sentinel Action", "Restarted Synapse Gateway.")
        else:
            log("Body Critical Failure. Max retries exceeded.", "CRITICAL")
            alert_macos("CRITICAL FAILURE", "Synapse Gateway is dead.")
        dirty = True
    else:
        if state.get("body_strikes", 0) > 0:
            log("Body pulse restored.", "SUCCESS")
            state["body_strikes"] = 0
            dirty = True

    # 3. VITALS CHECK
    if check_vitals(state):
        dirty = True

    if dirty:
        save_state(state)


if __name__ == "__main__":
    run_sentinel()
