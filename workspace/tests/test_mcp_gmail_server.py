"""
Tests for sci_fi_dashboard.mcp_servers.gmail_server — Gmail integration.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _text(results: list) -> str:
    return results[0].text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_all_gmail_tools(self):
        from sci_fi_dashboard.mcp_servers.gmail_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"search_emails", "read_email", "get_unread", "send_email"}

    @pytest.mark.asyncio
    async def test_search_emails_requires_query(self):
        from sci_fi_dashboard.mcp_servers.gmail_server import list_tools

        tools = await list_tools()
        search_tool = next(t for t in tools if t.name == "search_emails")
        assert "query" in search_tool.inputSchema.get("required", [])

    @pytest.mark.asyncio
    async def test_send_email_requires_to_subject_body(self):
        from sci_fi_dashboard.mcp_servers.gmail_server import list_tools

        tools = await list_tools()
        send_tool = next(t for t in tools if t.name == "send_email")
        required = send_tool.inputSchema.get("required", [])
        assert "to" in required
        assert "subject" in required
        assert "body" in required


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------


class TestSearchEmails:
    @pytest.mark.asyncio
    async def test_search_returns_summaries(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        mock_svc = MagicMock()
        # messages().list().execute()
        mock_svc.users().messages().list().execute.return_value = {"messages": [{"id": "msg_1"}]}
        # messages().get().execute()
        mock_svc.users().messages().get().execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date", "value": "2026-01-01"},
                ]
            },
            "snippet": "Hi there...",
        }

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool(
                "search_emails", {"query": "from:alice", "max_results": 5}
            )

        data = json.loads(_text(result))
        assert len(data) == 1
        assert data[0]["id"] == "msg_1"
        assert data[0]["from"] == "alice@example.com"


# ---------------------------------------------------------------------------
# read_email
# ---------------------------------------------------------------------------


class TestReadEmail:
    @pytest.mark.asyncio
    async def test_read_email_plain_text_body(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        body_text = "This is the email body"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

        mock_svc = MagicMock()
        mock_svc.users().messages().get().execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "bob@example.com"},
                    {"name": "Subject", "value": "Test"},
                    {"name": "Date", "value": "2026-04-01"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": encoded_body},
                    }
                ],
            }
        }

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool("read_email", {"message_id": "msg_1"})

        data = json.loads(_text(result))
        assert data["body"] == body_text
        assert data["from"] == "bob@example.com"

    @pytest.mark.asyncio
    async def test_read_email_no_parts_fallback_body(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        body_text = "Inline body"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

        mock_svc = MagicMock()
        mock_svc.users().messages().get().execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "carol@example.com"},
                    {"name": "Subject", "value": "Inline"},
                    {"name": "Date", "value": "2026-04-01"},
                ],
                "body": {"data": encoded_body},
            }
        }

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool("read_email", {"message_id": "msg_2"})

        data = json.loads(_text(result))
        assert data["body"] == body_text


# ---------------------------------------------------------------------------
# get_unread
# ---------------------------------------------------------------------------


class TestGetUnread:
    @pytest.mark.asyncio
    async def test_get_unread_returns_summaries(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        mock_svc = MagicMock()
        mock_svc.users().messages().list().execute.return_value = {
            "messages": [{"id": "u1"}, {"id": "u2"}]
        }
        mock_svc.users().messages().get().execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@test.com"},
                    {"name": "Subject", "value": "Unread"},
                ]
            },
            "snippet": "Please read...",
        }

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool("get_unread", {"limit": 2})

        data = json.loads(_text(result))
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_get_unread_default_limit(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        mock_svc = MagicMock()
        mock_svc.users().messages().list().execute.return_value = {"messages": []}

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            await gmail_srv.call_tool("get_unread", {})

        # Check that the call used the default limit of 5
        mock_svc.users().messages().list.assert_called_with(
            userId="me", q="is:unread", maxResults=5
        )


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_send_email_constructs_mime_and_sends(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        mock_svc = MagicMock()
        mock_svc.users().messages().send().execute.return_value = {"id": "sent_1"}

        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool(
                "send_email",
                {"to": "test@example.com", "subject": "Hi", "body": "Hello!"},
            )

        assert "Email sent" in _text(result)
        mock_svc.users().messages().send.assert_called()


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        import sci_fi_dashboard.mcp_servers.gmail_server as gmail_srv

        mock_svc = MagicMock()
        with patch.object(gmail_srv, "_get_gmail_service", return_value=mock_svc):
            result = await gmail_srv.call_tool("nonexistent", {})

        assert "Unknown tool" in _text(result)
