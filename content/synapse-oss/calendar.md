# Synapse-OSS — 365-Day Content Calendar
_Generated: 2026-03-28_
_Source: goldmine.md (72 findings)_

## Content Mix
- 40% architecture explainers (~146 days)
- 25% decisions (~91 days)
- 20% struggle/bug stories (~73 days)
- 15% tool/workflow tips (~55 days)

## Phase Overview
| Phase | Weeks | Days | Theme |
|-------|-------|------|-------|
| 1 — Foundation | 1–2 | 1–14 | What is Synapse? Who built it and why? |
| 2 — Systems Deep Dive | 3–16 | 15–112 | One system per week, inside-out |
| 3 — Decisions & Trade-offs | 17–30 | 113–210 | Why X over Y — opinion-driven |
| 4 — Struggles & Lessons | 31–42 | 211–294 | Bugs, failures, rebuilds |
| 5 — Meta & Reflections | 43–52 | 295–365 | Lessons, retrospectives, what's next |

---

## Phase 1 — Foundation

## Week 1 — Theme: What is Synapse?
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 1 | architecture | What I'm building and why I built it on WhatsApp | High | goldmine#full-request-pipeline |
| Tue | 2 | architecture | The problem: I needed an AI that actually knows me | High | goldmine#soul-brain-sync-pipeline |
| Wed | 3 | data-flow | 8 stages between your message and the AI's response | High | goldmine#gateway-pipeline-five-stages |
| Thu | 4 | architecture | Why I built this on 8GB RAM instead of the cloud | High | goldmine#ram-pressure-optimization |
| Fri | 5 | struggle | The first version depended on a private binary I couldn't ship | High | goldmine#openclaw-dependency-removal |
| Sat | 6 | tool-tip | How I plan big projects alone: phase gates with PLAN.md | Medium | goldmine#phase-based-development-story |
| Sun | 7 | architecture | Synapse in one diagram: the full system overview | Medium | goldmine#full-request-pipeline |

## Week 2 — Theme: The Stack
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 8 | decision | Why SQLite handles everything — embeddings, graph, sessions | High | goldmine#sqlite-only-no-postgres |
| Tue | 9 | decision | Why pure asyncio — no Redis, no Celery | Medium | goldmine#async-first-no-celery |
| Wed | 10 | decision | 16 AI providers dispatched with one routing call | High | goldmine#litellm-for-16-providers |
| Thu | 11 | architecture | Local-first: Ollama is the default, cloud is the fallback | High | goldmine#llm-routing-by-intent |
| Fri | 12 | struggle | Getting from 81% RAM usage to under 25% — three rounds | High | goldmine#ram-pressure-optimization |
| Sat | 13 | tool-tip | SQLite WAL mode: the one pragma that changes the concurrency model | Medium | goldmine#sqlite-wal-tuning |
| Sun | 14 | decision | The full tech stack in 90 seconds — why every piece is here | Medium | goldmine#modular-requirements-split |

---

## Phase 2 — Systems Deep Dive

## Week 3 — Theme: Gateway Pipeline
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 15 | architecture | 5 gates before the AI reads your message | High | goldmine#gateway-pipeline-five-stages |
| Tue | 16 | pattern | FloodGate: why I buffer your messages for 3 seconds | High | goldmine#flood-gate-batching |
| Wed | 17 | pattern | Dedup: the 5-minute TTL filter that stops double replies | Medium | goldmine#dedup-ttl-filter |
| Thu | 18 | pattern | The task queue: asyncio.Queue with a hard max of 100 | Medium | goldmine#task-queue-asyncio |
| Fri | 19 | struggle | The Telegram bug that silently dropped messages for days | High | goldmine#telegram-enqueue-fn-bug |
| Sat | 20 | pattern | The factory closure that fixed Telegram's flood adapter | Medium | goldmine#make-flood-enqueue-factory |
| Sun | 21 | data-flow | Full request flow walkthrough: channel to LLM to send | Medium | goldmine#full-request-pipeline |

## Week 4 — Theme: Memory & RAG
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 22 | architecture | How my AI remembers things: hybrid vector + keyword search | High | goldmine#hybrid-rag-retrieval |
| Tue | 23 | data-flow | ANN + FTS merged and reranked — why two indexes beat one | High | goldmine#hybrid-rag-retrieval |
| Wed | 24 | decision | Why I replaced Qdrant with a SQLite extension | High | goldmine#no-qdrant-sqlite-vec |
| Thu | 25 | tool-tip | FlashRank bypass: cutting retrieval from 1.2s to 350ms | High | goldmine#flashrank-bypass-for-speed |
| Fri | 26 | struggle | NetworkX was eating 155MB just to sit in memory | High | goldmine#networkx-to-sqlite-migration |
| Sat | 27 | tool-tip | Content hash dedup: hash first, store only if new | Medium | goldmine#content-hash-dedup |
| Sun | 28 | data-flow | The full memory pipeline end to end | Medium | goldmine#hybrid-rag-retrieval |

## Week 5 — Theme: LLM Routing
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 29 | architecture | 4 different AIs for 4 different jobs | High | goldmine#llm-routing-by-intent |
| Tue | 30 | decision | Why Banglish routes to Gemini Flash, not GPT-4 | High | goldmine#banglish-routing-default |
| Wed | 31 | decision | Code questions get Claude with thinking mode on | Medium | goldmine#llm-routing-by-intent |
| Thu | 32 | architecture | The private hemisphere: air-gapped from all cloud APIs | High | goldmine#hemisphere-memory-separation |
| Fri | 33 | struggle | What happens when all 16 providers rate-limit at once | Medium | goldmine#openrouter-as-fallback |
| Sat | 34 | tool-tip | Context window guard: never silently truncate to a local model | Medium | goldmine#ollama-context-window-guard |
| Sun | 35 | decision | litellm: the one library that makes multi-provider routing trivial | Medium | goldmine#litellm-for-16-providers |

## Week 6 — Theme: Dual Cognition
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 36 | architecture | My AI thinks before it speaks | High | goldmine#dual-cognition-inner-monologue |
| Tue | 37 | architecture | What inner monologue actually means in code | High | goldmine#dual-cognition-inner-monologue |
| Wed | 38 | pattern | Tension scoring: the gap between thinking and saying | High | goldmine#dual-cognition-inner-monologue |
| Thu | 39 | pattern | Fast phrase bypass: don't run 600ms of reasoning for "ok" | Medium | goldmine#fast-phrase-bypass |
| Fri | 40 | struggle | First version ran inner monologue on every message — including "hi" | Medium | goldmine#fast-phrase-bypass |
| Sat | 41 | tool-tip | Compiled regex for fast short-phrase detection | Low | goldmine#fast-phrase-bypass |
| Sun | 42 | architecture | Dual cognition retrospective: was it worth building? | High | goldmine#dual-cognition-inner-monologue |

