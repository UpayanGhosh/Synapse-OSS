# Synapse Integrations — Quickstart

## For end users

You connect Google Calendar, Gmail, and other services to Synapse with one
command. You **never** need to visit Google Cloud Console, paste a JSON
file, or copy a client secret.

```bash
synapse integrations list
synapse integrations connect google_calendar
synapse integrations connect gmail
synapse integrations status google_calendar
synapse integrations verify google_calendar
synapse integrations disconnect gmail
```

Or, in chat:

> "connect my Google Calendar"

(owner-only — Synapse runs the OAuth flow and opens your browser)

When you run `connect`, Synapse opens your browser to Google. You sign in
with your Google account, click **Allow**, and you're done. The token is
stored at `~/.synapse/integrations/<integration>/token.json` (chmod 600).

### Pre-verification window: one extra click

Until the Synapse OAuth client passes Google's verification (a one-time
process the maintainer goes through), the consent screen will say "Google
hasn't verified this app." You'll see this **once per Google account**:

1. Click **Advanced** at the bottom-left of the consent screen.
2. Click **Go to Synapse (unsafe)**.
3. Continue with the normal consent flow.

After this one-time click, every subsequent action works seamlessly.
Once verification ships, the warning never appears.

This is the same workflow used by every OSS productivity tool that
predates its OAuth verification (n8n, Cal.com, Plane, AppFlowy, etc.).

### Privacy-conscious users: bring your own OAuth client

If you don't want to use the bundled Synapse client, you can register
your own Google Cloud project and pass the client_secret JSON:

```bash
synapse integrations connect google_calendar --client-secret ~/my-google-client.json
```

Or set `SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH=/path/to/client.json` once and
every subsequent connect uses it. Tokens are still stored locally; only
the OAuth client identity changes.

## For maintainers shipping a release

The bundled OAuth client_id and client_secret live in
`workspace/sci_fi_dashboard/integrations/registry.py`:

```python
SYNAPSE_GOOGLE_OAUTH_CLIENT = {
    "installed": {
        "client_id": "PLACEHOLDER_REPLACE_BEFORE_RELEASE.apps.googleusercontent.com",
        "client_secret": "PLACEHOLDER_NOT_ACTUALLY_SECRET_FOR_INSTALLED_APPS",
        ...
    }
}
```

To ship a real release:

1. **Create the Synapse OAuth client** (one time):
   - https://console.cloud.google.com/apis/credentials
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Type: **Desktop app**
   - Name: "Synapse"
   - Enable: Google Calendar API, Gmail API (and Drive when you ship that)

2. **Replace the placeholder strings** with the real `client_id` and
   `client_secret` issued by Google. Both ship in the package — for
   installed-app desktop OAuth Google does not treat the secret as
   confidential. (Reference:
   https://developers.google.com/identity/protocols/oauth2/native-app)

3. **Submit the OAuth verification** at https://console.cloud.google.com/apis/credentials/consent:
   - Application name: Synapse
   - Privacy policy URL (host one page)
   - Homepage URL
   - 30-second screen recording showing the full consent flow
   - Justify each scope (calendar.events, calendar.readonly,
     gmail.readonly, gmail.send, gmail.modify)
   - Submit. ETA 4–6 weeks. Cost $0.

4. **Until verification approves**, the "unverified app" warning shows
   on first connect. Document the one-time Advanced → Continue click in
   your release notes.

That's the full one-time setup. Adding new integrations later is just a
new `IntegrationDefinition` entry — no UX or CLI plumbing.

## Adding a new integration

1. Add an entry to `registry.py` with `name`, `display_name`,
   `auth_type`, `scopes`, `google_client_config`, and any
   `legacy_synapse_json_keys` for backwards-compatibility.

2. (Optional) Add a verify handler to `verify_handlers.py` that calls
   the integration's API to confirm access works.

3. (Optional) Add an MCP server in `mcp_servers/` if Synapse needs to
   expose tools to the LLM. The hub keeps
   `mcp.builtin_servers.<name>.token_path` populated automatically.

4. Done. `synapse integrations connect <name>` will work, the chat
   tool's alias map will pick it up, and onboarding will list it.

## Architecture details

See `docs/superpowers/specs/2026-05-08-integrations-hub-design.md` for
the full architecture, OAuth flow internals, token-store layout, and
the V3 backlog.
