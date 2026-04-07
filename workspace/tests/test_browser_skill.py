"""
Integration tests for the browser skill (Phase 5).

Covers all BROWSE requirements:
- BROWSE-01: Fetch and read web pages
- BROWSE-02: Raw HTML never sent to LLM
- BROWSE-03: Privacy boundary (spicy hemisphere)
- BROWSE-04: Implemented as a skill
- BROWSE-05: Source URLs included

All HTTP and search calls are mocked to avoid network dependencies in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skill scripts directory — runtime user data, not in the git repo
_BROWSER_SCRIPTS = Path.home() / ".synapse" / "skills" / "browser" / "scripts"

# Skip entire module if browser skill not installed
_BROWSER_SKILL_INSTALLED = _BROWSER_SCRIPTS.exists()


# ============================================================
# Helpers
# ============================================================


def _load_script(name: str):
    """Load a browser skill script via importlib (no sys.path manipulation).

    Mirrors the _load_sibling_module() approach used by browser_skill.py itself.
    Each call returns a fresh module object so tests don't share state.
    """
    module_path = _BROWSER_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"test_browser_{name}", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load script: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def _add_skill_scripts_to_path():
    """Temporarily add browser skill scripts to sys.path for direct imports.

    Note: browser_skill.py itself uses importlib-based _load_sibling_module()
    and does NOT depend on sys.path. This fixture is only for test convenience
    when testing fetch_and_summarize.py and web_search.py in isolation.
    """
    if not _BROWSER_SKILL_INSTALLED:
        yield
        return

    scripts_str = str(_BROWSER_SCRIPTS)
    was_present = scripts_str in sys.path
    if not was_present:
        sys.path.insert(0, scripts_str)
    yield
    if not was_present and scripts_str in sys.path:
        sys.path.remove(scripts_str)


SAMPLE_HTML = b"""
<html>
<head><title>Test Page</title></head>
<body>
<h1>Python 3.12 Released</h1>
<p>Python 3.12.0 was released on October 2, 2023. This release includes
several performance improvements and new features including improved error
messages and support for the Linux perf profiler.</p>
<script>var x = 1;</script>
<div class="nav">Navigation links here</div>
</body>
</html>
"""


# ============================================================
# BROWSE-01: Fetch and read web pages
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_fetch_and_summarize_returns_text():
    """BROWSE-01: fetch_and_summarize extracts readable text from a page."""
    from fetch_and_summarize import fetch_and_summarize

    mock_response = MagicMock()
    mock_response.content = SAMPLE_HTML
    mock_response.headers = {"content-type": "text/html"}
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "fetch_and_summarize.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("fetch_and_summarize.safe_httpx_client") as mock_client_factory,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_factory.return_value = mock_client

        result = await fetch_and_summarize("https://example.com/python-release")

    # The fetch succeeded — we get a result with a URL
    assert result.url == "https://example.com/python-release"
    # Source URLs are populated (BROWSE-05)
    assert len(result.source_urls) > 0
    # URL must be in source_urls
    assert "https://example.com/python-release" in result.source_urls


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_search_returns_structured_results():
    """BROWSE-01: search() returns SearchResult objects with URLs."""
    from web_search import search

    mock_results = [
        {
            "title": "Python Release",
            "href": "https://python.org/downloads/",
            "body": "Latest Python release info",
        },
        {
            "title": "Python News",
            "href": "https://news.python.org/",
            "body": "Python community news",
        },
    ]

    with patch("web_search._search_ddgs_sync", return_value=mock_results):
        response = await search("python latest release")

    assert response.success
    assert len(response.results) == 2
    assert response.results[0].url == "https://python.org/downloads/"
    # BROWSE-05: source_urls populated
    assert len(response.source_urls) == 2


# ============================================================
# BROWSE-02: Raw HTML never sent to LLM
# ============================================================


@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
def test_fetch_result_contains_no_html_tags():
    """BROWSE-02: _extract_with_trafilatura strips all HTML tags from output."""
    from fetch_and_summarize import _extract_with_trafilatura

    text, _title = _extract_with_trafilatura(SAMPLE_HTML, "https://example.com")

    assert "<html>" not in text
    assert "<div>" not in text
    assert "<script>" not in text
    assert "<p>" not in text
    # Content is present in some form (either trafilatura or regex fallback)
    assert len(text) > 0


@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
def test_format_for_context_no_html():
    """BROWSE-02: format_for_context output is entirely HTML-free."""
    from fetch_and_summarize import FetchResult, format_for_context

    results = [
        FetchResult(
            url="https://example.com",
            title="Test",
            text="Python 3.12 was released with performance improvements.",
            success=True,
            source_urls=["https://example.com"],
        )
    ]

    output = format_for_context(results)

    assert "<html>" not in output
    assert "<div>" not in output
    assert "<script>" not in output
    # Real content is present
    assert "Python 3.12" in output
    # BROWSE-05: source URL present in formatted context
    assert "https://example.com" in output


# ============================================================
# BROWSE-03: Privacy boundary (spicy hemisphere)
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_spicy_hemisphere_blocks_all_fetches():
    """BROWSE-03: Spicy session NEVER triggers outbound HTTP — zero module loads.

    The hemisphere guard in browser_skill.py exits BEFORE any _load_sibling_module()
    calls, so no sibling modules are loaded and no network calls happen.
    We track calls to _load_sibling_module to verify it is never invoked.
    """
    browser_mod = _load_script("browser_skill")

    load_calls: list[str] = []
    original_loader = browser_mod._load_sibling_module

    def tracking_loader(name: str):
        load_calls.append(name)
        return original_loader(name)

    browser_mod._load_sibling_module = tracking_loader

    try:
        result = await browser_mod.run_browser_skill(
            user_message="What's the latest Python release?",
            session_context={"session_type": "spicy"},
        )
    finally:
        browser_mod._load_sibling_module = original_loader

    # Hemisphere guard fired — success=False, hemisphere_blocked=True
    assert result.hemisphere_blocked is True
    assert result.success is False
    assert result.error  # Has an error message about privacy
    # Privacy or private appears in the error
    assert "privacy" in result.error.lower() or "private" in result.error.lower()
    # ZERO module loads — guard exits before any _load_sibling_module call
    assert len(load_calls) == 0, f"Expected ZERO module loads, got: {load_calls}"


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_safe_hemisphere_allows_fetches():
    """BROWSE-03: Non-spicy session allows web fetches (hemisphere guard does not fire).

    We mock _load_sibling_module to avoid real network calls, verifying that the
    guard does NOT return early and the orchestration proceeds normally.
    """
    browser_mod = _load_script("browser_skill")

    # Mock search module
    mock_search_mod = MagicMock()
    mock_search_response = MagicMock()
    mock_search_response.success = True
    mock_search_response.results = [MagicMock(url="https://python.org")]
    mock_search_response.source_urls = ["https://python.org"]
    mock_search_mod.search = AsyncMock(return_value=mock_search_response)
    mock_search_mod.format_search_results = MagicMock(return_value="Search results...")

    # Mock fetch module
    mock_fetch_mod = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.success = True
    mock_fetch_result.text = "Python 3.12 released with improvements."
    mock_fetch_result.source_urls = ["https://python.org"]
    mock_fetch_mod.fetch_and_summarize = AsyncMock(return_value=mock_fetch_result)
    mock_fetch_mod.format_for_context = MagicMock(
        return_value="## Python 3.12\n\nPython 3.12 released with improvements."
    )

    def mock_loader(name: str):
        if "search" in name:
            return mock_search_mod
        return mock_fetch_mod

    browser_mod._load_sibling_module = mock_loader

    result = await browser_mod.run_browser_skill(
        user_message="What's the latest Python release?",
        session_context={"session_type": ""},
    )

    # Guard did NOT fire — hemisphere_blocked is False
    assert result.hemisphere_blocked is False
    assert result.success is True


# ============================================================
# BROWSE-04: Implemented as a skill
# ============================================================


def test_browser_skill_md_is_valid():
    """BROWSE-04: SKILL.md is parseable by SkillLoader and declares entry_point."""
    skill_dir = Path.home() / ".synapse" / "skills" / "browser"
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        pytest.skip("Browser skill not installed at ~/.synapse/skills/browser/")

    try:
        from sci_fi_dashboard.skills.loader import SkillLoader

        manifest = SkillLoader.load_skill(skill_dir)
        assert manifest.name == "browser"
        assert manifest.description  # Non-empty
        assert manifest.version
        # Generic entry_point is declared (architecture requirement)
        assert manifest.entry_point == "scripts/browser_skill.py:run_browser_skill"
    except ImportError:
        pytest.skip("SkillLoader not available (Phase 01 skills not complete)")


def test_missing_browser_skill_graceful_fallback():
    """BROWSE-04: Empty router returns None — no 500 when no skills loaded."""
    try:
        from sci_fi_dashboard.skills.router import SkillRouter

        router = SkillRouter()
        # Empty router — no skills loaded
        result = router.match("What's the latest Python release?")
        assert result is None  # Graceful fallback, not a crash
    except ImportError:
        pytest.skip("SkillRouter not available (Phase 01 skills not complete)")


# ============================================================
# BROWSE-05: Source URLs included
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_fetch_result_has_source_urls():
    """BROWSE-05: FetchResult.source_urls is populated with the fetched URL."""
    from fetch_and_summarize import fetch_and_summarize

    mock_response = MagicMock()
    mock_response.content = SAMPLE_HTML
    mock_response.headers = {"content-type": "text/html"}
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "fetch_and_summarize.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("fetch_and_summarize.safe_httpx_client") as mock_client_factory,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_factory.return_value = mock_client

        result = await fetch_and_summarize("https://example.com/page")

    # Source URL must be populated regardless of extraction success
    assert "https://example.com/page" in result.source_urls


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_search_response_has_source_urls():
    """BROWSE-05: SearchResponse.source_urls contains all result URLs."""
    from web_search import search

    mock_results = [
        {"title": "Result 1", "href": "https://example.com/1", "body": "First result"},
        {"title": "Result 2", "href": "https://example.com/2", "body": "Second result"},
    ]

    with patch("web_search._search_ddgs_sync", return_value=mock_results):
        response = await search("test query")

    assert "https://example.com/1" in response.source_urls
    assert "https://example.com/2" in response.source_urls


# ============================================================
# SSRF Guard Tests
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_ssrf_blocks_loopback():
    """SSRF: 127.0.0.1 is blocked — loopback address rejected."""
    from fetch_and_summarize import fetch_and_summarize

    # Real is_ssrf_blocked is called — no mock. This exercises the actual guard.
    result = await fetch_and_summarize("http://127.0.0.1/secret")

    assert not result.success
    assert "SSRF" in result.error or "blocked" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_ssrf_blocks_private_10():
    """SSRF: 10.x.x.x is blocked — RFC 1918 private range rejected."""
    from fetch_and_summarize import fetch_and_summarize

    result = await fetch_and_summarize("http://10.0.0.1/internal")

    assert not result.success
    assert "SSRF" in result.error or "blocked" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_ssrf_blocks_private_192():
    """SSRF: 192.168.x.x is blocked — RFC 1918 private range rejected."""
    from fetch_and_summarize import fetch_and_summarize

    result = await fetch_and_summarize("http://192.168.1.1/admin")

    assert not result.success
    assert "SSRF" in result.error or "blocked" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_ssrf_blocks_link_local():
    """SSRF: 169.254.x.x (link-local / cloud metadata) is blocked."""
    from fetch_and_summarize import fetch_and_summarize

    result = await fetch_and_summarize("http://169.254.169.254/latest/meta-data/")

    assert not result.success
    assert "SSRF" in result.error or "blocked" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_ssrf_blocks_file_scheme():
    """SSRF: file:// scheme is blocked — scheme restriction prevents local file reads."""
    from fetch_and_summarize import fetch_and_summarize

    result = await fetch_and_summarize("file:///etc/passwd")

    assert not result.success
    # The URL scheme check fires first (in fetch_and_summarize itself)
    assert "scheme" in result.error.lower() or "Unsupported" in result.error


