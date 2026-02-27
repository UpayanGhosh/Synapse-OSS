import os
import json
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None  # Not available on Windows -- use filelock fallback
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64
from email.message import EmailMessage

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = os.getenv(
    "GOG_CREDENTIALS", str(PROJECT_ROOT / "skills" / "gog" / "client_secret.json")
)
TOKEN_FILE = os.getenv("GOG_TOKEN", str(PROJECT_ROOT / "skills" / "gog" / "token.json"))


class GoogleNative:
    def __init__(self):
        self.creds = None
        self.service_gmail = None
        self.service_calendar = None
        self.authenticate()

    def authenticate(self):
        if os.path.exists(TOKEN_FILE):
            self.creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, "w") as token:
                if fcntl:
                    fcntl.flock(token, fcntl.LOCK_EX)
                token.write(self.creds.to_json())
                if fcntl:
                    fcntl.flock(token, fcntl.LOCK_UN)

        self.service_gmail = build("gmail", "v1", credentials=self.creds)
        self.service_calendar = build("calendar", "v3", credentials=self.creds)

    def search_emails(self, query="OTP", max_results=5, user_tier=None):
        """
        user_tier must be 0 (Admin) or 1 (VIP) to access emails.
        Guest (2) access is DENIED immediately.
        """
        # HARD GATEKEEPING
        if user_tier is None or user_tier > 1:
            print(f"[Security] Denied Gmail Access for Tier {user_tier}")
            return ["ACCESS DENIED: Insufficient permissions to read emails."]

        try:
            results = (
                self.service_gmail.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            messages = results.get("messages", [])

            summary = []
            for msg in messages:
                txt = (
                    self.service_gmail.users()
                    .messages()
                    .get(userId="me", id=msg["id"])
                    .execute()
                )
                payload = txt.get("payload", {})
                headers = payload.get("headers", [])
                subject = next(
                    (h["value"] for h in headers if h["name"] == "Subject"),
                    "No Subject",
                )
                sender = next(
                    (h["value"] for h in headers if h["name"] == "From"), "Unknown"
                )
                snippet = txt.get("snippet", "")
                summary.append(
                    f"From: {sender} | Subject: {subject} | Snippet: {snippet}"
                )
            return summary
        except Exception as e:
            return [f"Error searching emails: {str(e)}"]


if __name__ == "__main__":
    # Test run
    g = GoogleNative()
    print(g.search_emails())
