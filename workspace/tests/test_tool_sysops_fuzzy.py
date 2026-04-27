"""
Test Suite: edit_synapse_config fuzzy-match fallback (RT3)
==========================================================
Tests for the fuzzy-match fallback path in ``edit_synapse_config`` —
when a user supplies an invalid model name, the tool should:

* exact-match → apply silently
* close-match (similarity ≥ 0.85) → auto-apply + return note
* ambiguous (suggestions but no clear winner) → return suggestions list
* no match → return helpful error pointing at list_available_models
* offline (no reachable list) → fall back to prefix-only check

All HTTP discovery is mocked — these tests never hit real endpoints.

See: .planning/JARVIS-ARCH-PLAN.md (RT3)
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard import tool_sysops  # noqa: E402
from sci_fi_dashboard.tool_registry import ToolContext  # noqa: E402
from sci_fi_dashboard.tool_sysops import (  # noqa: E402
    _discover_reachable_models,
    _edit_synapse_config_factory,
    _fuzzy_match_model,
)


# Realistic snapshot of what Copilot+Ollama return — used as the canonical
# fixture for every test in this module.
FAKE_REACHABLE = [
    "github_copilot/claude-3-5-sonnet-20241022",
    "github_copilot/claude-3-7-sonnet-thought",
    "github_copilot/gemini-2.0-flash-001",
    "github_copilot/gemini-2.5-flash",
    "github_copilot/gemini-2.5-pro",
    "github_copilot/gpt-4o",
    "github_copilot/gpt-4o-mini",
    "github_copilot/o3-mini",
    "ollama_chat/llama3.2:3b",
    "ollama_chat/mistral:latest",
    "ollama_chat/nomic-embed-text:latest",
]


@pytest.fixture(autouse=True)
def reset_models_cache():
    """Clear the module-level cache before each test so nothing leaks across."""
    tool_sysops._models_cache["models"] = []
    tool_sysops._models_cache["expires_at"] = 0.0
    tool_sysops._models_cache["fetched"] = False
    yield
    tool_sysops._models_cache["models"] = []
    tool_sysops._models_cache["expires_at"] = 0.0
    tool_sysops._models_cache["fetched"] = False


@pytest.fixture(autouse=True)
def default_openai_codex_oauth_missing(monkeypatch):
    """Keep OpenAI Codex trust-prefix deterministic unless a test opts in."""
    monkeypatch.setattr(
        "sci_fi_dashboard.openai_codex_oauth.load_credentials",
        lambda: None,
    )


@pytest.fixture
def fake_synapse_config(tmp_path, monkeypatch):
    """Patch Path.home() to a tmp dir holding a minimal synapse.json so the
    edit_synapse_config tool reads/writes against an isolated file.
    """
    home = tmp_path / "home"
    synapse_dir = home / ".synapse"
    synapse_dir.mkdir(parents=True)
    cfg_path = synapse_dir / "synapse.json"
    cfg_path.write_text(
        json.dumps(
            {
                "model_mappings": {
                    "casual": {"model": "github_copilot/gpt-4o-mini"},
                    "code": {"model": "github_copilot/claude-3-5-sonnet-20241022"},
                },
                "providers": {"github_copilot": {}, "ollama": {}},
            },
            indent=2,
        )
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return cfg_path


def _make_ctx(owner: bool = True) -> ToolContext:
    return ToolContext(
        chat_id="test_chat",
        sender_id="test_sender",
        sender_is_owner=owner,
        workspace_dir="/tmp",
        config={},
    )


# ---------------------------------------------------------------------------
# 1a. _version_digits — extract the version-digit signature of a model name
# ---------------------------------------------------------------------------


class TestVersionDigits:
    """Direct unit tests for _version_digits."""

    @pytest.mark.unit
    def test_extracts_simple_digits(self):
        assert tool_sysops._version_digits("gpt-4") == ("4",)
        assert tool_sysops._version_digits("gpt-4o") == ("4",)

    @pytest.mark.unit
    def test_extracts_multi_part_versions(self):
        assert tool_sysops._version_digits("gemini-2.0-flash") == ("2", "0")
        assert tool_sysops._version_digits("claude-3-5-sonnet") == ("3", "5")

    @pytest.mark.unit
    def test_no_digits_returns_empty_tuple(self):
        assert tool_sysops._version_digits("ollama_chat/mistral") == ()
        assert tool_sysops._version_digits("foo-bar-baz") == ()

    @pytest.mark.unit
    def test_strips_provider_prefix_for_extraction(self):
        # Current implementation runs findall over the whole string; provider
        # prefix "github_copilot/" has no digits so this is a no-op. Test
        # documents the observed behavior so future changes to prefix handling
        # surface here.
        result = tool_sysops._version_digits("github_copilot/gemini-2.0-flash-001")
        assert "2" in result and "0" in result


# ---------------------------------------------------------------------------
# 1b. _digit_compat — the version-digit prefix safety guard
# ---------------------------------------------------------------------------


class TestDigitCompat:
    """Direct unit tests for _digit_compat — the version-digit prefix safety guard."""

    @pytest.mark.unit
    def test_no_digits_either_side(self):
        """When neither has digits → compatible (free pass)."""
        assert tool_sysops._digit_compat("foo", "bar") is True
        assert tool_sysops._digit_compat("ollama_chat/mistral", "anthropic/claude") is True

    @pytest.mark.unit
    def test_request_no_digits_candidate_has_digits(self):
        """Request without digits is compatible with any digit-bearing candidate."""
        assert tool_sysops._digit_compat("gemini-flash", "github_copilot/gemini-2.5-flash") is True
        assert tool_sysops._digit_compat("claude-sonnet", "anthropic/claude-3-5-sonnet") is True

    @pytest.mark.unit
    def test_request_digits_candidate_no_digits_returns_false(self):
        """Request with digits but candidate has none → not compatible (different concept)."""
        assert tool_sysops._digit_compat("gemini-2", "gemini") is False
        assert tool_sysops._digit_compat("gpt-4", "ollama_chat/mistral") is False

    @pytest.mark.unit
    def test_request_digits_prefix_of_candidate(self):
        """Request digits are a prefix of candidate digits → compatible (build suffix dropped)."""
        assert (
            tool_sysops._digit_compat("gemini-2.0", "github_copilot/gemini-2.0-flash-001")
            is True
        )
        assert tool_sysops._digit_compat("gpt-4", "github_copilot/gpt-4o") is True

    @pytest.mark.unit
    def test_request_digits_diverge_from_candidate(self):
        """Different version generations → not compatible (prevents wrong-version auto-apply)."""
        assert tool_sysops._digit_compat("gemini-2.0", "gemini-2.5") is False
        assert (
            tool_sysops._digit_compat("gemini-3-flash", "github_copilot/gemini-2.5-flash")
            is False
        )
        assert tool_sysops._digit_compat("gpt-3.5", "gpt-4") is False

    @pytest.mark.unit
    def test_request_has_more_digit_components_than_candidate(self):
        """Request has more digit components than candidate → not compatible."""
        # Request "2.0.1" has 3 components, candidate "2.0" has 2 → not a prefix.
        assert tool_sysops._digit_compat("foo-2.0.1", "foo-2.0") is False


# ---------------------------------------------------------------------------
# 1. _fuzzy_match_model — pure function tests (no I/O)
# ---------------------------------------------------------------------------


class TestFuzzyMatchModel:
    """Tests for the pure fuzzy-match helper."""

    @pytest.mark.unit
    def test_empty_reachable_returns_no_suggestions(self):
        suggestions, top, sim = _fuzzy_match_model("anything", [])
        assert suggestions == []
        assert top is None
        assert sim == 0.0

    @pytest.mark.unit
    def test_close_suffix_match_scores_high(self):
        """Bare suffix 'gemini-2.0-flash' should match
        'github_copilot/gemini-2.0-flash-001' with high similarity.
        """
        suggestions, top, sim = _fuzzy_match_model("gemini-2.0-flash", FAKE_REACHABLE)
        assert len(suggestions) > 0
        assert top is not None
        assert top.startswith("github_copilot/gemini-2.0-flash")
        assert sim >= 0.85

    @pytest.mark.unit
    def test_ambiguous_match_returns_suggestions_low_similarity(self):
        """'gemini-3-flash' is in the gemini family but no exact suffix match."""
        suggestions, top, sim = _fuzzy_match_model("gemini-3-flash", FAKE_REACHABLE)
        assert len(suggestions) > 0
        # Top match should be a gemini model (suffix similarity will catch it)
        assert top is not None
        assert "gemini" in top.lower()
        # But similarity should be below auto-apply threshold (different generation)
        assert sim < 0.85

    @pytest.mark.unit
    def test_no_match_returns_empty(self):
        """A totally unrelated string should produce no suggestions."""
        suggestions, top, sim = _fuzzy_match_model("xyzzy-nonsense-9000", FAKE_REACHABLE)
        assert suggestions == []
        assert top is None
        assert sim == 0.0

    @pytest.mark.unit
    def test_suggestions_capped_at_max(self):
        """Suggestions list never exceeds _FUZZY_MAX_SUGGESTIONS."""
        suggestions, _, _ = _fuzzy_match_model("gemini", FAKE_REACHABLE)
        assert len(suggestions) <= tool_sysops._FUZZY_MAX_SUGGESTIONS

    @pytest.mark.unit
    def test_full_string_exact_match_scores_one(self):
        """An exact match in reachable returns suggestion with similarity 1.0."""
        target = "github_copilot/gpt-4o"
        suggestions, top, sim = _fuzzy_match_model(target, FAKE_REACHABLE)
        assert target in suggestions
        assert top == target
        assert sim == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. _discover_reachable_models — cache + best-effort tests
# ---------------------------------------------------------------------------


class TestDiscoverReachableModels:
    """Tests for the discovery helper — verifies cache TTL + best-effort behavior."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_when_both_endpoints_fail(self, monkeypatch):
        """When httpx raises on every request, helper returns []."""
        # Force _get_copilot_token to raise so the Copilot path is skipped early.
        def _bust_token():
            raise RuntimeError("no token")

        monkeypatch.setattr("sci_fi_dashboard.llm_router._get_copilot_token", _bust_token)

        # Make every httpx GET raise.
        class _FailClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise RuntimeError("network down")

        monkeypatch.setattr("httpx.AsyncClient", _FailClient)

        models = await _discover_reachable_models()
        assert models == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_ttl_honored(self, monkeypatch):
        """Second call within TTL should not re-query — return cached list."""
        # Seed the cache directly so we don't have to mock httpx.
        import time as _time

        tool_sysops._models_cache["models"] = ["github_copilot/gpt-4o"]
        tool_sysops._models_cache["expires_at"] = _time.monotonic() + 1000.0
        tool_sysops._models_cache["fetched"] = True

        # If the helper bypasses cache, this httpx mock would be invoked.
        called = {"count": 0}

        class _SpyClient:
            def __init__(self, *a, **kw):
                called["count"] += 1

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise AssertionError("should not be called when cache is fresh")

        monkeypatch.setattr("httpx.AsyncClient", _SpyClient)

        models = await _discover_reachable_models()
        assert models == ["github_copilot/gpt-4o"]
        assert called["count"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_expires_and_refetches(self, monkeypatch):
        """When the cache has expired, helper re-queries and updates cache."""
        import time as _time

        # Seed an EXPIRED cache — fetched=True but expires_at in the past so the
        # TTL guard is what should force the refetch (not the fetched flag).
        tool_sysops._models_cache["models"] = ["github_copilot/old-model"]
        tool_sysops._models_cache["expires_at"] = _time.monotonic() - 10.0
        tool_sysops._models_cache["fetched"] = True

        # Force token + httpx to fail so the helper just returns [] but still
        # writes the cache. We're verifying the refetch path is taken, not the
        # specific return value.
        def _bust_token():
            raise RuntimeError("no token")

        monkeypatch.setattr("sci_fi_dashboard.llm_router._get_copilot_token", _bust_token)

        class _FailClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise RuntimeError("network down")

        monkeypatch.setattr("httpx.AsyncClient", _FailClient)

        models = await _discover_reachable_models()
        # Old cache value should NOT have leaked through; refetch ran and
        # produced [] because both endpoints failed.
        assert models == []


# ---------------------------------------------------------------------------
# 3. edit_synapse_config — fuzzy fallback integration tests
# ---------------------------------------------------------------------------


async def _call_set(factory_tool, key_path: str, value):
    """Helper: invoke the tool's _execute with action=set."""
    return await factory_tool.execute(
        {"action": "set", "key_path": key_path, "value": value}
    )


class TestEditSynapseConfigFuzzy:
    """Integration tests for the fuzzy-match path in edit_synapse_config."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_exact_match_applies(self, fake_synapse_config, monkeypatch):
        """Exact reachable model passes validation and writes config."""
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        assert tool is not None

        result = await _call_set(tool, "model_mappings.casual.model", "github_copilot/gpt-4o")
        assert not result.is_error, f"expected success, got: {result.content}"
        payload = json.loads(result.content)
        assert payload["status"] == "applied"
        assert payload["value"] == "github_copilot/gpt-4o"
        assert "note" not in payload  # No fuzzy auto-apply happened

        # Verify file was written
        cfg = json.loads(fake_synapse_config.read_text(encoding="utf-8"))
        assert cfg["model_mappings"]["casual"]["model"] == "github_copilot/gpt-4o"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_close_suffix_match_auto_applies_with_note(
        self, fake_synapse_config, monkeypatch
    ):
        """value='gemini-2.0-flash' auto-applies 'github_copilot/gemini-2.0-flash-001'."""
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "model_mappings.casual.model", "gemini-2.0-flash")

        assert not result.is_error, f"expected success, got: {result.content}"
        payload = json.loads(result.content)
        assert payload["status"] == "applied"
        # Auto-applied value should be the close match, not the original.
        assert payload["value"] == "github_copilot/gemini-2.0-flash-001"
        # Note should be present and reference both the requested and applied values.
        assert "note" in payload
        assert "gemini-2.0-flash" in payload["note"]
        assert "gemini-2.0-flash-001" in payload["note"]
        assert "auto-applied" in payload["note"].lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ambiguous_no_prefix_rejected_with_configured_providers_hint(
        self, fake_synapse_config, monkeypatch
    ):
        """value='gemini-3-flash' — no "/" prefix, no auto-apply → trust-prefix
        rejects with missing-prefix error that lists configured providers and
        points to TOOLS.md (RT3.6 replaced the old 'Closest matches' message).
        """
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "model_mappings.casual.model", "gemini-3-flash")

        assert result.is_error, f"expected error, got success: {result.content}"
        err = json.loads(result.content)["error"]
        assert "provider prefix" in err  # missing-prefix message
        assert "Configured providers" in err
        assert "TOOLS.md" in err  # points at the curl recipes
        # Must not have written anything to config.
        cfg = json.loads(fake_synapse_config.read_text(encoding="utf-8"))
        assert cfg["model_mappings"]["casual"]["model"] == "github_copilot/gpt-4o-mini"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_fuzzy_match_no_prefix_rejected(
        self, fake_synapse_config, monkeypatch
    ):
        """value='xyzzy-nonsense-9000' — no fuzzy match AND no '/' → trust-prefix
        rejects with missing-prefix error.
        """
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool, "model_mappings.casual.model", "xyzzy-nonsense-9000"
        )

        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "provider prefix" in err
        assert "Configured providers" in err
        # Must not have written anything to config.
        cfg = json.loads(fake_synapse_config.read_text(encoding="utf-8"))
        assert cfg["model_mappings"]["casual"]["model"] == "github_copilot/gpt-4o-mini"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_string_value_rejected(self, fake_synapse_config, monkeypatch):
        """Non-string value yields a clear type error."""
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "model_mappings.casual.model", 42)
        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "must be a string" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_offline_fallback_accepts_configured_provider_prefix(
        self, fake_synapse_config, monkeypatch
    ):
        """When discovery returns empty (offline), trust-prefix still accepts
        values whose provider is in the always-trusted set (Copilot/Ollama)
        even without a real api_key. No prefix or unknown prefix is rejected.
        """
        async def _stub(timeout: float = 3.0):
            return []  # Both endpoints unreachable

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))

        # github_copilot is always trusted (no synapse.json key required).
        result = await _call_set(
            tool,
            "model_mappings.casual.model",
            "github_copilot/future-model",
        )
        assert not result.is_error, f"expected success, got: {result.content}"

        # No prefix → trust-prefix rejects it.
        result_bad = await _call_set(
            tool, "model_mappings.casual.model", "no-prefix-here"
        )
        assert result_bad.is_error
        err = json.loads(result_bad.content)["error"]
        assert "provider prefix" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_owner_factory_returns_none(self, fake_synapse_config):
        """Non-owner sessions don't get the tool at all."""
        tool = _edit_synapse_config_factory(_make_ctx(owner=False))
        assert tool is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_model_path_skips_fuzzy(self, fake_synapse_config, monkeypatch):
        """Setting a non-model key (e.g. providers config) should not invoke fuzzy logic."""
        # If the helper is touched at all, the test fails.
        async def _boom(timeout: float = 3.0):
            raise AssertionError("fuzzy path should not run for non-model keys")

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _boom)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "session.dual_cognition_timeout", 7.5)
        assert not result.is_error, f"expected success, got: {result.content}"


