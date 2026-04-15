"""
SynapseMCPClient — connects Synapse to all MCP servers (built-in + user-configured).
Tool routing: serverName__toolName (e.g., synapse-gmail__search_emails)
"""

import asyncio
import contextlib
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger("synapse.mcp.client")


@dataclass
class MCPServerConnection:
    name: str
    session: ClientSession | None = None
    tools: list[dict] = field(default_factory=list)
    connected: bool = False
    ctx: Any = field(default=None, repr=False)


class SynapseMCPClient:
    def __init__(self):
        self._servers: dict[str, MCPServerConnection] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}  # key -> (serverName, originalToolName)

    async def _connect_server(
        self, name: str, server_params: StdioServerParameters, *, register_unqualified: bool = False
    ) -> None:
        ctx = None
        session = None
        try:
            ctx = stdio_client(server_params)
            read, write = await ctx.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in tools_resp.tools
            ]
            self._servers[name] = MCPServerConnection(
                name=name, session=session, tools=tools, connected=True, ctx=ctx
            )
            for tool in tools:
                self._tool_map[f"{name}__{tool['name']}"] = (name, tool["name"])
                if register_unqualified:
                    unqualified = tool["name"]
                    if unqualified in self._tool_map:
                        logger.warning(
                            f"[MCP] Tool name conflict: '{unqualified}' already registered "
                            f"(server: {self._tool_map[unqualified][0]}), overwriting with '{name}'"
                        )
                    self._tool_map[unqualified] = (name, tool["name"])
            logger.info(f"Connected to MCP server '{name}' with {len(tools)} tools")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{name}': {e}")
            for handle in (session, ctx):
                if handle is not None:
                    with contextlib.suppress(Exception):
                        await handle.__aexit__(None, None, None)

    async def connect_builtin_server(self, name: str, module_path: str) -> None:
        params = StdioServerParameters(command=sys.executable, args=["-m", module_path])
        await self._connect_server(name, params, register_unqualified=True)

    async def connect_custom_server(
        self, name: str, command: str, args: list[str], env: dict | None = None
    ) -> None:
        params = StdioServerParameters(command=command, args=args, env=env)
        await self._connect_server(name, params, register_unqualified=False)

    async def call_tool(self, tool_name: str, arguments: dict, timeout: float = 10.0) -> str:
        if tool_name not in self._tool_map:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        server_name, original_name = self._tool_map[tool_name]
        conn = self._servers.get(server_name)
        if not conn or not conn.connected or not conn.session:
            return json.dumps({"error": f"Server '{server_name}' not connected"})
        try:
            result = await asyncio.wait_for(
                conn.session.call_tool(original_name, arguments), timeout=timeout
            )
            return "\n".join(c.text for c in result.content if hasattr(c, "text"))
        except TimeoutError:
            return json.dumps({"error": f"Tool call timed out after {timeout}s: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": f"Tool call failed: {e}"})

    def list_all_tools(self) -> list[dict]:
        all_tools = []
        for name, conn in self._servers.items():
            for tool in conn.tools:
                all_tools.append(
                    {
                        "name": f"{name}__{tool['name']}",
                        "description": f"[{name}] {tool['description']}",
                        "inputSchema": tool["inputSchema"],
                    }
                )
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
            with contextlib.suppress(Exception):
                await conn.session.__aexit__(None, None, None)
        if conn.ctx:
            with contextlib.suppress(Exception):
                await conn.ctx.__aexit__(None, None, None)
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
        tasks = [
            self.connect_builtin_server(name, builtin_modules[name])
            for name, cfg in mcp_config.builtin_servers.items()
            if cfg.enabled and name in builtin_modules
        ]
        tasks += [
            self.connect_custom_server(name, cfg.command, cfg.args, cfg.env or None)
            for name, cfg in mcp_config.custom_servers.items()
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def disconnect_all(self) -> None:
        for conn in self._servers.values():
            if conn.session:
                with contextlib.suppress(Exception):
                    await conn.session.__aexit__(None, None, None)
            if conn.ctx:
                with contextlib.suppress(Exception):
                    await conn.ctx.__aexit__(None, None, None)
        self._servers.clear()
        self._tool_map.clear()