## Week 7 — Theme: Soul-Brain Sync Overview
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 43 | architecture | How my AI learns who I am over time | High | goldmine#soul-brain-sync-pipeline |
| Tue | 44 | data-flow | Realtime processing: every message updates the profile instantly | Medium | goldmine#sbs-distillation-cycle |
| Wed | 45 | data-flow | Batch distillation: every 50 messages the AI rewrites its model of you | High | goldmine#sbs-distillation-cycle |
| Thu | 46 | architecture | 8 profile layers: from core_identity to meta | High | goldmine#eight-layer-profile-system |
| Fri | 47 | struggle | Building a learning loop that doesn't drift into noise | High | goldmine#sbs-distillation-cycle |
| Sat | 48 | tool-tip | Peak-End Rule from psychology — implemented as a SQL ORDER BY | High | goldmine#peak-end-rule-in-sql |
| Sun | 49 | architecture | Soul-Brain Sync in one diagram | Medium | goldmine#soul-brain-sync-pipeline |

## Week 8 — Theme: SBS Deep Dive
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 50 | pattern | The 8 profile layers explained one by one | High | goldmine#eight-layer-profile-system |
| Tue | 51 | pattern | core_identity vs emotional_state: what's actually in each layer | Medium | goldmine#eight-layer-profile-system |
| Wed | 52 | data-flow | From 8 JSON files to a 1500-token system prompt segment | High | goldmine#prompt-compiler |
| Thu | 53 | architecture | The Prompt Compiler: bridge between stored profile and live context | High | goldmine#prompt-compiler |
| Fri | 54 | struggle | When the profile drifts: what bad distillation looks like in production | Medium | goldmine#sbs-distillation-cycle |
| Sat | 55 | tool-tip | Exemplar selection: few-shot examples chosen automatically per message | Medium | goldmine#eight-layer-profile-system |
| Sun | 56 | decision | Why I built SBS instead of using an existing memory library | High | goldmine#soul-brain-sync-pipeline |

## Week 9 — Theme: Multi-Channel Architecture
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 57 | architecture | One AI, four messaging apps, zero code duplication | High | goldmine#multi-channel-basechannel-abc |
| Tue | 58 | pattern | BaseChannel ABC: the 6 methods every channel must implement | Medium | goldmine#multi-channel-basechannel-abc |
| Wed | 59 | pattern | ChannelRegistry: startup and shutdown via FastAPI lifespan | Medium | goldmine#channel-registry-lifecycle |
| Thu | 60 | architecture | Adding a 5th channel: what that actually looks like in code | Medium | goldmine#multi-channel-basechannel-abc |
| Fri | 61 | struggle | Discord and Slack weren't wired to the flood gate — silent failure | High | goldmine#telegram-enqueue-fn-bug |
| Sat | 62 | pattern | _make_flood_enqueue(): plugging any channel into the pipeline via closure | Medium | goldmine#make-flood-enqueue-factory |
| Sun | 63 | architecture | Channel architecture retrospective | Medium | goldmine#multi-channel-basechannel-abc |

## Week 10 — Theme: Security & Access Control
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 64 | architecture | Who can DM your AI? It's a config value, not hardcoded | High | goldmine#dm-policy-enum |
| Tue | 65 | data-flow | DM access resolution: policy → store → result in one pure function | Medium | goldmine#dm-access-control-resolution |
| Wed | 66 | pattern | JSONL pairing store: the simplest possible append-only audit trail | Medium | goldmine#jsonl-audit-trail |
| Thu | 67 | architecture | The Sentinel: fail-closed file access control for the AI's own data | High | goldmine#sentinel-file-access-control |
| Fri | 68 | struggle | My AI could access its own config without permission — until Sentinel | High | goldmine#sentinel-file-access-control |
| Sat | 69 | tool-tip | SSRF guard: rejecting private IPs before fetching any media URL | Medium | goldmine#media-pipeline-ssrf-guard |
| Sun | 70 | decision | Security decisions I made for a personal AI | Medium | goldmine#dm-policy-enum |

## Week 11 — Theme: Media Pipeline
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 71 | architecture | How my AI handles images, audio, and documents | Medium | goldmine#media-pipeline-ssrf-guard |
| Tue | 72 | data-flow | SSRF → MIME → store → TTL: the 4 stages of media handling | Medium | goldmine#media-pipeline-ssrf-guard |
| Wed | 73 | struggle | MIME detection: which source do you trust when they all disagree? | High | goldmine#mime-detection-precedence |
| Thu | 74 | tool-tip | Magic bytes beat HTTP headers beat file extensions — always | Medium | goldmine#mime-detection-precedence |
| Fri | 75 | struggle | Building SSRF protection for a WhatsApp bot nobody told me to | Medium | goldmine#media-pipeline-ssrf-guard |
| Sat | 76 | tool-tip | TTL cleanup: auto-deleting stored media after 120 seconds | Low | goldmine#media-pipeline-ssrf-guard |
| Sun | 77 | architecture | Media pipeline retrospective: what I'd build differently | Medium | goldmine#media-pipeline-ssrf-guard |

## Week 12 — Theme: Sessions & WebSocket
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 78 | architecture | The WebSocket control plane: real-time access to the AI's brain | Medium | goldmine#websocket-control-plane |
| Tue | 79 | data-flow | Typed JSON frame protocol: chat.send, channels.status, models.list | Medium | goldmine#websocket-control-plane |
| Wed | 80 | pattern | SessionActorQueue: one asyncio.Lock per user, no race conditions | High | goldmine#session-actor-queue |
| Thu | 81 | decision | Per-session locking vs global lock: why granularity matters | Medium | goldmine#session-actor-queue |
| Fri | 82 | struggle | The double-done asyncio bug that crashed the queue with no traceback | High | goldmine#safe-task-done-guard |
| Sat | 83 | tool-tip | _safe_task_done(): the one-line guard against a silent crash | Medium | goldmine#safe-task-done-guard |
| Sun | 84 | architecture | Session management: what's next | Low | goldmine#websocket-control-plane |