# ---------------------------------------------------------------------------
# 4. RT3.6: trust-prefix fallback — configured-provider awareness
# ---------------------------------------------------------------------------


@pytest.fixture
def configured_synapse_config(tmp_path, monkeypatch):
    """synapse.json with a realistic multi-provider mix:
        * anthropic + openai → real-looking keys (trusted)
        * gemini             → placeholder "YOUR_..." (not trusted)
        * groq               → empty string (not trusted)
        * github_copilot     → present but no api_key (always trusted anyway)
        * openai_codex       → present but no api_key (trusted only when local
                               OAuth credentials exist)
        * ollama             → present but no api_key (always trusted anyway)
    """
    home = tmp_path / "home"
    synapse_dir = home / ".synapse"
    synapse_dir.mkdir(parents=True)
    cfg_path = synapse_dir / "synapse.json"
    cfg_path.write_text(
        json.dumps(
            {
                "model_mappings": {
                    "casual": {"model": "github_copilot/gpt-4o-mini"},
                },
                "providers": {
                    "anthropic": {"api_key": "sk-ant-real-key-XXXXX"},
                    "openai": {"api_key": "sk-real-XXXXX"},
                    "gemini": {"api_key": "YOUR_GEMINI_API_KEY"},
                    "groq": {"api_key": ""},
                    "github_copilot": {},
                    "openai_codex": {},
                    "ollama": {},
                },
            },
            indent=2,
        )
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    # SYNAPSE_HOME would override Path.home() inside SynapseConfig.load(), so
    # scrub it for the duration of the test to keep the fixture honest.
    monkeypatch.delenv("SYNAPSE_HOME", raising=False)
    return cfg_path


class TestGetConfiguredProviders:
    """Direct unit tests for _get_configured_providers — the source of truth
    for trust-prefix's accepted-provider set."""

    @pytest.mark.unit
    def test_real_keys_included(self, configured_synapse_config):
        configured = tool_sysops._get_configured_providers()
        assert "anthropic" in configured
        assert "openai" in configured

    @pytest.mark.unit
    def test_always_trusted_providers_always_present(self, configured_synapse_config):
        configured = tool_sysops._get_configured_providers()
        # github_copilot (JWT auth) + ollama_chat / ollama (local daemon)
        # are always in the trusted set regardless of synapse.json keys.
        assert "github_copilot" in configured
        assert "ollama_chat" in configured
        assert "ollama" in configured

    @pytest.mark.unit
    def test_openai_codex_included_when_oauth_credentials_present(
        self, configured_synapse_config, monkeypatch
    ):
        fake_creds = type(
            "_Creds",
            (),
            {"access_token": "access-token", "refresh_token": "refresh-token"},
        )()
        monkeypatch.setattr(
            "sci_fi_dashboard.openai_codex_oauth.load_credentials",
            lambda: fake_creds,
        )
        configured = tool_sysops._get_configured_providers()
        assert "openai_codex" in configured

    @pytest.mark.unit
    def test_openai_codex_filtered_when_oauth_credentials_missing(
        self, configured_synapse_config
    ):
        configured = tool_sysops._get_configured_providers()
        assert "openai_codex" not in configured

    @pytest.mark.unit
    def test_placeholder_key_filtered(self, configured_synapse_config):
        configured = tool_sysops._get_configured_providers()
        # gemini's api_key is "YOUR_GEMINI_API_KEY" → placeholder, not trusted.
        assert "gemini" not in configured

    @pytest.mark.unit
    def test_empty_key_filtered(self, configured_synapse_config):
        configured = tool_sysops._get_configured_providers()
        # groq's api_key is "" → not trusted.
        assert "groq" not in configured

    @pytest.mark.unit
    def test_unknown_provider_absent(self, configured_synapse_config):
        configured = tool_sysops._get_configured_providers()
        assert "deepseek" not in configured
        assert "mistral" not in configured

    @pytest.mark.unit
    def test_placeholder_literals_filtered(self, tmp_path, monkeypatch):
        """Keys equal to the literal PLACEHOLDER / changeme strings are filtered."""
        home = tmp_path / "home"
        synapse_dir = home / ".synapse"
        synapse_dir.mkdir(parents=True)
        (synapse_dir / "synapse.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "anthropic": {"api_key": "PLACEHOLDER"},
                        "openai": {"api_key": "changeme"},
                        "cohere": {"api_key": "real-key"},
                    }
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        monkeypatch.delenv("SYNAPSE_HOME", raising=False)

        configured = tool_sysops._get_configured_providers()
        assert "anthropic" not in configured
        assert "openai" not in configured
        assert "cohere" in configured

    @pytest.mark.unit
    def test_returns_always_trusted_on_load_failure(self, tmp_path, monkeypatch):
        """If synapse.json is missing, helper still returns the always-trusted set."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        monkeypatch.delenv("SYNAPSE_HOME", raising=False)

        configured = tool_sysops._get_configured_providers()
        assert configured == {
            "github_copilot",
            "ollama_chat",
            "ollama",
        }


class TestTrustPrefixFallback:
    """Integration tests: edit_synapse_config with RT3.6 trust-prefix fallback."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_anthropic_prefix_accepted_when_configured(
        self, configured_synapse_config, monkeypatch
    ):
        """Case C: anthropic/claude-... accepted because anthropic key is real,
        even when fuzzy returns sub-threshold Copilot suggestions.
        """
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool,
            "model_mappings.casual.model",
            "anthropic/claude-3-haiku-20240307",
        )
        assert not result.is_error, f"expected success, got: {result.content}"
        payload = json.loads(result.content)
        assert payload["status"] == "applied"
        # Must have written the user's value verbatim — no silent swap to Copilot.
        assert payload["value"] == "anthropic/claude-3-haiku-20240307"
        # And no auto-apply note (we didn't switch to a fuzzy match).
        assert "note" not in payload

        cfg = json.loads(configured_synapse_config.read_text(encoding="utf-8"))
        assert (
            cfg["model_mappings"]["casual"]["model"]
            == "anthropic/claude-3-haiku-20240307"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_provider_rejected_with_hint(
        self, configured_synapse_config, monkeypatch
    ):
        """Case D: deepseek/foo rejected — error lists configured providers
        (anthropic, openai) but NOT placeholder-keyed ones (gemini)."""
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "model_mappings.casual.model", "deepseek/foo")
        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "deepseek" in err
        assert "unknown provider" in err
        # Configured providers must appear in the hint...
        assert "anthropic" in err
        assert "openai" in err
        # ...but providers with placeholder keys should NOT.
        assert "gemini" not in err
        assert "groq" not in err
        # Points at the docs for the curl-recipe workflow.
        assert "TOOLS.md" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_placeholder_key_provider_not_trusted(
        self, configured_synapse_config, monkeypatch
    ):
        """Case F: gemini/... rejected because gemini's key is placeholder."""
        async def _stub(timeout: float = 3.0):
            return list(FAKE_REACHABLE)

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool, "model_mappings.casual.model", "gemini/gemini-1.5-flash"
        )
        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "gemini" in err
        # Configured alternatives still surfaced.
        assert "anthropic" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_copilot_special_always_trusted(
        self, configured_synapse_config, monkeypatch
    ):
        """Case I edge: github_copilot is always in the configured set even
        without an explicit api_key — runtime validates the model name."""
        async def _stub(timeout: float = 3.0):
            return []  # offline — force trust-prefix path

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool, "model_mappings.casual.model", "github_copilot/gpt-5-future"
        )
        assert not result.is_error, f"expected success, got: {result.content}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_openai_codex_prefix_accepted_with_oauth_credentials(
        self, configured_synapse_config, monkeypatch
    ):
        """openai_codex/... is accepted when local OAuth state is present."""
        async def _stub(timeout: float = 3.0):
            return []  # offline — force trust-prefix path

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)
        fake_creds = type(
            "_Creds",
            (),
            {"access_token": "access-token", "refresh_token": "refresh-token"},
        )()
        monkeypatch.setattr(
            "sci_fi_dashboard.openai_codex_oauth.load_credentials",
            lambda: fake_creds,
        )

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool, "model_mappings.casual.model", "openai_codex/gpt-5-codex"
        )
        assert not result.is_error, f"expected success, got: {result.content}"
        payload = json.loads(result.content)
        assert payload["value"] == "openai_codex/gpt-5-codex"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_openai_codex_prefix_rejected_without_oauth_credentials(
        self, configured_synapse_config, monkeypatch
    ):
        """openai_codex/... is rejected when OAuth state is missing locally."""
        async def _stub(timeout: float = 3.0):
            return []  # offline — force trust-prefix path

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)
        monkeypatch.setattr(
            "sci_fi_dashboard.openai_codex_oauth.load_credentials",
            lambda: None,
        )

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool, "model_mappings.casual.model", "openai_codex/gpt-5-codex"
        )
        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "unknown provider" in err
        assert "openai_codex" in err

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_offline_configured_provider_accepted(
        self, configured_synapse_config, monkeypatch
    ):
        """Case H: offline (reachable empty), anthropic configured → accept."""
        async def _stub(timeout: float = 3.0):
            return []

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(
            tool,
            "model_mappings.casual.model",
            "anthropic/claude-3-5-sonnet-20241022",
        )
        assert not result.is_error, f"expected success, got: {result.content}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_offline_unknown_provider_rejected(
        self, configured_synapse_config, monkeypatch
    ):
        """Case H negative: offline + unknown provider → reject."""
        async def _stub(timeout: float = 3.0):
            return []

        monkeypatch.setattr(tool_sysops, "_discover_reachable_models", _stub)

        tool = _edit_synapse_config_factory(_make_ctx(owner=True))
        result = await _call_set(tool, "model_mappings.casual.model", "deepseek/v3")
        assert result.is_error
        err = json.loads(result.content)["error"]
        assert "unknown provider" in err
        assert "deepseek" in err
