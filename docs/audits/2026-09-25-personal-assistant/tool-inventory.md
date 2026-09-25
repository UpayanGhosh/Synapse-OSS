# Synapse tool inventory

This inventory separates the tools registered in the chat runtime from features that require configuration or are implemented elsewhere. The native registry is initialized only when available, and resolves tools per request; owner checks, Sentinel/tool-safety filtering, prompt tier, and model tool-call support can reduce the set exposed on a given turn. See [`api_gateway.py`](../../../workspace/sci_fi_dashboard/api_gateway.py#L179) and [`chat_pipeline.py`](../../../workspace/sci_fi_dashboard/chat_pipeline.py#L2717).

## Native chat tools

The gateway registers these 14 factory names: seven general tools and seven system-operation tools. Sources: [`tool_registry.py`](../../../workspace/sci_fi_dashboard/tool_registry.py#L217) and [`tool_sysops.py`](../../../workspace/sci_fi_dashboard/tool_sysops.py#L504).

| Tool | What it does | Availability / guard |
| --- | --- | --- |
| `web_search` | Fetches and extracts readable content from a supplied URL. | Network/legacy fetch implementation must be available. |
| `web_query` | Searches DuckDuckGo HTML results and returns result titles and URLs. | Requires `httpx` and network access. |
| `query_memory` | Searches relevant episodes in the verified conversation’s personal-memory scope. | Missing verified scope or store returns no results; it does not query the global memory engine. |
| `calendar` | Handles natural-language calendar questions, availability, date resolution, and event changes. | Requires Calendar Core and a configured Google Calendar token; destructive edits use explicit confirmation. |
| `connect_integration` | Lists integration options/status or starts an OAuth connection. | Owner-only; currently supports Google Calendar, Gmail, Notion, and Slack aliases. |
| `read_file` | Reads a file through Sentinel. | Sentinel-gated. |
| `write_file` | Writes a text file and audit-logs the operation. | Owner-only and Sentinel-gated; binary/structured-file writes are blocked. |
| `bash_exec` | Runs a shell command. | Owner-only, command safety checks and timeout/output caps apply. |
| `edit_file` | Replaces text in a file. | Owner-only and Sentinel-gated. |
| `grep_tool` | Searches file contents, using ripgrep when available. | Searches the selected workspace/path; result count is capped. |
| `glob_tool` | Finds files by path/name pattern. | Searches the selected workspace/path; result count is capped. |
| `edit_synapse_config` | Reads or changes `~/.synapse/synapse.json`, validating and backing up changes. | Owner-only. Model selection can be checked against reachable Copilot/Ollama models. |
| `list_directory` | Lists directory entries. | Sentinel-gated. |
| `list_available_models` | Lists models reachable from GitHub Copilot and Ollama. | Only reports those providers and only when their endpoints/auth are reachable. |

Registration and implementation details: [`tool_registry.py`](../../../workspace/sci_fi_dashboard/tool_registry.py#L717), [`tool_sysops.py`](../../../workspace/sci_fi_dashboard/tool_sysops.py#L1065). `switch_model`, `import_memory`, and `list_tools` have definitions in [`tool_features.py`](../../../workspace/sci_fi_dashboard/tool_features.py#L94), but no runtime registration/call path was found; they are not part of the callable native list.

## Conditional MCP and skills

MCP is disabled when the `mcp` configuration section is absent. When enabled, Synapse can connect configured built-in servers for memory, conversation, tools, Gmail, Calendar, and Slack, plus custom stdio servers. See [`mcp_config.py`](../../../workspace/sci_fi_dashboard/mcp_config.py#L87), [`mcp_client.py`](../../../workspace/sci_fi_dashboard/mcp_client.py#L138), and gateway startup in [`api_gateway.py`](../../../workspace/sci_fi_dashboard/api_gateway.py#L272).

Important wiring boundary: the chat model’s native schemas come from `ToolRegistry.resolve`; connected MCP server tools are not dynamically added to that registry. The MCP client is attached to the worker and used by configured proactive flows, so connection/listing alone does not mean every MCP function is callable by the chat model. See [`chat_pipeline.py`](../../../workspace/sci_fi_dashboard/chat_pipeline.py#L2717) and [`api_gateway.py`](../../../workspace/sci_fi_dashboard/api_gateway.py#L285).

Skills are a separate, optional procedure/entrypoint system. The gateway seeds bundled skills and builds a router when the skill system is available; matched skills run through `SkillRunner`. They are not a fixed native tool list, and available procedures depend on installed/enabled skill manifests. See [`api_gateway.py`](../../../workspace/sci_fi_dashboard/api_gateway.py#L445) and [`chat_pipeline.py`](../../../workspace/sci_fi_dashboard/chat_pipeline.py#L2409).

## Not verified as native capabilities

There is no native Maps or weather integration, no standard browser tool in the built-in MCP server list, and no verified browser-based shopping/order workflow. A custom MCP server or a suitable installed skill could add capabilities, but the current registry does not guarantee them. The repository has a browser MCP server module, but it is not one of the built-in modules connected by `SynapseMCPClient` (`mcp_client.py:139-146`).
