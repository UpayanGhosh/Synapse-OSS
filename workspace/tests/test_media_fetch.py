"""
test_media_fetch.py — Tests for media/fetch.py

Covers:
  - MediaFetchError exception
  - SSRF block enforcement
  - Size limit enforcement via Content-Length header
  - Size limit enforcement via streaming
  - HTTP error status
  - Timeout handling
  - ssrf_policy="allow" bypass
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.fetch import MediaFetchError, fetch_media


class TestMediaFetchError:
    def test_construction(self):
        err = MediaFetchError("test reason")
        assert err.reason == "test reason"
        assert str(err) == "test reason"

    def test_is_exception(self):
        assert issubclass(MediaFetchError, Exception)


class TestFetchMedia:
    @pytest.mark.asyncio
    async def test_ssrf_blocked_url(self):
        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked", return_value=True):
            with pytest.raises(MediaFetchError, match="SSRF blocked"):
                await fetch_media("http://127.0.0.1/secret", max_bytes=1000)

    @pytest.mark.asyncio
    async def test_ssrf_policy_allow_skips_check(self):
        """ssrf_policy='allow' skips the SSRF guard entirely."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        async def mock_iter():
            yield b"data"

        mock_resp.aiter_bytes = mock_iter
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked") as mock_ssrf, \
             patch("sci_fi_dashboard.media.fetch.safe_httpx_client", return_value=mock_client):
            result = await fetch_media("http://127.0.0.1/data", max_bytes=10000, ssrf_policy="allow")
            mock_ssrf.assert_not_called()
            assert result == b"data"

    @pytest.mark.asyncio
    async def test_content_length_exceeds_limit(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-length": "5000"}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked", return_value=False), \
             patch("sci_fi_dashboard.media.fetch.safe_httpx_client", return_value=mock_client):
            with pytest.raises(MediaFetchError, match="Content-Length"):
                await fetch_media("https://example.com/big", max_bytes=1000)

    @pytest.mark.asyncio
    async def test_http_error_status(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 404
        mock_resp.headers = {}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked", return_value=False), \
             patch("sci_fi_dashboard.media.fetch.safe_httpx_client", return_value=mock_client):
            with pytest.raises(MediaFetchError, match="HTTP 404"):
                await fetch_media("https://example.com/gone", max_bytes=1000)

    @pytest.mark.asyncio
    async def test_redirect_ssrf_raises_permission_error(self):
        """PermissionError from redirect hook is caught and wrapped."""
        mock_client = AsyncMock()
        mock_client.stream.side_effect = PermissionError("SSRF blocked on redirect: http://127.0.0.1")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked", return_value=False), \
             patch("sci_fi_dashboard.media.fetch.safe_httpx_client", return_value=mock_client):
            with pytest.raises(MediaFetchError, match="SSRF blocked on redirect"):
                await fetch_media("https://example.com/redir", max_bytes=1000)

    @pytest.mark.asyncio
    async def test_timeout_raises_media_fetch_error(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.stream.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.media.fetch.is_ssrf_blocked", return_value=False), \
             patch("sci_fi_dashboard.media.fetch.safe_httpx_client", return_value=mock_client):
            with pytest.raises(MediaFetchError, match="Timeout"):
                await fetch_media("https://slow.example.com", max_bytes=1000)
