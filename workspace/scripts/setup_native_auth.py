import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = os.getenv(
    "GOG_CREDENTIALS", str(PROJECT_ROOT / "skills" / "gog" / "client_secret.json")
)
TOKEN_FILE = os.getenv("GOG_TOKEN", str(PROJECT_ROOT / "skills" / "gog" / "token.json"))


def setup():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Starting new authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
            print("Authentication successful! Token saved.")


if __name__ == "__main__":
    setup()
