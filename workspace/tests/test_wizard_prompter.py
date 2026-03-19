"""
test_wizard_prompter.py — Tests for wizard_prompter.py

Covers:
  WP-01: StubPrompter.text() returns the pre-set value for a registered key
  WP-02: StubPrompter raises AssertionError for an unexpected prompt key
  WP-03: StubPrompter raises WizardCancelledError when the value is CANCEL sentinel
  WP-04: QuestionaryPrompter.text() raises WizardCancelledError when questionary returns None
  WP-05: _run_interactive(prompter=StubPrompter(...)) raises WizardCancelledError when the
         stub cancels on the first prompt — wizard exits cleanly via typer.Exit(1)
  WP-06: StubPrompter.select() returns pre-set value
  WP-07: StubPrompter.multiselect() returns pre-set list value
  WP-08: StubPrompter.confirm() returns pre-set bool value
  WP-09: StubPrompter tracks call order via internal _calls list
  WP-10: QuestionaryPrompter.select() raises WizardCancelledError when questionary returns None
  WP-11: QuestionaryPrompter.multiselect() raises WizardCancelledError when questionary returns None
  WP-12: QuestionaryPrompter.confirm() raises WizardCancelledError when questionary returns None

No questionary installation required — QuestionaryPrompter tests mock the questionary module.
No live network calls. All file writes go to tmp_path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

try:
    from cli.wizard_prompter import (
        CANCEL,
        QuestionaryPrompter,
        StubPrompter,
        WizardCancelledError,
    )

    WIZARD_PROMPTER_AVAILABLE = True
except ImportError:
    WIZARD_PROMPTER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not WIZARD_PROMPTER_AVAILABLE,
    reason="cli.wizard_prompter not available",
)


# ===========================================================================
# WP-01 through WP-03: StubPrompter basic contract
# ===========================================================================


def test_stub_prompter_text_returns_preset_value():
    """WP-01: StubPrompter.text() returns the value registered for that message."""
    stub = StubPrompter({"Enter your name:": "Alice"})
    result = stub.text("Enter your name:")
    assert result == "Alice"


def test_stub_prompter_raises_assertion_on_unexpected_key():
    """WP-02: StubPrompter raises AssertionError for a prompt key not in the answers dict."""
    stub = StubPrompter({"Known question:": "answer"})
    with pytest.raises(AssertionError, match="unexpected prompt"):
        stub.text("Unknown question:")


def test_stub_prompter_raises_wizard_cancelled_error_on_cancel_sentinel():
    """WP-03: StubPrompter raises WizardCancelledError when the value is the CANCEL sentinel."""
    stub = StubPrompter({"Confirm action:": CANCEL})
    with pytest.raises(WizardCancelledError):
        stub.confirm("Confirm action:")


def test_stub_prompter_cancel_sentinel_on_text():
    """WP-03 variant: CANCEL sentinel also works for .text() calls."""
    stub = StubPrompter({"Enter token:": CANCEL})
    with pytest.raises(WizardCancelledError):
        stub.text("Enter token:")


# ===========================================================================
# WP-04: QuestionaryPrompter raises WizardCancelledError when questionary returns None
# ===========================================================================


def test_questionary_prompter_text_raises_on_none():
    """WP-04: QuestionaryPrompter.text() raises WizardCancelledError when questionary returns None."""
    prompter = QuestionaryPrompter()
    mock_q = MagicMock()
    mock_q.text.return_value.ask.return_value = None  # simulate Ctrl+C

    with patch.dict("sys.modules", {"questionary": mock_q}):
        with pytest.raises(WizardCancelledError):
            prompter.text("Enter something:")


# ===========================================================================
# WP-05: _run_interactive exits cleanly (via typer.Exit) when StubPrompter cancels
# ===========================================================================


def test_run_interactive_exits_cleanly_when_stub_cancels_on_first_prompt(
    tmp_path, monkeypatch
):
    """WP-05: WizardCancelledError from StubPrompter is caught and converted to typer.Exit(1).

    The StubPrompter cancels on 'Synapse-OSS Setup Wizard' (the intro call is a no-op),
    so we cancel on the very first prompt that requires a real answer — the provider
    multiselect. The wizard should swallow WizardCancelledError and raise typer.Exit(1).
    """
    import typer

    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    # Cancel on the provider multiselect — the first actual prompt in quickstart flow
    stub = StubPrompter(
        {
            "Select LLM providers to configure (Space to toggle, Enter to confirm):": CANCEL,
        }
    )

    with (
        patch("cli.onboard._check_for_openclaw", return_value=None),
    ):
        with pytest.raises(typer.Exit) as exc_info:
            _run_interactive(prompter=stub, flow="quickstart")

    assert exc_info.value.exit_code == 1, (
        f"WizardCancelledError must exit with code 1, got {exc_info.value.exit_code}"
    )


# ===========================================================================
# WP-06 through WP-09: StubPrompter additional method coverage
# ===========================================================================


def test_stub_prompter_select_returns_preset_value():
    """WP-06: StubPrompter.select() returns the pre-set value."""
    stub = StubPrompter({"Pick one:": "option_b"})
    result = stub.select("Pick one:", choices=["option_a", "option_b"])
    assert result == "option_b"


def test_stub_prompter_multiselect_returns_preset_list():
    """WP-07: StubPrompter.multiselect() returns the pre-set list."""
    stub = StubPrompter({"Select providers:": ["gemini", "openai"]})
    result = stub.multiselect("Select providers:", choices=["gemini", "openai", "groq"])
    assert result == ["gemini", "openai"]


def test_stub_prompter_confirm_returns_preset_bool():
    """WP-08: StubPrompter.confirm() returns the pre-set bool."""
    stub = StubPrompter({"Do you agree?": True})
    result = stub.confirm("Do you agree?")
    assert result is True


def test_stub_prompter_tracks_call_order():
    """WP-09: StubPrompter records the order of calls in _calls."""
    stub = StubPrompter(
        {
            "First question:": "first",
            "Second question:": "second",
        }
    )
    stub.text("First question:")
    stub.text("Second question:")
    assert stub._calls == ["First question:", "Second question:"]


# ===========================================================================
# WP-10 through WP-12: QuestionaryPrompter None-guard for other methods
# ===========================================================================


def test_questionary_prompter_select_raises_on_none():
    """WP-10: QuestionaryPrompter.select() raises WizardCancelledError when questionary returns None."""
    prompter = QuestionaryPrompter()
    mock_q = MagicMock()
    mock_q.select.return_value.ask.return_value = None

    with patch.dict("sys.modules", {"questionary": mock_q}):
        with pytest.raises(WizardCancelledError):
            prompter.select("Choose:", choices=["a", "b"])


def test_questionary_prompter_multiselect_raises_on_none():
    """WP-11: QuestionaryPrompter.multiselect() raises WizardCancelledError when questionary returns None."""
    prompter = QuestionaryPrompter()
    mock_q = MagicMock()
    mock_q.checkbox.return_value.ask.return_value = None

    with patch.dict("sys.modules", {"questionary": mock_q}):
        with pytest.raises(WizardCancelledError):
            prompter.multiselect("Choose many:", choices=["a", "b"])


def test_questionary_prompter_confirm_raises_on_none():
    """WP-12: QuestionaryPrompter.confirm() raises WizardCancelledError when questionary returns None."""
    prompter = QuestionaryPrompter()
    mock_q = MagicMock()
    mock_q.confirm.return_value.ask.return_value = None

    with patch.dict("sys.modules", {"questionary": mock_q}):
        with pytest.raises(WizardCancelledError):
            prompter.confirm("Are you sure?")
