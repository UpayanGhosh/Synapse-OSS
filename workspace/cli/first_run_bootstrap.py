from __future__ import annotations

from pathlib import Path


def _identity_has_values(content: str) -> bool:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-") or ":" not in stripped:
            continue
        value = stripped.split(":", 1)[1].strip().strip("*_` ")
        if value:
            return True
    return False


def needs_first_run_bootstrap(workspace_dir: Path) -> bool:
    bootstrap = workspace_dir / "BOOTSTRAP.md"
    if not bootstrap.exists():
        return False
    identity = workspace_dir / "IDENTITY.md"
    if not identity.exists():
        return True
    return not _identity_has_values(identity.read_text(encoding="utf-8"))


def bootstrap_kickoff_message() -> str:
    return (
        "Hi Synapse. I just finished installing you in the CLI. "
        "Please start the first-run ritual from BOOTSTRAP.md, ask one question at a time, "
        "learn who you are, who I am, and What should I call you. "
        "Update IDENTITY.md, USER.md, SOUL.md, and AGENTS.md as needed, then delete BOOTSTRAP.md after the ritual completes."
    )
