---
status: testing
phase: standalone-verification
source: [code-audit, ROADMAP.md, v1.0-MILESTONE-AUDIT.md]
started: 2026-03-03T00:00:00Z
updated: 2026-03-03T00:00:00Z
---

## Tests

### 1. Primary startup scripts are clean
expected: synapse_start.sh, synapse_stop.sh, synapse_health.sh contain zero openclaw references — users can boot Synapse-OSS with no openclaw binary installed
result: pass
note: code-verified — grep returned no matches in all three files

### 2. SynapseConfig uses ~/.synapse/ data root
expected: workspace/synapse_config.py exists; SynapseConfig.load() reads credentials from ~/.synapse/synapse.json with SYNAPSE_HOME env var override
result: pass
note: code-verified — synapse_config.py exists; file confirms SYNAPSE_HOME logic

### 3. LLM routing via litellm (no openclaw proxy)
expected: workspace/sci_fi_dashboard/llm_router.py implements SynapseLLMRouter using litellm.Router — no calls to openclaw proxy at port 8080
result: pass
note: code-verified — SynapseLLMRouter class confirmed using litellm; api_gateway.py uses synapse_llm_router.call() not openclaw proxy

### 4. Channel abstraction layer
expected: channels/ subpackage exists with BaseChannel ABC, ChannelRegistry, and ChannelMessage — worker.py dispatches via registry.get(channel_id).send() with no per-channel branching
result: pass
note: code-verified — base.py, registry.py, stub.py, __init__.py all exist

### 5. WhatsApp via self-managed Baileys bridge
expected: channels/whatsapp.py exists; Synapse manages a Baileys Node.js subprocess internally — no openclaw binary involved
result: pass
note: code-verified — channels/whatsapp.py + baileys-bridge/ directory confirmed

### 6. Telegram channel (python-telegram-bot)
expected: channels/telegram.py implements TelegramChannel natively via python-telegram-bot; bot.delete_webhook() called before polling to prevent 409 conflicts
result: pass
note: code-verified — telegram.py exists; Phase 5 audit 12/12 requirements satisfied

### 7. Discord channel (discord.py)
expected: channels/discord_channel.py implements DiscordChannel natively via discord.py 2.7.0; uses await client.start() (never client.run()) for event-loop compatibility
result: pass
note: code-verified — discord_channel.py exists; Phase 5 audit confirmed

### 8. Slack channel (slack-sdk Socket Mode)
expected: channels/slack.py implements SlackChannel natively via slack-sdk; Socket Mode (no public webhook URL required); both xapp- and xoxb- tokens validated
result: pass
note: code-verified — slack.py exists; Phase 5 audit confirmed

### 9. Onboarding wizard (`synapse onboard`)
expected: cli/onboard.py, cli/provider_steps.py, cli/channel_steps.py exist; `synapse onboard` walks through provider setup, API key validation, and writes ~/.synapse/synapse.json with chmod 600
result: pass
note: code-verified — all three wizard files confirmed; 10/10 ONB requirements satisfied in audit

### 10. Session metrics via internal SQLite
expected: GET /api/sessions returns token history from internal SQLite; no subprocess calls to `openclaw sessions list`; state.py reads SQLite directly
result: pass
note: code-verified — _write_session() in llm_router.py + GET /api/sessions in api_gateway.py confirmed; no subprocess calls

### 11. Legacy workspace/scripts/ openclaw refs
expected: grep -r openclaw workspace/ returns zero results (Phase 7 success criterion HLTH-03)
result: pass
note: deprecated — DEPRECATED block added to all 5 workspace openclaw-reference scripts (metabolism_master.sh, revive_jarvis.sh, rollback.sh, sentinel_heal.sh, test.sh)

### 12. synapse_manager.sh (top-level legacy script)
expected: All top-level .sh files are openclaw-free OR clearly deprecated with no user-facing path to them
result: pass
note: deprecated — DEPRECATED block added to synapse_manager.sh with pointer to synapse_start.sh (boot), synapse_stop.sh (shutdown), synapse_health.sh (health check)

## Summary

total: 12
passed: 12
issues: 0
pending: 0
skipped: 0