## Week 13 — Theme: CLI & Onboarding
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 85 | architecture | The onboarding wizard: making a complex system one-command installable | Medium | goldmine#cross-platform-daemon-install |
| Tue | 86 | struggle | Three operating systems, three different daemon APIs, one wizard | High | goldmine#cross-platform-daemon-install |
| Wed | 87 | struggle | Fresh Mac install: 6 onboarding gaps I'd never seen before | High | goldmine#mac-fresh-setup-hurdles |
| Thu | 88 | pattern | WizardPrompter Protocol: testing interactive CLIs without mock libraries | High | goldmine#wizard-prompter-protocol |
| Fri | 89 | decision | Why I used a Protocol for test doubles instead of a mocking framework | Medium | goldmine#wizard-prompter-protocol |
| Sat | 90 | tool-tip | questionary + typer: the two libraries that make CLI wizards pleasant | Medium | goldmine#cross-platform-daemon-install |
| Sun | 91 | architecture | Onboarding retrospective: what actually broke in the wild | High | goldmine#mac-fresh-setup-hurdles |

## Week 14 — Theme: Knowledge Graph
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 92 | architecture | The knowledge graph: storing what things mean, not just what was said | High | goldmine#networkx-to-sqlite-migration |
| Tue | 93 | decision | Why I migrated from NetworkX to SQLite for the graph | High | goldmine#networkx-to-sqlite-migration |
| Wed | 94 | data-flow | Subject-predicate-object triples stored in plain SQLite | Medium | goldmine#networkx-to-sqlite-migration |
| Thu | 95 | architecture | Graph vs vector: when to use each for memory retrieval | High | goldmine#hybrid-rag-retrieval |
| Fri | 96 | struggle | NetworkX was using 155MB just to sit idle between queries | High | goldmine#networkx-to-sqlite-migration |
| Sat | 97 | tool-tip | Querying a knowledge graph with pure SQL | Medium | goldmine#networkx-to-sqlite-migration |
| Sun | 98 | decision | Would I use a real graph database next time? Honest answer. | Medium | goldmine#networkx-to-sqlite-migration |

## Week 15 — Theme: Database Deep Dive
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 99 | architecture | The SQLite setup handling vectors, graphs, and sessions simultaneously | High | goldmine#sqlite-only-no-postgres |
| Tue | 100 | tool-tip | WAL mode: the pragma that enables concurrent readers during writes | Medium | goldmine#sqlite-wal-tuning |
| Wed | 101 | tool-tip | SQLITE_BUSY: exponential backoff for lock contention | Medium | goldmine#sqlite-lock-retry-backoff |
| Thu | 102 | pattern | Shadow table swap: atomic ingestion without Postgres transactions | High | goldmine#atomic-shadow-table-ingestion |
| Fri | 103 | struggle | The concurrent write bug that WAL mode alone didn't fix | High | goldmine#sqlite-lock-retry-backoff |
| Sat | 104 | tool-tip | Atomic config writes: tempfile + os.replace() for crash safety | Medium | goldmine#atomic-config-write |
| Sun | 105 | decision | SQLite in a production personal project: the honest verdict | High | goldmine#sqlite-only-no-postgres |

## Week 16 — Theme: Audio, ML Models & Phase 2 Wrap
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 106 | decision | Why I use Groq Whisper instead of a local model for transcription | High | goldmine#groq-whisper-zero-ram |
| Tue | 107 | tool-tip | Cloud transcription with zero local RAM impact | Medium | goldmine#groq-whisper-zero-ram |
| Wed | 108 | decision | The RAM budget: which models load locally, which go to the cloud | High | goldmine#lazy-toxic-bert-model |
| Thu | 109 | pattern | LazyToxicScorer: load a 600MB model on demand, unload after 30s idle | Medium | goldmine#lazy-toxic-bert-model |
| Fri | 110 | struggle | 600MB sitting loaded and idle: the model I forgot to unload | High | goldmine#lazy-toxic-bert-model |
| Sat | 111 | tool-tip | Auto-unload pattern for large ML models in async Python | Medium | goldmine#lazy-toxic-bert-model |
| Sun | 112 | architecture | Phase 2 retrospective: 14 systems, what I actually learned | High | goldmine#soul-brain-sync-pipeline |

---

## Phase 3 — Decisions & Trade-offs

## Week 17 — Theme: SQLite vs the world
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 113 | decision | Why I chose SQLite when every tutorial says Postgres | High | goldmine#sqlite-only-no-postgres |
| Tue | 114 | decision | sqlite-vec vs Qdrant: vector search at personal-project scale | High | goldmine#no-qdrant-sqlite-vec |
| Wed | 115 | decision | SQLite for graphs: the NetworkX migration numbers | High | goldmine#networkx-to-sqlite-migration |
| Thu | 116 | decision | SQLite for sessions, config, and JSONL audit trails | Medium | goldmine#jsonl-audit-trail |
| Fri | 117 | struggle | The moment SQLite proved itself: the RAM numbers that settled it | High | goldmine#ram-pressure-optimization |
| Sat | 118 | tool-tip | When SQLite is enough — and the one sign it's not | High | goldmine#sqlite-only-no-postgres |
| Sun | 119 | decision | SQLite retrospective: 12 months in, any regrets? | High | goldmine#sqlite-only-no-postgres |

## Week 18 — Theme: Async architecture choices
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 120 | decision | I removed Celery from the project — here's what replaced it | High | goldmine#async-first-no-celery |
| Tue | 121 | pattern | Pure asyncio: one event loop, everything in one process | Medium | goldmine#async-first-no-celery |
| Wed | 122 | pattern | Bounded queue with explicit rejection: backpressure done simply | Medium | goldmine#task-queue-asyncio |
| Thu | 123 | pattern | Per-session locking instead of global serialization | Medium | goldmine#session-actor-queue |
| Fri | 124 | struggle | The Celery job that never completed: why I ripped it out | High | goldmine#async-first-no-celery |
| Sat | 125 | tool-tip | asyncio.Lock per key: isolate concurrency to the user level | Medium | goldmine#session-actor-queue |
| Sun | 126 | decision | Async-first retrospective: what I'd tell myself at the start | High | goldmine#async-first-no-celery |

## Week 19 — Theme: Language & personalization decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 127 | decision | Why Banglish is the primary language, not the edge case | High | goldmine#banglish-routing-default |
| Tue | 128 | decision | Building for Bengali code-switching: what that means technically | High | goldmine#banglish-routing-default |
| Wed | 129 | architecture | 8 profile layers: how personalization is structured and stored | High | goldmine#eight-layer-profile-system |
| Thu | 130 | architecture | Why a static system prompt isn't enough for a personal AI | High | goldmine#soul-brain-sync-pipeline |
| Fri | 131 | struggle | First SBS version silently overwrote good profile data with noise | High | goldmine#sbs-distillation-cycle |
| Sat | 132 | tool-tip | Implicit feedback detection: regex patterns that catch when the AI was wrong | Medium | goldmine#sbs-distillation-cycle |
| Sun | 133 | decision | Personalization retrospective: is learning from conversations worth it? | High | goldmine#soul-brain-sync-pipeline |

