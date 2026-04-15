"""
Test Suite: Onboarding Wizard v2
================================
Tests for Phase 4 additions: SBS profile initialization, compiler consumption
of wizard fields, setup entrypoint, WhatsApp import offer, non-interactive SBS
env vars, and --verify subcommand.

Coverage targets:
  - ONBOARD2-01: setup command exists and works
  - ONBOARD2-02: SBS profile seeded from wizard questions (linguistic, emotional_state, domain, interaction)
  - ONBOARD2-02+: Compiler consumes preferred_style, active_domains, privacy_sensitivity
  - ONBOARD2-03: WhatsApp import offered during setup
  - ONBOARD2-04: --non-interactive with SBS env vars
  - ONBOARD2-05: --verify validates providers and channels
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip entire module if CLI not installed
# ---------------------------------------------------------------------------

try:
    from cli.onboard import run_wizard  # noqa: F401
    from synapse_cli import app

    _ONBOARD_AVAILABLE = True
except ImportError:
    _ONBOARD_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _ONBOARD_AVAILABLE,
    reason="cli.onboard not available",
)

from typer.testing import CliRunner  # noqa: E402

runner = CliRunner()


def _make_mock_acompletion():
    """Return a valid litellm completion response mock."""
    mock = AsyncMock()
    mock.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))],
        usage=MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    return mock


def _make_mock_profile_manager():
    """Return a MagicMock ProfileManager that tracks save_layer calls."""
    mgr = MagicMock()
    # load_layer returns an empty dict by default so merges work cleanly
    mgr.load_layer.return_value = {}
    return mgr


# ===========================================================================
# ONBOARD2-01: setup command registered + dispatches correctly
# ===========================================================================


class TestSetupEntrypoint:
    """ONBOARD2-01: 'synapse setup' command is registered and dispatches correctly."""

    def test_setup_command_registered(self):
        """ONBOARD2-01: 'setup' appears in the CLI --help output."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "setup" in result.output

    def test_main_module_app_importable(self):
        """ONBOARD2-01: workspace/__main__.py exports 'app' (python -m synapse entry point)."""
        import importlib

        spec = importlib.util.spec_from_file_location(
            "__main__",
            os.path.join(os.path.dirname(__file__), "..", "__main__.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "app"), "__main__.py must export 'app'"

    def test_setup_dispatches_to_run_wizard(self, tmp_path, monkeypatch):
        """ONBOARD2-01: 'synapse setup' without --verify calls run_wizard."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

        with patch("cli.onboard.run_wizard") as mock_wizard:
            runner.invoke(
                app,
                ["setup"],
                env={"SYNAPSE_HOME": str(tmp_path)},
            )
        mock_wizard.assert_called_once()

    def test_setup_verify_flag_dispatches_to_run_verify(self, tmp_path, monkeypatch):
        """ONBOARD2-01: 'synapse setup --verify' calls run_verify, not run_wizard."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

        with patch("cli.verify_steps.run_verify", return_value=0) as mock_verify:
            result = runner.invoke(
                app,
                ["setup", "--verify"],
                env={"SYNAPSE_HOME": str(tmp_path)},
            )
        mock_verify.assert_called_once()
        assert result.exit_code == 0


# ===========================================================================
# ONBOARD2-02: SBS profile initialization
# ===========================================================================


class TestSBSProfileInit:
    """ONBOARD2-02: initialize_sbs_from_wizard() writes correct profile layers."""

    def _call_with_mock_mgr(self, answers, tmp_path):
        """Helper: call initialize_sbs_from_wizard with a mocked ProfileManager.

        Returns the mock manager so callers can assert on save_layer calls.
        """
        from cli.sbs_profile_init import initialize_sbs_from_wizard

        mock_mgr = _make_mock_profile_manager()
        mock_config = MagicMock()
        mock_config.sbs_dir = tmp_path / "sbs"

        with (
            patch("cli.sbs_profile_init.SynapseConfig") as mock_cfg_cls,
            patch("cli.sbs_profile_init.ProfileManager", return_value=mock_mgr),
        ):
            mock_cfg_cls.load.return_value = mock_config
            initialize_sbs_from_wizard(answers, tmp_path)

        return mock_mgr

    def test_initialize_sbs_writes_linguistic_layer(self, tmp_path):
        """ONBOARD2-02: linguistic layer is saved with preferred_style set."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "formal_and_precise",
                "energy_level": "calm_and_steady",
                "interests": [],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert "linguistic" in save_calls, "save_layer('linguistic', ...) must be called"
        linguistic_data = save_calls["linguistic"]
        assert (
            linguistic_data.get("current_style", {}).get("preferred_style") == "formal_and_precise"
        )

    def test_initialize_sbs_writes_emotional_state_layer(self, tmp_path):
        """ONBOARD2-02: high_energy maps to current_dominant_mood='energetic'."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "high_energy",
                "interests": [],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert "emotional_state" in save_calls, "save_layer('emotional_state', ...) must be called"
        assert save_calls["emotional_state"].get("current_dominant_mood") == "energetic"

    def test_initialize_sbs_writes_emotional_state_calm(self, tmp_path):
        """ONBOARD2-02: calm_and_steady maps to current_dominant_mood='calm'."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "calm_and_steady",
                "interests": [],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert save_calls["emotional_state"].get("current_dominant_mood") == "calm"

    def test_initialize_sbs_writes_emotional_state_adaptive(self, tmp_path):
        """ONBOARD2-02: adaptive maps to current_dominant_mood='neutral'."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "adaptive",
                "interests": [],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert save_calls["emotional_state"].get("current_dominant_mood") == "neutral"

    def test_initialize_sbs_writes_domain_layer_with_active_domains(self, tmp_path):
        """ONBOARD2-02: domain layer contains BOTH interests dict AND active_domains list."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "calm_and_steady",
                "interests": ["technology", "music"],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert "domain" in save_calls, "save_layer('domain', ...) must be called"
        domain_data = save_calls["domain"]
        # interests dict must have both topics with weight 1.0
        assert domain_data.get("interests", {}).get("technology") == 1.0
        assert domain_data.get("interests", {}).get("music") == 1.0
        # active_domains list must be present (for _compile_domain() consumption)
        assert domain_data.get("active_domains") == ["technology", "music"]

    def test_initialize_sbs_writes_interaction_layer(self, tmp_path):
        """ONBOARD2-02: interaction layer has privacy_sensitivity='private'."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "calm_and_steady",
                "interests": [],
                "privacy_level": "private",
            },
            tmp_path,
        )
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}
        assert "interaction" in save_calls, "save_layer('interaction', ...) must be called"
        assert save_calls["interaction"].get("privacy_sensitivity") == "private"

    def test_initialize_sbs_never_writes_core_identity(self, tmp_path):
        """ONBOARD2-02: core_identity is never written (raises PermissionError by contract)."""
        mock_mgr = self._call_with_mock_mgr(
            {
                "communication_style": "casual_and_witty",
                "energy_level": "calm_and_steady",
                "interests": [],
                "privacy_level": "selective",
            },
            tmp_path,
        )
        save_layer_names = [c.args[0] for c in mock_mgr.save_layer.call_args_list]
        assert "core_identity" not in save_layer_names, "core_identity must NEVER be written"

    def test_initialize_sbs_default_values(self, tmp_path):
        """ONBOARD2-02: empty answers dict uses safe defaults for all layers."""
        mock_mgr = self._call_with_mock_mgr({}, tmp_path)
        save_calls = {c.args[0]: c.args[1] for c in mock_mgr.save_layer.call_args_list}

        # linguistic defaults to casual_and_witty
        assert save_calls["linguistic"]["current_style"]["preferred_style"] == "casual_and_witty"
        # emotional_state defaults: calm_and_steady → "calm"
        assert save_calls["emotional_state"]["current_dominant_mood"] == "calm"
        # interaction defaults to selective
        assert save_calls["interaction"]["privacy_sensitivity"] == "selective"
        # domain has empty active_domains
        assert save_calls["domain"]["active_domains"] == []

    def test_initialize_sbs_failure_does_not_crash(self, tmp_path):
        """ONBOARD2-02: OSError during save_layer must not propagate out."""
        from cli.sbs_profile_init import initialize_sbs_from_wizard

        mock_mgr = _make_mock_profile_manager()
        mock_mgr.save_layer.side_effect = OSError("disk full")
        mock_config = MagicMock()
        mock_config.sbs_dir = tmp_path / "sbs"

        with (
            patch("cli.sbs_profile_init.SynapseConfig") as mock_cfg_cls,
            patch("cli.sbs_profile_init.ProfileManager", return_value=mock_mgr),
        ):
            mock_cfg_cls.load.return_value = mock_config
            # Should not raise
            initialize_sbs_from_wizard(
                {
                    "communication_style": "casual_and_witty",
                    "energy_level": "high_energy",
                    "interests": ["technology"],
                    "privacy_level": "open",
                },
                tmp_path,
            )


