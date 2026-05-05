# Onboarding Bugs And Fixes

This file tracks real errors encountered while installing and onboarding Synapse on a fresh
system. Each entry should capture the exact symptom, environment, suspected cause, fix, and
verification command.

## How To Add An Error

Paste the raw error output into the chat. For each issue, we will record:

- **Status:** `new`, `investigating`, `fixed`, `verified`, or `deferred`
- **Where it happened:** command, step, OS, branch
- **Exact error:** raw terminal output or log snippet
- **Likely cause:** what appears to be broken
- **Fix:** code, docs, config, or user action
- **Verification:** command or behavior that proves the fix

## Issues

### 1. OpenAI Codex OAuth refreshes the device code too aggressively

- **Status:** fixed, pending verification
- **Where it happened:** `synapse onboard` provider setup, OpenAI Codex / ChatGPT subscription OAuth
- **Exact error:** Browser opens `https://auth.openai.com/codex/device`, redirects to ChatGPT login, but if login is not completed within roughly 10-15 seconds the terminal refreshes the generated authentication code and opens/redirects again.
- **Expected behavior:** Onboarding should show one device-code prompt and keep polling that same code until the user completes login, the code naturally expires, or a real error occurs. It should not regenerate a fresh code just because the user needs more time to log in.
- **Likely cause:** `poll_device_code()` raises after three `"device authorization is unknown"` poll responses, and `openai_codex_device_flow()` catches that condition by requesting a fresh code once. At a 5 second polling interval, this creates the observed 10-15 second refresh loop.
- **Fix:** Keep polling the current device code until normal expiry and remove the automatic fresh-code retry in onboarding. Surface guidance only if the single code ultimately fails or expires.
- **Verification:** Add/update tests proving OpenAI Codex onboarding calls `login_device_code()` only once for an unknown-device-auth failure, and that polling does not raise after only three unknown responses.

### 2. OpenAI Codex onboarding does not let the user choose a model

- **Status:** fixed, pending verification
- **Where it happened:** `synapse onboard` provider setup, OpenAI Codex model mapping
- **Exact error:** After OpenAI Codex login succeeds, onboarding silently defaults model mappings to `openai_codex/gpt-5.4` instead of asking which model the user wants.
- **Expected behavior:** Interactive onboarding should always give the user a model-selection prompt, including a manual model entry option, even if the curated/live catalog currently has only one OpenAI Codex model.
- **Likely cause:** `_KNOWN_MODELS["openai_codex"]` contains only `openai_codex/gpt-5.4`, and `_build_model_mappings_interactive()` has a single-model collapse path that auto-assigns the only model to all roles.
- **Fix:** Remove the interactive single-model collapse so the picker still appears and the manual-entry escape hatch remains available.
- **Verification:** Add a test for single-model interactive mapping that proves `prompter.select()` is called and a manually entered model can be used.

### 3. Fresh onboarding defaults to Bengali/Banglish style

- **Status:** fixed, pending verification
- **Where it happened:** Fresh chat after onboarding / default persona behavior
- **Exact error:** Synapse responds in Banglish or Bengali-English mix even when the user did not select that language or style.
- **Expected behavior:** A fresh OSS install should default to neutral English, or to whatever language/style the onboarding wizard explicitly collected from the user. Bengali/Banglish should only appear when the profile, examples, detected user messages, or explicit preferences justify it.
- **Likely cause:** Several runtime prompt paths hardcode Banglish as the casual/local-language flavor. Low `banglish_ratio` currently still compiles to "Primarily English with occasional Banglish flavor", compact casual prompts say "Banglish when it fits", and the legacy persona prompt injects "Required Bengali/Banglish Keywords".
- **Fix:** Replace Banglish-specific defaults with neutral language/style wording, collect region/locality/preferred language during onboarding, and instruct Synapse to ask the user for local-language examples when confidence is low.
- **Verification:** Add/update tests proving default SBS prompt compilation contains no Banglish/Bengali instruction when the ratio is unset or zero, and that compact casual prompts are language-neutral by default.

