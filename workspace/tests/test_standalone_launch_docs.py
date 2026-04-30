from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

LAUNCH_SCRIPTS = (
    "synapse_onboard.bat",
    "synapse_onboard.sh",
    "synapse_start.bat",
    "synapse_start.sh",
    "synapse_stop.bat",
    "synapse_stop.sh",
)

LEGACY_USER_FACING_STRINGS = (
    "pip install -e",
    "workspace/synapse_cli.py",
    "--app-dir",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_launch_scripts_delegate_to_installed_synapse_cli_without_legacy_bootstrap() -> None:
    for script in LAUNCH_SCRIPTS:
        content = _read(script)
        for legacy in LEGACY_USER_FACING_STRINGS:
            assert legacy not in content, f"{legacy!r} leaked into {script}"

    assert "synapse onboard" in _read("synapse_onboard.sh")
    assert "synapse onboard" in _read("synapse_onboard.bat")
    assert "synapse start" in _read("synapse_start.sh")
    assert "synapse start" in _read("synapse_start.bat")
    assert "synapse stop" in _read("synapse_stop.sh")
    assert "synapse stop" in _read("synapse_stop.bat")


def test_readme_quick_start_is_npm_first_and_developer_setup_is_separate() -> None:
    content = _read("README.md")
    quick_start = _section(content, "## Quick Start", "## Docs")

    for command in (
        "npm install -g synapse-oss",
        "synapse install",
        "synapse onboard",
        "synapse start",
    ):
        assert command in quick_start

    for legacy in LEGACY_USER_FACING_STRINGS:
        assert legacy not in quick_start

    assert "developer" in quick_start.lower()
    assert "git clone https://github.com/UpayanGhosh/Synapse-OSS.git" not in quick_start


def test_how_to_run_install_path_uses_synapse_product_home_not_repo_bootstrap() -> None:
    content = _read("HOW_TO_RUN.md")
    install_path = _section(content, "## Part 2", "## Part 7")

    for command in (
        "npm install -g synapse-oss",
        "synapse install",
        "synapse onboard",
        "synapse start",
    ):
        assert command in install_path

    assert ".synapse" in install_path
    assert "normal users do not need the github repo" in install_path.lower()

    for legacy in LEGACY_USER_FACING_STRINGS:
        assert legacy not in install_path
