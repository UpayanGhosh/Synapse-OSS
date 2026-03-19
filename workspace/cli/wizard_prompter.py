"""
wizard_prompter.py — WizardPrompter Protocol and concrete implementations.

Provides a testability boundary so interactive wizard steps can be exercised
in tests by injecting a StubPrompter with pre-set answers, without needing a
real terminal or the questionary package.

Exports:
  WizardCancelledError  — raised on Ctrl+C / cancelled prompt
  CANCEL                — sentinel value to make StubPrompter raise WizardCancelledError
  WizardPrompter        — Protocol (structural interface)
  QuestionaryPrompter   — concrete implementation wrapping questionary (lazy import)
  StubPrompter          — test implementation driven by a dict of pre-set answers
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Cancel sentinel and error
# ---------------------------------------------------------------------------

CANCEL: object = object()  # Sentinel: StubPrompter raises WizardCancelledError when value is this


class WizardCancelledError(Exception):
    """Raised when the user cancels the wizard (Ctrl+C or EOF).

    Caught at the top of _run_interactive() and exits with code 1.
    """


# ---------------------------------------------------------------------------
# WizardPrompter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class WizardPrompter(Protocol):
    """Structural interface for wizard I/O.

    Methods mirror the @clack/prompts API translated to Python synchronous
    equivalents. All return real Python values, not Promises.

    Concrete implementations:
      - QuestionaryPrompter: wraps questionary, raises WizardCancelledError on None
      - StubPrompter:        driven by a dict of pre-set answers (for tests)
    """

    def intro(self, title: str) -> None:
        """Print an intro/welcome banner."""
        ...

    def outro(self, msg: str) -> None:
        """Print a closing message."""
        ...

    def note(self, msg: str, title: str | None = None) -> None:
        """Print an informational note/panel."""
        ...

    def select(self, message: str, choices: list, default: Any = None) -> Any:
        """Present a single-select prompt. Returns the selected value."""
        ...

    def multiselect(self, message: str, choices: list) -> list:
        """Present a multi-select (checkbox) prompt. Returns list of selected values."""
        ...

    def text(self, message: str, default: str = "", password: bool = False) -> str:
        """Prompt for a text string. Returns the entered string."""
        ...

    def confirm(self, message: str, default: bool = True) -> bool:
        """Prompt for a yes/no confirmation. Returns bool."""
        ...


# ---------------------------------------------------------------------------
# QuestionaryPrompter — concrete implementation (lazy questionary import)
# ---------------------------------------------------------------------------


class QuestionaryPrompter:
    """Concrete WizardPrompter that wraps questionary for real terminal use.

    questionary is imported lazily inside each method so that importing this
    module at command-discovery time does NOT crash if questionary is absent.

    Any questionary call that returns None (Ctrl+C / EOF) is converted to
    WizardCancelledError, providing a single consistent cancel path.
    """

    # --- Rich helpers (conditional import at class level for perf) ---

    def _rich_print(self, msg: str) -> None:
        """Print using Rich if available, else plain print."""
        try:
            from rich.console import Console  # noqa: PLC0415

            Console().print(msg)
        except ImportError:
            print(msg)

    # --- Protocol methods ---

    def intro(self, title: str) -> None:
        try:
            from rich.console import Console  # noqa: PLC0415
            from rich.panel import Panel  # noqa: PLC0415

            Console().print(Panel(f"[bold blue]{title}[/]", expand=False))
        except ImportError:
            print(f"\n=== {title} ===\n")

    def outro(self, msg: str) -> None:
        self._rich_print(f"[bold green]{msg}[/]")

    def note(self, msg: str, title: str | None = None) -> None:
        try:
            from rich.console import Console  # noqa: PLC0415
            from rich.panel import Panel  # noqa: PLC0415

            Console().print(Panel(msg, title=title, expand=False))
        except ImportError:
            if title:
                print(f"--- {title} ---")
            print(msg)

    def select(self, message: str, choices: list, default: Any = None) -> Any:
        try:
            import questionary  # noqa: PLC0415
        except ImportError as exc:
            raise WizardCancelledError("questionary not installed") from exc

        result = questionary.select(message, choices=choices, default=default).ask()
        if result is None:
            raise WizardCancelledError()
        return result

    def multiselect(self, message: str, choices: list) -> list:
        try:
            import questionary  # noqa: PLC0415
        except ImportError as exc:
            raise WizardCancelledError("questionary not installed") from exc

        result = questionary.checkbox(message, choices=choices).ask()
        if result is None:
            raise WizardCancelledError()
        return result

    def text(self, message: str, default: str = "", password: bool = False) -> str:
        try:
            import questionary  # noqa: PLC0415
        except ImportError as exc:
            raise WizardCancelledError("questionary not installed") from exc

        if password:
            result = questionary.password(message).ask()
        else:
            result = questionary.text(message, default=default).ask()
        if result is None:
            raise WizardCancelledError()
        return result

    def confirm(self, message: str, default: bool = True) -> bool:
        try:
            import questionary  # noqa: PLC0415
        except ImportError as exc:
            raise WizardCancelledError("questionary not installed") from exc

        result = questionary.confirm(message, default=default).ask()
        if result is None:
            raise WizardCancelledError()
        return result


# ---------------------------------------------------------------------------
# StubPrompter — test double driven by a pre-set answers dict
# ---------------------------------------------------------------------------


class StubPrompter:
    """Test double for WizardPrompter.

    Constructed with a dict mapping prompt message strings to their pre-set
    answers. Raises AssertionError for any unexpected question (to catch
    untested prompts during test development). Raises WizardCancelledError
    if the pre-set value for a key is the CANCEL sentinel.

    Usage::

        from cli.wizard_prompter import StubPrompter, CANCEL

        stub = StubPrompter({
            "Select LLM providers": ["gemini"],
            "Select channels": [],
            "Reconfigure?": False,
            "Cancel this prompt": CANCEL,  # will raise WizardCancelledError
        })
        _run_interactive(prompter=stub)
    """

    def __init__(self, answers: dict[str, Any]) -> None:
        self._answers = answers
        self._calls: list[str] = []  # record order of calls for assertions

    def _get(self, message: str) -> Any:
        self._calls.append(message)
        if message not in self._answers:
            raise AssertionError(
                f"StubPrompter: unexpected prompt {message!r}.\n"
                f"  Registered keys: {list(self._answers)}"
            )
        value = self._answers[message]
        if value is CANCEL:
            raise WizardCancelledError(f"CANCEL sentinel triggered for {message!r}")
        return value

    def intro(self, title: str) -> None:
        pass  # silently swallow in tests

    def outro(self, msg: str) -> None:
        pass  # silently swallow in tests

    def note(self, msg: str, title: str | None = None) -> None:
        pass  # silently swallow in tests

    def select(self, message: str, choices: list, default: Any = None) -> Any:
        return self._get(message)

    def multiselect(self, message: str, choices: list) -> list:
        return self._get(message)

    def text(self, message: str, default: str = "", password: bool = False) -> str:
        return self._get(message)

    def confirm(self, message: str, default: bool = True) -> bool:
        return self._get(message)
