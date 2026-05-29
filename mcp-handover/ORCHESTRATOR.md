# MCP Implementation Orchestrator — Synapse-OSS

> **INSTRUCTIONS FOR CLAUDE SONNET 4.6**: Execute phases sequentially. For each phase, read ONLY the corresponding phase file. Do NOT read all files at once.

## Vision
Synapse-OSS is a hyper-personalized AI assistant that grows with its user. MCP (Model Context Protocol) connects Synapse to the user's entire digital life — Gmail, Calendar, Slack — through a standardized protocol. The goal: a proactive, life-aware companion that checks your schedule, emails, and messages BEFORE you ask.

## Architecture: Hub-and-Spoke
- **Synapse = Hub** (MCP Host + Client + Server)
- **Each service = Spoke** (MCP Server: memory, gmail, calendar, slack, tools)
- **Proactive Awareness**: Background polling of personal services, injected into system prompts

## Repo Location
`C:\Users\upayan.ghosh\personal\Synapse-OSS`

## Key Existing Files (read CLAUDE.md in repo root for full map)
| File | What |
|------|------|
| `workspace/synapse_config.py` | SynapseConfig dataclass (frozen), loads from synapse.json |
| `workspace/sci_fi_dashboard/api_gateway.py` | FastAPI app, all singleton init |
| `workspace/sci_fi_dashboard/memory_engine.py` | `MemoryEngine.query()` and `.add_memory()` |
| `workspace/sci_fi_dashboard/llm_router.py` | `SynapseLLMRouter` — litellm dispatch |
| `workspace/sci_fi_dashboard/channels/base.py` | `BaseChannel` ABC, `ChannelMessage` DTO |
| `workspace/sci_fi_dashboard/gateway/worker.py` | `MessageWorker._handle_task()` |
| `workspace/sci_fi_dashboard/sbs/orchestrator.py` | `SBSOrchestrator.get_system_prompt()` |
| `workspace/sci_fi_dashboard/db/tools.py` | `ToolRegistry.search_web()` |
| `workspace/sci_fi_dashboard/sbs/sentinel/gateway.py` | `Sentinel` file access control |

## Phase Execution Order

### Phase 0: Prerequisites
**Read**: `mcp-handover/phase0-prereqs.md`
**Goal**: Install deps, create config models, update synapse.json schema
**Verify**: `pip install mcp` succeeds, `from mcp_config import MCPConfig` works

### Phase 1: Core MCP Servers (Week 1)
**Read**: `mcp-handover/phase1-core-servers.md`
**Goal**: Create 3 MCP servers — Memory, Conversation, Tools
**Verify**: `mcp-inspector python -m sci_fi_dashboard.mcp_servers.memory_server` shows tools

### Phase 2: Personal Life Servers (Week 2)
**Read**: `mcp-handover/phase2-personal-servers.md`
**Goal**: Create Gmail, Calendar, Slack MCP servers
**Verify**: `mcp-inspector` shows gmail/calendar/slack tools

### Phase 3: MCP Client + Gateway Integration (Week 3)
**Read**: `mcp-handover/phase3-client-integration.md`
**Goal**: SynapseMCPClient connects to all servers, integrated into gateway pipeline
**Verify**: Start Synapse, logs show "[MCP] Connected. Available tools: N"

### Phase 4: Proactive Awareness Engine (Week 4)
**Read**: `mcp-handover/phase4-proactive.md`
**Goal**: Background polling + SBS injection + notification triggers
**Verify**: System prompt includes [PROACTIVE AWARENESS] block

### Phase 5: Registry + Synapse-as-Server (Week 5+)
**Read**: `mcp-handover/phase5-registry-and-server.md`
**Goal**: User-configurable MCP servers + expose Synapse itself as MCP server
**Verify**: Community MCP server connects; `mcp-inspector` shows synapse tools

## Security Rules (apply to ALL phases)
- All tool arguments validated via JSON Schema before execution
- File operations gated by Sentinel (fail-closed)
- No API keys/tokens in tool results
- MCP server logs go to stderr (stdout = protocol)
- Email/web content capped at 3000 chars
- SSRF prevention via existing `is_ssrf_blocked()`

## After Each Phase
1. Run `cd workspace && pytest tests/ -v` — verify no regressions (302+ tests)
2. Commit with message: `feat(mcp): phase N — <description>`
3. Read the next phase file