### 4. No obvious reset command for re-onboarding

- **Status:** fixed, pending verification
- **Where it happened:** Tester/developer workflow after a previous successful onboarding
- **Exact error:** Users can get stuck with existing `~/.synapse` state and there is no obvious reset button/command to wipe or back up onboarding state before testing a different setup.
- **Expected behavior:** Synapse should expose a clear reset flow that backs up current data, lets users choose reset scope, and optionally launches onboarding again.
- **Likely cause:** Reset behavior exists as a hidden `synapse onboard --reset ...` flag, but there is no top-level `synapse reset` command or documented re-onboard workflow.
- **Fix:** Add a `synapse reset` command with safe backup semantics and an optional `--reonboard` flag; document reset scopes in README/HOW_TO_RUN.
- **Verification:** Add CLI tests proving `synapse reset --scope config --yes` backs up `synapse.json`, rejects invalid scopes, and can dispatch into onboarding when `--reonboard` is used.

### 5. Provider compatibility cannot be tested affordably by one maintainer

- **Status:** fixed, pending verification
- **Where it happened:** Release/testing strategy for the full onboarding provider list
- **Exact error:** Synapse lists 25 providers, but a maintainer cannot realistically buy and maintain credentials for every provider just to know whether onboarding still works.
- **Expected behavior:** Provider correctness should be tested with a cheap contract suite for every provider and opt-in live smoke tests only when credentials/services are available.
- **Likely cause:** Provider validation lived inside onboarding logic without a dedicated test matrix or documented live-test policy.
- **Fix:** Add `tests/providers/test_provider_contracts.py` for mocked provider contract coverage, `tests/providers/test_provider_live.py` for opt-in credential-based smoke tests, pytest flags for live provider tests, and provider testing docs.
- **Verification:** Run provider contract tests on every PR; run live tests before release for available provider credentials.

### 6. Chat reports "Invalid API key" after Gemini validated during onboarding

- **Status:** fixed, pending verification
- **Where it happened:** `synapse chat` after onboarding with Gemini
- **Exact error:** `Error: Gateway chat failed: HTTP 401: {"detail":"Invalid API key"}` followed by `Diagnostic hint: run /status, then synapse verify.`
- **Expected behavior:** If Gemini validated during onboarding, chat should not imply the Gemini provider key is invalid when the 401 came from Synapse gateway auth. The CLI should retry a stale token mismatch where possible and explain gateway-token fixes clearly.
- **Likely cause:** The string `Invalid API key` is emitted by `sci_fi_dashboard.middleware.validate_api_key()` when the request `x-api-key` does not match the gateway token. The CLI sends `SYNAPSE_GATEWAY_TOKEN` first, so a stale shell env token can override the current `synapse.json gateway.token`.
- **Fix:** Make the chat client retry gateway 401 auth failures with the alternate env/config token, then raise a gateway-specific error that says this is not the LLM provider key. Improve the chat diagnostic hint for gateway auth mismatches.
- **Verification:** Add tests for stale env-token retry, final gateway-auth error wording, and the CLI diagnostic hint.

### 7. Gemini key validates but selected Gemini/Gemma model later rate-limits

- **Status:** fixed, pending verification
- **Where it happened:** Gemini onboarding and first chat/model smoke tests
- **Exact error:** A just-created Gemini API key can pass authentication, but some models return `429 RESOURCE_EXHAUSTED` with quota details such as `limit: 0` for the specific model.
- **Expected behavior:** Onboarding should validate against a model that is broadly usable on current free-tier projects, should not save a provider when validation hits quota, and should not make alphabetical `/models` sorting nudge users toward Gemma/Pro models before Flash models.
- **Likely cause:** Gemini API quotas are per Google Cloud project and per model, not per API key. Validation used `gemini-2.0-flash`, while the live model picker could select different models such as `gemma-4-*` or `gemini-2.5-pro`, each with separate quota behavior.
- **Fix:** Switch Gemini validation to `gemini-2.5-flash-lite`, treat `RateLimitError` as failed readiness instead of accepted success, and sort Gemini live catalog entries so Flash-Lite/Flash appear before Pro/Gemma.
- **Verification:** Add tests for Gemini validation model choice, quota rejection, and live catalog sort order; run live 1-token smoke checks when credentials are available.

