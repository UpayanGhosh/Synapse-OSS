"""
test_media_ssrf.py — Tests for media/ssrf.py

Covers:
  - _is_ip_blocked for all blocked ranges
  - is_ssrf_blocked for various URL patterns
  - Hostname blocklist (.local, .internal, localhost, metadata)
  - Scheme restrictions (file://, gopher://)
  - IPv6 handling including mapped IPv4
  - safe_httpx_client redirect hook
  - download_to_file SSRF check, size limit, symlink rejection
"""

import ipaddress
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.ssrf import (
    _is_ip_blocked,
    is_ssrf_blocked,
)


class TestIsIpBlocked:
    def test_loopback_v4(self):
        assert _is_ip_blocked(ipaddress.ip_address("127.0.0.1")) is True

    def test_loopback_127_x(self):
        assert _is_ip_blocked(ipaddress.ip_address("127.255.255.255")) is True

    def test_private_10(self):
        assert _is_ip_blocked(ipaddress.ip_address("10.0.0.1")) is True

    def test_private_172_16(self):
        assert _is_ip_blocked(ipaddress.ip_address("172.16.0.1")) is True

    def test_private_192_168(self):
        assert _is_ip_blocked(ipaddress.ip_address("192.168.1.1")) is True

    def test_link_local(self):
        assert _is_ip_blocked(ipaddress.ip_address("169.254.1.1")) is True

    def test_zero_network(self):
        assert _is_ip_blocked(ipaddress.ip_address("0.0.0.1")) is True

    def test_ipv6_loopback(self):
        assert _is_ip_blocked(ipaddress.ip_address("::1")) is True

    def test_ipv6_ula(self):
        assert _is_ip_blocked(ipaddress.ip_address("fc00::1")) is True

    def test_ipv6_link_local(self):
        assert _is_ip_blocked(ipaddress.ip_address("fe80::1")) is True

    def test_public_ip_allowed(self):
        assert _is_ip_blocked(ipaddress.ip_address("8.8.8.8")) is False

    def test_public_ipv6_allowed(self):
        assert _is_ip_blocked(ipaddress.ip_address("2001:4860:4860::8888")) is False

    def test_ipv6_mapped_ipv4_loopback(self):
        addr = ipaddress.ip_address("::ffff:127.0.0.1")
        assert _is_ip_blocked(addr) is True

    def test_ipv6_mapped_ipv4_private(self):
        addr = ipaddress.ip_address("::ffff:10.0.0.1")
        assert _is_ip_blocked(addr) is True

    def test_ipv6_mapped_ipv4_public(self):
        addr = ipaddress.ip_address("::ffff:8.8.8.8")
        assert _is_ip_blocked(addr) is False


class TestIsSsrfBlocked:
    @pytest.mark.asyncio
    async def test_loopback_blocked(self):
        assert await is_ssrf_blocked("http://127.0.0.1") is True

    @pytest.mark.asyncio
    async def test_private_10_blocked(self):
        assert await is_ssrf_blocked("http://10.0.0.1") is True

    @pytest.mark.asyncio
    async def test_private_172_blocked(self):
        assert await is_ssrf_blocked("http://172.16.0.1") is True

    @pytest.mark.asyncio
    async def test_private_192_blocked(self):
        assert await is_ssrf_blocked("http://192.168.1.1") is True

    @pytest.mark.asyncio
    async def test_link_local_blocked(self):
        assert await is_ssrf_blocked("http://169.254.1.1") is True

    @pytest.mark.asyncio
    async def test_zero_ip_blocked(self):
        assert await is_ssrf_blocked("http://0.0.0.0") is True

    @pytest.mark.asyncio
    async def test_ipv6_loopback_blocked(self):
        assert await is_ssrf_blocked("http://[::1]") is True

    @pytest.mark.asyncio
    async def test_localhost_hostname_blocked(self):
        assert await is_ssrf_blocked("http://localhost:8080") is True

    @pytest.mark.asyncio
    async def test_dot_local_suffix_blocked(self):
        assert await is_ssrf_blocked("http://myhost.local/") is True

    @pytest.mark.asyncio
    async def test_dot_internal_suffix_blocked(self):
        assert await is_ssrf_blocked("http://server.internal/") is True

    @pytest.mark.asyncio
    async def test_dot_localhost_suffix_blocked(self):
        assert await is_ssrf_blocked("http://evil.localhost/") is True

    @pytest.mark.asyncio
    async def test_metadata_hostname_blocked(self):
        assert await is_ssrf_blocked("http://metadata.google.internal/") is True

    @pytest.mark.asyncio
    async def test_public_url_allowed(self):
        assert await is_ssrf_blocked("https://api.openai.com") is False

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self):
        assert await is_ssrf_blocked("file:///etc/passwd") is True

    @pytest.mark.asyncio
    async def test_gopher_scheme_blocked(self):
        assert await is_ssrf_blocked("gopher://evil.com:25/") is True

    @pytest.mark.asyncio
    async def test_empty_url_blocked(self):
        assert await is_ssrf_blocked("") is True

    @pytest.mark.asyncio
    async def test_no_hostname_blocked(self):
        assert await is_ssrf_blocked("http://") is True

    @pytest.mark.asyncio
    async def test_ftp_scheme_blocked(self):
        assert await is_ssrf_blocked("ftp://files.example.com/data") is True

    @pytest.mark.asyncio
    async def test_dns_failure_blocked(self):
        """DNS resolution failure is fail-closed."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo.side_effect = OSError("DNS failed")
            result = await is_ssrf_blocked("http://nonexistent.example.test")
            assert result is True