## Week 20 — Theme: LLM routing philosophy
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 134 | decision | One AI isn't enough. Here's how I route between four of them. | High | goldmine#llm-routing-by-intent |
| Tue | 135 | decision | Why code questions go to Claude, not Gemini | High | goldmine#llm-routing-by-intent |
| Wed | 136 | decision | The private mode: when nothing leaves the local machine | High | goldmine#hemisphere-memory-separation |
| Thu | 137 | decision | Ollama model discovery: auto-detecting what's available at startup | Medium | goldmine#ollama-context-window-guard |
| Fri | 138 | struggle | The router that sent code questions to the wrong model for a week | High | goldmine#llm-routing-by-intent |
| Sat | 139 | tool-tip | Context window guard: routing by token count, not just message intent | Medium | goldmine#ollama-context-window-guard |
| Sun | 140 | decision | LLM routing retrospective: is multi-model worth the added complexity? | High | goldmine#llm-routing-by-intent |

## Week 21 — Theme: Local vs cloud
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 141 | decision | The case for local-first AI: why Ollama runs by default, not GPT-4 | High | goldmine#llm-routing-by-intent |
| Tue | 142 | decision | Privacy as architecture: the spicy hemisphere that never touches a server | High | goldmine#hemisphere-memory-separation |
| Wed | 143 | decision | Groq vs local Whisper: the pragmatic trade-off on 8GB RAM | High | goldmine#groq-whisper-zero-ram |
| Thu | 144 | decision | The RAM budget: which workloads run locally and which don't | High | goldmine#ram-pressure-optimization |
| Fri | 145 | struggle | Local models aren't always better: the Banglish discovery | High | goldmine#banglish-routing-default |
| Sat | 146 | tool-tip | Setting up Ollama for a personal AI project — the non-obvious steps | Medium | goldmine#ollama-context-window-guard |
| Sun | 147 | decision | Local-first retrospective: what changed after 12 months | High | goldmine#llm-routing-by-intent |

## Week 22 — Theme: Open source decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 148 | decision | Why I open-sourced a personal AI assistant | High | goldmine#openclaw-dependency-removal |
| Tue | 149 | struggle | The dependency I couldn't ship: removing OpenClaw from the public repo | High | goldmine#openclaw-dependency-removal |
| Wed | 150 | decision | Contributor infrastructure: what you need before the first external PR | Medium | goldmine#phase-based-development-story |
| Thu | 151 | decision | CONTRIBUTING.md and CODE_OF_CONDUCT.md: why they matter at 3 stars | Low | goldmine#phase-based-development-story |
| Fri | 152 | struggle | The first external PR (Cohere provider): what I got wrong in review | Medium | goldmine#openclaw-dependency-removal |
| Sat | 153 | tool-tip | SYMBOLS.md and a ctags file: making your codebase navigable for LLMs | Medium | goldmine#phase-based-development-story |
| Sun | 154 | decision | Open source retrospective: was going public worth it? | High | goldmine#openclaw-dependency-removal |

## Week 23 — Theme: Testing philosophy
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 155 | decision | Why I write 302 tests for a personal side project | High | goldmine#wizard-prompter-protocol |
| Tue | 156 | pattern | Protocol-based test doubles: no mocking library required | High | goldmine#wizard-prompter-protocol |
| Wed | 157 | decision | What I test and what I deliberately skip | Medium | goldmine#wizard-prompter-protocol |
| Thu | 158 | pattern | Smoke vs unit vs integration: how I split pytest markers | Medium | goldmine#wizard-prompter-protocol |
| Fri | 159 | struggle | The WAL concurrent write test that only fails on Windows | High | goldmine#windows-ci-lint-failures |
| Sat | 160 | tool-tip | pytest -m unit|integration|smoke: organizing markers from day 1 | Medium | goldmine#wizard-prompter-protocol |
| Sun | 161 | decision | Testing retrospective: what I wish I'd tested from day 1 | High | goldmine#wizard-prompter-protocol |

## Week 24 — Theme: Architecture patterns
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 162 | pattern | ABC vs Protocol: when to use each in Python | Medium | goldmine#multi-channel-basechannel-abc |
| Tue | 163 | pattern | Dependency injection without a DI framework | Medium | goldmine#type-checking-import-guard |
| Wed | 164 | pattern | TYPE_CHECKING: the import guard that fixes circular dependencies | Medium | goldmine#type-checking-import-guard |
| Thu | 165 | decision | Why every channel is its own file, not a class hierarchy | Medium | goldmine#multi-channel-basechannel-abc |
| Fri | 166 | struggle | Circular imports: the refactor I didn't see coming at 10k lines | High | goldmine#type-checking-import-guard |
| Sat | 167 | tool-tip | dataclass field(default_factory=list): avoiding the mutable default trap | Medium | goldmine#multi-channel-basechannel-abc |
| Sun | 168 | decision | Architecture patterns I'd adopt from day 1 on the next project | High | goldmine#multi-channel-basechannel-abc |

## Week 25 — Theme: Data design decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 169 | decision | Why JSONL for audit trails instead of a database table | Medium | goldmine#jsonl-audit-trail |
| Tue | 170 | decision | Append-only logs: the simplest durable state store that exists | Medium | goldmine#jsonl-audit-trail |
| Wed | 171 | pattern | Shadow table swap: atomic ingestion without a Postgres transaction | High | goldmine#atomic-shadow-table-ingestion |
| Thu | 172 | decision | Content hash deduplication: hash before you store, always | Medium | goldmine#content-hash-dedup |
| Fri | 173 | struggle | Running the same ingest twice: the bug that doubled my memory DB | High | goldmine#content-hash-dedup |
| Sat | 174 | tool-tip | Atomic writes: tempfile → os.replace() for crash-safe config | Medium | goldmine#atomic-config-write |
| Sun | 175 | decision | Data design retrospective: the decisions that aged best | High | goldmine#sqlite-only-no-postgres |

## Week 26 — Theme: Memory architecture decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 176 | decision | Two memory hemispheres: why safe and spicy are separate namespaces | High | goldmine#hemisphere-memory-separation |
| Tue | 177 | decision | Vector + FTS hybrid: why neither search type alone is good enough | High | goldmine#hybrid-rag-retrieval |
| Wed | 178 | decision | FlashRank over heavier rerankers: the latency trade-off | Medium | goldmine#flashrank-bypass-for-speed |
| Thu | 179 | decision | sqlite-vec vs Qdrant: the real performance comparison at personal scale | High | goldmine#no-qdrant-sqlite-vec |
| Fri | 180 | struggle | The retrieval that kept returning irrelevant 10-month-old memories | High | goldmine#hybrid-rag-retrieval |
| Sat | 181 | tool-tip | nomic-embed-text: the local embedding model that punches above its weight | Medium | goldmine#hybrid-rag-retrieval |
| Sun | 182 | decision | Memory architecture retrospective: v1 vs v3, what changed | High | goldmine#hybrid-rag-retrieval |