### 8. Synapse fails to switch from quirky/casual to professional on request

- **Status:** fixed, unit verified, pending live verification
- **Where it happened:** Chat prompt injection / SBS tone adaptation
- **Exact error:** User asks Synapse to become professional or stop being witty/quirky, but the reply stays close-friend/casual.
- **Expected behavior:** A direct tone switch in the current user message should override learned persona style for that turn, and session-scoped style requests should persist for the current chat session unless the user says the change is only for this reply.
- **Likely cause:** Feedback detection matched phrases like `professional`, but applying the feedback only adjusted a language-mix ratio and did not set `preferred_style`. Separately, compact prompts and relationship-voice contracts hardcoded close-friend/casual/teasing language near the user message, overpowering the requested professional tone.
- **Fix:** Added a canonical runtime `StylePolicy` layer with session-scoped overrides, explicit turn-only scope detection, a final high-priority `STYLE POLICY` prompt block, relationship-voice suppression, stance suppression, compact-prompt policy awareness, and clearer feedback categories (`tone_more_professional`, `tone_more_casual`, `length_shorter`, `length_more_detailed`) with backward-compatible aliases.
- **Verification:** `python3 -m py_compile` passed for touched runtime/test files. `PYTHONPATH=workspace pytest -o addopts='' workspace/tests/test_style_policy.py workspace/tests/test_stance.py -q` passed (`11 passed`). Full chat/CLI/SBS tests still need the complete project Python environment (`httpx`, `fastapi`, `filelock`, `pytest-asyncio`) before live verification.

### 9. MCP integrations are present but not production-complete for proactive companion workflows

- **Status:** investigating
- **Where it happened:** MCP + proactive awareness expectations for Calendar, Gmail, GitHub, and preferred chat-platform nudges
- **Exact issue:** Synapse should proactively use connected MCP services, for example:
  - Google Calendar: periodically check upcoming meetings and nudge the user on WhatsApp/Telegram/Slack/Discord with a short meeting summary.
  - GitHub: detect new PRs in watched repositories and nudge the user with repo name and basic PR details.
  - Gmail: summarize important new emails, watch a specific thread, notify when a new email arrives, and let the user draft/send replies from their preferred chat platform.
- **Expected behavior:** MCP integrations should work as companion workflows, not only as raw tools. They need polling, deduplication, importance filtering, per-user/channel delivery preferences, thread/repo watch state, and safe action confirmation for sending messages or email.
- **Current implementation status:** Calendar MCP has `get_upcoming`, `list_events`, and `create_event`; Gmail MCP has `search_emails`, `read_email`, `get_unread`, and `send_email`; Slack MCP has mention/message tools; proactive polling can gather Calendar/Gmail/Slack context and inject it into prompts. However, proactive delivery is not complete end-to-end, GitHub MCP/watch support is not implemented in Synapse's builtin MCP list, Gmail thread-watch/draft workflows are not implemented as durable user workflows, and full MCP tests could not run in the current Homebrew Python environment because dependencies such as `mcp`, `pydantic`, and `pytest-asyncio` are missing.
- **Likely cause:** MCP servers were built as low-level tool endpoints first. The higher-level companion behavior still needs a workflow layer that stores watches/subscriptions, decides what is important, deduplicates previously announced items, and delivers through the user's preferred channel.
- **Fix needed:** Add an MCP workflow layer for proactive notifications:
  - Auto-inject MCP auth tokens for internal MCP calls when gateway auth is enabled.
  - Add Calendar event nudge workflow with lookahead window, dedupe, summary formatting, and delivery through the configured preferred channel.
  - Add GitHub MCP/server support and watched-repo PR polling with PR dedupe and basic metadata notification.
  - Add Gmail importance summary, watched-thread state, new-message detection, draft generation, and explicit confirmation before sending.
  - Add `/status` or `synapse verify` diagnostics showing connected MCP servers, enabled workflows, last poll time, last error, and last delivered notification.
