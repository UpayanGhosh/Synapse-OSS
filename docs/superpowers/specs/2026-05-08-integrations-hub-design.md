# Synapse Integrations Hub — Design

## Goal

End-user friction for connecting Google Calendar / Gmail / Notion / Slack /
… should be **one click**: "Sign in with Google". Zero Cloud Console
visits, zero JSON paths, zero environment variables. Synapse owns one
verified OAuth client and ships it bundled. End users only ever see the
Google consent screen.

This is exactly how Claude Desktop, Notion, ChatGPT, n8n, Cal.com handle
Google integrations. Self-hosted OSS apps that want enterprise-grade UX
all converge on the same pattern.

## Non-goals

- Hosting an OAuth relay server. Synapse stays self-hosted; the OAuth
  client_id is bundled in the Python package, not served from a backend.
- Replacing the existing per-user `--client-secret` BYO path. Power users
  who don't trust the bundled client can keep using their own.
- Wiring every integration on day one. Calendar + Gmail land first
  because their MCP servers and registry entries already exist; Notion
  and Slack ship registry stubs (auth_type recorded, scopes empty) and
  full wiring lands in a follow-up.

## Architecture

```
workspace/sci_fi_dashboard/integrations/
  __init__.py              public exports
  errors.py                IntegrationError
  registry.py              IntegrationDefinition catalogue + bundled OAuth client
  oauth_flow.py            run_oauth_desktop_flow() — InstalledAppFlow.from_client_config
  token_store.py           ~/.synapse/integrations/<name>/token.json + legacy fallback
  config.py                synapse.json integrations section + legacy mcp.builtin_servers mirroring
  verify_handlers.py       per-integration smoke checks (calendar, gmail)
  manager.py               connect / verify / status / disconnect / list_integrations

workspace/cli/integrations_commands.py   Typer-friendly thin wrappers
workspace/synapse_cli.py                 `synapse integrations {connect,verify,status,disconnect,list,info}`
workspace/sci_fi_dashboard/tool_registry.py   `connect_integration` chat tool (owner-only)
```

### IntegrationDefinition (registry.py)

Frozen dataclass capturing everything the hub needs about one service:

| Field | Purpose |
|---|---|
| `name` | stable id (e.g. `google_calendar`) |
| `display_name` | shown in CLI / chat (e.g. "Google Calendar") |
| `auth_type` | `oauth2_desktop` / `oauth2_workspace` / `bot_token` / `api_key` |
| `scopes` | OAuth scopes (Google) |
| `google_client_config` | bundled `from_client_config` payload (client_id, redirect_uris) |
| `legacy_token_paths` | older paths to read for backwards-compat (e.g. `~/.synapse/google/calendar_token.json`) |
| `legacy_synapse_json_keys` | dotted keys to keep populated so existing MCP servers find the token without modification |
| `available` | whether ConnectIntegration is wired today (notion/slack: false) |
| `description` / `setup_notes` | shown in `synapse integrations info <name>` |

### Bundled OAuth client (registry.py → SYNAPSE_GOOGLE_OAUTH_CLIENT)

```python
SYNAPSE_GOOGLE_OAUTH_CLIENT = {
    "installed": {
        "client_id": "PLACEHOLDER_REPLACE_BEFORE_RELEASE.apps.googleusercontent.com",
        "client_secret": "PLACEHOLDER_NOT_ACTUALLY_SECRET_FOR_INSTALLED_APPS",
        ...
    }
}
```

The `client_secret` for **installed-app desktop OAuth** is not actually
treated as confidential by Google — see Google's installed-app docs. It
ships with the app. This is industry-standard for desktop OAuth and is
what every CLI/desktop OSS app does (gh, gcloud, vscode, etc.).

The hub refuses to run the OAuth flow while the client_id starts with
`"PLACEHOLDER"` UNLESS the user explicitly passes `--client-secret` or
sets `SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH`. This is the safety net during
the pre-verification window.

### Token storage

```
~/.synapse/integrations/google_calendar/token.json   ← canonical
~/.synapse/google/calendar_token.json                 ← legacy fallback
```

`find_existing_token()` prefers the canonical path, falls back to legacy.
On `connect`, the token is always saved to the canonical path; the
manager's `verify` migrates legacy installs forward without user action.

### Legacy synapse.json mirroring

```json
{
  "integrations": {
    "google_calendar": {
      "enabled": true,
      "token_path": "~/.synapse/integrations/google_calendar/token.json",
      "auth_type": "oauth2_desktop",
      "scopes": ["...calendar.readonly", "...calendar.events"],
      "account_email": "user@gmail.com",
      "connected_at": "2026-05-08T..."
    }
  },
  "mcp": {
    "builtin_servers": {
      "calendar": {
        "enabled": true,
        "token_path": "~/.synapse/integrations/google_calendar/token.json"
      }
    }
  }
}
```