## Week 27 — Theme: Security design decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 183 | decision | Designing DM access control for a personal AI | High | goldmine#dm-policy-enum |
| Tue | 184 | decision | Four DM policies: pairing, allowlist, open, disabled — and when to use each | Medium | goldmine#dm-policy-enum |
| Wed | 185 | decision | Fail-closed Sentinel: the AI can't access its own files without permission | High | goldmine#sentinel-file-access-control |
| Thu | 186 | decision | SSRF protection before media fetch: the threat model I was ignoring | Medium | goldmine#media-pipeline-ssrf-guard |
| Fri | 187 | struggle | The access control gap I only found after going open source | High | goldmine#sentinel-file-access-control |
| Sat | 188 | tool-tip | Pure functions for access control: why resolve_dm_access() has no side effects | Medium | goldmine#dm-access-control-resolution |
| Sun | 189 | decision | Security retrospective: what I'd add to the MVP if I could go back | High | goldmine#dm-policy-enum |

## Week 28 — Theme: CI/CD & tooling decisions
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 190 | decision | ruff + black: the lint stack that runs in CI without configuration battles | Low | goldmine#windows-ci-lint-failures |
| Tue | 191 | decision | Modular requirements: why ML deps are optional installs | Medium | goldmine#modular-requirements-split |
| Wed | 192 | decision | GitHub Actions on a personal project: is it worth the setup? | Medium | goldmine#phase-based-development-story |
| Thu | 193 | tool-tip | The tags file: 1215 symbols indexed for LLM-assisted navigation | Medium | goldmine#phase-based-development-story |
| Fri | 194 | struggle | The noqa comment that wasn't valid — and CI passed it silently for weeks | Medium | goldmine#windows-ci-lint-failures |
| Sat | 195 | tool-tip | ruff select vs ignore: narrowing lint to the rules that actually matter | Low | goldmine#windows-ci-lint-failures |
| Sun | 196 | decision | Tooling retrospective: what I'd add to the day-1 setup | Medium | goldmine#phase-based-development-story |

## Week 29 — Theme: Development methodology
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 197 | decision | Phase-gated development: how I build large systems alone | High | goldmine#phase-based-development-story |
| Tue | 198 | decision | PLAN.md → VERIFICATION.md: the cycle that keeps me honest | High | goldmine#phase-based-development-story |
| Wed | 199 | decision | Gap-closure plans: what to do when UAT fails mid-phase | High | goldmine#phase-based-development-story |
| Thu | 200 | decision | Why I write plans before code — even on solo projects | High | goldmine#phase-based-development-story |
| Fri | 201 | struggle | The phase that passed verification but broke on a real Mac install | High | goldmine#mac-fresh-setup-hurdles |
| Sat | 202 | tool-tip | Keeping a SYMBOLS.md: the index AI assistants actually use | Medium | goldmine#phase-based-development-story |
| Sun | 203 | decision | Development methodology retrospective: what I'd keep and what I'd drop | High | goldmine#phase-based-development-story |

## Week 30 — Theme: Personal project philosophy
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 204 | decision | Why I build in public instead of keeping this private | High | goldmine#openclaw-dependency-removal |
| Tue | 205 | decision | Choosing Banglish-first over English-first: the personal call | High | goldmine#banglish-routing-default |
| Wed | 206 | decision | Synapse as a portfolio project: what I prioritized and why | High | goldmine#phase-based-development-story |
| Thu | 207 | decision | When to add a feature vs when to stop and clean up | Medium | goldmine#phase-based-development-story |
| Fri | 208 | struggle | The feature I spent 2 weeks on and then deleted entirely | High | goldmine#openclaw-dependency-removal |
| Sat | 209 | tool-tip | Goldmine.md: how I stay organized for content about my own project | Medium | goldmine#phase-based-development-story |
| Sun | 210 | decision | Personal project retrospective: 6 months in, what I know now | High | goldmine#soul-brain-sync-pipeline |

---

## Phase 4 — Struggles & Lessons

## Week 31 — Theme: The RAM crisis
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 211 | struggle | The machine became unusable. The AI was eating 81% RAM. | High | goldmine#ram-pressure-optimization |
| Tue | 212 | struggle | Round 1: profiling the memory hogs one module at a time | High | goldmine#ram-pressure-optimization |
| Wed | 213 | struggle | Round 2: NetworkX to SQLite — 155MB to 1.2MB for the same data | High | goldmine#networkx-to-sqlite-migration |
| Thu | 214 | struggle | Round 3: lazy loading the models that were sitting idle at 600MB | High | goldmine#lazy-toxic-bert-model |
| Fri | 215 | struggle | After three rounds of optimization: 81% to under 25% RAM | High | goldmine#ram-pressure-optimization |
| Sat | 216 | tool-tip | How to profile Python memory usage without installing a dedicated tool | Medium | goldmine#ram-pressure-optimization |
| Sun | 217 | struggle | RAM crisis retrospective: what I'd architect differently from day 1 | High | goldmine#ram-pressure-optimization |

## Week 32 — Theme: The OpenClaw removal
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 218 | struggle | I built this on a private binary I couldn't open source | High | goldmine#openclaw-dependency-removal |
| Tue | 219 | struggle | The decision: rewrite the entire WhatsApp integration from scratch | High | goldmine#openclaw-dependency-removal |
| Wed | 220 | struggle | Replacing OpenClaw with Baileys: a Node.js bridge from Python | High | goldmine#baileys-crash-recovery |
| Thu | 221 | struggle | Two runtimes, one AI: when Node.js crashes and Python has to recover | High | goldmine#baileys-crash-recovery |
| Fri | 222 | struggle | Exponential backoff for a WhatsApp bridge that crashes randomly | Medium | goldmine#baileys-crash-recovery |
| Sat | 223 | tool-tip | Cross-runtime health checking: HTTP heartbeats from Python to Node | Medium | goldmine#baileys-crash-recovery |
| Sun | 224 | struggle | OpenClaw removal retrospective: what I learned about hard dependencies | High | goldmine#openclaw-dependency-removal |

