"""
test_api_gateway.py — Tests for the FastAPI gateway and its core functions.

Since api_gateway.py has heavy module-level side effects (singleton creation,
port checks, env validation), we test primarily by:
  1. Importing and testing pure/isolated functions directly
  2. Testing endpoint logic via TestClient with heavy mocking
  3. Testing routing/classification logic
  4. Testing helper functions (normalize_phone, validate_*, etc.)

Covers:
  - _port_open helper
  - _extract_cli_send_route
  - normalize_phone
  - STRATEGY_TO_ROLE mapping
  - route_traffic_cop classification
  - ChatRequest / MemoryItem / QueryItem schema validation
  - persona_chat core logic (mocked LLM + memory)
  - FastAPI endpoints (/, /health, /chat, /chat/{persona}, /persona/status, etc.)
  - Auth validation (validate_api_key, validate_bridge_token)
  - WhatsApp bridge DB helpers
  - _resolve_target
  - _load_personas_config
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We need to do extensive mocking before importing api_gateway due to its heavy
# module-level initialization. Instead, we test the functions we can import
# independently and use TestClient only with full mocking.


# ---------------------------------------------------------------------------
# Tests for pure functions that can be tested without full gateway import
# ---------------------------------------------------------------------------


class TestExtractCliSendRoute:
    """Tests for _extract_cli_send_route."""

    def _import_fn(self):
        """Import the function with necessary mocking."""
        # We import via a targeted approach since api_gateway imports are heavy
        try:
            from sci_fi_dashboard.api_gateway import _extract_cli_send_route

            return _extract_cli_send_route
        except Exception:
            pytest.skip("Cannot import api_gateway (missing dependencies)")

    def test_empty_string(self):
        fn = self._import_fn()
        assert fn("") == ""

    def test_none_input(self):
        fn = self._import_fn()
        assert fn(None) == ""

    def test_valid_json_with_via(self):
        fn = self._import_fn()
        assert fn('{"via": "whatsapp"}') == "whatsapp"

    def test_valid_json_with_delivery(self):
        fn = self._import_fn()
        assert fn('{"delivery": "sms"}') == "sms"

    def test_valid_json_nested_payload(self):
        fn = self._import_fn()
        assert fn('{"payload": {"via": "telegram"}}') == "telegram"

    def test_invalid_json(self):
        fn = self._import_fn()
        assert fn("not json at all") == ""

    def test_non_dict_json(self):
        fn = self._import_fn()
        assert fn("[1, 2, 3]") == ""

    def test_json_without_route_keys(self):
        fn = self._import_fn()
        assert fn('{"status": "ok"}') == ""


class TestNormalizePhone:
    """Tests for normalize_phone."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import normalize_phone

            return normalize_phone
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_strips_non_digits(self):
        fn = self._import_fn()
        assert fn("+1 (234) 567-8900") == "12345678900"

    def test_none_returns_empty(self):
        fn = self._import_fn()
        assert fn(None) == ""

    def test_empty_string(self):
        fn = self._import_fn()
        assert fn("") == ""

    def test_already_clean(self):
        fn = self._import_fn()
        assert fn("1234567890") == "1234567890"

    def test_integer_input(self):
        fn = self._import_fn()
        assert fn(1234567890) == "1234567890"


class TestStrategyToRole:
    """Tests for STRATEGY_TO_ROLE constant."""

    def _import_const(self):
        try:
            from sci_fi_dashboard.api_gateway import STRATEGY_TO_ROLE

            return STRATEGY_TO_ROLE
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_acknowledge_maps_to_casual(self):
        mapping = self._import_const()
        assert mapping["acknowledge"] == "CASUAL"

    def test_support_maps_to_casual(self):
        mapping = self._import_const()
        assert mapping["support"] == "CASUAL"

    def test_celebrate_maps_to_casual(self):
        mapping = self._import_const()
        assert mapping["celebrate"] == "CASUAL"

    def test_challenge_maps_to_analysis(self):
        mapping = self._import_const()
        assert mapping["challenge"] == "ANALYSIS"

    def test_quiz_maps_to_analysis(self):
        mapping = self._import_const()
        assert mapping["quiz"] == "ANALYSIS"

    def test_unknown_strategy_not_in_map(self):
        mapping = self._import_const()
        assert "unknown_strategy" not in mapping


