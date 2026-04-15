"""
Tests for sci_fi_dashboard.browser.navigation_guard — SSRF prevention and redirect validation.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.browser.navigation_guard import (
    NavigationBlockedError,
    assert_navigation_allowed,
    assert_navigation_result_allowed,
    redirect_guard,
)

# ---------------------------------------------------------------------------
# NavigationBlockedError
# ---------------------------------------------------------------------------


class TestNavigationBlockedError:
    def test_stores_url_and_reason(self):
        err = NavigationBlockedError("http://evil.com", "SSRF detected")
        assert err.url == "http://evil.com"
        assert err.reason == "SSRF detected"
        assert "evil.com" in str(err)
        assert "SSRF detected" in str(err)


# ---------------------------------------------------------------------------
# assert_navigation_allowed
# ---------------------------------------------------------------------------


class TestAssertNavigationAllowed:
    @pytest.mark.asyncio
    async def test_allows_about_blank(self):
        await assert_navigation_allowed("about:blank")

    @pytest.mark.asyncio
    async def test_allows_http_url(self):
        with patch(
            "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await assert_navigation_allowed("http://example.com")

    @pytest.mark.asyncio
    async def test_allows_https_url(self):
        with patch(
            "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await assert_navigation_allowed("https://example.com/path")

    @pytest.mark.asyncio
    async def test_blocks_ftp_protocol(self):
        with pytest.raises(NavigationBlockedError, match="protocol not allowed"):
            await assert_navigation_allowed("ftp://example.com")

    @pytest.mark.asyncio
    async def test_blocks_file_protocol(self):
        with pytest.raises(NavigationBlockedError, match="protocol not allowed"):
            await assert_navigation_allowed("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_blocks_javascript_protocol(self):
        with pytest.raises(NavigationBlockedError, match="protocol not allowed"):
            await assert_navigation_allowed("javascript:alert(1)")

    @pytest.mark.asyncio
    async def test_blocks_data_protocol(self):
        with pytest.raises(NavigationBlockedError, match="protocol not allowed"):
            await assert_navigation_allowed("data:text/html,<script>")

    @pytest.mark.asyncio
    async def test_blocks_ssrf_url(self):
        with (
            patch(
                "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
                new_callable=AsyncMock,
                return_value=True,
            ),
            pytest.raises(NavigationBlockedError, match="private or blocked"),
        ):
            await assert_navigation_allowed("http://169.254.169.254/metadata")

    @pytest.mark.asyncio
    async def test_case_insensitive_protocol_check(self):
        with patch(
            "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await assert_navigation_allowed("HTTP://example.com")
            await assert_navigation_allowed("HTTPS://example.com")


# ---------------------------------------------------------------------------
# assert_navigation_result_allowed
# ---------------------------------------------------------------------------


class TestAssertNavigationResultAllowed:
    @pytest.mark.asyncio
    async def test_delegates_to_assert_navigation_allowed(self):
        with patch(
            "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await assert_navigation_result_allowed("https://example.com")

    @pytest.mark.asyncio
    async def test_blocks_private_final_url(self):
        with (
            patch(
                "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
                new_callable=AsyncMock,
                return_value=True,
            ),
            pytest.raises(NavigationBlockedError),
        ):
            await assert_navigation_result_allowed("http://10.0.0.1/admin")


# ---------------------------------------------------------------------------
# redirect_guard context manager
# ---------------------------------------------------------------------------


class TestRedirectGuard:
    @pytest.mark.asyncio
    async def test_no_redirect_no_error(self):
        mock_page = MagicMock()
        mock_page.on = MagicMock()

        async with redirect_guard(mock_page):
            pass  # No redirect happened

        # Should complete without error

    @pytest.mark.asyncio
    async def test_safe_redirect_no_error(self):
        mock_page = MagicMock()
        registered_handler = None

        def capture_on(event, handler):
            nonlocal registered_handler
            if event == "response":
                registered_handler = handler

        mock_page.on = capture_on

        with patch(
            "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
            new_callable=AsyncMock,
            return_value=False,
        ):
            async with redirect_guard(mock_page):
                # Simulate a safe 301 redirect
                if registered_handler:
                    mock_response = MagicMock()
                    mock_response.status = 301
                    mock_response.headers = {"location": "https://safe.example.com"}
                    mock_response.url = "https://old.example.com"
                    await registered_handler(mock_response)

    @pytest.mark.asyncio
    async def test_ssrf_redirect_raises_and_closes_page(self):
        mock_page = MagicMock()
        mock_page.close = AsyncMock()
        registered_handler = None

        def capture_on(event, handler):
            nonlocal registered_handler
            if event == "response":
                registered_handler = handler

        mock_page.on = capture_on

        with (
            patch(
                "sci_fi_dashboard.browser.navigation_guard.is_ssrf_blocked",
                new_callable=AsyncMock,
                return_value=True,
            ),
            pytest.raises(NavigationBlockedError, match="redirect hop"),
        ):
            async with redirect_guard(mock_page):
                # Simulate a malicious 302 redirect to private IP
                if registered_handler:
                    mock_response = MagicMock()
                    mock_response.status = 302
                    mock_response.headers = {"location": "http://169.254.169.254"}
                    mock_response.url = "https://public.example.com"
                    await registered_handler(mock_response)

        mock_page.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_redirect_response_ignored(self):
        mock_page = MagicMock()
        registered_handler = None

        def capture_on(event, handler):
            nonlocal registered_handler
            if event == "response":
                registered_handler = handler

        mock_page.on = capture_on

        async with redirect_guard(mock_page):
            # Simulate a normal 200 response
            if registered_handler:
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.headers = {}
                await registered_handler(mock_response)

        # No error should be raised
