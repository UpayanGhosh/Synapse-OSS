from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


class GatewayProcessManager:
    def __init__(
        self, port: int = 8000, host: str = "127.0.0.1", timeout_sec: float = 30.0
    ):
        self.port = int(port)
        self.host = host
        self.timeout_sec = float(timeout_sec)
        self._owned_process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_reachable(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=2.0)
            return int(response.status_code) < 500
        except Exception:
            return False

    def ensure_running(self) -> subprocess.Popen | None:
        if self.is_reachable():
            return None
        cwd = Path(__file__).resolve().parents[1]
        args = [
            sys.executable,
            "-m",
            "uvicorn",
            "sci_fi_dashboard.api_gateway:app",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        self._owned_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
            cwd=str(cwd),
        )
        if not self.wait_until_ready():
            self.stop()
            raise RuntimeError(f"Gateway failed to start on {self.base_url}")
        return self._owned_process

    def wait_until_ready(self) -> bool:
        deadline = time.monotonic() + self.timeout_sec
        while time.monotonic() < deadline:
            if self.is_reachable():
                return True
            time.sleep(0.25)
        return False

    def stop(self) -> None:
        if self._owned_process is None:
            return
        self._owned_process.terminate()
        self._owned_process = None
