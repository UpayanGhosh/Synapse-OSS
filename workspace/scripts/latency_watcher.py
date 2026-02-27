import asyncio
import websockets
import subprocess
import sys
import time
import os
from datetime import datetime

# Import Config
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import config

TARGET_SENDER = config.ADMIN_PHONE
if not TARGET_SENDER:
    TARGET_SENDER = "UNKNOWN"

WS_URL = f"ws://{config.SERVER_HOST}:{config.SERVER_PORT}/ws/status"
PING_INTERVAL = 5  # Send ping every 5s
TIMEOUT = 10.0  # If pong takes > 10s, alarm


async def send_whatsapp(msg):
    try:
        print(f"ALARM: {msg}")
        # Fire and forget
        subprocess.Popen(
            ["openclaw", "message", "send", "-t", TARGET_SENDER, "-m", msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"Failed to send WA: {e}")


async def wait_for_port(host, port, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(1)
    return False


async def monitor():
    print(f"Starting WS Latency Watcher for {TARGET_SENDER}")

    # Wait for server to bind port
    try:
        is_up = await wait_for_port(config.SERVER_HOST, config.SERVER_PORT)
        if not is_up:
            print(f"Timeout waiting for Port {config.SERVER_PORT}. Exiting.")
            sys.exit(1)
    except Exception as e:
        print(f"Error checking port: {e}")

    print(f"Connecting to {WS_URL}...")

    last_pong = time.time()

    while True:
        try:
            async with websockets.connect(WS_URL) as websocket:
                print("Connected to Server.")
                last_pong = time.time()

                while True:
                    # 1. Send Ping
                    try:
                        await websocket.send("ping")
                        send_time = time.time()

                        # 2. Wait for Pong with timeout
                        response = await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                        if response == "pong":
                            latency = (time.time() - send_time) * 1000
                            last_pong = time.time()
                            # print(f"Heartbeat: {latency:.1f}ms") # Verbose
                        elif response.startswith("STATUS:BUSY"):
                            print(f"Server Busy: {response}")
                            # Reset timer implicitly
                            last_pong = time.time()

                    except asyncio.TimeoutError:
                        print("Timeout waiting for Pong!")
                        diff = time.time() - last_pong
                        await send_whatsapp(f"[WARN] Gateway Unresponsive! Lag: {diff:.1f}s")

                    await asyncio.sleep(PING_INTERVAL)

        except ConnectionRefusedError:
            print("Connection Refused - Server Down?")
            await send_whatsapp("[WARN] Gateway Down! Connection refused.")
            await asyncio.sleep(10)  # Wait before retry
        except Exception as e:
            print(f"Watcher Error: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("Watcher stopped.")