- **Verification:** Install/use the complete project environment, then run `pytest tests/test_mcp_*.py tests/test_proactive_engine.py -q`. Add integration tests for Calendar nudge, GitHub PR nudge, Gmail watched-thread nudge, channel delivery, auth-token injection, and notification dedupe.

## Proactive Companion Feature Requests

These are not installation bugs. They are realistic 2026 companion-AI expectations that should
be tracked, implemented, and verified as product features.

### FR-1. Notification preferences and quiet hours

- **Status:** requested
- **User value:** Synapse should feel helpful without becoming noisy.
- **Expected behavior:** During onboarding or settings, Synapse asks when it may nudge the user, which channels to use, what counts as urgent, and whether daily briefs are enabled.
- **Implementation notes:** Store per-user preferences for quiet hours, preferred channel, urgency threshold, daily brief time, and allowed proactive sources.
- **Verification:** Tests prove proactive notifications are suppressed during quiet hours unless urgent, and routed to the configured preferred channel.

### FR-2. Calendar meeting nudges

- **Status:** requested
- **User value:** User should not have to manually track every meeting.
- **Expected behavior:** Synapse checks Google Calendar periodically and nudges the user before upcoming meetings with time, title, attendees, meeting link, and a short summary.
- **Implementation notes:** Use Calendar MCP `get_upcoming`, add event dedupe, configurable lookahead window, summary formatting, and channel delivery.
- **Verification:** Tests prove one notification per event window, no duplicate nudges, and correct channel delivery.

### FR-3. Daily brief

- **Status:** requested
- **User value:** User gets a useful morning overview without asking.
- **Expected behavior:** Synapse sends a daily brief containing today’s meetings, important unread emails, reminders/tasks, watched PRs/issues, and watched threads.
- **Implementation notes:** Build a scheduled proactive job that aggregates enabled sources, summarizes them, and respects quiet hours/channel preferences.
- **Verification:** Tests prove the brief includes configured sources, omits disabled sources, and sends at the configured time.

### FR-4. Gmail important email radar

- **Status:** requested
- **User value:** User only gets nudged for emails that matter.
- **Expected behavior:** Synapse periodically checks unread Gmail, classifies emails as urgent/needs-reply/FYI/noise, and nudges only for important items.
- **Implementation notes:** Use Gmail MCP `get_unread` and `read_email`; add importance classification, sender allow/deny rules, dedupe, and summary text.
- **Verification:** Tests prove noisy emails are suppressed, important emails create one nudge, and repeated polls do not duplicate alerts.

### FR-5. Gmail watched thread and reply drafting

- **Status:** requested
- **User value:** User can ask Synapse to keep an eye on an email conversation and draft replies from chat.
- **Expected behavior:** User can say “watch this email thread”; Synapse stores the thread watch, nudges when a new reply arrives, drafts a response from WhatsApp/Telegram/Slack/Discord, and asks for confirmation before sending.
- **Implementation notes:** Add durable watched-thread state, new-message detection, draft generation, and explicit `yes/no` send confirmation. Sending should use Gmail MCP `send_email`.
- **Verification:** Tests prove watched threads detect new messages, drafts are generated, and no email is sent without confirmation.

### FR-6. GitHub PR watcher

- **Status:** requested
- **User value:** User notices new PRs without living in GitHub notifications.
- **Expected behavior:** For watched repositories, Synapse nudges when a new PR appears or review is requested, including repo name, PR title, author, URL, and basic metadata.
- **Implementation notes:** Add GitHub MCP/server or GitHub API connector support, watched repo state, PR dedupe, and notification delivery. V1 should notify only; no automated review required.
- **Verification:** Tests prove new PRs notify once, old PRs do not re-notify, and watched repo settings isolate notifications by user.