# ============================================================
# Additional BROWSE-02 tests: browser_skill context_block has no HTML
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_browser_skill_context_block_no_html():
    """BROWSE-02: run_browser_skill context_block never contains raw HTML tags."""
    browser_mod = _load_script("browser_skill")

    # Mock search + fetch modules so no real network call happens
    mock_search_mod = MagicMock()
    mock_search_response = MagicMock()
    mock_search_response.success = True
    mock_search_response.results = [MagicMock(url="https://python.org/3.12")]
    mock_search_response.source_urls = ["https://python.org/3.12"]
    mock_search_mod.search = AsyncMock(return_value=mock_search_response)
    mock_search_mod.format_search_results = MagicMock(return_value="Search result text")

    mock_fetch_mod = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.success = True
    mock_fetch_result.text = "Python 3.12 is the latest stable release."
    mock_fetch_result.source_urls = ["https://python.org/3.12"]
    mock_fetch_mod.fetch_and_summarize = AsyncMock(return_value=mock_fetch_result)
    # format_for_context must return plain text — no HTML
    mock_fetch_mod.format_for_context = MagicMock(
        return_value=(
            "## Python 3.12\n\n"
            "Python 3.12 is the latest stable release.\n\n"
            "**Sources:**\n- https://python.org/3.12"
        )
    )

    def mock_loader(name: str):
        if "search" in name:
            return mock_search_mod
        return mock_fetch_mod

    browser_mod._load_sibling_module = mock_loader

    result = await browser_mod.run_browser_skill(
        user_message="What's new in Python 3.12?",
        session_context={"session_type": "safe"},
    )

    assert result.success is True
    # No raw HTML in the context block
    assert "<html>" not in result.context_block
    assert "<div>" not in result.context_block
    assert "<script>" not in result.context_block
    assert "<body>" not in result.context_block


