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
        safe = text.replace("'", "\\'")
        await page.wait_for_function(
            f"document.body.innerText.includes('{safe}')",
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


async def evaluate_js(page: Page, expression: str) -> dict:
    result = await page.evaluate(expression)
    return {"ok": True, "result": str(result)}
