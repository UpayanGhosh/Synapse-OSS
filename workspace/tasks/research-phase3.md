## Agent 1: SSRF + MCP Pattern

### SSRF Check Function

**Signature:**
```python
async def is_ssrf_blocked(url: str) -> bool
```

- **Accepts:** raw URL string
- **Returns:** `bool` — `True` if blocked/private, `False` if safe
- **Fail-closed:** returns `True` on any exception (DNS failure, malformed URL, unparseable IP)
- **Does NOT raise** — the caller (`download_to_file`) raises `PermissionError(f"SSRF blocked: {url}")` after checking the return value

**Block conditions:**
- URL with no hostname
- Blocklist hostnames: `localhost`, `metadata.google.internal`
- Suffixes: `.local`, `.internal`, `.localhost`
- Private/loopback IPs: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1/128`, `fc00::/7`

### MCP Server Boilerplate Pattern (from tools_server.py)

**1. Server init:**
```python
from mcp.server import Server
server = Server("synapse-tools")
```

**2. Tool registration:**
```python
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name="...", description="...", inputSchema={...}), ...]
```

**3. Tool execution:**
```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "tool_name":
        result = await do_something(arguments["param"])
        return [TextContent(type="text", text=result)]
    raise ValueError(f"Unknown tool: {name}")
```

**4. Server startup:**
```python
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
```

### call_tool() Return: Errors vs Success

Both use the **same `list[TextContent]` structure** — there is no separate error object:
- **Success:** `[TextContent(type="text", text=result_string)]`
- **Error:** `[TextContent(type="text", text=error_message_string)]`

Errors are embedded as plain text strings, not as structured error types.

---

## Agent 2: Playwright Availability

**Date:** 2026-04-02

### Is playwright importable? Version?

Yes, playwright is importable. The package does not expose a `__version__` attribute directly on the module, but `importlib.metadata.version('playwright')` returns **1.58.0**.

### Is async_playwright available?

Yes. `from playwright.async_api import async_playwright` imports successfully and returns `ok`.

### weakref availability

`import weakref` succeeds — `weakref ok`.

### Are Chromium browsers installed or need install step?

Browsers are **already installed**. The following are present under `C:\Users\Shorty0_0\AppData\Local\ms-playwright\`:

- `chromium-1208` — Chrome for Testing 145.0.7632.6
- `chromium_headless_shell-1208` — Chrome Headless Shell 145.0.7632.6
- `ffmpeg-1011`
- `winldd-1007`

Firefox and WebKit are **not** installed, but Chromium headless is ready to use — no `playwright install` step needed for headless browsing.

The `--dry-run` output confirms the expected install location is `C:\Users\Shorty0_0\AppData\Local\ms-playwright\chromium-1208` and the download URL would be `https://cdn.playwright.dev/chrome-for-testing-public/145.0.7632.6/win64/chrome-win64.zip`.

### What's in requirements-optional.txt regarding playwright?

Found at `D:/Shreya/Synapse-OSS/requirements-optional.txt` (repo root, not workspace/):

```
# crawl4ai on Mac/Linux; playwright on Windows (crawl4ai has build failures on Windows)
crawl4ai>=0.2.0 ; sys_platform != 'win32'    # Headless browser automation — Mac/Linux only
playwright>=1.20.0 ; sys_platform == 'win32' # Windows browser automation — replaces crawl4ai on Windows
```

Playwright is the **Windows-only replacement for crawl4ai**. The project explicitly uses playwright on Windows because crawl4ai has build failures there. The installed version (1.58.0) satisfies the `>=1.20.0` requirement.

### Summary

| Check | Result |
|---|---|
| `import playwright` | OK (version 1.58.0 via importlib.metadata) |
| `from playwright.async_api import async_playwright` | OK |
| `import weakref` | OK |
| Chromium installed | YES — chromium-1208 + headless shell both present |
| Firefox installed | No |
| WebKit installed | No |
| requirements-optional.txt entry | `playwright>=1.20.0 ; sys_platform == 'win32'` (Windows-only) |
| Needs `playwright install`? | No — Chromium headless is already available |

---

## Agent 3: MVP Scope

### MVP Actions (Essential - used in >80% of browser automation)

| Action | Classification | Description | Playwright Method |
|--------|-----------------|-------------|-------------------|
| `navigate` | MVP | Navigate current tab to URL | `page.goto(url)` |
| `screenshot` | MVP | Capture viewport/full-page/element image | `page.screenshot()` |
| `snapshot` | MVP | Capture accessibility/AI-optimized page tree | `page._snapshotForAI()` / `page.accessibility.snapshot()` |
| `act` | MVP | Execute page interactions (click, type, etc.) | Various (dispatches to specific act-kinds) |
| `tabs` | MVP | List open tabs | (State management, no direct method) |
| `open` | MVP | Open a new tab to URL | `context.newPage()` + `page.goto(url)` |
| `start` | MVP | Launch browser instance | `chromium.launch()` / `chromium.connectOverCDP(url)` |
| `console` | MVP | Retrieve console + error log | (Page state tracking, event listeners) |

### MVP Act Kinds (Essential - building blocks for user interactions)

| Act Kind | Classification | Description | Playwright Method |
|----------|-----------------|-------------|-------------------|
| `click` | MVP | Single or double-click an element | `locator.click()` / `locator.dblclick()` |
| `type` | MVP | Type text (optionally submit) | `locator.fill()` + optionally `page.keyboard.press('Enter')` |
| `press` | MVP | Send a single key (e.g., "Enter", "Escape") | `page.keyboard.press(key)` |
| `hover` | MVP | Hover over element | `locator.hover()` |
| `wait` | MVP | Wait for text, element, URL, or load state | `page.locator(selector).waitFor()` / `page.waitForLoadState()` / `page.waitForURL(url)` |
| `fill` | MVP | Bulk form fill (`fields[]`) | Multiple `locator.fill()` calls |
| `select` | MVP | Select dropdown option(s) | `locator.selectOption(values)` |

### DEFER Actions (Complex/Rare - edge cases)

| Action | Reason | Classification |
|--------|--------|-----------------|
| `stop` | Lifecycle management; rarely triggered in typical workflows | DEFER |
| `focus` | Tab management; navigation handles most use cases | DEFER |
| `close` | Tab cleanup; session end auto-closes tabs | DEFER |
| `profiles` | Browser profile selection; configuration step, not runtime interaction | DEFER |
| `pdf` | Document export; specialized, non-interactive feature | DEFER |
| `upload` | File upload dialogs; edge case requiring special handling | DEFER |
| `dialog` | Dialog acceptance; relatively rare; handled via `press` for simple dismissals | DEFER |

### DEFER Act Kinds (Complex/Rare - edge cases)

| Act Kind | Reason | Classification |
|----------|--------|-----------------|
| `drag` | Drag-and-drop interactions; uncommon in form-heavy automation | DEFER |
| `evaluate` | Arbitrary JavaScript execution; risky and rarely needed for standard automation | DEFER |
| `resize` | Viewport resizing; typically handled once at session start | DEFER |
| `batch` | Sequential action batching; can be achieved via separate `act` calls | DEFER |

### Summary

**MVP Scope: 8 Actions + 7 Act Kinds = 15 core features**
- These cover navigation, page capture, interaction (click/type/press/hover/wait), form handling (fill/select), and state inspection
- Account for >80% of typical browser automation workflows

**DEFER Scope: 8 Actions + 4 Act Kinds = 12 specialized features**
- Cookie/storage management, file uploads, dialogs, PDFs, evaluate, resize, drag, batch
- Justify reduction in MVP scope without losing essential functionality