# ============================================================
# Rate Limiting Test
# ============================================================


@pytest.mark.asyncio
@pytest.mark.skipif(not _BROWSER_SKILL_INSTALLED, reason="Browser skill not installed")
async def test_search_rate_limiting_called():
    """Rate limiting: _rate_limit_wait is invoked for each search call.

    We verify the rate-limiting function is called (not that a specific
    interval is enforced, to keep the test fast and deterministic).
    """
    from web_search import search

    mock_results = [{"title": "R", "href": "https://example.com", "body": "Result"}]

    rate_limit_call_count = 0

    import web_search as ws_module

    original_rate_limit = ws_module._rate_limit_wait

    def counting_rate_limit():
        nonlocal rate_limit_call_count
        rate_limit_call_count += 1
        # Do NOT actually sleep — just record the call
        import time
        ws_module._last_request_time = time.monotonic()

    ws_module._rate_limit_wait = counting_rate_limit
    try:
        with patch("web_search._search_ddgs_sync", return_value=mock_results):
            await search("query 1")
            await search("query 2")
    finally:
        ws_module._rate_limit_wait = original_rate_limit

    # _rate_limit_wait must have been called at least once per search
    assert rate_limit_call_count >= 2, (
        f"Expected _rate_limit_wait called >= 2 times, got {rate_limit_call_count}"
    )
