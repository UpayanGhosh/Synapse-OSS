# TOOLS.md - Local Tool Notes

Skills define tool behavior. This file stores local setup notes.

## Runtime

- Gateway: `http://127.0.0.1:8000`
- Health: `GET /health`
- Memory DB: `~/.synapse/workspace/db/memory.db`
- Knowledge graph DB: `~/.synapse/workspace/db/knowledge_graph.db`
- Runtime config: `~/.synapse/synapse.json`

## Tool Style

- Use tools invisibly when the user wants results.
- Explain tool failures plainly.
- Do not expose raw diagnostics in chat channels.
- Prefer local/private tools when available.
- Ask before external side effects or sensitive transmission.

## Channel Formatting

- Telegram/WhatsApp: short human paragraphs, no tables.
- Discord/Slack: use reactions when they acknowledge without interrupting.
- CLI/dashboard: more structure is acceptable.

## Notes

Add local device names, voice IDs, browser setup, SSH aliases, and other non-secret
environment details here.