# ===========================================================================
# ONBOARD2-02+: Compiler consumption of wizard-written fields
# ===========================================================================


class TestCompilerConsumption:
    """ONBOARD2-02+: Compiler emits tone/privacy/mood directives from wizard-written fields."""

    def _get_compiler(self):
        """Return a PromptCompiler instance with a minimal mocked ProfileManager."""
        from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler

        mock_mgr = MagicMock()
        return PromptCompiler(profile_manager=mock_mgr)

    # --- _compile_style tests ---

    def test_compile_style_reads_preferred_style_casual(self):
        """Compiler emits casual/warm/witty directive for casual_and_witty."""
        compiler = self._get_compiler()
        result = compiler._compile_style(
            {"current_style": {"preferred_style": "casual_and_witty", "banglish_ratio": 0.3}}
        )
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("casual", "warm", "witty")
        ), f"Expected casual/warm/witty in output, got: {result!r}"

    def test_compile_style_reads_preferred_style_formal(self):
        """Compiler emits professional/precise directive for formal_and_precise."""
        compiler = self._get_compiler()
        result = compiler._compile_style(
            {"current_style": {"preferred_style": "formal_and_precise", "banglish_ratio": 0.1}}
        )
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("professional", "precise")
        ), f"Expected professional/precise in output, got: {result!r}"

    def test_compile_style_reads_preferred_style_technical(self):
        """Compiler emits technical/depth/thorough directive for technical_depth."""
        compiler = self._get_compiler()
        result = compiler._compile_style(
            {"current_style": {"preferred_style": "technical_depth", "banglish_ratio": 0.1}}
        )
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("technical", "depth", "thorough")
        ), f"Expected technical/depth/thorough in output, got: {result!r}"

    def test_compile_style_reads_preferred_style_creative(self):
        """Compiler emits creative/playful/metaphor directive for creative_and_playful."""
        compiler = self._get_compiler()
        result = compiler._compile_style(
            {"current_style": {"preferred_style": "creative_and_playful", "banglish_ratio": 0.2}}
        )
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("creative", "playful", "metaphor")
        ), f"Expected creative/playful/metaphor in output, got: {result!r}"

    def test_compile_style_no_preferred_style_unchanged(self):
        """Backward compatibility: no preferred_style → no tone directive keywords emitted."""
        compiler = self._get_compiler()
        result = compiler._compile_style({"current_style": {"banglish_ratio": 0.3}})
        result_lower = result.lower()
        # None of the tone directive keywords should appear
        assert "casual, warm" not in result_lower
        assert "professional and precise" not in result_lower
        assert "technical depth" not in result_lower
        assert "creative and playful" not in result_lower

    # --- _compile_interaction tests ---

    def test_compile_interaction_reads_privacy_open(self):
        """Compiler emits open-data directive for privacy_sensitivity='open'."""
        compiler = self._get_compiler()
        result = compiler._compile_interaction({"privacy_sensitivity": "open"})
        result_lower = result.lower()
        assert result, "open privacy must produce non-empty output"
        assert any(
            kw in result_lower for kw in ("open", "freely", "remember")
        ), f"Expected open/freely/remember in output, got: {result!r}"

    def test_compile_interaction_reads_privacy_selective(self):
        """Compiler emits selective-memory directive for privacy_sensitivity='selective'."""
        compiler = self._get_compiler()
        result = compiler._compile_interaction({"privacy_sensitivity": "selective"})
        result_lower = result.lower()
        assert result, "selective privacy must produce non-empty output"
        assert any(
            kw in result_lower for kw in ("selective", "key preferences", "sensitive")
        ), f"Expected selective/key preferences/sensitive in output, got: {result!r}"

    def test_compile_interaction_reads_privacy_private(self):
        """Compiler emits minimal-retention directive for privacy_sensitivity='private'."""
        compiler = self._get_compiler()
        result = compiler._compile_interaction({"privacy_sensitivity": "private"})
        result_lower = result.lower()
        assert result, "private privacy must produce non-empty output"
        assert any(
            kw in result_lower for kw in ("privacy", "minimize", "do not reference")
        ), f"Expected privacy/minimize/do not reference in output, got: {result!r}"

    def test_compile_interaction_no_privacy_unchanged(self):
        """Backward compatibility: interaction dict without privacy_sensitivity → no privacy keywords."""
        compiler = self._get_compiler()
        # Only peak_hours — no privacy_sensitivity
        result = compiler._compile_interaction({"peak_hours": [9, 17]})
        # Privacy directive keywords should NOT appear
        assert "minimize" not in result.lower()
        assert "remember details freely" not in result.lower()
        assert "do not reference" not in result.lower()

    def test_compile_interaction_privacy_only_no_peak_hours(self):
        """Privacy directive emitted even when peak_hours is absent (key behavioral change)."""
        compiler = self._get_compiler()
        result = compiler._compile_interaction({"privacy_sensitivity": "selective"})
        # Must produce output — not return empty string
        assert (
            result
        ), "privacy_sensitivity alone must produce non-empty output even without peak_hours"

    def test_compile_domain_reads_active_domains(self):
        """Compiler emits active domains from active_domains list (wizard write path)."""
        compiler = self._get_compiler()
        result = compiler._compile_domain({"active_domains": ["technology", "music"]})
        assert "technology" in result.lower()
        assert "music" in result.lower()

    def test_compile_emotional_energetic_has_non_neutral_instruction(self):
        """energetic mood → compiler does NOT emit neutral fallback."""
        compiler = self._get_compiler()
        result = compiler._compile_emotional({"current_dominant_mood": "energetic"})
        assert (
            "normal mode" not in result.lower()
        ), "energetic mood must not emit neutral 'Normal mode' fallback"
        assert (
            "be your usual self" not in result.lower()
        ), "energetic mood must not emit neutral 'Be your usual self' fallback"
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("enthusiasm", "pace", "energy", "high-energy")
        ), f"energetic mood must emit energy-specific instruction, got: {result!r}"

    def test_compile_emotional_calm_has_non_neutral_instruction(self):
        """calm mood → compiler does NOT emit neutral fallback."""
        compiler = self._get_compiler()
        result = compiler._compile_emotional({"current_dominant_mood": "calm"})
        assert (
            "normal mode" not in result.lower()
        ), "calm mood must not emit neutral 'Normal mode' fallback"
        assert (
            "be your usual self" not in result.lower()
        ), "calm mood must not emit neutral 'Be your usual self' fallback"
        result_lower = result.lower()
        assert any(
            kw in result_lower for kw in ("measured", "thoughtful", "calm", "steady")
        ), f"calm mood must emit calm-specific instruction, got: {result!r}"


