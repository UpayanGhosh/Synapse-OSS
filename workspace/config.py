import os

from utils.env_loader import load_env_file

# Load .env from project root (walks up from this file to find it)
load_env_file()

# Server
SERVER_PORT = int(os.getenv("SERVER_PORT", "8989"))
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")

# Models
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

# Audio Processing
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Distributed Inference
WINDOWS_PC_IP = os.getenv("WINDOWS_PC_IP")

# Users
ADMIN_PHONE = os.getenv("ADMIN_PHONE")
VIP_PHONE = os.getenv("VIP_PHONE")
