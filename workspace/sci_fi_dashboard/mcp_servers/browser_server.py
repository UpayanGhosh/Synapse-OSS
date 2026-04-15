"""
MCP Server: Synapse Browser — headless Chromium automation via Playwright.
Run standalone: python -m sci_fi_dashboard.mcp_servers.browser_server
"""

import asyncio
import base64
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .base import logger, setup_logging

server = Server("synapse-browser")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="browser",
            description=(
                "Control a headless Chromium browser. "
                "Actions: start, stop, status, open, close, tabs, "
                "navigate, screenshot, snapshot, console, act"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "start",
                            "stop",
                            "status",
                            "open",
                            "close",
                            "tabs",
                            "navigate",
                            "screenshot",
                            "snapshot",
                            "console",
                            "act",
                        ],
                    },
                    "tab_id": {"type": "string"},
                    "url": {"type": "string"},
                    "session_key": {"type": "string", "default": "default"},
                    "full_page": {"type": "boolean", "default": False},
                    "selector": {"type": "string"},
                    "format": {
                        "type": "string",
                        "enum": ["ai", "aria"],
                        "default": "ai",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "click",
                            "type",
                            "press",
                            "hover",
                            "select",
                            "fill",
                            "wait",
                            "evaluate",
                        ],
                    },
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "selector": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                    },
                    "double_click": {"type": "boolean", "default": False},
                    "submit": {"type": "boolean", "default": False},
                    "timeout_ms": {"type": "integer", "default": 10000},
                    "expression": {"type": "string"},
                },
                "required": ["action"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "browser":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    from sci_fi_dashboard.browser import interactions as ix
    from sci_fi_dashboard.browser import session as sess
    from sci_fi_dashboard.browser.navigation_guard import NavigationBlockedError

    action = arguments.get("action")

    try:
        # ── Lifecycle ──────────────────────────────────────────────────────
        if action == "start":
            result = await sess.start_browser()
            return [TextContent(type="text", text=json.dumps(result))]

        elif action == "stop":
            result = await sess.stop_browser()
            return [TextContent(type="text", text=json.dumps(result))]

        elif action == "status":
            result = await sess.get_status()
            return [TextContent(type="text", text=json.dumps(result))]

        # ── Tab management ─────────────────────────────────────────────────
        elif action == "open":
            url = arguments.get("url", "about:blank")
            session_key = arguments.get("session_key", "default")
            result = await sess.open_tab(url, session_key)
            return [TextContent(type="text", text=json.dumps(result))]

        elif action == "close":
            tab_id = arguments["tab_id"]
            result = await sess.close_tab(tab_id)
            return [TextContent(type="text", text=json.dumps(result))]

        elif action == "tabs":
            result = await sess.list_tabs()
            return [TextContent(type="text", text=json.dumps(result))]

        # ── Navigation ─────────────────────────────────────────────────────
        elif action == "navigate":
            tab_id = arguments["tab_id"]
            url = arguments["url"]
            result = await sess.navigate(tab_id, url)
            return [TextContent(type="text", text=json.dumps(result))]

        # ── Page capture ───────────────────────────────────────────────────
        elif action == "screenshot":
            tab_id = arguments["tab_id"]
            page = sess.get_page(tab_id)
            png_bytes = await ix.take_screenshot(
                page,
                full_page=arguments.get("full_page", False),
                element_selector=arguments.get("selector"),
            )
            b64 = base64.b64encode(png_bytes).decode("ascii")
            return [TextContent(type="text", text=f"data:image/png;base64,{b64}")]

        elif action == "snapshot":
            tab_id = arguments["tab_id"]
            page = sess.get_page(tab_id)
            result = await ix.take_snapshot(
                page,
                format=arguments.get("format", "ai"),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif action == "console":
            tab_id = arguments["tab_id"]
            result = await sess.get_console(tab_id)
            return [TextContent(type="text", text=json.dumps(result))]

        # ── Interactions (act) ─────────────────────────────────────────────
        elif action == "act":
            tab_id = arguments["tab_id"]
            page = sess.get_page(tab_id)
            kind = arguments.get("kind")

            if kind == "click":
                result = await ix.click(
                    page,
                    selector=arguments["selector"],
                    double=arguments.get("double_click", False),
                    button=arguments.get("button", "left"),
                )
            elif kind == "type":
                result = await ix.type_text(
                    page,
                    selector=arguments["selector"],
                    text=arguments["text"],
                    submit=arguments.get("submit", False),
                )
            elif kind == "press":
                result = await ix.press_key(page, key=arguments["key"])
            elif kind == "hover":
                result = await ix.hover(page, selector=arguments["selector"])
            elif kind == "select":
                result = await ix.select_option(
                    page,
                    selector=arguments["selector"],
                    values=arguments.get("values", []),
                )
            elif kind == "fill":
                result = await ix.fill_form(
                    page,
                    fields=arguments.get("fields", []),
                )
            elif kind == "wait":
                result = await ix.wait_for(
                    page,
                    text=arguments.get("text"),
                    selector=arguments.get("selector"),
                    url=arguments.get("url"),
                    timeout_ms=arguments.get("timeout_ms", 10_000),
                )
            elif kind == "evaluate":
                result = await ix.evaluate_js(page, expression=arguments["expression"])
            else:
                return [TextContent(type="text", text=f"Unknown act kind: {kind}")]

            return [TextContent(type="text", text=json.dumps(result))]

        else:
            return [TextContent(type="text", text=f"Unknown action: {action}")]

    except NavigationBlockedError as e:
        return [TextContent(type="text", text=f"BLOCKED: {e.reason}")]
    except KeyError as e:
        return [TextContent(type="text", text=f"Missing parameter: {e}")]
    except Exception as e:
        logger.exception("browser tool error (action=%s)", action)
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse Browser MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