`mcp_servers/calendar_server.py` continues to read
`mcp.builtin_servers.calendar.token_path` — no change required there.

### Chat tool

`connect_integration` is owner-only and serial. User in chat:

> "connect my Google Calendar"

The tool:
1. Normalizes "Google Calendar" → `google_calendar` via the alias map.
2. Calls `manager.connect("google_calendar")` in a worker thread.
3. The OAuth flow opens the user's browser (host where the gateway runs,
   which for a typical self-hosted Synapse install IS the user's laptop).
4. User signs in, clicks Allow, the consent window closes itself.
5. Tool returns a verified payload with account email + token path.

Total chat-side time: ~10–30 seconds depending on how fast the user types
their Google password.

## Maintainer responsibilities (one-time)

This section is the action checklist for whoever ships the verified
Synapse OAuth client.

1. **Register the OAuth client** in Google Cloud Console under your
   project of choice ("Synapse" recommended). Application type:
   **Desktop app**. Redirect URI: `http://localhost`.

2. **Copy the issued credentials** into
   `workspace/sci_fi_dashboard/integrations/registry.py` →
   `SYNAPSE_GOOGLE_OAUTH_CLIENT["installed"]`. Replace **both**
   `client_id` and `client_secret` (the secret is bundled, not actually
   secret for installed apps).

3. **Submit OAuth verification** with Google:
   - Privacy policy URL (one page on synapse.dev or wherever)
   - Homepage URL
   - 30-second screen recording showing the consent flow
   - Justification per scope (calendar.events: "user asks Synapse to
     read/create their events through chat"; gmail.modify: "user asks
     Synapse to draft and send replies via chat with explicit
     confirmation")
   - Cost: $0
   - Timeline: 4–6 weeks
   - Status: pending until approved

4. **Until verification ships**, end users see "Google hasn't verified
   this app" once. They click `Advanced → Go to Synapse (unsafe)` once.
   After that, the smooth flow.

5. **After verification ships**, no warning ever again. Same UX as
   Claude Desktop / Notion / ChatGPT.

The OAuth client_id is **public** — it's safe (and necessary) to bundle
in the Synapse-OSS git repo. The "secret" is, per Google docs, also
public for installed apps. Anyone forking Synapse can either keep using
the official Synapse client_id (their consent screen will show "Synapse")
or substitute their own via `SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH`.

## Adding a new integration

1. Add an `IntegrationDefinition` to `registry.py` with name, scopes,
   `google_client_config` (or `auth_type` + custom flow), legacy paths,
   description.

2. (Optional) Add a verify handler to `verify_handlers.py` — pure
   function `(credentials) -> dict` that calls the integration's API
   to confirm access works.

3. Run `synapse integrations connect <name>`. Done.

4. Add the integration's MCP server (if any) to `mcp_servers/`. The
   `legacy_synapse_json_keys` field on the definition controls which
   `mcp.builtin_servers.<x>.token_path` keys the hub keeps populated so
   the MCP server keeps reading them transparently.

## Acceptance

- [x] `from sci_fi_dashboard.integrations import connect, verify, status,
      disconnect, list_integrations` works.
- [x] `synapse integrations list` shows google_calendar / gmail / notion
      / slack.
- [x] `synapse integrations connect google_calendar` runs OAuth
      (rejects with placeholder warning until real client_id ships, or
      until `--client-secret` overrides).
- [x] Tokens land in `~/.synapse/integrations/<name>/token.json`.
- [x] Legacy `mcp.builtin_servers.calendar.token_path` is mirrored so
      existing MCP server keeps working without changes.
- [x] Chat tool `connect_integration` is owner-only, accepts integration
      name aliases (calendar, gmail, gcal, notion, slack), runs OAuth in
      a worker thread, returns verified receipt.
- [x] Existing `synapse calendar connect --client-secret <path>` flow
      continues to work for power users / dev testing.

## V3 backlog

- Notion workspace OAuth (different flow — workspace-scoped tokens).
- Slack bot-token entry (interactive paste during onboarding).
- "Connect from chat" UX where the gateway runs on a remote host:
  fall back to device-code OAuth flow (the user runs the auth on their
  laptop, types a code on the remote gateway).
- Token refresh telemetry surfaced in `synapse memory memory-health`.
- Multiple Google accounts per integration (research item — unclear
  whether users want this or one-account-per-service is fine).
