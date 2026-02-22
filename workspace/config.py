
import os
from dotenv import load_dotenv

# Load .env from project root
# config.py is in /path/to/openclaw/workspace/
# .env is in /path/to/openclaw/
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(ROOT_DIR, ".env")
load_dotenv(ENV_PATH)

# Architecture
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8989"))
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")

# Models
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

# Users
ADMIN_PHONE = os.getenv("ADMIN_PHONE")
VIP_PHONE = os.getenv("VIP_PHONE")

# Validation
if not ADMIN_PHONE:
    print("WARNING: ADMIN_PHONE not set in .env")

def get_redis_config():
    return {
        "broker": REDIS_URL,
        "backend": REDIS_URL
    }
