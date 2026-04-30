"""
Tool Registry — Factory-based tool resolution for Synapse-OSS
==============================================================
Phase 1 of the Tool Execution milestone. Provides a registry where
tool factories produce SynapseTool instances scoped to each chat session.

The LLM call site resolves tools once per request via ToolRegistry.resolve(),
then passes get_schemas() output as the `tools=` parameter. After the LLM
returns a tool_call, execute() dispatches to the matching SynapseTool.
"""

from __future__ import annotations

import json
import logging
import re
import html
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Binary file guard for write_file
# ---------------------------------------------------------------------------
# Extensions of structured/binary files that must NOT be written via the raw
# write_file tool. Direct text writes on these formats either corrupt the
# data (SQLite, LanceDB, Parquet, archives) or bypass a proper ingestion
# pipeline (audio/video/images that need transcoding). The guard fires
# BEFORE Sentinel runs — its purpose is teaching the LLM the right path,
# not enforcing security (Sentinel handles that separately).
BINARY_WRITE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".db",
        ".sqlite",
        ".sqlite3",
        ".lancedb",
        ".parquet",
        ".gz",
        ".tar",
        ".zip",
        ".png",
        ".jpg",
        ".jpeg",
        ".mp3",
        ".ogg",
        ".mp4",
        ".webm",
        ".pdf",
    }
)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Session-scoped context injected into tool factories at resolution time."""

    chat_id: str
    sender_id: str
    sender_is_owner: bool
    workspace_dir: str
    config: dict
    channel_id: str | None = None


@dataclass
class ToolResult:
    """Uniform result format — all tool returns normalize to this."""

    content: str
    is_error: bool = False
    media: list[dict] = field(default_factory=list)


@dataclass
class SynapseTool:
    """A fully resolved tool ready for execution."""

    name: str
    description: str
    parameters: dict  # JSON Schema (top-level type: "object")
    execute: Callable[[dict], Awaitable[ToolResult]]
    owner_only: bool = False
    serial: bool = False  # if True, never run in parallel


ToolFactory = Callable[[ToolContext], SynapseTool | None]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Factory-based tool registry with per-request resolution."""

    def __init__(self) -> None:
        self._factories: list[tuple[str, ToolFactory]] = []
        self._resolved: dict[str, SynapseTool] = {}

    def register_factory(self, name: str, factory: ToolFactory) -> None:
        """Register a factory that produces a SynapseTool (or None to skip)."""
        self._factories.append((name, factory))

    def register_tool(self, tool: SynapseTool) -> None:
        """Convenience: register a static tool as a trivial factory."""
        self.register_factory(tool.name, lambda _ctx: tool)

    def resolve(self, context: ToolContext) -> list[SynapseTool]:
        """Resolve all factories for the given session context.

        Factories may return ``None`` to exclude themselves (e.g. owner-only
        tools when ``sender_is_owner`` is False). Duplicate tool names are
        silently dropped — first registration wins.
        """
        self._resolved.clear()
        tools: list[SynapseTool] = []
        for name, factory in self._factories:
            try:
                tool = factory(context)
                if tool is None:
                    continue
                if tool.name in self._resolved:
                    continue
                self._resolved[tool.name] = tool
                tools.append(tool)
            except Exception as e:
                logger.warning(f"Tool factory '{name}' failed: {e}")
        return tools

    def get_schemas(self, tools: list[SynapseTool]) -> list[dict]:
        """Return OpenAI function-calling compatible schema list."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """Execute a previously resolved tool by name."""
        tool = self._resolved.get(name)
        if not tool:
            return ToolResult(
                content=f'{{"error": "Unknown tool: {name}"}}',
                is_error=True,
            )
        try:
            return await tool.execute(arguments)
        except Exception as e:
            return ToolResult(
                content=f'{{"error": "Tool \'{name}\' failed: {e}"}}',
                is_error=True,
            )


# ---------------------------------------------------------------------------
# Result normalization helpers
# ---------------------------------------------------------------------------


def text_result(text: str) -> ToolResult:
    """Wrap a plain string as a successful ToolResult."""
    return ToolResult(content=text)


def error_result(message: str) -> ToolResult:
    """Wrap an error message as a failed ToolResult."""
    return ToolResult(content=json.dumps({"error": message}), is_error=True)


def json_result(payload: Any) -> ToolResult:
    """Serialize an arbitrary payload as pretty JSON."""
    return ToolResult(content=json.dumps(payload, indent=2, default=str))


def normalize_raw_result(raw: Any) -> ToolResult:
    """Convert any return value into a ToolResult."""
    if isinstance(raw, ToolResult):
        return raw
    if isinstance(raw, str):
        return text_result(raw)
    if isinstance(raw, dict):
        return json_result(raw)
    if raw is None:
        return text_result("(no output)")
    return text_result(str(raw))


# ---------------------------------------------------------------------------
# Built-in tool factories
# ---------------------------------------------------------------------------


def _web_search_factory(_ctx: ToolContext) -> SynapseTool:
    """Factory for the web_search tool (delegates to db.tools.ToolRegistry)."""

    async def _execute(arguments: dict) -> ToolResult:
        try:
            from db.tools import ToolRegistry as LegacyToolRegistry

            content = await LegacyToolRegistry.search_web(arguments["url"])
            return text_result(content)
        except Exception as e:
            return error_result(f"web_search failed: {e}")

    return SynapseTool(
        name="web_search",
        description=(
            "Fetch and extract content from a URL as clean markdown. "
            "Use for up-to-date information not in memory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to visit and extract content from.",
                }
            },
            "required": ["url"],
        },
        execute=_execute,
    )


def _decode_result_url(href: str) -> str:
    href = html.unescape(str(href or "").strip())
    if href.startswith("//"):
        href = "https:" + href
    href = urllib.parse.unquote(href)
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs:
        href = qs["uddg"][0]
    return href


def _clean_html_text(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    return re.sub(r"\s+", " ", text).strip()


def parse_search_results(raw_html: str, limit: int = 5) -> list[dict[str, str]]:
    """Parse common DuckDuckGo HTML/lite result layouts."""
    patterns = (
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]+class=["\']result-link["\'][^>]*>(.*?)</a>',
        r'<a[^>]+class=["\']result-link["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]+class=["\']result__a["\'][^>]*>(.*?)</a>',
        r'<a[^>]+class=["\']result__a["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for href, title_html in re.findall(pattern, raw_html, flags=re.I | re.S):
            url = _decode_result_url(href)
            title = _clean_html_text(title_html)
            if not title or not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url})
            if len(results) >= limit:
                return results
    return results


def extract_readable_html_text(raw_html: str, max_chars: int = 3000) -> str:
    """Best-effort visible text extraction without heavyweight parser deps."""
    text = re.sub(
        r"<(script|style|noscript|svg|canvas|iframe)\b[^>]*>.*?</\1>",
        " ",
        str(raw_html or ""),
        flags=re.I | re.S,
    )
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    main_match = re.search(r"<main\b[^>]*>(.*?)</main>", text, flags=re.I | re.S)
    article_match = re.search(r"<article\b[^>]*>(.*?)</article>", text, flags=re.I | re.S)
    if main_match:
        text = main_match.group(1)
    elif article_match:
        text = article_match.group(1)
    text = _clean_html_text(text)
    return text[:max_chars]


def _web_query_factory(_ctx: ToolContext) -> SynapseTool:
    """Factory for web_query: search the web by natural-language query."""

    async def _execute(arguments: dict) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return error_result("web_query failed: missing query")
        limit = int(arguments.get("limit", 5) or 5)
        limit = max(1, min(limit, 10))

        try:
            import httpx
        except Exception as exc:
            return error_result(f"web_query failed: httpx unavailable: {exc}")

        urls = [
            "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query}),
            "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
        ]
        raw_html = ""
        try:
            async with httpx.AsyncClient(
                timeout=12.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                for url in urls:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    raw_html = resp.text
                    results = parse_search_results(raw_html, limit=limit)
                    if results:
                        return json_result({"query": query, "results": results})
        except Exception as exc:
            return error_result(f"web_query failed: {exc}")

        return json_result(
            {
                "query": query,
                "results": [],
                "warning": "Search request completed, but no result links were parsed.",
            }
        )

    return SynapseTool(
        name="web_query",
        description="Search the public web by query and return result titles and URLs.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language web search query.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return, 1-10.",
                },
            },
            "required": ["query"],
        },
        execute=_execute,
    )


def _query_memory_factory(memory_engine: Any) -> ToolFactory:
    """Return a factory that captures a MemoryEngine reference."""

    def _factory(_ctx: ToolContext) -> SynapseTool:
        async def _execute(arguments: dict) -> ToolResult:
            try:
                result = memory_engine.query(
                    text=arguments["query"],
                    limit=arguments.get("limit", 5),
                )
                return json_result(result)
            except Exception as e:
                return error_result(f"query_memory failed: {e}")

        return SynapseTool(
            name="query_memory",
            description=(
                "Search the knowledge base using hybrid RAG "
                "(vector + full-text + rerank). Returns ranked results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
            execute=_execute,
        )

    return _factory


def _read_file_factory(_ctx: ToolContext) -> SynapseTool:
    """Factory for the read_file tool (Sentinel-gated)."""

    async def _execute(arguments: dict) -> ToolResult:
        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_read_file

            result = agent_read_file(arguments["path"])
            return text_result(result)
        except Exception as e:
            return error_result(f"read_file failed: {e}")

    return SynapseTool(
        name="read_file",
        description="Read file contents (Sentinel-gated).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to read.",
                }
            },
            "required": ["path"],
        },
        execute=_execute,
    )


def _write_file_factory(ctx: ToolContext) -> SynapseTool | None:
    """Factory for the write_file tool (Sentinel-gated, owner-only)."""
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        # Binary-extension guard — fires BEFORE Sentinel so the LLM gets a
        # specific, actionable error pointing at the right alternative path
        # (FastAPI /add for memory.db, sqlite3/ffmpeg/etc. for other binaries).
        # Sentinel still gates everything else; this is purely about LLM
        # guidance, not security.
        path = arguments.get("path", "")
        if isinstance(path, str) and path:
            ext = Path(path).suffix.lower()
            if ext in BINARY_WRITE_EXTENSIONS:
                return error_result(
                    f"write_file refused: '{path}' is a binary file ({ext}). "
                    f"Direct binary writes corrupt structured data. "
                    f"For memory.db specifically: use the FastAPI gateway via "
                    f"bash_exec(\"curl -X POST http://127.0.0.1:8000/add "
                    f"-H 'Content-Type: application/json' "
                    f"-d '{{\\\"content\\\":\\\"...\\\", \\\"category\\\":\\\"...\\\"}}'\") "
                    f"— it runs the proper embedding + RAG pipeline. "
                    f"For other binary files: use the appropriate CLI tool via bash_exec "
                    f"(sqlite3 for DBs, ffmpeg for audio/video, ImageMagick for images, etc.). "
                    f"See MEMORY.md → Memory Ingestion Protocol for full guidance."
                )

        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_write_file

            result = agent_write_file(arguments["path"], arguments["content"])
            return text_result(result)
        except Exception as e:
            return error_result(f"write_file failed: {e}")

    return SynapseTool(
        name="write_file",
        description="Write to a file (Sentinel-gated, audit logged). Owner only.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write to.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["path", "content"],
        },
        execute=_execute,
        owner_only=True,
    )


def register_builtin_tools(
    registry: ToolRegistry,
    memory_engine: Any,
    project_root: str,
) -> None:
    """Register all four built-in tool factories on the given registry.

    Parameters
    ----------
    registry : ToolRegistry
        The registry to populate.
    memory_engine : MemoryEngine
        A live MemoryEngine instance whose ``.query()`` method will be called.
    project_root : str
        Workspace root path (unused currently, reserved for future factories).
    """
    registry.register_factory("web_search", _web_search_factory)
    registry.register_factory("web_query", _web_query_factory)
    registry.register_factory("query_memory", _query_memory_factory(memory_engine))
    registry.register_factory("read_file", _read_file_factory)
    registry.register_factory("write_file", _write_file_factory)
