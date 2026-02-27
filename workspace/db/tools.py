import asyncio
import json
import sys


class ToolRegistry:
    @staticmethod
    def get_tool_schemas():
        """Returns the OpenAI-compatible JSON schema for the tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Searches the live internet by visiting a URL and extracting the main content as clean markdown. Use this whenever you need up-to-date information, weather, or factual data not in your memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The exact URL to visit (e.g., 'https://lite.cnn.com' or a google search URL like 'https://www.google.com/search?q=weather+kolkata')",
                            }
                        },
                        "required": ["url"],
                    },
                },
            }
        ]

    @staticmethod
    async def search_web(url: str) -> str:
        """The actual execution engine for the browser.

        Dispatches to Playwright on Windows (sys.platform == 'win32') and
        Crawl4AI on Mac/Linux. Both backends return up to 3000 chars of
        visible page text.
        """
        if sys.platform == "win32":
            return await ToolRegistry._search_web_playwright(url)
        else:
            return await ToolRegistry._search_web_crawl4ai(url)

    @staticmethod
    async def _search_web_crawl4ai(url: str) -> str:
        from crawl4ai import AsyncWebCrawler  # lazy import -- only on Mac/Linux

        print(f"[Crawl4AI] Navigating to: {url}...")
        try:
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url)
                # CRITICAL: Truncate to 3000 chars to protect your 8GB VRAM context limit
                clean_text = result.markdown[:3000]
                print(f"[Crawl4AI] Successfully extracted {len(clean_text)} characters.")
                return clean_text
        except Exception as e:
            return f"Error accessing {url}: {str(e)}"

    @staticmethod
    async def _search_web_playwright(url: str) -> str:
        from playwright.async_api import async_playwright  # lazy import -- only on Windows

        print(f"[Playwright] Navigating to: {url}...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, timeout=15000)
                # inner_text("body") returns visible text -- closest equivalent to crawl4ai markdown output
                # CRITICAL: Truncate to 3000 chars to protect your 8GB VRAM context limit
                text = await page.inner_text("body")
                clean_text = text[:3000]
                await browser.close()
                print(f"[Playwright] Successfully extracted {len(clean_text)} characters.")
                return clean_text
        except Exception as e:
            return f"Error accessing {url}: {str(e)}"
