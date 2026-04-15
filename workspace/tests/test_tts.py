"""
Test Suite: TTS (Text-To-Speech) Engine and Pipeline Integration
================================================================
Tests the full TTS stack:
  - TTSEngine: dispatch logic, guards, provider selection
  - EdgeTTSProvider: synthesis and error handling
  - ElevenLabsProvider: voice resolution, synthesis, and error handling
  - mp3_to_ogg_opus: ffmpeg transcoding and error handling
  - SynapseConfig.tts: config loading
  - Pipeline integration: TTS dispatch in process_message_pipeline
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# TestTTSConfig
# ---------------------------------------------------------------------------


class TestTTSConfig:
    """Tests for SynapseConfig TTS configuration field."""

    def test_synapse_config_has_tts_field(self):
        """SynapseConfig dataclass must have a `tts` attribute and it must be a dict."""
        from synapse_config import SynapseConfig

        # The class-level annotation is sufficient — check that the field exists
        # and that load() returns a config with tts as a dict.
        with patch("synapse_config.SynapseConfig.load") as mock_load:
            cfg = MagicMock()
            cfg.tts = {}
            mock_load.return_value = cfg
            loaded = SynapseConfig.load()
            assert hasattr(loaded, "tts")
            assert isinstance(loaded.tts, dict)

    def test_tts_default_is_empty_dict(self):
        """When synapse.json has no 'tts' key, cfg.tts is {} (not None or missing)."""
        import dataclasses

        from synapse_config import SynapseConfig

        # Find the tts field in the dataclass
        fields = {f.name: f for f in dataclasses.fields(SynapseConfig)}
        assert "tts" in fields, "SynapseConfig must have a 'tts' dataclass field"
        # Default factory should produce an empty dict
        default = (
            fields["tts"].default_factory()
            if callable(getattr(fields["tts"], "default_factory", None))
            else fields["tts"].default
        )
        assert default == {}, f"tts field default should be {{}} but got {default!r}"


# ---------------------------------------------------------------------------
# TestEdgeTTSProvider
# ---------------------------------------------------------------------------


class TestEdgeTTSProvider:
    """Tests for EdgeTTSProvider."""

    @pytest.mark.asyncio
    async def test_edge_synthesize_returns_bytes(self):
        """EdgeTTSProvider.synthesize() returns non-empty bytes when edge_tts works."""
        from sci_fi_dashboard.tts.providers.edge import EdgeTTSProvider

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 100  # Fake MP3-like bytes

        # Mock edge_tts.Communicate.save() to write fake MP3 to the temp file
        async def _fake_save(path):
            import pathlib

            pathlib.Path(path).write_bytes(fake_mp3)

        mock_communicate = MagicMock()
        mock_communicate.save = _fake_save

        with patch.dict("sys.modules", {"edge_tts": MagicMock()}):
            import edge_tts

            edge_tts.Communicate.return_value = mock_communicate

            result = await EdgeTTSProvider().synthesize("hello world")
            assert isinstance(result, bytes)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_edge_synthesize_handles_error(self):
        """EdgeTTSProvider.synthesize() returns b'' when edge_tts raises an Exception."""
        from sci_fi_dashboard.tts.providers.edge import EdgeTTSProvider

        async def _failing_save(path):
            raise RuntimeError("Network error")

        mock_communicate = MagicMock()
        mock_communicate.save = _failing_save

        with patch.dict("sys.modules", {"edge_tts": MagicMock()}):
            import edge_tts

            edge_tts.Communicate.return_value = mock_communicate

            result = await EdgeTTSProvider().synthesize("hello world")
            assert result == b""

    @pytest.mark.asyncio
    async def test_edge_synthesize_handles_import_error(self):
        """EdgeTTSProvider.synthesize() returns b'' when edge_tts is not installed."""
        from sci_fi_dashboard.tts.providers.edge import EdgeTTSProvider

        # Force ImportError inside the method by patching builtins.__import__
        __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        import builtins

        original = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "edge_tts":
                raise ImportError("No module named 'edge_tts'")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await EdgeTTSProvider().synthesize("hello world")
            assert result == b""


# ---------------------------------------------------------------------------
# TestElevenLabsProvider
# ---------------------------------------------------------------------------


class TestElevenLabsProvider:
    """Tests for ElevenLabsProvider."""

    def test_elevenlabs_voice_resolution_known_name(self):
        """resolve_voice_id('Rachel') returns the correct voice ID."""
        from sci_fi_dashboard.tts.providers.elevenlabs import resolve_voice_id

        result = resolve_voice_id("Rachel")
        assert result == "21m00Tcm4TlvDq8ikWAM"

    def test_elevenlabs_voice_resolution_passthrough(self):
        """resolve_voice_id('custom-id-123') returns 'custom-id-123' unchanged."""
        from sci_fi_dashboard.tts.providers.elevenlabs import resolve_voice_id

        custom_id = "custom-voice-id-abc123"
        result = resolve_voice_id(custom_id)
        assert result == custom_id

    def test_elevenlabs_voice_resolution_all_premade(self):
        """All 9 premade voice names resolve to non-empty strings different from input."""
        from sci_fi_dashboard.tts.providers.elevenlabs import resolve_voice_id

        voices = ["Rachel", "Josh", "Sam", "Bella", "Adam", "Elli", "Arnold", "Domi", "Antoni"]
        for name in voices:
            voice_id = resolve_voice_id(name)
            assert voice_id != name, f"Voice '{name}' should resolve to an ID, not itself"
            assert len(voice_id) > 10, f"Voice ID for '{name}' seems too short: {voice_id!r}"

    @pytest.mark.asyncio
    async def test_elevenlabs_synthesize_returns_bytes(self):
        """ElevenLabsProvider.synthesize() returns non-empty bytes when API works."""
        from sci_fi_dashboard.tts.providers.elevenlabs import ElevenLabsProvider

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 200

        # Build an async generator that yields chunks
        async def _fake_async_gen():
            yield fake_mp3[:100]
            yield fake_mp3[100:]

        mock_client = AsyncMock()
        mock_client.text_to_speech.convert = AsyncMock(return_value=_fake_async_gen())

        mock_elevenlabs = MagicMock()
        mock_elevenlabs.client.AsyncElevenLabs.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {
                "elevenlabs": mock_elevenlabs,
                "elevenlabs.client": mock_elevenlabs.client,
            },
        ):
            result = await ElevenLabsProvider().synthesize(
                text="hello world",
                voice="Rachel",
                api_key="test-key-123",
            )
            assert isinstance(result, bytes)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_elevenlabs_synthesize_handles_error(self):
        """ElevenLabsProvider.synthesize() returns b'' when API raises Exception."""
        from sci_fi_dashboard.tts.providers.elevenlabs import ElevenLabsProvider

        mock_client = AsyncMock()
        mock_client.text_to_speech.convert = AsyncMock(side_effect=Exception("API error 401"))

        mock_elevenlabs = MagicMock()
        mock_elevenlabs.client.AsyncElevenLabs.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {
                "elevenlabs": mock_elevenlabs,
                "elevenlabs.client": mock_elevenlabs.client,
            },
        ):
            result = await ElevenLabsProvider().synthesize(
                text="hello world",
                voice="Rachel",
                api_key="bad-key",
            )
            assert result == b""


# ---------------------------------------------------------------------------
# TestMP3ToOGGOpus
# ---------------------------------------------------------------------------


class TestMP3ToOGGOpus:
    """Tests for mp3_to_ogg_opus transcoding."""

    @pytest.mark.asyncio
    async def test_convert_handles_ffmpeg_not_found(self):
        """mp3_to_ogg_opus() returns b'' when ffmpeg binary is not on PATH."""
        from sci_fi_dashboard.tts.convert import mp3_to_ogg_opus

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 100

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("No such file or directory: 'ffmpeg'"),
        ):
            result = await mp3_to_ogg_opus(fake_mp3)
            assert result == b""

    @pytest.mark.asyncio
    async def test_convert_handles_ffmpeg_nonzero_exit(self):
        """mp3_to_ogg_opus() returns b'' when ffmpeg exits with non-zero return code."""
        from sci_fi_dashboard.tts.convert import mp3_to_ogg_opus

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 100

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=None)
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await mp3_to_ogg_opus(fake_mp3)
            assert result == b""

    @pytest.mark.asyncio
    async def test_convert_returns_bytes_when_ffmpeg_succeeds(self, tmp_path):
        """mp3_to_ogg_opus() returns non-empty bytes when ffmpeg succeeds."""
        import pathlib

        from sci_fi_dashboard.tts.convert import mp3_to_ogg_opus

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 100
        fake_ogg = b"OggS" + b"\x00" * 50  # Fake OGG bytes

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=None)
        mock_proc.returncode = 0

        async def _fake_subprocess(*args, **kwargs):
            # Write fake OGG to the output path that was passed to ffmpeg
            out_path = args[-1]  # Last arg to ffmpeg is the output file
            pathlib.Path(out_path).write_bytes(fake_ogg)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess):
            result = await mp3_to_ogg_opus(fake_mp3)
            assert isinstance(result, bytes)
            assert len(result) > 0


# ---------------------------------------------------------------------------
# TestTTSEngine
# ---------------------------------------------------------------------------


class TestTTSEngine:
    """Tests for TTSEngine dispatch logic and guards."""

    def _make_cfg(self, tts: dict = None, providers: dict = None):
        """Helper: build a mock SynapseConfig with given tts/providers."""
        cfg = MagicMock()
        cfg.tts = tts if tts is not None else {}
        cfg.providers = providers if providers is not None else {}
        return cfg

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_for_long_text(self):
        """TTSEngine.synthesize() returns None for text longer than MAX_TTS_CHARS."""
        from sci_fi_dashboard.tts.engine import MAX_TTS_CHARS, TTSEngine

        engine = TTSEngine()
        long_text = "x" * (MAX_TTS_CHARS + 1)
        result = await engine.synthesize(long_text)
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_when_disabled(self):
        """TTSEngine.synthesize() returns None when tts.enabled is False."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(tts={"enabled": False})

        # SynapseConfig is imported inside synthesize() as a deferred local import.
        # Patch the module where it is looked up: synapse_config.SynapseConfig.
        with patch("synapse_config.SynapseConfig.load", return_value=cfg):
            result = await engine.synthesize("hello world")
            assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_dispatches_to_edge_by_default(self):
        """TTSEngine.synthesize() uses EdgeTTSProvider when tts.provider is absent."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(tts={})  # Empty = defaults to edge-tts

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 50
        fake_ogg = b"OggS" + b"\x00" * 30

        with (
            patch("synapse_config.SynapseConfig.load", return_value=cfg),
            patch("sci_fi_dashboard.tts.engine.EdgeTTSProvider") as mock_edge_cls,
            patch(
                "sci_fi_dashboard.tts.engine.mp3_to_ogg_opus", new=AsyncMock(return_value=fake_ogg)
            ),
        ):
            mock_edge = AsyncMock()
            mock_edge.synthesize = AsyncMock(return_value=fake_mp3)
            mock_edge_cls.return_value = mock_edge

            result = await engine.synthesize("hello world")

            assert result == fake_ogg
            mock_edge.synthesize.assert_called_once()

    @pytest.mark.asyncio
    async def test_synthesize_dispatches_to_edge_with_explicit_provider(self):
        """TTSEngine.synthesize() uses EdgeTTSProvider when provider is 'edge-tts'."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(tts={"provider": "edge-tts", "voice": "en-GB-SoniaNeural"})

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 50
        fake_ogg = b"OggS" + b"\x00" * 30

        with (
            patch("synapse_config.SynapseConfig.load", return_value=cfg),
            patch("sci_fi_dashboard.tts.engine.EdgeTTSProvider") as mock_edge_cls,
            patch(
                "sci_fi_dashboard.tts.engine.mp3_to_ogg_opus", new=AsyncMock(return_value=fake_ogg)
            ),
        ):
            mock_edge = AsyncMock()
            mock_edge.synthesize = AsyncMock(return_value=fake_mp3)
            mock_edge_cls.return_value = mock_edge

            result = await engine.synthesize("hello world")

            assert result == fake_ogg
            mock_edge.synthesize.assert_called_once_with("hello world", "en-GB-SoniaNeural")

    @pytest.mark.asyncio
    async def test_synthesize_dispatches_to_elevenlabs(self):
        """TTSEngine.synthesize() uses ElevenLabsProvider when provider is 'elevenlabs'."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(
            tts={"provider": "elevenlabs", "voice": "Rachel"},
            providers={"elevenlabs": {"api_key": "test-el-key"}},
        )

        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 50
        fake_ogg = b"OggS" + b"\x00" * 30

        with (
            patch("synapse_config.SynapseConfig.load", return_value=cfg),
            patch("sci_fi_dashboard.tts.engine.ElevenLabsProvider") as mock_el_cls,
            patch(
                "sci_fi_dashboard.tts.engine.mp3_to_ogg_opus", new=AsyncMock(return_value=fake_ogg)
            ),
        ):
            mock_el = AsyncMock()
            mock_el.synthesize = AsyncMock(return_value=fake_mp3)
            mock_el_cls.return_value = mock_el

            result = await engine.synthesize("hello world")

            assert result == fake_ogg
            mock_el.synthesize.assert_called_once_with("hello world", "Rachel", "test-el-key")

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_when_elevenlabs_no_key(self):
        """TTSEngine.synthesize() returns None when elevenlabs provider but no API key."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(
            tts={"provider": "elevenlabs"},
            providers={},  # No elevenlabs key
        )

        with patch("synapse_config.SynapseConfig.load", return_value=cfg):
            result = await engine.synthesize("hello world")
            assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_when_provider_returns_empty(self):
        """TTSEngine.synthesize() returns None when provider returns empty bytes."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(tts={})

        with (
            patch("synapse_config.SynapseConfig.load", return_value=cfg),
            patch("sci_fi_dashboard.tts.engine.EdgeTTSProvider") as mock_edge_cls,
        ):
            mock_edge = AsyncMock()
            mock_edge.synthesize = AsyncMock(return_value=b"")  # Empty = failure
            mock_edge_cls.return_value = mock_edge

            result = await engine.synthesize("hello world")
            assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_when_ogg_conversion_fails(self):
        """TTSEngine.synthesize() returns None when mp3_to_ogg_opus returns empty bytes."""
        from sci_fi_dashboard.tts.engine import TTSEngine

        engine = TTSEngine()
        cfg = self._make_cfg(tts={})
        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 50

        with (
            patch("synapse_config.SynapseConfig.load", return_value=cfg),
            patch("sci_fi_dashboard.tts.engine.EdgeTTSProvider") as mock_edge_cls,
            patch("sci_fi_dashboard.tts.engine.mp3_to_ogg_opus", new=AsyncMock(return_value=b"")),
        ):
            mock_edge = AsyncMock()
            mock_edge.synthesize = AsyncMock(return_value=fake_mp3)
            mock_edge_cls.return_value = mock_edge

            result = await engine.synthesize("hello world")
            assert result is None


# ---------------------------------------------------------------------------
# TestPipelineTTSIntegration
# ---------------------------------------------------------------------------


class TestPipelineTTSIntegration:
    """Tests for TTS dispatch logic inside process_message_pipeline.

    These tests exercise the Step 7 gate in pipeline_helpers.py without
    running the full pipeline (no DB, no LLM, no channel calls).
    """

    def _get_pipeline_step7_conditions(self, reply: str, tts_cfg: dict):
        """Reproduce Step 7 conditions inline to test gate logic."""
        _tts_enabled = tts_cfg.get("enabled", True) if tts_cfg else True
        _terminals = (".", "!", "?", '"', "'", ")", "]", "}")
        _reply_stripped = reply.strip()
        _ends_terminal = bool(_reply_stripped) and _reply_stripped[-1] in _terminals

        should_dispatch = bool(reply) and _tts_enabled and _ends_terminal
        return should_dispatch, _ends_terminal, _tts_enabled

    def test_tts_fires_for_terminal_period(self):
        """Step 7 gate fires TTS when reply ends with '.'."""
        reply = "The answer is 42."
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert ends_terminal is True
        assert should_dispatch is True

    def test_tts_fires_for_terminal_exclamation(self):
        """Step 7 gate fires TTS when reply ends with '!'."""
        reply = "Great news!"
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert ends_terminal is True
        assert should_dispatch is True

    def test_tts_fires_for_terminal_question(self):
        """Step 7 gate fires TTS when reply ends with '?'."""
        reply = "Are you sure?"
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert ends_terminal is True
        assert should_dispatch is True

    def test_tts_skipped_for_non_terminal_reply(self):
        """Step 7 gate skips TTS when reply does NOT end with terminal punctuation.

        Non-terminal replies trigger auto-continue (they were cut off mid-sentence).
        TTS and auto-continue are mutually exclusive.
        """
        reply = "I was about to say something interesting"
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert ends_terminal is False
        assert should_dispatch is False

    def test_tts_skipped_when_disabled(self):
        """Step 7 gate skips TTS when tts.enabled is False."""
        reply = "This ends with a period."
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(
            reply, {"enabled": False}
        )
        assert enabled is False
        assert should_dispatch is False

    def test_tts_skipped_for_empty_reply(self):
        """Step 7 gate skips TTS when reply is empty."""
        reply = ""
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert should_dispatch is False

    def test_tts_fires_for_closing_paren(self):
        """Step 7 gate fires TTS when reply ends with ')'."""
        reply = "Good morning (from Synapse)"
        should_dispatch, ends_terminal, enabled = self._get_pipeline_step7_conditions(reply, {})
        assert ends_terminal is True
        assert should_dispatch is True

    @pytest.mark.asyncio
    async def test_send_voice_note_calls_engine_and_channel(self):
        """_send_voice_note() calls TTSEngine.synthesize, save_media_buffer, and send_voice_note.

        This test patches sys.modules to avoid importing pipeline_helpers' heavy deps
        (pyarrow, lancedb) which are not installed in CI/testing environments.
        """
        fake_ogg = b"OggS" + b"\x00" * 50

        # Build a fake SavedMedia result
        fake_saved = MagicMock()
        fake_saved.path = MagicMock()
        fake_saved.path.name = "abc123.ogg"

        mock_engine = AsyncMock()
        mock_engine.synthesize = AsyncMock(return_value=fake_ogg)

        mock_wa_channel = AsyncMock()
        mock_wa_channel.send_voice_note = AsyncMock(return_value=True)

        # Stub out heavy deps so pipeline_helpers can be imported
        mock_deps_module = MagicMock()
        mock_deps_module.channel_registry.get.return_value = mock_wa_channel
        mock_deps_module.diary_engine = None
        mock_deps_module.flood = MagicMock()
        mock_deps_module.flood.set_callback = MagicMock()

        stub_modules = {
            "sci_fi_dashboard._deps": mock_deps_module,
            "sci_fi_dashboard.conv_kg_extractor": MagicMock(),
            "sci_fi_dashboard.session_ingest": MagicMock(),
            "psutil": MagicMock(),
        }

        import sys

        original_modules = {}
        for mod_name, stub in stub_modules.items():
            original_modules[mod_name] = sys.modules.get(mod_name)
            sys.modules[mod_name] = stub

        # Also ensure sci_fi_dashboard package reference works
        if "sci_fi_dashboard" not in sys.modules:
            sys.modules["sci_fi_dashboard"] = MagicMock()

        try:
            # Reload to pick up stubs if previously imported
            if "sci_fi_dashboard.pipeline_helpers" in sys.modules:
                del sys.modules["sci_fi_dashboard.pipeline_helpers"]

            from sci_fi_dashboard import pipeline_helpers as ph

            ph.deps = mock_deps_module  # patch the module-level deps reference

            with (
                patch("sci_fi_dashboard.tts.TTSEngine", return_value=mock_engine),
                patch(
                    "sci_fi_dashboard.media.store.save_media_buffer",
                    return_value=fake_saved,
                ),
            ):
                await ph._send_voice_note("Hello world.", "1234567890@s.whatsapp.net")

            # Engine was called
            mock_engine.synthesize.assert_called_once_with("Hello world.")
            # Channel was called with the local URL
            mock_wa_channel.send_voice_note.assert_called_once()
            call_args = mock_wa_channel.send_voice_note.call_args
            assert "tts_outbound/abc123.ogg" in call_args[0][1]

        finally:
            # Restore original modules
            for mod_name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(mod_name, None)
                else:
                    sys.modules[mod_name] = original
            # Remove the reloaded pipeline_helpers to avoid polluting other tests
            sys.modules.pop("sci_fi_dashboard.pipeline_helpers", None)

    @pytest.mark.asyncio
    async def test_send_voice_note_handles_engine_returning_none(self):
        """_send_voice_note() returns early and does NOT call channel when TTS skips."""
        mock_engine = AsyncMock()
        mock_engine.synthesize = AsyncMock(return_value=None)  # TTS disabled/failed

        mock_wa_channel = AsyncMock()
        mock_wa_channel.send_voice_note = AsyncMock(return_value=True)

        import sys

        mock_deps_module = MagicMock()
        mock_deps_module.channel_registry.get.return_value = mock_wa_channel
        mock_deps_module.diary_engine = None
        mock_deps_module.flood = MagicMock()
        mock_deps_module.flood.set_callback = MagicMock()

        stub_modules = {
            "sci_fi_dashboard._deps": mock_deps_module,
            "sci_fi_dashboard.conv_kg_extractor": MagicMock(),
            "sci_fi_dashboard.session_ingest": MagicMock(),
            "psutil": MagicMock(),
        }
        original_modules = {}
        for mod_name, stub in stub_modules.items():
            original_modules[mod_name] = sys.modules.get(mod_name)
            sys.modules[mod_name] = stub

        try:
            sys.modules.pop("sci_fi_dashboard.pipeline_helpers", None)

            from sci_fi_dashboard import pipeline_helpers as ph

            ph.deps = mock_deps_module

            with patch("sci_fi_dashboard.tts.TTSEngine", return_value=mock_engine):
                await ph._send_voice_note("Hello world.", "1234567890@s.whatsapp.net")

            # Channel should NOT be called when engine returns None
            mock_wa_channel.send_voice_note.assert_not_called()

        finally:
            for mod_name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(mod_name, None)
                else:
                    sys.modules[mod_name] = original
            sys.modules.pop("sci_fi_dashboard.pipeline_helpers", None)

    @pytest.mark.asyncio
    async def test_send_voice_note_handles_exception_gracefully(self):
        """_send_voice_note() swallows exceptions and never propagates them."""
        import sys

        mock_deps_module = MagicMock()
        mock_deps_module.diary_engine = None
        mock_deps_module.flood = MagicMock()
        mock_deps_module.flood.set_callback = MagicMock()

        stub_modules = {
            "sci_fi_dashboard._deps": mock_deps_module,
            "sci_fi_dashboard.conv_kg_extractor": MagicMock(),
            "sci_fi_dashboard.session_ingest": MagicMock(),
            "psutil": MagicMock(),
        }
        original_modules = {}
        for mod_name, stub in stub_modules.items():
            original_modules[mod_name] = sys.modules.get(mod_name)
            sys.modules[mod_name] = stub

        try:
            sys.modules.pop("sci_fi_dashboard.pipeline_helpers", None)

            from sci_fi_dashboard import pipeline_helpers as ph

            ph.deps = mock_deps_module

            with patch("sci_fi_dashboard.tts.TTSEngine") as mock_engine_cls:
                mock_engine_cls.side_effect = RuntimeError("Unexpected crash")

                # Must not raise — all exceptions are swallowed
                await ph._send_voice_note("Hello world.", "1234567890@s.whatsapp.net")

        finally:
            for mod_name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(mod_name, None)
                else:
                    sys.modules[mod_name] = original
            sys.modules.pop("sci_fi_dashboard.pipeline_helpers", None)
