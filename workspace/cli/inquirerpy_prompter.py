"""
inquirerpy_prompter.py — InquirerPy-based WizardPrompter implementation.

Drop-in replacement for QuestionaryPrompter using InquirerPy for better
Windows cmd.exe compatibility (no prompt_toolkit Space/arrow key issues),
fuzzy search on multiselect (useful with 19 providers), and richer styling.

This module is only imported when InquirerPy is installed. onboard.py falls
back to QuestionaryPrompter with a try/ImportError guard.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel

from cli.wizard_prompter import WizardCancelledError

_console = Console()


# ---------------------------------------------------------------------------
# Choice conversion helpers
# ---------------------------------------------------------------------------


def _convert_for_select(choices: list) -> list:
    """Convert questionary Choice/Separator objects to InquirerPy format for select().

    questionary.Choice(title, value=...) -> {"name": title, "value": value}
    questionary.Separator(line)          -> InquirerPy Separator(line)
    str                                  -> str (pass-through)
    """
    from InquirerPy.separator import Separator as IpySeparator  # noqa: PLC0415

    result = []
    for c in choices:
        if isinstance(c, str):
            result.append(c)
        elif hasattr(c, "value") and hasattr(c, "title"):
            # questionary.Choice — title can be str or list of FormattedText tuples
            title = c.title
            if isinstance(title, list):
                title = "".join(
                    part[1] if isinstance(part, tuple) else str(part) for part in title
                )
            result.append({"name": str(title), "value": c.value})
        elif hasattr(c, "line"):
            # questionary.Separator
            result.append(IpySeparator(str(c.line)))
        else:
            result.append(c)
    return result


def _convert_for_multiselect(choices: list) -> list:
    """Convert choices for fuzzy multiselect — strips Separators (not supported in fuzzy mode).

    Separators are intentionally dropped here because:
    - InquirerPy fuzzy does not render Separators as group dividers
    - Fuzzy search makes grouping less important (user can type to filter)
    """
    result = []
    for c in choices:
        if isinstance(c, str):
            result.append(c)
        elif hasattr(c, "value") and hasattr(c, "title"):
            title = c.title
            if isinstance(title, list):
                title = "".join(
                    part[1] if isinstance(part, tuple) else str(part) for part in title
                )
            result.append({"name": str(title), "value": c.value})
        # Separators are intentionally skipped
    return result


# ---------------------------------------------------------------------------
# InquirerPyPrompter
# ---------------------------------------------------------------------------


class InquirerPyPrompter:
    """WizardPrompter implementation using InquirerPy + Rich.

    Behaviour:
      - select()      → inquirer.select()  with Separator support
      - multiselect() → inquirer.fuzzy()   with multiselect=True (fuzzy search, no Separators)
      - text()        → inquirer.text() / inquirer.secret()
      - confirm()     → inquirer.confirm()
      - intro/outro/note → Rich Panel display

    Any cancelled prompt (Ctrl+C) raises WizardCancelledError, matching the
    same cancel path as QuestionaryPrompter.
    """

    # --- Display methods ---

    def intro(self, title: str) -> None:
        _console.print(Panel(f"[bold cyan]{title}[/]", expand=False, border_style="cyan"))

    def outro(self, msg: str) -> None:
        _console.print(Panel(f"[bold green]{msg}[/]", expand=False, border_style="green"))

    def note(self, msg: str, title: str | None = None) -> None:
        _console.print(Panel(msg, title=title, expand=False, border_style="dim"))

    # --- Prompt methods ---

    def select(self, message: str, choices: list, default: Any = None) -> Any:
        from InquirerPy import inquirer  # noqa: PLC0415

        converted = _convert_for_select(choices)
        try:
            result = inquirer.select(
                message=message,
                choices=converted,
                default=default,
            ).execute()
        except KeyboardInterrupt:
            raise WizardCancelledError() from None
        if result is None:
            raise WizardCancelledError()
        return result

    def multiselect(self, message: str, choices: list) -> list:
        from InquirerPy import inquirer  # noqa: PLC0415

        converted = _convert_for_multiselect(choices)
        try:
            result = inquirer.fuzzy(
                message=message,
                choices=converted,
                multiselect=True,
                max_height="50%",
            ).execute()
        except KeyboardInterrupt:
            raise WizardCancelledError() from None
        if result is None:
            raise WizardCancelledError()
        return result

    def text(self, message: str, default: str = "", password: bool = False) -> str:
        from InquirerPy import inquirer  # noqa: PLC0415

        try:
            if password:
                result = inquirer.secret(message=message).execute()
            else:
                result = inquirer.text(message=message, default=default).execute()
        except KeyboardInterrupt:
            raise WizardCancelledError() from None
        if result is None:
            raise WizardCancelledError()
        return result

    def confirm(self, message: str, default: bool = True) -> bool:
        from InquirerPy import inquirer  # noqa: PLC0415

        try:
            result = inquirer.confirm(message=message, default=default).execute()
        except KeyboardInterrupt:
            raise WizardCancelledError() from None
        if result is None:
            raise WizardCancelledError()
        return result
