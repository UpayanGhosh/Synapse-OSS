"""
Entry point for synapse.news skill.

Fetches Reuters top-news RSS feed and extracts the top 5 headlines.
Uses only stdlib (xml.etree.ElementTree) for XML parsing — no external deps beyond httpx.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Reuters publicly available RSS feed (no API key required)
_REUTERS_RSS = "https://feeds.reuters.com/reuters/topNews"
_FALLBACK_RSS = "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"


@dataclass
class NewsResult:
    context_block: str
    source_urls: list[str] = field(default_factory=list)
    error: str = ""


async def get_news_context(user_message: str, session_context: dict | None) -> NewsResult:
    """
    Fetch Reuters RSS feed, parse top 5 headlines, return formatted context for the LLM.
    """
    import httpx  # lazy import

    headlines, links, feed_url = await _fetch_headlines(httpx, _REUTERS_RSS)
    if not headlines:
        # Try fallback feed
        headlines, links, feed_url = await _fetch_headlines(httpx, _FALLBACK_RSS)

    if not headlines:
        return NewsResult(
            context_block="",
            error="Could not fetch news headlines. Both RSS feeds were unreachable.",
        )

    lines = [f"Latest headlines from {feed_url}:\n"]
    for i, (title, link) in enumerate(zip(headlines, links), 1):
        lines.append(f"{i}. {title}")
        if link:
            lines.append(f"   {link}")

    return NewsResult(
        context_block="\n".join(lines),
        source_urls=links[:5],
    )


async def _fetch_headlines(
    httpx_module, feed_url: str
) -> tuple[list[str], list[str], str]:
    """
    Attempt to fetch and parse an RSS feed. Returns (titles, links, feed_url) or empty lists.
    """
    try:
        async with httpx_module.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                feed_url,
                headers={"User-Agent": "Synapse-News/1.0 (+https://github.com/synapse-oss)"},
            )
            resp.raise_for_status()
            return _parse_rss(resp.text, feed_url)
    except Exception:  # noqa: BLE001
        return [], [], feed_url


def _parse_rss(xml_text: str, feed_url: str) -> tuple[list[str], list[str], str]:
    """
    Parse RSS 2.0 XML and extract top 5 <item> titles and links.
    Returns (titles, links, feed_url).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], [], feed_url

    # RSS 2.0: /rss/channel/item  OR  Atom: /feed/entry
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    titles: list[str] = []
    links: list[str] = []

    for item in items[:5]:
        # Title
        title_el = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
        title = (title_el.text or "").strip() if title_el is not None else ""

        # Link — RSS uses <link> text; Atom uses <link href="...">
        link_el = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
        if link_el is not None:
            link = link_el.get("href") or (link_el.text or "").strip()
        else:
            link = ""

        if title:
            titles.append(title)
            links.append(link)

    return titles, links, feed_url