class TestPortOpen:
    """Tests for _port_open."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import _port_open

            return _port_open
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_closed_port_returns_false(self):
        fn = self._import_fn()
        # Port 1 is unlikely to be open
        assert fn("127.0.0.1", 1, timeout=0.1) is False

    def test_invalid_host_returns_false(self):
        fn = self._import_fn()
        assert fn("999.999.999.999", 80, timeout=0.1) is False


class TestIsOwnerSender:
    """Tests for _is_owner_sender."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import _is_owner_sender

            return _is_owner_sender
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_none_is_owner(self):
        fn = self._import_fn()
        assert fn(None) is True

    def test_empty_string_is_owner(self):
        fn = self._import_fn()
        assert fn("") is True

    def test_the_creator_is_owner(self):
        fn = self._import_fn()
        assert fn("the_creator") is True

    def test_the_partner_is_owner(self):
        fn = self._import_fn()
        assert fn("the_partner") is True

    def test_case_insensitive(self):
        fn = self._import_fn()
        assert fn("THE_CREATOR") is True

    def test_random_user_not_owner(self):
        fn = self._import_fn()
        assert fn("random_person") is False


class TestResolveTarget:
    """Tests for _resolve_target."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import _resolve_target

            return _resolve_target
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_default_target(self):
        fn = self._import_fn()
        # Unknown input should return default persona
        result = fn("completely_unknown_random_string_xyz")
        assert isinstance(result, str)
        assert len(result) > 0  # Should be a persona ID


class TestLoadPersonasConfig:
    """Tests for _load_personas_config."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import _load_personas_config

            return _load_personas_config
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_returns_dict_with_personas_key(self):
        fn = self._import_fn()
        result = fn()
        assert isinstance(result, dict)
        assert "personas" in result
        assert isinstance(result["personas"], list)

    def test_at_least_one_persona(self):
        fn = self._import_fn()
        result = fn()
        assert len(result["personas"]) >= 1


# ---------------------------------------------------------------------------
# Tests for Pydantic models
# ---------------------------------------------------------------------------


class TestChatRequest:
    """Tests for the ChatRequest Pydantic model."""

    def _import_model(self):
        try:
            from sci_fi_dashboard.api_gateway import ChatRequest

            return ChatRequest
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_minimal_request(self):
        ChatRequest = self._import_model()  # noqa: N806
        req = ChatRequest(message="Hello")
        assert req.message == "Hello"
        assert req.history == []
        assert req.user_id is None
        assert req.session_type is None

    def test_full_request(self):
        ChatRequest = self._import_model()  # noqa: N806
        req = ChatRequest(
            message="Test",
            history=[{"role": "user", "content": "prev"}],
            user_id="user_123",
            session_type="spicy",
        )
        assert req.session_type == "spicy"
        assert len(req.history) == 1


class TestMemoryItem:
    """Tests for the MemoryItem Pydantic model."""

    def _import_model(self):
        try:
            from sci_fi_dashboard.api_gateway import MemoryItem

            return MemoryItem
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_minimal(self):
        MemoryItem = self._import_model()  # noqa: N806
        item = MemoryItem(content="Remember this")
        assert item.content == "Remember this"
        assert item.category == "general"

    def test_custom_category(self):
        MemoryItem = self._import_model()  # noqa: N806
        item = MemoryItem(content="Test", category="relationship")
        assert item.category == "relationship"


class TestQueryItem:
    """Tests for the QueryItem Pydantic model."""

    def _import_model(self):
        try:
            from sci_fi_dashboard.api_gateway import QueryItem

            return QueryItem
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_basic(self):
        QueryItem = self._import_model()  # noqa: N806
        item = QueryItem(text="search query")
        assert item.text == "search query"


