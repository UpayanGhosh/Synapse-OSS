"""
browser/interactions.py — Page interaction implementations.

All functions accept a playwright Page as first arg.
Default timeout is 5000ms unless noted.
"""

from __future__ import annotations

import base64
import re

from playwright.async_api import Page

_DEFAULT_TIMEOUT = 5000
_MAX_SNAPSHOT_CHARS = 50_000
_MAX_DIMENSION = 2000


async def take_screenshot(
    page: Page,
    full_page: bool = False,
    element_selector: str | None = None,
) -> bytes:
    """Return PNG bytes for a viewport/full-page/element screenshot.

    If the resulting image would exceed 2000px on either side, the viewport
    is resized before capture (element screenshots are not resized).
    """
    if element_selector:
        return await page.locator(element_selector).screenshot(timeout=_DEFAULT_TIMEOUT)

    if not full_page:
        vp = page.viewport_size or {"width": 1280, "height": 720}
        if vp["width"] > _MAX_DIMENSION or vp["height"] > _MAX_DIMENSION:
            new_w = min(vp["width"], _MAX_DIMENSION)
            new_h = min(vp["height"], _MAX_DIMENSION)
            await page.set_viewport_size({"width": new_w, "height": new_h})

    return await page.screenshot(full_page=full_page)


async def take_snapshot(page: Page, format: str = "ai") -> dict:
    """Return a text representation of the page.

    format="aria": playwright accessibility snapshot
    format="ai":   stripped HTML — text + links only, no scripts/styles
    """
    if format == "aria":
        snapshot = await page.accessibility.snapshot()
        import json
        text = json.dumps(snapshot, ensure_ascii=False)
        return {"snapshot": text}

    # format == "ai": strip to text + links
    html = await page.content()
    # Remove script/style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    truncated = len(text) > _MAX_SNAPSHOT_CHARS
    return {"snapshot": text[:_MAX_SNAPSHOT_CHARS], "truncated": truncated}


async def click(
    page: Page,
    selector: str,
    double: bool = False,
    button: str = "left",
) -> dict:
    loc = page.locator(selector)
    if double:
        await loc.dblclick(button=button, timeout=_DEFAULT_TIMEOUT)
    else:
        await loc.click(button=button, timeout=_DEFAULT_TIMEOUT)
    return {"ok": True, "selector": selector}


async def type_text(
    page: Page,
    selector: str,
    text: str,
    submit: bool = False,
) -> dict:
    await page.locator(selector).fill(text, timeout=_DEFAULT_TIMEOUT)
    if submit:
        await page.keyboard.press("Enter")
    return {"ok": True}


async def press_key(page: Page, key: str) -> dict:
    await page.keyboard.press(key)
    return {"ok": True, "key": key}


async def hover(page: Page, selector: str) -> dict:
    await page.locator(selector).hover(timeout=_DEFAULT_TIMEOUT)
    return {"ok": True}


async def select_option(page: Page, selector: str, values: list[str]) -> dict:
    await page.locator(selector).select_option(values, timeout=_DEFAULT_TIMEOUT)
    return {"ok": True, "selected": values}


async def fill_form(page: Page, fields: list[dict]) -> dict:
    """Fill multiple form fields. Each field: {selector, value}."""
    for f in fields:
        await page.locator(f["selector"]).fill(f["value"], timeout=_DEFAULT_TIMEOUT)
    return {"ok": True, "filled": len(fields)}


async def wait_for(
    page: Page,
    text: str | None = None,
    selector: str | None = None,
    url: str | None = None,
    timeout_ms: int = 10_000,
) -> dict:
    """Wait for a condition: text present, selector visible, or URL match."""
    timeout_ms = min(timeout_ms, 30_000)

    if text is not None:
        # Pass text as an argument to avoid JS injection via f-string interpolation.
        await page.wait_for_function(
            "(t) => document.body.innerText.includes(t)",
            arg=text,
            timeout=timeout_ms,
        )
        return {"ok": True, "condition": "text"}

    if selector is not None:
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return {"ok": True, "condition": "selector"}

    if url is not None:
        await page.wait_for_url(url, timeout=timeout_ms)
        return {"ok": True, "condition": "url"}

    return {"ok": False, "condition": "none_specified"}


_MAX_EVAL_RESULT_CHARS = 50_000

# Patterns that indicate dangerous JS API usage.  This is a defence-in-depth
# heuristic — not a sandbox replacement — but it blocks the most common
# data-exfiltration and same-origin-bypass vectors.
_BLOCKED_JS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE),
    re.compile(r"\bdocument\s*\.\s*cookie\b", re.IGNORECASE),
    re.compile(r"\blocalStorage\b", re.IGNORECASE),
    re.compile(r"\bsessionStorage\b", re.IGNORECASE),
    re.compile(r"\bindexedDB\b", re.IGNORECASE),
    re.compile(r"\bnavigator\s*\.\s*sendBeacon\b", re.IGNORECASE),
    re.compile(r"\bimportScripts\b", re.IGNORECASE),
    re.compile(r"\bWebSocket\b", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bFunction\s*\(", re.IGNORECASE),
]


async def evaluate_js(page: Page, expression: str) -> dict:
    """Execute a JS expression in page context and return the result.

    Security boundary
    -----------------
    * A blocklist rejects expressions that reference common exfiltration or
      persistence APIs (fetch, XHR, cookies, storage, WebSocket, eval, etc.).
    * The stringified result is truncated to ``_MAX_EVAL_RESULT_CHARS``.

    This is **not** a sandbox.  The caller is responsible for ensuring that
    ``expression`` comes from a trusted source (e.g. an MCP tool invocation
    with appropriate access controls), not from untrusted user input.
    """
    for pattern in _BLOCKED_JS_PATTERNS:
        if pattern.search(expression):
            return {
                "ok": False,
                "error": (
                    f"Expression blocked: matches restricted pattern "
                    f"{pattern.pattern!r}.  Avoid fetch, XHR, cookies, "
                    f"storage, WebSocket, eval, and Function()."
                ),
            }

    result = await page.evaluate(expression)
    text = str(result)
    truncated = len(text) > _MAX_EVAL_RESULT_CHARS
    return {
        "ok": True,
        "result": text[:_MAX_EVAL_RESULT_CHARS],
        "truncated": truncated,
    }