### FR-7. Meeting prep brief

- **Status:** requested
- **User value:** User enters meetings with context.
- **Expected behavior:** Before important meetings, Synapse can summarize attendees, agenda/description, meeting link, and relevant recent emails or notes when available.
- **Implementation notes:** Start with Calendar-only prep; later enrich with Gmail/Drive search. Use the same dedupe and channel delivery layer as calendar nudges.
- **Verification:** Tests prove prep briefs include event metadata and do not hallucinate missing agenda/details.

### FR-8. Post-meeting follow-up capture

- **Status:** requested
- **User value:** User can quickly save decisions/action items after meetings.
- **Expected behavior:** After a meeting ends, Synapse asks whether the user wants to save decisions, action items, or reminders from that meeting.
- **Implementation notes:** Trigger after calendar events end, respect quiet hours, and save user-confirmed notes into memory/tasks.
- **Verification:** Tests prove the follow-up fires once per eligible meeting and stores only confirmed user-provided content.

### FR-9. Waiting-on tracker

- **Status:** requested
- **User value:** Synapse helps track loose ends.
- **Expected behavior:** User can say “remind me if Arjun does not reply by Friday” or “track that I am waiting for PR review”; Synapse checks the relevant source or reminds at deadline.
- **Implementation notes:** V1 can support user-declared waits with deadlines; later connect waits to Gmail/GitHub/Slack signals.
- **Verification:** Tests prove waits are stored, checked at deadline, resolved when the expected signal arrives, and not duplicated.

### FR-10. Cross-channel identity continuity

- **Status:** requested
- **User value:** Synapse remembers the same user across WhatsApp, Telegram, Slack, Discord, and CLI.
- **Expected behavior:** If the same person uses multiple channels, Synapse keeps the same preferences, memory, watches, and proactive notification settings.
- **Implementation notes:** Build on existing identity/session links; expose a clear way to link/unlink channel identities safely.
- **Verification:** Tests prove linked identities share preferences and memory while unlinked identities stay isolated.

### FR-11. “What did I miss?” catch-up

- **Status:** requested
- **User value:** User can catch up after being away.
- **Expected behavior:** User asks “what did I miss today?” and Synapse summarizes calendar changes, important emails, watched threads, PRs/issues, and reminders since the last check.
- **Implementation notes:** Use the proactive workflow ledger as the source of truth for recent notifications and unannounced important items.
- **Verification:** Tests prove the catch-up window is time-bounded, source-aware, and does not include disabled integrations.

## Reel-Inspired Companion Agent Watchlist

These feature requests come from the "five agents everyone needs" reel transcript. They are
tracked as realistic Synapse product tracks, with current implementation status called out so
we can separate existing foundations from missing workflow work.

### FR-12. Life Admin Agent

- **Status:** partially available foundation, feature requested
- **User value:** Synapse should track bills, renewals, subscriptions, assignments, calendar obligations, and other pending life-admin items before they become emergencies.
- **Already present:** Calendar MCP primitives (`get_upcoming`, `list_events`, `create_event`), Gmail MCP primitives (`search_emails`, `read_email`, `get_unread`), bundled reminders skill, and proactive Calendar/Gmail/Slack context polling foundation.
- **Missing behavior:** Bill/renewal/subscription detection, assignment/deadline extraction, document-backed admin item storage, unified pending-item ledger, snooze/done/ignore controls, and safe confirmation for any irreversible action.
- **Implementation checklist:** Add an `admin_items` store with source, due date, owner, status, and confidence; extract due dates from Gmail/Calendar/docs; send daily/weekly pending digests; support "mark done", "snooze", and "ignore"; respect notification preferences and quiet hours.
- **Verification:** Tests prove detected admin items are deduped by source, due dates survive restarts, completed items stop nudging, and no payment/subscription action happens without explicit confirmation.

### FR-13. Wellness Manager

