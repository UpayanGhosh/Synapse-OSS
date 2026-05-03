# Deploy

Two production deployment paths: container (Docker) and bare-metal Linux (systemd).

## Docker

```bash
docker build -t synapse:latest .
docker run -p 8000:8000 -v synapse-data:/home/synapse/.synapse synapse:latest
```

The image runs as a non-root user (`synapse`, uid 10001). Persistent state (DBs,
profiles, KG) lives at `/home/synapse/.synapse` inside the container — mount a
named volume there so it survives container restarts.

Healthcheck: `GET /health` (returns `{"status": "ok"|"degraded", ...}` —
see `workspace/sci_fi_dashboard/routes/health.py`).

The image expects environment variables for provider keys (`GEMINI_API_KEY`,
`OPENROUTER_API_KEY`, etc. — see CLAUDE.md). Pass via `--env` or `--env-file`,
or commit them to your `synapse.json` providers block before building (not
recommended for shared images).

## systemd (Linux servers)

1. Place repo at `/opt/synapse`, owned by user `synapse`.
2. Create `/etc/synapse/synapse.env` with environment variables (or omit — the
   unit tolerates a missing file via the leading `-` on `EnvironmentFile`).
3. `sudo cp deploy/synapse.service /etc/systemd/system/`
4. `sudo systemctl daemon-reload && sudo systemctl enable --now synapse`
5. Logs: `journalctl -u synapse -f`

The unit binds to `127.0.0.1:8000` by default. Front it with nginx/Caddy for
TLS and external exposure.

`ReadWritePaths` permits writes to `/var/lib/synapse` (recommended location for
`SYNAPSE_HOME`) and `/opt/synapse` (for in-place log/cache writes). Adjust if
your install layout differs.
