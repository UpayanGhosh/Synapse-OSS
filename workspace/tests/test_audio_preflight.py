"""
test_audio_preflight.py — Tests for media/audio_preflight.py

Covers:
  - AudioPreflightResult dataclass
  - File not found
  - File size exceeds limit
  - Duration exceeds limit
  - Passes all checks
  - ffprobe unavailable (skips duration check)
  - ffprobe error handling
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.audio_preflight import (
    AudioPreflightResult,
    _probe_duration,
    check_audio_preflight,
)


class TestAudioPreflightResult:
    def test_construction_ok(self):
        result = AudioPreflightResult(
            ok=True, reason="", duration_seconds=10.5, file_size_bytes=1024
        )
        assert result.ok is True
        assert result.reason == ""
        assert result.duration_seconds == 10.5
        assert result.file_size_bytes == 1024

    def test_construction_failed(self):
        result = AudioPreflightResult(
            ok=False, reason="Too big", duration_seconds=None, file_size_bytes=0
        )
        assert result.ok is False
        assert result.reason == "Too big"


class TestCheckAudioPreflight:
    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        result = await check_audio_preflight(tmp_path / "nonexistent.ogg")
        assert result.ok is False
        assert "File not found" in result.reason
        assert result.file_size_bytes == 0
        assert result.duration_seconds is None

    @pytest.mark.asyncio
    async def test_file_too_large(self, tmp_path):
        big_file = tmp_path / "big.ogg"
        big_file.write_bytes(b"x" * 1000)

        result = await check_audio_preflight(big_file, max_size_bytes=500)
        assert result.ok is False
        assert "exceeds limit" in result.reason
        assert result.file_size_bytes == 1000

    @pytest.mark.asyncio
    async def test_passes_when_within_limits(self, tmp_path):
        audio_file = tmp_path / "good.ogg"
        audio_file.write_bytes(b"x" * 100)

        with patch("sci_fi_dashboard.media.audio_preflight._probe_duration", return_value=None):
            result = await check_audio_preflight(audio_file, max_size_bytes=1000)
            assert result.ok is True
            assert result.reason == ""
            assert result.file_size_bytes == 100

    @pytest.mark.asyncio
    async def test_duration_exceeds_limit(self, tmp_path):
        audio_file = tmp_path / "long.ogg"
        audio_file.write_bytes(b"x" * 100)

        with patch("sci_fi_dashboard.media.audio_preflight._probe_duration", return_value=8000.0):
            result = await check_audio_preflight(audio_file, max_duration_seconds=7200)
            assert result.ok is False
            assert "Duration" in result.reason
            assert result.duration_seconds == 8000.0

    @pytest.mark.asyncio
    async def test_duration_within_limit(self, tmp_path):
        audio_file = tmp_path / "short.ogg"
        audio_file.write_bytes(b"x" * 100)

        with patch("sci_fi_dashboard.media.audio_preflight._probe_duration", return_value=60.0):
            result = await check_audio_preflight(
                audio_file, max_size_bytes=1000, max_duration_seconds=7200
            )
            assert result.ok is True
            assert result.duration_seconds == 60.0

    @pytest.mark.asyncio
    async def test_duration_none_when_ffprobe_unavailable(self, tmp_path):
        audio_file = tmp_path / "noprobe.ogg"
        audio_file.write_bytes(b"x" * 100)

        with patch("sci_fi_dashboard.media.audio_preflight._probe_duration", return_value=None):
            result = await check_audio_preflight(audio_file, max_size_bytes=1000)
            assert result.ok is True
            assert result.duration_seconds is None


class TestProbeDuration:
    @pytest.mark.asyncio
    async def test_ffprobe_not_found(self):
        with patch("shutil.which", return_value=None):
            result = await _probe_duration(Path("/some/file.ogg"))
            assert result is None

    @pytest.mark.asyncio
    async def test_ffprobe_returns_duration(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"123.456\n", b"")
        mock_proc.returncode = 0

        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await _probe_duration(Path("/some/file.ogg"))
            assert result == pytest.approx(123.456)

    @pytest.mark.asyncio
    async def test_ffprobe_nonzero_returncode(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error")
        mock_proc.returncode = 1

        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await _probe_duration(Path("/some/file.ogg"))
            assert result is None

    @pytest.mark.asyncio
    async def test_ffprobe_empty_output(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await _probe_duration(Path("/some/file.ogg"))
            assert result is None

    @pytest.mark.asyncio
    async def test_ffprobe_oserror(self):
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("asyncio.create_subprocess_exec", side_effect=OSError("boom")),
        ):
            result = await _probe_duration(Path("/some/file.ogg"))
            assert result is None
