import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = os.getenv('GOG_CREDENTIALS', '/path/to/openclaw/workspace/skills/gog/client_secret.json')
TOKEN_FILE = os.getenv('GOG_TOKEN', '/path/to/openclaw/workspace/skills/gog/token.pickle')

def setup():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Starting new authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
            print("Authentication successful! Token saved.")

if __name__ == "__main__":
    setup()