## Week 33 — Theme: CI & platform hell
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 225 | struggle | Windows CI kept failing and I couldn't reproduce it locally | High | goldmine#windows-ci-lint-failures |
| Tue | 226 | struggle | The noqa comment that wasn't valid — silent failure for weeks | Medium | goldmine#windows-ci-lint-failures |
| Wed | 227 | struggle | The WAL concurrent write test: only fails on Windows, never on Mac | High | goldmine#windows-ci-lint-failures |
| Thu | 228 | struggle | datetime.utcnow(): the Python 3.12 deprecation I didn't notice | Medium | goldmine#datetime-utcnow-deprecation |
| Fri | 229 | struggle | Systematically hunting and replacing deprecated calls across 15k lines | Medium | goldmine#datetime-utcnow-deprecation |
| Sat | 230 | tool-tip | Finding every deprecated call in a Python project: one grep command | Medium | goldmine#datetime-utcnow-deprecation |
| Sun | 231 | struggle | CI retrospective: the failures that were actually worth fixing | Medium | goldmine#windows-ci-lint-failures |

## Week 34 — Theme: Channel bugs
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 232 | struggle | Messages were being silently dropped. I found out 3 days later. | High | goldmine#telegram-enqueue-fn-bug |
| Tue | 233 | struggle | The Telegram enqueue_fn: a factory pattern bug that looked fine | High | goldmine#telegram-enqueue-fn-bug |
| Wed | 234 | struggle | Debugging a message drop with no stack trace and no error log | High | goldmine#telegram-enqueue-fn-bug |
| Thu | 235 | struggle | Discord and Slack weren't flood-gated: introduced a bug while adding a feature | High | goldmine#make-flood-enqueue-factory |
| Fri | 236 | struggle | Integration tests that caught what unit tests couldn't see | Medium | goldmine#telegram-enqueue-fn-bug |
| Sat | 237 | tool-tip | Testing async pipeline integration: the pattern that works reliably | Medium | goldmine#telegram-enqueue-fn-bug |
| Sun | 238 | struggle | Channel bug retrospective: what I'd have tested from day 1 | Medium | goldmine#telegram-enqueue-fn-bug |

## Week 35 — Theme: Onboarding hell
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 239 | struggle | The fresh Mac install that revealed 6 gaps I'd never seen | High | goldmine#mac-fresh-setup-hurdles |
| Tue | 240 | struggle | The onboarding wizard that worked on my machine and failed on yours | High | goldmine#mac-fresh-setup-hurdles |
| Wed | 241 | struggle | launchd vs systemd vs Task Scheduler: the three daemon APIs in one wizard | High | goldmine#cross-platform-daemon-install |
| Thu | 242 | struggle | GitHub Copilot device flow: interactive OAuth in a CLI wizard | Medium | goldmine#cross-platform-daemon-install |
| Fri | 243 | struggle | QR code in a terminal: smaller than it sounds, took longer than expected | Medium | goldmine#cross-platform-daemon-install |
| Sat | 244 | tool-tip | Testing onboarding: the only way is a genuine fresh install | High | goldmine#mac-fresh-setup-hurdles |
| Sun | 245 | struggle | Onboarding retrospective: what I'd ship first if I started again | High | goldmine#mac-fresh-setup-hurdles |

## Week 36 — Theme: Memory & retrieval bugs
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 246 | struggle | The retrieval that kept surfacing irrelevant 10-month-old memories | High | goldmine#hybrid-rag-retrieval |
| Tue | 247 | struggle | Vector-only search fails on short queries — here's why | High | goldmine#hybrid-rag-retrieval |
| Wed | 248 | struggle | FTS-only search fails on semantic queries — here's why | Medium | goldmine#hybrid-rag-retrieval |
| Thu | 249 | struggle | The hybrid merge formula: hours spent on a ranking weight | High | goldmine#hybrid-rag-retrieval |
| Fri | 250 | struggle | The reranker that made retrieval slower without making it better | High | goldmine#flashrank-bypass-for-speed |
| Sat | 251 | tool-tip | High-confidence bypass: skip the reranker when the top result is obvious | High | goldmine#flashrank-bypass-for-speed |
| Sun | 252 | struggle | RAG retrospective: what actually changed from v1 to v3 | High | goldmine#hybrid-rag-retrieval |

## Week 37 — Theme: Concurrency bugs
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 253 | struggle | The garbled response: two workers racing on the same user's context | High | goldmine#session-actor-queue |
| Tue | 254 | struggle | asyncio.Queue with no size limit: how I hit OOM under sustained load | High | goldmine#task-queue-asyncio |
| Wed | 255 | struggle | The double-done crash: ValueError with no stack trace in the queue | High | goldmine#safe-task-done-guard |
| Thu | 256 | struggle | SQLITE_BUSY: the error I didn't handle for the first 3 months | High | goldmine#sqlite-lock-retry-backoff |
| Fri | 257 | struggle | Finding race conditions in asyncio: the debugging process that worked | High | goldmine#session-actor-queue |
| Sat | 258 | tool-tip | asyncio debugging: how to find which coroutine is holding the lock | Medium | goldmine#session-actor-queue |
| Sun | 259 | struggle | Concurrency retrospective: the bugs that only appear under real load | High | goldmine#session-actor-queue |

## Week 38 — Theme: Security gaps
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 260 | struggle | The access control I forgot to add until someone asked me about it | High | goldmine#sentinel-file-access-control |
| Tue | 261 | struggle | SSRF: the attack I didn't think about until the media pipeline | High | goldmine#media-pipeline-ssrf-guard |
| Wed | 262 | struggle | MIME spoofing: the file that claimed to be a JPEG but wasn't | High | goldmine#mime-detection-precedence |
| Thu | 263 | struggle | DM access: the stranger who messaged my AI and got a response | High | goldmine#dm-policy-enum |
| Fri | 264 | struggle | Adding security after the fact: the retroactive hardening sprint | High | goldmine#sentinel-file-access-control |
| Sat | 265 | tool-tip | Defense in depth for a personal AI: the checklist I now run | Medium | goldmine#media-pipeline-ssrf-guard |
| Sun | 266 | struggle | Security retrospective: what belongs in the MVP, not the backlog | High | goldmine#dm-policy-enum |

## Week 39 — Theme: SBS bugs
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 267 | struggle | The profile that drifted: the AI forgot how I speak | High | goldmine#sbs-distillation-cycle |
| Tue | 268 | struggle | Overwriting good data with bad distillation: the silent regression | High | goldmine#sbs-distillation-cycle |
| Wed | 269 | struggle | The 1500-token segment that was too long for the model's context window | High | goldmine#prompt-compiler |
| Thu | 270 | struggle | Teaching the AI to recognize when it got something wrong | High | goldmine#sbs-distillation-cycle |
| Fri | 271 | struggle | The batch distillation that ran at 2am and corrupted the profile | High | goldmine#sbs-distillation-cycle |
| Sat | 272 | tool-tip | Profile versioning: how to recover from a bad distillation run | Medium | goldmine#eight-layer-profile-system |
| Sun | 273 | struggle | SBS retrospective: the hardest subsystem to get right | High | goldmine#soul-brain-sync-pipeline |