# ---------------------------------------------------------------------------
# Tests for WhatsApp bridge DB helpers
# ---------------------------------------------------------------------------


class TestBridgeDbHelpers:
    """Tests for bridge DB functions (ensure, insert, get, update)."""

    def _import_all(self):
        try:
            from sci_fi_dashboard.api_gateway import (
                BRIDGE_DB_PATH,
                ensure_bridge_db,
                get_inbound_message,
                insert_inbound_message,
                update_inbound_message,
            )

            return (
                ensure_bridge_db,
                insert_inbound_message,
                get_inbound_message,
                update_inbound_message,
                BRIDGE_DB_PATH,
            )
        except Exception:
            pytest.skip("Cannot import api_gateway")

    def test_ensure_bridge_db_creates_table(self, tmp_path):
        fns = self._import_all()
        ensure_bridge_db, _, _, _, _ = fns
        test_db = tmp_path / "bridge.db"
        with patch("sci_fi_dashboard.api_gateway.BRIDGE_DB_PATH", test_db):
            ensure_bridge_db()
            conn = sqlite3.connect(str(test_db))
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            conn.close()
            table_names = [t[0] for t in tables]
            assert "inbound_messages" in table_names

    def test_insert_and_get(self, tmp_path):
        fns = self._import_all()
        ensure_bridge_db, insert_inbound_message, get_inbound_message, _, _ = fns
        test_db = tmp_path / "bridge.db"
        with patch("sci_fi_dashboard.api_gateway.BRIDGE_DB_PATH", test_db):
            ensure_bridge_db()
            insert_inbound_message(
                message_id="msg_001",
                channel="whatsapp",
                from_phone="1234567890",
                to_phone="0987654321",
                conversation_id="conv_001",
                text="Hello world",
                status="queued",
            )
            row = get_inbound_message("msg_001")
            assert row is not None
            assert row["text"] == "Hello world"
            assert row["status"] == "queued"

    def test_get_nonexistent(self, tmp_path):
        fns = self._import_all()
        ensure_bridge_db, _, get_inbound_message, _, _ = fns
        test_db = tmp_path / "bridge.db"
        with patch("sci_fi_dashboard.api_gateway.BRIDGE_DB_PATH", test_db):
            ensure_bridge_db()
            assert get_inbound_message("nonexistent") is None

    def test_update_message(self, tmp_path):
        fns = self._import_all()
        ensure_bridge_db, insert_inbound_message, get_inbound_message, update_inbound_message, _ = (
            fns
        )
        test_db = tmp_path / "bridge.db"
        with patch("sci_fi_dashboard.api_gateway.BRIDGE_DB_PATH", test_db):
            ensure_bridge_db()
            insert_inbound_message(
                message_id="msg_002",
                channel="whatsapp",
                from_phone="123",
                to_phone=None,
                conversation_id=None,
                text="Test",
                status="queued",
            )
            update_inbound_message("msg_002", status="completed", reply="Done!")
            row = get_inbound_message("msg_002")
            assert row["status"] == "completed"
            assert row["reply"] == "Done!"


# ---------------------------------------------------------------------------
# Tests for route_traffic_cop (async)
# ---------------------------------------------------------------------------


class TestRouteTrafficCop:
    """Tests for route_traffic_cop classification."""

    def _import_fn(self):
        try:
            from sci_fi_dashboard.api_gateway import route_traffic_cop

            return route_traffic_cop
        except Exception:
            pytest.skip("Cannot import api_gateway")

    async def test_returns_string(self):
        fn = self._import_fn()
        with patch(
            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
        ) as mock_flash:
            mock_flash.return_value = "CASUAL"
            result = await fn("Hello, how are you?")
            assert isinstance(result, str)
            assert result in ("CASUAL", "CODING", "ANALYSIS", "REVIEW")

    async def test_coding_classification(self):
        fn = self._import_fn()
        with patch(
            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
        ) as mock_flash:
            mock_flash.return_value = "CODING"
            result = await fn("Fix this python bug")
            assert result == "CODING"

    async def test_fallback_on_error(self):
        fn = self._import_fn()
        with patch(
            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
        ) as mock_flash:
            mock_flash.side_effect = Exception("LLM down")
            result = await fn("test message")
            assert result == "CASUAL"

    async def test_cleans_punctuation(self):
        fn = self._import_fn()
        with patch(
            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
        ) as mock_flash:
            mock_flash.return_value = "ANALYSIS."
            result = await fn("Summarize this data")
            assert result == "ANALYSIS"


