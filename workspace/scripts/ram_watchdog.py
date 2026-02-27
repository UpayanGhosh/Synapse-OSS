import psutil
import time
import os
import subprocess
import requests

# Threshold: 85% RAM Usage
THRESHOLD = 85.0
CHECK_INTERVAL = 60  # Check every 1 minute

def get_ram_usage():
    return psutil.virtual_memory().percent

def send_alert(msg):
    # Send WhatsApp alert via OpenClaw Gateway (if running)
    # Using the local agent to send message is complex from a standalone script without auth.
    # For now, we'll just log it. In a real setup, we'd hit the webhook.
    print(f"[WARN] ALERT: {msg}")

def free_memory():
    print("[CLEAN] Attempting to free memory (Safe Mode)...")
    
    # 1. Kill Chrome/Brave Renderers (They eat the most RAM)
    try:
        # Pkill is standard and doesn't need sudo for owned processes
        subprocess.run(["pkill", "-f", "Brave Browser Helper"], check=False)
        subprocess.run(["pkill", "-f", "Google Chrome Helper"], check=False)
        send_alert("[CLEAN] Cleared Browser Renderers to save RAM.")
    except Exception as e:
        print(f"Error killing browser: {e}")

    # 2. Restart Celery Workers (They accumulate memory over time)
    # This is drastic, so only if VERY critical (>90%)?
    # Keeping it simple for now: just browsers.

def main():
    print(f"👀 RAM Watchdog Started. Threshold: {THRESHOLD}%")
    while True:
        usage = get_ram_usage()
        if usage > THRESHOLD:
            msg = f"RAM Critical: {usage}%! System under load."
            send_alert(msg)
            # free_memory() # Uncomment if we have a safe kill-list
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
