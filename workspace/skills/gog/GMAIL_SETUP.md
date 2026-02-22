# Setting up Gmail for GOG

To read emails (like OTPs), you cannot use the default GOG credentials. You must create your own Google Cloud Project.

## Steps

1.  **Go to Google Cloud Console**: https://console.cloud.google.com/
2.  **Create a New Project** (e.g., "Jarvis-Gmail").
3.  **Enable APIs**:
    - Search for **"Gmail API"** and enable it.
    - Search for **"Google Calendar API"** and enable it (if you want calendar too).
4.  **Configure OAuth Consent Screen**:
    - User Type: **External**.
    - App Name: "Jarvis".
    - Test Users: Add your email (`user@example.com`).
5.  **Create Credentials**:
    - Go to **Credentials** > **Create Credentials** > **OAuth Client ID**.
    - Application Type: **Desktop App**.
    - Name: "GOG CLI".
    - Download the JSON file (it will look like `client_secret_xgSF...json`).
6.  **Save the file**:
    - Rename it to `client_secret.json`.
    - Place it in this folder (`/path/to/openclaw/workspace/skills/gog/client_secret.json`).
7.  **Run Setup**:
    - `gog auth credentials workspace/skills/gog/client_secret.json`
    - `gog auth add user@example.com --services gmail,calendar`