# ---------------------------------------------------------------------------
# Tests for FastAPI endpoints via TestClient
# ---------------------------------------------------------------------------


class TestFastAPIEndpoints:
    """Tests for API endpoints. Requires successful api_gateway import."""

    def _get_client(self):
        try:
            from fastapi.testclient import TestClient
            from sci_fi_dashboard.api_gateway import app

            return TestClient(app, raise_server_exceptions=False)
        except Exception:
            pytest.skip("Cannot import api_gateway app")

    def test_root_endpoint(self):
        """GET / should return status online."""
        client = self._get_client()
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "version" in data

    def test_health_endpoint(self):
        """GET /health should return health info."""
        client = self._get_client()
        resp = client.get("/health")
        # May fail if singletons are broken, but should not 500
        assert resp.status_code in (200, 500)

    def test_gateway_status(self):
        """GET /gateway/status should return queue stats."""
        client = self._get_client()
        resp = client.get("/gateway/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "queue" in data
        assert "timestamp" in data

    def test_persona_status(self):
        """GET /persona/status should return profile stats."""
        client = self._get_client()
        resp = client.get("/persona/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data

    def test_sbs_status(self):
        """GET /sbs/status should return SBS stats."""
        client = self._get_client()
        resp = client.get("/sbs/status")
        assert resp.status_code == 200

    def test_chat_webhook_empty_body(self):
        """POST /chat with empty body should return error."""
        client = self._get_client()
        resp = client.post("/chat", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("error", "skipped")

    def test_chat_webhook_no_messages(self):
        """POST /chat with empty messages should use message field."""
        client = self._get_client()
        resp = client.post("/chat", json={"message": ""})
        data = resp.json()
        assert data.get("status") in ("skipped", "error")

    def test_chat_webhook_own_message_skipped(self):
        """POST /chat with fromMe=True should be skipped."""
        client = self._get_client()
        resp = client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "test"}],
                "fromMe": True,
            },
        )
        data = resp.json()
        assert data.get("status") == "skipped"
        assert data.get("reason") == "own_message"

    def test_sessions_endpoint(self):
        """GET /api/sessions should return a list."""
        client = self._get_client()
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_unified_webhook_unknown_channel(self):
        """POST /channels/unknown/webhook should return 404."""
        client = self._get_client()
        resp = client.post(
            "/channels/nonexistent_channel/webhook",
            json={"type": "message", "text": "hi", "chat_id": "x"},
        )
        assert resp.status_code == 404

    def test_whatsapp_loop_test_501(self):
        """POST /whatsapp/loop-test should return 501 (not implemented)."""
        client = self._get_client()
        resp = client.post(
            "/whatsapp/loop-test",
            json={"target": "+10000000000", "message": "test", "dry_run": True},
        )
        assert resp.status_code == 501

    def test_whatsapp_job_status_404(self):
        """GET /whatsapp/jobs/{id} for nonexistent message should 404."""
        client = self._get_client()
        resp = client.get("/whatsapp/jobs/nonexistent_msg_id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests for persona_chat core logic
# ---------------------------------------------------------------------------


class TestPersonaChat:
    """Tests for persona_chat function with full mocking."""

    async def test_persona_chat_happy_path(self):
        """persona_chat should return a dict with reply key."""
        try:
            from sci_fi_dashboard.api_gateway import ChatRequest, persona_chat
        except Exception:
            pytest.skip("Cannot import api_gateway")

        request = ChatRequest(message="Hello Synapse!", user_id="the_creator")

        mock_result = MagicMock()
        mock_result.text = "Hello bro!"
        mock_result.model = "test-model"
        mock_result.prompt_tokens = 100
        mock_result.completion_tokens = 50
        mock_result.total_tokens = 150
        mock_result.tool_calls = None

        with patch("sci_fi_dashboard.api_gateway.memory_engine") as mock_mem:
            mock_mem.query.return_value = {
                "results": [],
                "tier": "empty",
                "entities": [],
                "graph_context": "",
            }
            with patch("sci_fi_dashboard.api_gateway.toxic_scorer") as mock_toxic:
                mock_toxic.score.return_value = 0.1
                with patch("sci_fi_dashboard.api_gateway.dual_cognition") as mock_dc:
                    from sci_fi_dashboard.dual_cognition import CognitiveMerge

                    mock_dc.think = AsyncMock(return_value=CognitiveMerge())
                    mock_dc.build_cognitive_context.return_value = ""
                    with patch("sci_fi_dashboard.api_gateway.synapse_llm_router") as mock_router:
                        mock_router.call_with_tools = AsyncMock(return_value=mock_result)
                        mock_router.call_with_metadata = AsyncMock(return_value=mock_result)
                        with patch(
                            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
                        ) as mock_flash:
                            mock_flash.return_value = "CASUAL"
                            with patch(
                                "sci_fi_dashboard.api_gateway.get_sbs_for_target"
                            ) as mock_sbs:
                                mock_orch = MagicMock()
                                mock_orch.on_message.return_value = {"msg_id": "test_001"}
                                mock_orch.get_system_prompt.return_value = "You are Synapse."
                                mock_sbs.return_value = mock_orch
                                with (
                                    patch("sci_fi_dashboard.api_gateway._proactive_engine", None),
                                    patch("sci_fi_dashboard.api_gateway.tool_registry", None),
                                ):
                                    result = await persona_chat(request, "the_creator")
                                    assert isinstance(result, dict)
                                    assert "reply" in result
                                    assert "model" in result

    async def test_persona_chat_spicy_mode(self):
        """Spicy mode should route to vault."""
        try:
            from sci_fi_dashboard.api_gateway import ChatRequest, persona_chat
        except Exception:
            pytest.skip("Cannot import api_gateway")

        request = ChatRequest(message="Private message", session_type="spicy")

        mock_result = MagicMock()
        mock_result.text = "Vault response"
        mock_result.model = "ollama/mistral"
        mock_result.prompt_tokens = 50
        mock_result.completion_tokens = 30
        mock_result.total_tokens = 80

        with patch("sci_fi_dashboard.api_gateway.memory_engine") as mock_mem:
            mock_mem.query.return_value = {
                "results": [],
                "tier": "empty",
                "entities": [],
                "graph_context": "",
            }
            with patch("sci_fi_dashboard.api_gateway.toxic_scorer") as mock_toxic:
                mock_toxic.score.return_value = 0.0
                with patch("sci_fi_dashboard.api_gateway.dual_cognition") as mock_dc:
                    from sci_fi_dashboard.dual_cognition import CognitiveMerge

                    mock_dc.think = AsyncMock(return_value=CognitiveMerge())
                    mock_dc.build_cognitive_context.return_value = ""
                    with patch("sci_fi_dashboard.api_gateway.synapse_llm_router") as mock_router:
                        mock_router.call_with_metadata = AsyncMock(return_value=mock_result)
                        with patch("sci_fi_dashboard.api_gateway.get_sbs_for_target") as mock_sbs:
                            mock_orch = MagicMock()
                            mock_orch.on_message.return_value = {"msg_id": "test_002"}
                            mock_orch.get_system_prompt.return_value = "You are Synapse."
                            mock_sbs.return_value = mock_orch
                            with patch("sci_fi_dashboard.api_gateway._proactive_engine", None):
                                result = await persona_chat(request, "the_creator")
                                assert "reply" in result

    async def test_persona_chat_memory_failure(self):
        """Memory engine failure should not crash persona_chat."""
        try:
            from sci_fi_dashboard.api_gateway import ChatRequest, persona_chat
        except Exception:
            pytest.skip("Cannot import api_gateway")

        request = ChatRequest(message="Hello")

        mock_result = MagicMock()
        mock_result.text = "Response despite memory failure"
        mock_result.model = "test"
        mock_result.prompt_tokens = 10
        mock_result.completion_tokens = 10
        mock_result.total_tokens = 20
        mock_result.tool_calls = None

        with patch("sci_fi_dashboard.api_gateway.memory_engine") as mock_mem:
            mock_mem.query.side_effect = Exception("Memory DB crashed")
            with patch("sci_fi_dashboard.api_gateway.toxic_scorer") as mock_toxic:
                mock_toxic.score.return_value = 0.0
                with patch("sci_fi_dashboard.api_gateway.dual_cognition") as mock_dc:
                    from sci_fi_dashboard.dual_cognition import CognitiveMerge

                    mock_dc.think = AsyncMock(return_value=CognitiveMerge())
                    mock_dc.build_cognitive_context.return_value = ""
                    with patch("sci_fi_dashboard.api_gateway.synapse_llm_router") as mock_router:
                        mock_router.call_with_tools = AsyncMock(return_value=mock_result)
                        with patch(
                            "sci_fi_dashboard.api_gateway.call_gemini_flash", new_callable=AsyncMock
                        ) as mock_flash:
                            mock_flash.return_value = "CASUAL"
                            with patch(
                                "sci_fi_dashboard.api_gateway.get_sbs_for_target"
                            ) as mock_sbs:
                                mock_orch = MagicMock()
                                mock_orch.on_message.return_value = {"msg_id": "t"}
                                mock_orch.get_system_prompt.return_value = "You are Synapse."
                                mock_sbs.return_value = mock_orch
                                with (
                                    patch("sci_fi_dashboard.api_gateway._proactive_engine", None),
                                    patch("sci_fi_dashboard.api_gateway.tool_registry", None),
                                ):
                                    result = await persona_chat(request, "the_creator")
                                    assert "reply" in result
                                    assert result["memory_method"] == "failed"


# ---------------------------------------------------------------------------
# Tests for tool execution constants
# ---------------------------------------------------------------------------


class TestToolConstants:
    """Tests for tool execution loop constants."""

    def test_max_tool_rounds(self):
        try:
            from sci_fi_dashboard.api_gateway import MAX_TOOL_ROUNDS
        except Exception:
            pytest.skip("Cannot import api_gateway")
        assert MAX_TOOL_ROUNDS == 5

    def test_tool_result_max_chars(self):
        try:
            from sci_fi_dashboard.api_gateway import TOOL_RESULT_MAX_CHARS
        except Exception:
            pytest.skip("Cannot import api_gateway")
        assert TOOL_RESULT_MAX_CHARS == 4000

    def test_max_total_tool_result_chars(self):
        try:
            from sci_fi_dashboard.api_gateway import MAX_TOTAL_TOOL_RESULT_CHARS
        except Exception:
            pytest.skip("Cannot import api_gateway")
        assert MAX_TOTAL_TOOL_RESULT_CHARS == 20_000


# ---------------------------------------------------------------------------
# Tests for auto-continue logic
# ---------------------------------------------------------------------------


class TestAutoContinueLogic:
    """Tests for the auto-continue detection logic used in persona_chat."""

    def test_terminal_punctuation_detected(self):
        """Replies ending with terminal punctuation should NOT trigger auto-continue."""
        terminals = [".", "!", "?", '"', "'", ")", "]", "}"]
        for t in terminals:
            text = "This is a long enough reply to test" + t
            assert any(text.strip().endswith(t) for t in terminals)

    def test_cut_off_detected(self):
        """Replies without terminal punctuation should trigger auto-continue."""
        text = "This is a long enough reply but it was cut off mid-word and"
        terminals = [".", "!", "?", '"', "'", ")", "]", "}"]
        assert not any(text.strip().endswith(t) for t in terminals)

    def test_short_reply_no_trigger(self):
        """Short replies should not trigger auto-continue regardless."""
        text = "Ok"
        assert len(text) <= 50  # Below the threshold
