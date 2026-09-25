# Lessons

- 2026-09-25: Synapse is a general “do this for me” assistant. Calendar, departure, and shopping requests are acceptance scenarios for a shared capability and durable goal architecture, not reasons to specialize the product around one example.
- 2026-09-25: A strict TDD request also applies to review-found races. Capture a behavioral failing regression before changing startup order; if a correction lands first, document that exception honestly and reproduce the pre-fix failure in isolation when practical.
- 2026-09-25: Root owns design decisions; delegated agents gather evidence, implement approved contracts and test, and escalate deviations.
- 2026-09-25: An owner-filtered recall API is insufficient if the prompt, native memory tool, subagent snapshot, short-history key, or old transcript miner can still reach unowned personal data. Carry the same verified scope through every interactive branch and test the negative path with a cross-user sentinel.
- 2026-09-25: A relationship preference in a profile reminder can be overridden by a later runtime style policy. Resolve the effective style from bounded, evidence-backed profile values before composing that final policy; current-turn explicit intent wins.
- 2026-09-25: For an asynchronous outbox, a fake channel send can finish before the persisted acceptance status transition. Test the durable row with a bounded poll, while still asserting one send and one stable outbox entry.
- 2026-09-25: Keep context sync mining bounded to the working docs by default. A full-repo MemPalace mine can outlive a lost execution session, so retain the session ID for long commands and treat drawer counts without an exit code as incomplete evidence. Use an explicit opt-in for full mining.
