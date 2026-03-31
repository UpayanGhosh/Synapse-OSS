"""
SynapseMCPClient — connects Synapse to all MCP servers (built-in + user-configured).
Tool routing: serverName__toolName (e.g., synapse-gmail__search_emails)
"""
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

logger = logging.getLogger("synapse.mcp.client")


@dataclass
class MCPServerConnection:
    name: str
    session: ClientSession | None = None
    tools: list[dict] = field(default_factory=list)
    connected: bool = False


class SynapseMCPClient:
    def __init__(self):
        self._servers: dict[str, MCPServerConnection] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}  # key -> (serverName, originalToolName)
        self._contexts: list = []  # track context managers for cleanup

    async def connect_builtin_server(self, name: str, module_path: str) -> None:
        server_params = StdioServerParameters(command=sys.executable, args=["-m", module_path])
        try:
            ctx = stdio_client(server_params)
            read, write = await ctx.__aenter__()
            self._contexts.append(ctx)
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in tools_resp.tools
            ]
            self._servers[name] = MCPServerConnection(
                name=name, session=session, tools=tools, connected=True
            )
            for tool in tools:
                self._tool_map[f"{name}__{tool['name']}"] = (name, tool["name"])
                self._tool_map[tool["name"]] = (name, tool["name"])  # unqualified fallback
            logger.info(f"Connected to MCP server '{name}' with {len(tools)} tools")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{name}': {e}")

    async def connect_custom_server(
        self, name: str, command: str, args: list[str], env: dict | None = None
    ) -> None:
        server_params = StdioServerParameters(command=command, args=args, env=env)
        try:
            ctx = stdio_client(server_params)
            read, write = await ctx.__aenter__()
            self._contexts.append(ctx)
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in tools_resp.tools
            ]
            self._servers[name] = MCPServerConnection(
                name=name, session=session, tools=tools, connected=True
            )
            for tool in tools:
                self._tool_map[f"{name}__{tool['name']}"] = (name, tool["name"])
            logger.info(f"Connected to custom MCP server '{name}' with {len(tools)} tools")
        except Exception as e:
            logger.error(f"Failed to connect to custom MCP server '{name}': {e}")

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self._tool_map:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        server_name, original_name = self._tool_map[tool_name]
        conn = self._servers.get(server_name)
        if not conn or not conn.connected or not conn.session:
            return json.dumps({"error": f"Server '{server_name}' not connected"})
        try:
            result = await conn.session.call_tool(original_name, arguments)
            return "\n".join(c.text for c in result.content if hasattr(c, "text"))
        except Exception as e:
            return json.dumps({"error": f"Tool call failed: {e}"})

    def list_all_tools(self) -> list[dict]:
        all_tools = []
        for name, conn in self._servers.items():
            for tool in conn.tools:
                all_tools.append({
                    "name": f"{name}__{tool['name']}",
                    "description": f"[{name}] {tool['description']}",
                    "inputSchema": tool["inputSchema"],
                })
        return all_tools

    async def add_server(
        self, name: str, command: str, args: list[str], env: dict | None = None
    ) -> bool:
        """Dynamically add and connect to a new MCP server at runtime."""
        if name in self._servers:
            logger.warning(f"Server '{name}' already connected")
            return False
        await self.connect_custom_server(name, command, args, env)
        return name in self._servers and self._servers[name].connected

    async def remove_server(self, name: str) -> bool:
        """Disconnect and remove an MCP server."""
        conn = self._servers.get(name)
        if not conn:
            return False
        if conn.session:
            try:
                await conn.session.__aexit__(None, None, None)
            except Exception:
                pass
        to_remove = [k for k, (sn, _) in self._tool_map.items() if sn == name]
        for k in to_remove:
            del self._tool_map[k]
        del self._servers[name]
        return True

    async def connect_all(self, mcp_config) -> None:
        builtin_modules = {
            "memory": "sci_fi_dashboard.mcp_servers.memory_server",
            "conversation": "sci_fi_dashboard.mcp_servers.conversation_server",
            "tools": "sci_fi_dashboard.mcp_servers.tools_server",
            "gmail": "sci_fi_dashboard.mcp_servers.gmail_server",
            "calendar": "sci_fi_dashboard.mcp_servers.calendar_server",
            "slack": "sci_fi_dashboard.mcp_servers.slack_server",
        }
        for name, cfg in mcp_config.builtin_servers.items():
            if cfg.enabled and name in builtin_modules:
                await self.connect_builtin_server(name, builtin_modules[name])
        for name, cfg in mcp_config.custom_servers.items():
            await self.connect_custom_server(name, cfg.command, cfg.args, cfg.env or None)

    async def disconnect_all(self) -> None:
        for conn in self._servers.values():
            if conn.session:
                try:
                    await conn.session.__aexit__(None, None, None)
                except Exception:
                    pass
        for ctx in self._contexts:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._servers.clear()
        self._tool_map.clear()
        self._contexts.clear()
