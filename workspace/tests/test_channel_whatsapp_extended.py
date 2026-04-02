"""Extended WhatsApp channel tests — filling gaps not covered in test_whatsapp_channel.py.

Covers:
- receive() text and media normalization
- receive() DM security blocking
- receive() returns None for non-message events
- send_media(), send_reaction(), send_typing(), mark_read()
- Group management: create_group, invite, leave, update_subject, get_metadata
- get_status() enhanced health check
- logout(), relink()
"""

import asyncio
import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WA_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.whatsapp") is not None

pytestmark = pytest.mark.skipif(
    not WA_AVAILABLE, reason="WhatsAppChannel not available"
)

if WA_AVAILABLE:
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel
    from sci_fi_dashboard.channels.security import (
        ChannelSecurityConfig,
        DmPolicy,
        PairingStore,
    )


# ===========================================================================
# receive() Tests
# ===========================================================================


class TestWhatsAppReceive:

    @pytest.mark.asyncio
    async def test_receive_text_message(self):
        ch = WhatsAppChannel(bridge_port=5010)
        payload = {
            "type": "message",
            "chat_id": "919876@s.whatsapp.net",
            "user_id": "919876@s.whatsapp.net",
            "text": "Hello from WhatsApp",
            "timestamp": 1700000000,
            "message_id": "msg123",
            "sender_name": "Alice",
            "is_group": False,
        }
        msg = await ch.receive(payload)
        assert msg is not None
        assert msg.channel_id == "whatsapp"
        assert msg.text == "Hello from WhatsApp"
        assert msg.user_id == "919876@s.whatsapp.net"
        assert msg.sender_name == "Alice"
        assert msg.is_group is False

    @pytest.mark.asyncio
    async def test_receive_media_message(self):
        ch = WhatsAppChannel(bridge_port=5010)
        payload = {
            "type": "message",
            "chat_id": "chat1",
            "user_id": "user1",
            "text": "",
            "mediaCaption": "Check this out",
            "mediaType": "image",
            "mediaUrl": "http://example.com/img.jpg",
            "mediaMimeType": "image/jpeg",
        }
        msg = await ch.receive(payload)
        assert msg is not None
        assert msg.text == "Check this out"
        assert msg.raw.get("media_type") == "image"
        assert msg.raw.get("media_url") == "http://example.com/img.jpg"

    @pytest.mark.asyncio
    async def test_receive_non_message_event_returns_none(self):
        ch = WhatsAppChannel(bridge_port=5010)
        for event_type in ("message_status", "typing_indicator", "reaction"):
            payload = {"type": event_type, "chat_id": "c1"}
            result = await ch.receive(payload)
            assert result is None

    @pytest.mark.asyncio
    async def test_receive_dm_blocked_by_security(self, tmp_path):
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        cfg = ChannelSecurityConfig(
            dm_policy=DmPolicy.ALLOWLIST, allow_from=["allowed_user"]
        )
        ch = WhatsAppChannel(
            bridge_port=5010, security_config=cfg, pairing_store=store
        )
        payload = {
            "type": "message",
            "chat_id": "blocked_user",
            "user_id": "blocked_user",
            "text": "should be blocked",
            "is_group": False,
        }
        result = await ch.receive(payload)
        assert result is None

    @pytest.mark.asyncio
    async def test_receive_group_message_skips_security(self, tmp_path):
        store = PairingStore("whatsapp", data_root=tmp_path)
        await store.load()
        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.DISABLED)
        ch = WhatsAppChannel(
            bridge_port=5010, security_config=cfg, pairing_store=store
        )
        payload = {
            "type": "message",
            "chat_id": "group@g.us",
            "user_id": "user1",
            "text": "group msg",
            "is_group": True,
        }
        result = await ch.receive(payload)
        assert result is not None


# ===========================================================================
# Outbound messaging
# ===========================================================================


class TestWhatsAppOutbound:

    @pytest.mark.asyncio
    async def test_send_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.send("chat1", "Hello")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.send("chat1", "Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_media_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.send_media("chat1", "http://img.png", "image", "cap")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_reaction_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.send_reaction("chat1", "msg1", "thumbsup")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_reaction_failure(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.send_reaction("chat1", "msg1", "thumbsup")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_typing_no_error(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        # Should not raise
        await ch.send_typing("chat1")

    @pytest.mark.asyncio
    async def test_mark_read_no_error(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        # Should not raise
        await ch.mark_read("chat1", "msg1")


# ===========================================================================
# Session management
# ===========================================================================


class TestWhatsAppSession:

    @pytest.mark.asyncio
    async def test_logout_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.logout()
        assert result is True

    @pytest.mark.asyncio
    async def test_logout_failure(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.logout()
        assert result is False

    @pytest.mark.asyncio
    async def test_relink_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.relink()
        assert result is True

    @pytest.mark.asyncio
    async def test_relink_failure(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.relink()
        assert result is False


# ===========================================================================
# Group management
# ===========================================================================


class TestWhatsAppGroups:

    @pytest.mark.asyncio
    async def test_invite_to_group_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.invite_to_group("grp@g.us", ["user1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_leave_group_success(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.leave_group("grp@g.us")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_group_subject(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_post(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
        result = await ch.update_group_subject("grp@g.us", "New Name")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_group_metadata(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_get(self_client, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"subject": "Test Group", "participants": []}
            return resp

        monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
        result = await ch.get_group_metadata("grp@g.us")
        assert result is not None
        assert result["subject"] == "Test Group"

    @pytest.mark.asyncio
    async def test_get_group_metadata_not_found(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)

        async def mock_get(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
        result = await ch.get_group_metadata("grp@g.us")
        assert result is None


# ===========================================================================
# Enhanced status
# ===========================================================================


class TestWhatsAppStatus:

    @pytest.mark.asyncio
    async def test_get_status_includes_extra_fields(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=59999)
        ch._connection_state = "connected"
        ch._connected_since = "2025-01-01T00:00:00"
        ch._auth_timestamp = "2025-01-01T00:00:00"
        ch._restart_count = 2
        ch._last_disconnect_reason = "515"

        # Mock health_check to return basic dict
        async def mock_health(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.AsyncClient.get", mock_health)

        status = await ch.get_status()
        assert status["connected_since"] == "2025-01-01T00:00:00"
        assert status["restart_count"] == 2
        assert status["connection_state"] == "connected"
