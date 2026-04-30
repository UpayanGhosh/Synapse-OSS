from __future__ import annotations

from pathlib import Path


def needs_first_run_bootstrap(workspace_dir: Path) -> bool:
    bootstrap = workspace_dir / "BOOTSTRAP.md"
    return bootstrap.exists()


def bootstrap_kickoff_message(workspace_dir: Path | None = None) -> str:
    bootstrap_text = ""
    if workspace_dir is not None:
        bootstrap_path = workspace_dir / "BOOTSTRAP.md"
        try:
            bootstrap_text = bootstrap_path.read_text(encoding="utf-8").strip()
        except OSError:
            bootstrap_text = ""

    base = (
        "Hi Synapse. I just finished installing you in the CLI. "
        "Read BOOTSTRAP.md now and start the first-run ritual inside this CLI chat. "
        "Do not dump a form. Ask one question at a time, starting naturally with: "
        "'Hey. I just came online. Who am I? Who are you?' "
        "Learn your name, nature, vibe, signature emoji, my name, timezone, boundaries, "
        "channels, memory preferences, and what kind of proactivity feels helpful. "
        "Update IDENTITY.md, USER.md, CORE.md, SOUL.md, and AGENTS.md as needed, "
        "then delete BOOTSTRAP.md after the ritual completes."
    )
    if not bootstrap_text:
        return base
    return (
        f"{base}\n\n"
        "BOOTSTRAP.md CONTENT:\n"
        "```markdown\n"
        f"{bootstrap_text}\n"
        "```\n\n"
        "Your next visible reply must greet the user and ask only the first bootstrap "
        "question. Do not summarize this file back to the user."
    )