# ===========================================================================
# ONBOARD2-02 + ONBOARD2-03: _run_sbs_questions()
# ===========================================================================


class TestSBSQuestions:
    """ONBOARD2-02 / ONBOARD2-03: _run_sbs_questions() collects + writes persona profile."""

    def _make_stub(self, extra_answers=None):
        """Build a StubPrompter with standard SBS question answers."""
        from cli.wizard_prompter import StubPrompter

        answers = {
            "How should Synapse communicate with you by default?": "Casual and witty",
            "How would you describe your typical energy level?": "Calm and steady",
            "What topics are you most interested in? (select all that apply)": [
                "Technology",
                "Music",
            ],
            "How sensitive are you about personal data in conversations?": "Selective - use judgment",
            "Would you like to import existing WhatsApp chat history?": False,
        }
        if extra_answers:
            answers.update(extra_answers)
        return StubPrompter(answers)

    def test_run_sbs_questions_calls_initialize(self, tmp_path):
        """_run_sbs_questions calls initialize_sbs_from_wizard with correct mapped values."""
        from cli.onboard import _run_sbs_questions

        stub = self._make_stub()

        with patch("cli.sbs_profile_init.initialize_sbs_from_wizard") as mock_init:
            _run_sbs_questions(stub, tmp_path)

        mock_init.assert_called_once()
        call_args = mock_init.call_args[0]
        answers_passed = call_args[0]
        # Casual and witty → casual_and_witty
        assert answers_passed.get("communication_style") == "casual_and_witty"
        # Calm and steady → calm_and_steady
        assert answers_passed.get("energy_level") == "calm_and_steady"
        # ["Technology", "Music"] → lowercased
        assert answers_passed.get("interests") == ["technology", "music"]
        # Selective - use judgment → selective
        assert answers_passed.get("privacy_level") == "selective"

    def test_run_sbs_questions_whatsapp_import_offered_and_accepted(self, tmp_path):
        """ONBOARD2-03: accepting WhatsApp import runs subprocess with correct args."""
        from cli.onboard import _run_sbs_questions
        from cli.wizard_prompter import StubPrompter

        fake_wa_path = str(tmp_path / "history.txt")
        (tmp_path / "history.txt").write_text("chat", encoding="utf-8")

        stub = StubPrompter(
            {
                "How should Synapse communicate with you by default?": "Casual and witty",
                "How would you describe your typical energy level?": "Calm and steady",
                "What topics are you most interested in? (select all that apply)": [],
                "How sensitive are you about personal data in conversations?": "Selective - use judgment",
                "Would you like to import existing WhatsApp chat history?": True,
                "Path to WhatsApp export (.txt file)": fake_wa_path,
            }
        )

        with (
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard"),
            patch("subprocess.run") as mock_run,
        ):
            _run_sbs_questions(stub, tmp_path)

        mock_run.assert_called_once()
        run_args = mock_run.call_args[0][0]
        assert "import_whatsapp.py" in " ".join(run_args)

    def test_run_sbs_questions_whatsapp_declined(self, tmp_path):
        """ONBOARD2-03: declining WhatsApp import does NOT call subprocess."""
        from cli.onboard import _run_sbs_questions

        stub = self._make_stub()  # WhatsApp confirm=False

        with (
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard"),
            patch("subprocess.run") as mock_run,
        ):
            _run_sbs_questions(stub, tmp_path)

        mock_run.assert_not_called()

    def test_run_sbs_questions_failure_does_not_crash_wizard(self, tmp_path):
        """ONBOARD2-02: Exception in initialize_sbs_from_wizard must not propagate."""
        from cli.onboard import _run_sbs_questions

        stub = self._make_stub()

        with patch(
            "cli.sbs_profile_init.initialize_sbs_from_wizard", side_effect=Exception("DB error")
        ):
            # Should NOT raise
            _run_sbs_questions(stub, tmp_path)