- **Status:** partial mood foundation, feature requested
- **User value:** Synapse should help the user notice mood, sleep, hydration, and overload patterns without becoming intrusive.
- **Already present:** SBS realtime processing can detect mood/emotional signals from chat, profile state can track emotional trends, and calendar events can provide a foundation for meeting-load awareness.
- **Missing behavior:** Opt-in wellness preferences, hydration nudges, sleep tracking, wearable/health-app integration, call-heavy-day detection, wellness summaries, and boundaries for sensitive health language.
- **Implementation checklist:** Start with manual mood/sleep check-ins, hydration reminders, and calendar-derived overload nudges; add consent-first settings; later add optional Apple Health/Google Fit style adapters if feasible.
- **Verification:** Tests prove wellness nudges are opt-in, quiet hours are respected, meeting-load summaries use real calendar events, and Synapse does not present wellness observations as medical advice.

### FR-14. Finance Manager

- **Status:** mostly missing, high-safety feature requested
- **User value:** Synapse should help users stay aware of bills, budgets, investments, and market context without pretending to be a financial advisor.
- **Already present:** Generic news/web-style foundations can support market news summaries, and the Life Admin track can cover bill reminders once implemented.
- **Missing behavior:** Bank/investment connectors, portfolio/watchlist tracking, budget categories, transaction import, market alerts, and high-stakes finance safety boundaries.
- **Implementation checklist:** For v1, support manual watchlists, manual holdings snapshots, bill/subscription reminders, public market-news summaries, and "explain what changed" briefings. Defer trading, money movement, and regulated financial advice.
- **Verification:** Tests prove finance summaries are source-attributed where possible, no trade/payment action is available, and advice-like requests receive safe educational framing.

### FR-15. Content Manager

- **Status:** mostly missing, feature requested
- **User value:** Content creators should get help with posting schedules, idea capture, trend awareness, analytics summaries, and "what is working" reviews.
- **Already present:** Memory/notes foundations can store ideas, reminders can schedule posts, and news/web-style foundations can support trend discovery.
- **Missing behavior:** Content calendar, Meta/Instagram Insights integration, Notion/notes connector workflow, analytics ingestion, trend watchlists, and weekly performance reports.
- **Implementation checklist:** Start with an idea inbox, content calendar reminders, manual analytics CSV import, trend watch summaries, and weekly "what worked / what to try next" reports. Add Meta/Notion integrations after the core workflow is stable.
- **Verification:** Tests prove scheduled posts nudge once, imported analytics generate deterministic summaries, disabled platforms are omitted, and creator notes stay scoped to the right user/session.

### FR-16. Relationship Manager

- **Status:** partial memory/reminder foundation, feature requested
- **User value:** Synapse should help users remember important people, birthdays, anniversaries, reply-later promises, and relationship maintenance moments.
- **Already present:** SBS/memory foundations can store relationship context, relationship voice logic exists, and the reminders skill can schedule user-declared follow-ups.
- **Missing behavior:** Durable contact/date book, birthday/anniversary nudges, reply-later tracker, last-contact summaries, per-person preferences, and privacy controls for sensitive relationship data.
- **Implementation checklist:** Add opt-in contact facts with source and confidence; support "remember X's birthday", "remind me to reply to Y", and weekly people check-ins; expose edit/delete controls for personal facts.
- **Verification:** Tests prove contacts stay isolated by user identity, reminders fire at the configured time, deleted personal facts stop appearing, and Synapse never invents birthdays or anniversaries.

### Suggested Build Order

- **First:** FR-12 Life Admin Agent and FR-16 Relationship Manager, because they reuse existing Calendar/Gmail/reminder/memory foundations and create high daily value.
- **Second:** FR-13 Wellness Manager v1 with manual check-ins and calendar-derived overload detection, avoiding wearable complexity at first.
- **Third:** FR-15 Content Manager v1 with idea inbox, calendar reminders, manual analytics import, and weekly reports.
- **Careful/deferred:** FR-14 Finance Manager should begin with watchlists, bills, and market/news awareness only. Bank connectors, investment automation, and payments need a stronger safety and compliance design before implementation.