## Week 40 — Theme: The dual cognition experiment
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 274 | struggle | I added inner monologue to my AI. Here's what went wrong first. | High | goldmine#dual-cognition-inner-monologue |
| Tue | 275 | struggle | Tension scoring: when the AI disagreed with itself on every message | High | goldmine#dual-cognition-inner-monologue |
| Wed | 276 | struggle | Running inner monologue on every message: the latency hit in production | High | goldmine#fast-phrase-bypass |
| Thu | 277 | struggle | The fast bypass that saved the dual cognition experiment | High | goldmine#fast-phrase-bypass |
| Fri | 278 | struggle | Does inner monologue actually improve responses? The honest answer. | High | goldmine#dual-cognition-inner-monologue |
| Sat | 279 | tool-tip | Measuring the latency cost of a pre-LLM reasoning step | Medium | goldmine#dual-cognition-inner-monologue |
| Sun | 280 | struggle | Dual cognition retrospective: would I build it again? | High | goldmine#dual-cognition-inner-monologue |

## Week 41 — Theme: WhatsApp & cross-runtime
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 281 | struggle | Node.js crashes. Python doesn't know. Messages are lost silently. | High | goldmine#baileys-crash-recovery |
| Tue | 282 | struggle | Exponential backoff for a bridge process that might not restart | High | goldmine#baileys-crash-recovery |
| Wed | 283 | struggle | Session persistence across WhatsApp reconnects | High | goldmine#baileys-crash-recovery |
| Thu | 284 | struggle | Why the WhatsApp protocol lives in Node.js and Python can't replace it | Medium | goldmine#baileys-crash-recovery |
| Fri | 285 | struggle | The 3am reconnect loop that ran for 6 hours before I noticed | High | goldmine#baileys-crash-recovery |
| Sat | 286 | tool-tip | Cross-runtime health checks: HTTP polling from Python to a Node process | Medium | goldmine#baileys-crash-recovery |
| Sun | 287 | struggle | WhatsApp integration retrospective: the most fragile part of the stack | High | goldmine#baileys-crash-recovery |

## Week 42 — Theme: Open source growing pains
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 288 | struggle | The first external contributor: what I wasn't ready for | High | goldmine#openclaw-dependency-removal |
| Tue | 289 | struggle | Reviewing the Cohere provider PR: what I missed on first pass | Medium | goldmine#openclaw-dependency-removal |
| Wed | 290 | struggle | Making sure local files don't leak into a public repository | High | goldmine#openclaw-dependency-removal |
| Thu | 291 | struggle | gitignore archaeology: the files I'd been committing without noticing | Medium | goldmine#openclaw-dependency-removal |
| Fri | 292 | struggle | Writing a CONTRIBUTING.md that contributors actually read and follow | Medium | goldmine#phase-based-development-story |
| Sat | 293 | tool-tip | Pre-commit hooks for a multi-platform open source project | Medium | goldmine#windows-ci-lint-failures |
| Sun | 294 | struggle | Open source phase 1 retrospective: month 1 in public | High | goldmine#openclaw-dependency-removal |

---

## Phase 5 — Meta & Reflections

## Week 43 — Theme: Architecture retrospective
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 295 | architecture | Synapse 12 months in: what survived vs what I rewrote | High | goldmine#soul-brain-sync-pipeline |
| Tue | 296 | architecture | The 3 biggest architecture decisions — and whether they were right | High | goldmine#sqlite-only-no-postgres |
| Wed | 297 | architecture | What stayed identical from v1 to v3 | High | goldmine#gateway-pipeline-five-stages |
| Thu | 298 | architecture | What I rewrote completely — and why | High | goldmine#networkx-to-sqlite-migration |
| Fri | 299 | struggle | The architecture mistake that cost me 2 weeks to unwind | High | goldmine#ram-pressure-optimization |
| Sat | 300 | tool-tip | Drawing the architecture: the one diagram I use to explain Synapse | Medium | goldmine#full-request-pipeline |
| Sun | 301 | architecture | What architecture means for a solo personal project | High | goldmine#phase-based-development-story |

## Week 44 — Theme: Things I'd do differently
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 302 | decision | If I started Synapse today: the first 3 decisions I'd make differently | High | goldmine#sqlite-only-no-postgres |
| Tue | 303 | decision | I'd add security on day 1, not month 6 | High | goldmine#sentinel-file-access-control |
| Wed | 304 | decision | I'd write the onboarding wizard before the features | High | goldmine#mac-fresh-setup-hurdles |
| Thu | 305 | decision | I'd use protocol-based test doubles from the start | Medium | goldmine#wizard-prompter-protocol |
| Fri | 306 | struggle | The decision I regret most: what I built that nobody needed yet | High | goldmine#phase-based-development-story |
| Sat | 307 | tool-tip | 3 tools I'd add to my dev setup from day 1 | Medium | goldmine#phase-based-development-story |
| Sun | 308 | decision | Hindsight architecture: the system I'd design knowing what I know now | High | goldmine#soul-brain-sync-pipeline |

## Week 45 — Theme: The GenAI transition story
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 309 | decision | I'm a .NET developer building GenAI systems in Python. Here's the gap. | High | goldmine#banglish-routing-default |
| Tue | 310 | decision | What transfers from .NET to Python AI: more than you'd think | High | goldmine#async-first-no-celery |
| Wed | 311 | decision | What doesn't transfer: the Python ecosystem surprises | High | goldmine#modular-requirements-split |
| Thu | 312 | decision | Why I chose to build instead of take courses | High | goldmine#phase-based-development-story |
| Fri | 313 | struggle | The things that took 10x longer than expected as a GenAI newcomer | High | goldmine#sbs-distillation-cycle |
| Sat | 314 | tool-tip | How I learn new ML concepts: the project-first approach | Medium | goldmine#hybrid-rag-retrieval |
| Sun | 315 | decision | GenAI transition: 12 months in, the honest assessment | High | goldmine#soul-brain-sync-pipeline |