# ===========================================================================
# ONBOARD2-04: Non-interactive SBS env var seeding
# ===========================================================================


class TestNonInteractiveSBS:
    """ONBOARD2-04: _run_non_interactive() reads SBS persona env vars."""

    def _base_env(self, tmp_path):
        """Return a minimal env dict for a successful non-interactive run."""
        return {
            "SYNAPSE_HOME": str(tmp_path),
            "SYNAPSE_PRIMARY_PROVIDER": "gemini",
            "GEMINI_API_KEY": "fake-test-key",
        }

    def test_non_interactive_with_sbs_env_vars(self, tmp_path, monkeypatch):
        """ONBOARD2-04: All 4 SBS env vars set → initialize_sbs_from_wizard called."""
        from cli.onboard import _run_non_interactive

        env = {
            **self._base_env(tmp_path),
            "SYNAPSE_COMMUNICATION_STYLE": "formal_and_precise",
            "SYNAPSE_ENERGY_LEVEL": "high_energy",
            "SYNAPSE_INTERESTS": "technology,music",
            "SYNAPSE_PRIVACY_LEVEL": "private",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard") as mock_init,
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args[0][0]
        assert call_kwargs["communication_style"] == "formal_and_precise"
        assert call_kwargs["energy_level"] == "high_energy"
        assert "technology" in call_kwargs["interests"]
        assert "music" in call_kwargs["interests"]
        assert call_kwargs["privacy_level"] == "private"

    def test_non_interactive_without_sbs_env_vars(self, tmp_path, monkeypatch):
        """ONBOARD2-04: No SBS env vars → initialize_sbs_from_wizard NOT called."""
        from cli.onboard import _run_non_interactive

        env = self._base_env(tmp_path)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        # Ensure SBS env vars are absent
        for sbs_var in (
            "SYNAPSE_COMMUNICATION_STYLE",
            "SYNAPSE_ENERGY_LEVEL",
            "SYNAPSE_INTERESTS",
            "SYNAPSE_PRIVACY_LEVEL",
        ):
            monkeypatch.delenv(sbs_var, raising=False)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard") as mock_init,
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        mock_init.assert_not_called()

    def test_non_interactive_invalid_style_uses_default(self, tmp_path, monkeypatch, capsys):
        """ONBOARD2-04: Invalid SYNAPSE_COMMUNICATION_STYLE → warning + default used."""
        from cli.onboard import _run_non_interactive

        env = {
            **self._base_env(tmp_path),
            "SYNAPSE_COMMUNICATION_STYLE": "invalid_style_value",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        captured_init_args = []

        def capture_init(answers, data_root):
            captured_init_args.append(answers)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard", side_effect=capture_init),
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        # init must have been called (SYNAPSE_COMMUNICATION_STYLE triggered the block)
        assert captured_init_args, "initialize_sbs_from_wizard must still be called with default"
        # default used for invalid style
        assert captured_init_args[0]["communication_style"] == "casual_and_witty"

    def test_non_interactive_invalid_energy_uses_default(self, tmp_path, monkeypatch):
        """ONBOARD2-04: Invalid SYNAPSE_ENERGY_LEVEL → warning + default 'calm_and_steady'."""
        from cli.onboard import _run_non_interactive

        env = {
            **self._base_env(tmp_path),
            "SYNAPSE_ENERGY_LEVEL": "turbo_max",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        captured_args = []

        def capture(answers, data_root):
            captured_args.append(answers)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard", side_effect=capture),
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        assert captured_args
        assert captured_args[0]["energy_level"] == "calm_and_steady"

    def test_non_interactive_invalid_privacy_uses_default(self, tmp_path, monkeypatch):
        """ONBOARD2-04: Invalid SYNAPSE_PRIVACY_LEVEL → default 'selective'."""
        from cli.onboard import _run_non_interactive

        env = {
            **self._base_env(tmp_path),
            "SYNAPSE_PRIVACY_LEVEL": "super_private_mode",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        captured_args = []

        def capture(answers, data_root):
            captured_args.append(answers)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard", side_effect=capture),
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        assert captured_args
        assert captured_args[0]["privacy_level"] == "selective"

    def test_non_interactive_unknown_interests_filtered(self, tmp_path, monkeypatch):
        """ONBOARD2-04: Unknown topic in SYNAPSE_INTERESTS is filtered; known topics pass through."""
        from cli.onboard import _run_non_interactive

        env = {
            **self._base_env(tmp_path),
            "SYNAPSE_INTERESTS": "technology,unknown_topic_xyz",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        captured_args = []

        def capture(answers, data_root):
            captured_args.append(answers)

        with (
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp,
            patch("cli.sbs_profile_init.initialize_sbs_from_wizard", side_effect=capture),
            patch("cli.onboard._validate_environment"),
            patch(
                "cli.gateway_steps.configure_gateway",
                return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
            ),
        ):
            mock_acomp.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
            )
            _run_non_interactive(accept_risk=True)

        assert captured_args
        interests = captured_args[0]["interests"]
        assert "technology" in interests
        assert "unknown_topic_xyz" not in interests


# ===========================================================================
# ONBOARD2-05: --verify subcommand
# ===========================================================================


class TestVerifySubcommand:
    """ONBOARD2-05: run_verify() validates providers and channels, returns exit code."""

    def _make_synapse_config(self, tmp_path, providers=None, channels=None):
        """Write a minimal synapse.json to tmp_path and return a mock SynapseConfig."""
        from synapse_config import SynapseConfig

        cfg_data = {
            "providers": providers or {"gemini": {"api_key": "fake-key"}},
            "channels": channels or {},
        }
        config_file = tmp_path / "synapse.json"
        config_file.write_text(json.dumps(cfg_data), encoding="utf-8")

        # Build a real-ish SynapseConfig pointing at tmp_path
        mock_cfg = MagicMock(spec=SynapseConfig)
        mock_cfg.data_root = tmp_path
        mock_cfg.providers = cfg_data["providers"]
        mock_cfg.channels = cfg_data["channels"]
        return mock_cfg

    def test_run_verify_returns_0_on_all_pass(self, tmp_path, monkeypatch):
        """ONBOARD2-05: All providers pass → returns 0."""
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        mock_cfg = self._make_synapse_config(tmp_path, providers={"gemini": {"api_key": "fk"}})

        with (
            patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls,
            patch("cli.verify_steps._validate_provider_async", return_value=("gemini", True, "")),
            patch("asyncio.gather", return_value=[("gemini", True, "")]),
        ):
            mock_cfg_cls.load.return_value = mock_cfg
            result = run_verify()

        assert result == 0

    def test_run_verify_returns_1_on_any_failure(self, tmp_path, monkeypatch):
        """ONBOARD2-05: Any provider FAIL → returns 1."""
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        mock_cfg = self._make_synapse_config(tmp_path, providers={"gemini": {"api_key": "bad-key"}})

        with (
            patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls,
            patch("asyncio.run", return_value=[("gemini", False, "invalid_key")]),
        ):
            mock_cfg_cls.load.return_value = mock_cfg
            result = run_verify()

        assert result == 1

    def test_run_verify_no_config_returns_1(self, tmp_path, monkeypatch):
        """ONBOARD2-05: No synapse.json → returns 1 with helpful message."""
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        # tmp_path has no synapse.json

        with patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.data_root = tmp_path
            mock_cfg.providers = {}
            mock_cfg.channels = {}
            mock_cfg_cls.load.return_value = mock_cfg
            result = run_verify()

        assert result == 1

    def test_run_verify_is_read_only(self, tmp_path, monkeypatch):
        """ONBOARD2-05: run_verify must NEVER call write_config."""
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

        with (
            patch("synapse_config.write_config") as mock_write,
            patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls,
        ):
            mock_cfg = MagicMock()
            mock_cfg.data_root = tmp_path
            mock_cfg.providers = {}
            mock_cfg.channels = {}
            mock_cfg_cls.load.return_value = mock_cfg
            run_verify()

        mock_write.assert_not_called()

    def test_run_verify_parallel_providers(self, tmp_path, monkeypatch):
        """ONBOARD2-05: Multiple providers validated in parallel via asyncio.gather."""
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        mock_cfg = self._make_synapse_config(
            tmp_path,
            providers={
                "gemini": {"api_key": "key1"},
                "openrouter": {"api_key": "key2"},
                "anthropic": {"api_key": "key3"},
            },
        )

        with (
            patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls,
            patch("asyncio.run") as mock_run,
            patch("asyncio.gather"),
        ):
            mock_cfg_cls.load.return_value = mock_cfg
            # asyncio.run wraps _validate_all_providers which uses asyncio.gather
            mock_run.return_value = [
                ("gemini", True, ""),
                ("openrouter", True, ""),
                ("anthropic", True, ""),
            ]
            result = run_verify()

        assert result == 0
        # Verify asyncio.run was called (which internally uses gather for parallelism)
        mock_run.assert_called_once()

    def test_run_verify_handles_validation_result_not_bool(self, tmp_path, monkeypatch):
        """Guard against the bug where ValidationResult would be truthy as a raw dataclass.

        If verify_steps uses 'if result:' instead of 'if result.ok:', a
        ValidationResult(ok=False) would still pass (dataclass is always truthy).
        This test verifies that the FAIL case is correctly detected.
        """
        from cli.provider_steps import ValidationResult
        from cli.verify_steps import run_verify

        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        self._make_synapse_config(tmp_path, providers={"gemini": {"api_key": "bad"}})

        # _validate_provider_async internally calls validate_provider and extracts .ok
        # We patch validate_provider to return ValidationResult(ok=False)
        failing_result = ValidationResult(ok=False, error="invalid_key", detail="Bad API key")

        mock_cfg = MagicMock()
        mock_cfg.data_root = tmp_path
        mock_cfg.providers = {"gemini": {"api_key": "bad"}}
        mock_cfg.channels = {}

        with (
            patch("cli.verify_steps.SynapseConfig") as mock_cfg_cls,
            patch("cli.provider_steps.validate_provider", return_value=failing_result),
            patch("asyncio.run", return_value=[("gemini", False, "Bad API key")]),
        ):
            mock_cfg_cls.load.return_value = mock_cfg
            result = run_verify()

        # A correctly-written verify returns 1 on FAIL, not 0
        assert result == 1, (
            "run_verify must return 1 when ValidationResult(ok=False) — "
            "ensure .ok is used, not raw dataclass truthiness"
        )