## Week 46 — Theme: Build-in-public lessons
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 316 | decision | Month 1 of building in public: what I posted, what I held back | High | goldmine#phase-based-development-story |
| Tue | 317 | decision | Going public: what I had to clean up before the repo went open source | High | goldmine#openclaw-dependency-removal |
| Wed | 318 | struggle | The post that flopped and the one I thought would flop but didn't | High | goldmine#ram-pressure-optimization |
| Thu | 319 | decision | What I share about Synapse vs what stays private | High | goldmine#hemisphere-memory-separation |
| Fri | 320 | struggle | Build-in-public anxiety: the posts I almost didn't publish | High | goldmine#phase-based-development-story |
| Sat | 321 | tool-tip | Finding the story in a git commit: how to turn git log into content | High | goldmine#phase-based-development-story |
| Sun | 322 | decision | Build-in-public retrospective: 6 months of posting about a personal project | High | goldmine#openclaw-dependency-removal |

## Week 47 — Theme: Tooling retrospective
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 323 | tool-tip | The 5 libraries that made Synapse possible | High | goldmine#litellm-for-16-providers |
| Tue | 324 | tool-tip | litellm: the routing layer I'd use on every multi-provider project | High | goldmine#litellm-for-16-providers |
| Wed | 325 | tool-tip | sqlite-vec: the extension that replaced Qdrant for me | High | goldmine#no-qdrant-sqlite-vec |
| Thu | 326 | tool-tip | FlashRank: fast reranking without a GPU | Medium | goldmine#flashrank-bypass-for-speed |
| Fri | 327 | tool-tip | questionary + typer: the CLI stack that makes onboarding pleasant | Medium | goldmine#cross-platform-daemon-install |
| Sat | 328 | tool-tip | Ollama: local model serving that actually just works | High | goldmine#ollama-context-window-guard |
| Sun | 329 | tool-tip | Full tooling stack retrospective: what I'd keep and what I'd swap | High | goldmine#litellm-for-16-providers |

## Week 48 — Theme: Personal project sustainability
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 330 | decision | How I keep a personal project alive for 12+ months | High | goldmine#phase-based-development-story |
| Tue | 331 | decision | Phase gates: the discipline that kept me shipping when motivation dropped | High | goldmine#phase-based-development-story |
| Wed | 332 | decision | When to add a feature vs when to stop and consolidate | Medium | goldmine#phase-based-development-story |
| Thu | 333 | struggle | The 3-week block where I didn't commit anything | High | goldmine#phase-based-development-story |
| Fri | 334 | struggle | Scope creep on a solo project: how it happens and how I caught it | High | goldmine#phase-based-development-story |
| Sat | 335 | tool-tip | Keeping a lessons.md: the personal project learning log | Medium | goldmine#phase-based-development-story |
| Sun | 336 | decision | Personal project sustainability retrospective: what actually works | High | goldmine#phase-based-development-story |

## Week 49 — Theme: Community & contributors
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 337 | decision | The first contributor PR: what you learn when someone else reads your code | High | goldmine#openclaw-dependency-removal |
| Tue | 338 | decision | Writing a CONTRIBUTING.md that contributors actually follow | Medium | goldmine#phase-based-development-story |
| Wed | 339 | decision | CODE_OF_CONDUCT.md: why it matters even for a 3-star repository | Low | goldmine#phase-based-development-story |
| Thu | 340 | struggle | Reviewing a PR for a module I wrote 6 months ago | High | goldmine#openclaw-dependency-removal |
| Fri | 341 | struggle | The contributor who found a bug in my test doubles | High | goldmine#wizard-prompter-protocol |
| Sat | 342 | tool-tip | Making your codebase contributor-friendly: the pre-merge checklist | Medium | goldmine#phase-based-development-story |
| Sun | 343 | decision | Community retrospective: what I'd do differently to attract contributors | High | goldmine#openclaw-dependency-removal |

## Week 50 — Theme: What's next for Synapse
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 344 | architecture | Synapse v2: what I'm planning and why | High | goldmine#soul-brain-sync-pipeline |
| Tue | 345 | decision | The features I'm adding next — and the ones I'm cutting | High | goldmine#phase-based-development-story |
| Wed | 346 | decision | Scaling beyond 8GB: what changes architecturally and what stays | High | goldmine#ram-pressure-optimization |
| Thu | 347 | architecture | Multi-user support: the architecture challenge I haven't solved yet | High | goldmine#session-actor-queue |
| Fri | 348 | decision | What I'd build if I had 6 more uninterrupted months | High | goldmine#soul-brain-sync-pipeline |
| Sat | 349 | tool-tip | Planning the next milestone: how I set up a new phase from scratch | Medium | goldmine#phase-based-development-story |
| Sun | 350 | architecture | The future architecture of Synapse: a preview | High | goldmine#soul-brain-sync-pipeline |

## Week 51 — Theme: The honest assessment
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 351 | decision | What Synapse actually does well — without hype | High | goldmine#hybrid-rag-retrieval |
| Tue | 352 | struggle | What Synapse doesn't do well — the honest list | High | goldmine#soul-brain-sync-pipeline |
| Wed | 353 | decision | Is a personal AI actually useful? 12 months of real data. | High | goldmine#banglish-routing-default |
| Thu | 354 | struggle | The features that sounded great in theory and turned out useless | High | goldmine#dual-cognition-inner-monologue |
| Fri | 355 | decision | Would I recommend building your own AI assistant? Honest answer. | High | goldmine#phase-based-development-story |
| Sat | 356 | tool-tip | How to evaluate your own project honestly: the framework I use | Medium | goldmine#phase-based-development-story |
| Sun | 357 | decision | Assessment retrospective: what the honest review revealed about my blindspots | High | goldmine#soul-brain-sync-pipeline |

## Week 52 — Theme: Year-end reflections
| Day | # | Category | Topic | Hook Potential | Source |
|-----|---|----------|-------|----------------|--------|
| Mon | 358 | decision | 365 days of building Synapse: the full timeline | High | goldmine#phase-based-development-story |
| Tue | 359 | struggle | The hardest week of the entire project | High | goldmine#ram-pressure-optimization |
| Wed | 360 | decision | The best decision I made — and it's not the one you'd expect | High | goldmine#sqlite-only-no-postgres |
| Thu | 361 | struggle | The worst decision I made — and how long it took to unwind | High | goldmine#openclaw-dependency-removal |
| Fri | 362 | architecture | Synapse year 1: before and after, the complete system | High | goldmine#soul-brain-sync-pipeline |
| Sat | 363 | tool-tip | The habits that kept this project alive for a year | Medium | goldmine#phase-based-development-story |
| Sun | 364 | decision | Year 2 starts now. Here's what changes. | High | goldmine#soul-brain-sync-pipeline |
| — | 365 | architecture | If you've followed from day 1: thank you. Here's what we built together. | High | goldmine#full-request-pipeline |
