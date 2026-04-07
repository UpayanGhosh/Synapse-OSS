# Phase 4: Onboarding Wizard v2 - Research

**Researched:** 2026-04-07
**Domain:** Python CLI wizard, SBS profile initialization, parallel provider validation, entrypoint design
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ONBOARD2-01 | `python -m synapse setup` completes full setup in under 5 minutes for a fresh user | Phase 3 sub-agents for parallel provider validation; `python -m synapse` entrypoint needs `__main__.py` or `setup` subcommand added to `synapse_cli.py` |
| ONBOARD2-02 | Wizard builds initial SBS profile via targeted questions (communication style, interests, privacy preferences) | `ProfileManager.save_layer()` exists and works; wizard must map question answers to `linguistic`, `emotional_state`, `interaction` layers using the exact schema in `profile/manager.py` |
| ONBOARD2-03 | Wizard offers WhatsApp history import during setup — `python scripts/import_whatsapp.py` presented as option, not required | `scripts/import_whatsapp.py` exists, accepts `--file`, `--speaker`, `--hemisphere`, `--dry-run`; wizard just needs to offer and invoke it |
| ONBOARD2-04 | Wizard supports `--non-interactive` flag with env vars for headless/Docker/CI setups | `_run_non_interactive()` already handles this; v2 must extend it with SBS profile env vars and the `--verify` flag |
| ONBOARD2-05 | After wizard completion, `python -m synapse setup --verify` confirms all configured providers and channels respond correctly | `validate_provider()` and channel validators in `cli/provider_steps.py` and `cli/channel_steps.py` already exist; `--verify` is a new subcommand against existing config |
</phase_requirements>

---

## Summary

Phase 4 builds on a mature, well-tested onboarding wizard (`cli/onboard.py`, `cli/provider_steps.py`, `cli/channel_steps.py`, `cli/wizard_prompter.py`) that shipped in v1.0. The existing wizard handles provider and channel selection, API key validation, `synapse.json` writing, and `--non-interactive` mode — all with full test coverage in `tests/test_onboard.py`. The v2 upgrade adds three new capabilities on top: (1) an SBS persona-question section that seeds the `linguistic`, `emotional_state`, and `interaction` profile layers at setup time instead of leaving them as blank defaults; (2) a WhatsApp history import offer (invoke `scripts/import_whatsapp.py` optionally); and (3) a `--verify` flag that re-runs provider and channel validation against an existing `synapse.json`.

The entrypoint gap is that `python -m synapse setup` does not exist yet. The current CLI command is `synapse onboard` (via `synapse_cli.py`). The requirements call for `python -m synapse setup`, which requires either adding a `__main__.py` package to a `synapse/` module, or adding a `setup` command alias to `synapse_cli.py`. The path of least resistance given the project's architecture is to add a `setup` subcommand to `synapse_cli.py` that calls the same `run_wizard()` entry point, and to also add a `workspace/__main__.py` so that `python -m synapse` (from `workspace/`) dispatches to `synapse_cli:app`. The 5-minute timing constraint with live API validation is met by using Phase 3 sub-agents to validate multiple providers in parallel (currently validation is sequential).

The SBS profile schema is fully understood from `sbs/profile/manager.py`. The `ProfileManager.save_layer()` method is the correct write path. `core_identity` is immutable (write-protected by design); the wizard must only write to `linguistic`, `emotional_state`, `interaction`, and optionally `domain`. The layer schemas are simple JSON dictionaries with well-defined fields — mapping wizard answers is straightforward.

**Primary recommendation:** Extend `cli/onboard.py` with a new `_run_sbs_questions()` step that runs after provider/channel setup, maps answers to profile layers using `ProfileManager.save_layer()`, and then add a `setup` alias in `synapse_cli.py` plus `workspace/__main__.py` to satisfy the `python -m synapse setup` entrypoint.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `typer` | `>=0.24.0` | CLI app framework, subcommand dispatch | Already the CLI layer in `synapse_cli.py`; provides `typer.Option`, `typer.Exit` |
| `questionary` | `>=2.1.0` | Interactive terminal prompts (select, checkbox, text, password) | Already the prompt library; `QuestionaryPrompter` wraps it |
| `rich` | bundled via `typer[all]` | Console panels, tables, color output | Already used in `cli/onboard.py`; `_RICH_AVAILABLE` guard pattern already established |
| `httpx` | current | Sync HTTP calls for channel validation | Already used in `cli/channel_steps.py` |
| `litellm` | `>=1.82.0,<1.83.0` | Provider API validation calls | Already used in `cli/provider_steps.py`; `validate_provider()` calls `litellm.acompletion` |
| `filelock` | current | Thread-safe profile layer writes | Already used in `ProfileManager._write_json()` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` | stdlib | Parallel provider validation via Phase 3 sub-agents | For `--verify` and for parallel validation in `_run_non_interactive()` |
| `pytest` | current | Test framework | All new wizard tests follow `test_onboard.py` pattern |
| `typer.testing.CliRunner` | bundled | CLI test runner | Use for all `python -m synapse setup` test coverage |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `questionary` | `InquirerPy` | `InquirerPy` is already shimmed in `cli/inquirerpy_prompter.py` but `questionary` is the standard — stick with it |
| Extending `cli/onboard.py` | New `cli/setup_v2.py` | New file avoids merge conflicts but requires more wiring; extending `onboard.py` reuses all test infrastructure |
| `ProfileManager.save_layer()` direct writes | Writing profile JSON directly | `save_layer()` has file locking and guards; never bypass it |

**Installation:** No new dependencies needed — all required libraries are already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

The wizard v2 changes are incremental additions to existing files:

```
workspace/
├── __main__.py              # NEW: enables `python -m synapse setup`
├── synapse_cli.py           # MODIFY: add `setup` command alias + `--verify` flag
├── cli/
│   ├── onboard.py           # MODIFY: add _run_sbs_questions(), extend _run_non_interactive()
│   ├── sbs_profile_init.py  # NEW: SBSProfileInitializer — maps wizard answers to profile layers
│   └── verify_steps.py      # NEW: per-provider + per-channel verify logic (for --verify)
└── tests/
    └── test_onboard_v2.py   # NEW: covers ONBOARD2-01 through ONBOARD2-05
```

### Pattern 1: `python -m synapse setup` Entrypoint

**What:** `workspace/__main__.py` invokes `synapse_cli:app` so that `python -m synapse setup` works from the workspace directory. The `setup` command in `synapse_cli.py` is an alias for `onboard` — same `run_wizard()` under the hood.

**When to use:** Required by ONBOARD2-01; this is a standard Python packaging pattern.

**Example:**
```python
# workspace/__main__.py
from synapse_cli import app

if __name__ == "__main__":
    app()
```

```python
# In synapse_cli.py — add alongside the existing `onboard` command:
@app.command()
def setup(
    non_interactive: bool = typer.Option(False, "--non-interactive", ...),
    verify: bool = typer.Option(False, "--verify", help="Verify existing config"),
    accept_risk: bool = typer.Option(False, "--accept-risk", ...),
) -> None:
    """Setup Synapse — alias for onboard, the primary entry point for new users."""
    if verify:
        from cli.verify_steps import run_verify
        run_verify()
    else:
        from cli.onboard import run_wizard
        run_wizard(non_interactive=non_interactive, accept_risk=accept_risk)
```

### Pattern 2: SBS Persona Question Step

**What:** A new `_run_sbs_questions(prompter, data_root)` function in `cli/onboard.py` (or delegated to `cli/sbs_profile_init.py`) that presents 4 targeted questions and writes answers to the appropriate profile layers using `ProfileManager.save_layer()`.

**When to use:** Called at the end of `_run_interactive()`, after provider/channel setup and before the wizard outro.

**The 4 questions (maps to requirements spec):**

| Question | Profile Layer | Field |
|----------|--------------|-------|
| Preferred communication style (formal/casual/technical/creative) | `linguistic` | `current_style.preferred_style` (new field, same dict) |
| Topics of interest (multi-select: tech, music, wellness, etc.) | `domain` | `interests` (dict with keys as topics, value `1.0` seed weight) |
| Privacy sensitivity level (public/private/max-private) | `interaction` | `privacy_sensitivity` (new field) |
| Import WhatsApp history? (yes/no — offer the option) | triggers `scripts/import_whatsapp.py` | N/A — triggers subprocess |

**Example:**
```python
# cli/sbs_profile_init.py
from pathlib import Path
from sci_fi_dashboard.sbs.profile.manager import ProfileManager

STYLE_CHOICES = ["casual_and_witty", "formal_and_precise", "technical_depth", "creative_and_playful"]
INTEREST_CHOICES = ["technology", "music", "wellness", "finance", "science", "arts", "sports", "cooking"]
PRIVACY_CHOICES = ["open", "selective", "private"]

def initialize_sbs_from_wizard(answers: dict, data_root: Path) -> None:
    """Write wizard answers to SBS profile layers. Uses ProfileManager — never writes JSON directly."""
    from synapse_config import SynapseConfig
    config = SynapseConfig.load()
    mgr = ProfileManager(config.sbs_dir / "sbs_the_creator" / "profiles")

    # linguistic layer
    linguistic = mgr.load_layer("linguistic")
    linguistic["current_style"]["preferred_style"] = answers.get("communication_style", "casual_and_witty")
    mgr.save_layer("linguistic", linguistic)

    # domain layer
    domain = mgr.load_layer("domain")
    for topic in answers.get("interests", []):
        domain["interests"][topic] = 1.0
    mgr.save_layer("domain", domain)

    # interaction layer
    interaction = mgr.load_layer("interaction")
    interaction["privacy_sensitivity"] = answers.get("privacy_level", "selective")
    mgr.save_layer("interaction", interaction)
```

### Pattern 3: Parallel Provider Validation (`--verify`)

**What:** `cli/verify_steps.py` validates every provider and channel configured in the existing `synapse.json` using the existing validation functions, running provider checks in parallel via `asyncio.gather()`.

**When to use:** Called when `python -m synapse setup --verify` is invoked. Also usable for post-wizard confirmation.

**Example:**
```python
# cli/verify_steps.py
import asyncio
from synapse_config import SynapseConfig
from cli.provider_steps import validate_provider, validate_ollama
from cli.channel_steps import validate_telegram_token, validate_discord_token

async def _validate_provider_async(name: str, api_key: str):
    """Wrap sync validate_provider for asyncio.gather() parallel execution."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, validate_provider, name, api_key)
    return name, result

def run_verify(non_interactive: bool = False) -> int:
    """Verify all providers and channels. Returns 0 on all-pass, 1 on any failure."""
    config = SynapseConfig.load()
    providers = config.providers
    channels = config.channels

    # Parallel provider validation
    tasks = []
    for name, cfg in providers.items():
        if name == "ollama":
            # Ollama uses HTTP check, not litellm
            tasks.append(("ollama", cfg.get("api_base", "http://localhost:11434")))
        else:
            key = cfg.get("api_key", "")
            tasks.append((name, key))

    async def _run_all():
        coros = [_validate_provider_async(n, k) for n, k in tasks if n != "ollama"]
        return await asyncio.gather(*coros, return_exceptions=True)

    results = asyncio.run(_run_all())
    # ... print pass/fail table, return exit code
```

### Pattern 4: Non-Interactive SBS Profile Seeding

**What:** Extend `_run_non_interactive()` in `cli/onboard.py` to accept SBS profile env vars and call `initialize_sbs_from_wizard()`.

**Env vars for non-interactive SBS:**
```
SYNAPSE_COMMUNICATION_STYLE=casual_and_witty
SYNAPSE_INTERESTS=technology,music
SYNAPSE_PRIVACY_LEVEL=selective
```

These are optional in `--non-interactive` mode — if absent, the defaults from `ProfileManager._ensure_defaults()` remain.

### Anti-Patterns to Avoid

- **Writing profile layer JSON directly (bypassing ProfileManager):** `ProfileManager._write_json()` uses `filelock`. Bypassing it risks file corruption when the server is running during setup.
- **Writing to `core_identity` layer from wizard:** `save_layer("core_identity", ...)` raises `PermissionError` by design — never attempt it.
- **Running `validate_provider()` sequentially for multiple providers:** Each call makes a live API call. With 3+ providers, sequential validation adds 6–15 seconds. Use `asyncio.gather()` with `run_in_executor()` (validate_provider is sync).
- **Importing `SBSOrchestrator` in wizard:** The orchestrator starts file-watchers and background tasks. Use `ProfileManager` directly for one-shot initialization.
- **`--verify` making write calls:** Verify must be read-only. Never modify config during `--verify`.
- **Hardcoding `sbs_the_creator` profile path:** The profile path is computed via `SynapseConfig.sbs_dir`. Use `config.sbs_dir / "sbs_the_creator" / "profiles"` — never hardcode `~/.synapse/...`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Terminal prompts | Custom readline input() loop | `QuestionaryPrompter` (existing) | Already handles Ctrl+C cancellation, empty input, StubPrompter for tests |
| File-safe profile writes | `open(path, 'w')` directly | `ProfileManager.save_layer()` | Includes filelock, schema validation, guard against core_identity writes |
| Provider API validation | Custom HTTP validation per provider | `validate_provider()` in `provider_steps.py` | Handles RateLimitError (valid key) vs AuthenticationError (invalid), env restore, litellm quirks |
| Channel token validation | Custom httpx calls | `validate_telegram_token()`, `validate_discord_token()`, `validate_slack_tokens()` in `channel_steps.py` | Already handles 401, 403, connection errors |
| Config file write | `json.dump()` directly | `write_config(data_root, config)` from `synapse_config.py` | Atomic write via temp file + `os.replace()`, enforces mode 600 |
| Parallel validation | Threading or subprocess | `asyncio.gather()` + `run_in_executor()` | Phase 3 sub-agents or simple asyncio — same pattern used throughout |

**Key insight:** Almost all building blocks for Phase 4 already exist. This phase is about wiring and extending, not building from scratch. The risk of breaking existing ONB tests by modifying `cli/onboard.py` is real — additions must be additive, not replacing existing flows.

---

## Common Pitfalls

### Pitfall 1: SBS Profile Path Mismatch

**What goes wrong:** The wizard writes profile layers to the wrong path, so the live SBS engine (started via `api_gateway.py`) reads defaults instead of wizard answers.

**Why it happens:** `SBSOrchestrator` computes its profile path from `config.sbs_dir`, which resolves to `~/.synapse/workspace/sci_fi_dashboard/synapse_data`. Inside there are two SBS instances: `sbs_the_creator` and `sbs_the_partner`, each with their own `profiles/current/` subdirectory. The wizard must write to the same path.

**How to avoid:** Always compute the profile dir as `SynapseConfig.load().sbs_dir / "sbs_the_creator" / "profiles"`. Load `SynapseConfig` after `synapse.json` is written — not before.

**Warning signs:** Wizard completes, but `linguistic.json` shows `"preferred_style": null` when queried via API.

---

### Pitfall 2: `core_identity` Write Attempt

**What goes wrong:** Wizard tries to personalize the assistant name or relationship from questions, and calls `ProfileManager.save_layer("core_identity", ...)` — raises `PermissionError` at runtime.

**Why it happens:** `core_identity` is marked IMMUTABLE in `ProfileManager.save_layer()`. It is the only layer with a write guard.

**How to avoid:** The wizard's SBS questions must only target `linguistic`, `emotional_state`, `interaction`, and `domain`. If the user wants to name the assistant or set relationship type, those are future features or manual edits to `core_identity.json`.

**Warning signs:** `PermissionError: core_identity is IMMUTABLE. Manual edit only.` in wizard output.

---

### Pitfall 3: `python -m synapse setup` Not Found

**What goes wrong:** `python -m synapse setup` fails with `No module named synapse.__main__` or `synapse is not a package`.

**Why it happens:** `synapse` is not a Python package (no `synapse/__init__.py`). The CLI entry point is `synapse_cli:app` per `pyproject.toml`. `python -m synapse` requires either a `synapse/` package with `__main__.py` or running from the workspace directory as `python -m workspace.synapse_cli`.

**How to avoid:** Add `workspace/__main__.py` that calls `from synapse_cli import app; app()`. This makes `python -m workspace` work, but not `python -m synapse`. For `python -m synapse setup` to work as written, add a `setup` command to `synapse_cli.py` and document the invocation as `python synapse_cli.py setup` OR via the installed `synapse` script. Alternatively, add `workspace/synapse/__init__.py` + `workspace/synapse/__main__.py` and update the import path — this is a larger refactor.

**Recommendation:** The simplest path is to document `python -m synapse setup` as equivalent to the installed `synapse setup` command, and add `workspace/__main__.py` as a convenience entry point for local development.

**Warning signs:** The requirement says `python -m synapse setup` — verify what Python packaging allows given that `synapse` is a CLI script name in `pyproject.toml[project.scripts]`, not a module.

---

### Pitfall 4: Breaking Existing ONB Tests

**What goes wrong:** Modifying `cli/onboard.py` to add SBS questions changes the prompt sequence, breaking `StubPrompter` expectations in `test_onboard.py`.

**Why it happens:** `StubPrompter` raises `AssertionError` for any unexpected prompt message. Any new `prompter.text()`, `prompter.confirm()`, or `prompter.select()` call added to the wizard flow will fail every existing test that doesn't provide answers for the new prompts.

**How to avoid:** The new SBS questions step must be a separate function (`_run_sbs_questions()`) that can be patched out in existing tests with `patch("cli.onboard._run_sbs_questions")`. Existing `_run_interactive()` calls `_run_sbs_questions()` at the end; all existing tests patch it to a no-op.

**Warning signs:** `AssertionError: StubPrompter: unexpected prompt 'What is your preferred communication style?'` in existing test runs.

---

### Pitfall 5: `--verify` Modifying Config State

**What goes wrong:** `--verify` accidentally updates `synapse.json` (e.g., refreshing a token, updating a timestamp).

**Why it happens:** `validate_provider()` currently restores `os.environ` after calls but doesn't write to config. Risk is if `--verify` calls any code path that writes config.

**How to avoid:** `run_verify()` must be purely read-only. Load config via `SynapseConfig.load()`, validate, report — never call `write_config()`.

---

### Pitfall 6: 5-Minute Timing Target with Live Validation

**What goes wrong:** Fresh install with 3 providers (Gemini, Anthropic, Groq) + Telegram takes 90s sequential validation — exceeds 5-minute target when combined with WhatsApp QR scan (~60s).

**Why it happens:** Current `validate_provider()` is synchronous and sequential.

**How to avoid:** Use `asyncio.gather()` + `loop.run_in_executor()` to validate all configured providers in parallel. For the `--verify` flag and non-interactive mode, this is a requirement. WhatsApp QR scan is inherently sequential (user interaction) but providers/channels without QR can be parallelized.

---

## Code Examples

Verified patterns from existing codebase:

### ProfileManager Layer Write (HIGH confidence — from `sbs/profile/manager.py`)

```python
from sci_fi_dashboard.sbs.profile.manager import ProfileManager
from pathlib import Path

mgr = ProfileManager(Path("~/.synapse/workspace/sci_fi_dashboard/synapse_data/sbs_the_creator/profiles"))

# Load → modify → save pattern (the only correct write pattern)
domain = mgr.load_layer("domain")
domain["interests"]["technology"] = 1.0
domain["interests"]["music"] = 0.8
mgr.save_layer("domain", domain)  # filelock + atomicity handled internally

# What layers can be written:
# linguistic, emotional_state, domain, interaction, vocabulary, exemplars, meta
# NEVER: core_identity (raises PermissionError)
```

### Parallel Provider Validation (Pattern — from `cli/provider_steps.py` + asyncio)

```python
import asyncio
from cli.provider_steps import validate_provider

async def validate_all_providers(providers: dict) -> dict:
    loop = asyncio.get_event_loop()
    async def _validate_one(name, key):
        result = await loop.run_in_executor(None, validate_provider, name, key)
        return name, result
    results = await asyncio.gather(*[
        _validate_one(n, cfg["api_key"])
        for n, cfg in providers.items()
        if n not in ("ollama", "github_copilot")
    ], return_exceptions=True)
    return dict(results)
```

### WizardPrompter SBS Questions Pattern (safe for testing)

```python
# In _run_interactive() — after channel setup, before outro:
def _run_sbs_questions(prompter, data_root: Path) -> None:
    """Collect persona-seeding answers and write to SBS profile layers."""
    style = prompter.select(
        "How should Synapse communicate with you by default?",
        choices=["Casual and witty", "Formal and precise", "Technical depth first", "Creative and playful"],
        default="Casual and witty",
    )
    interests = prompter.multiselect(
        "What topics are you most interested in? (optional — skip to set later)",
        choices=["Technology", "Music", "Wellness", "Finance", "Science", "Arts", "Sports", "Cooking"],
    )
    privacy = prompter.select(
        "How sensitive are you about personal data in conversations?",
        choices=["Open — store freely", "Selective — use judgment", "Private — minimal storage"],
        default="Selective — use judgment",
    )
    from cli.sbs_profile_init import initialize_sbs_from_wizard
    initialize_sbs_from_wizard(
        {"communication_style": style, "interests": interests, "privacy_level": privacy},
        data_root=data_root,
    )
```

### WhatsApp History Import Offer Pattern

```python
# In _run_interactive() — after SBS questions:
if prompter.confirm("Would you like to import existing WhatsApp chat history to seed your memory?", default=False):
    wa_file = prompter.text("Path to your WhatsApp export (.txt file)", default="")
    if wa_file:
        import subprocess, sys  # noqa: E401
        subprocess.run([sys.executable, "scripts/import_whatsapp.py", wa_file, "--hemisphere", "safe"], check=False)
```

### Non-Interactive SBS Env Vars Extension

```python
# In _run_non_interactive() — after writing synapse.json, before exit:
communication_style = os.environ.get("SYNAPSE_COMMUNICATION_STYLE", "")
interests_raw = os.environ.get("SYNAPSE_INTERESTS", "")
privacy_level = os.environ.get("SYNAPSE_PRIVACY_LEVEL", "")

if any([communication_style, interests_raw, privacy_level]):
    from cli.sbs_profile_init import initialize_sbs_from_wizard
    initialize_sbs_from_wizard(
        {
            "communication_style": communication_style or "casual_and_witty",
            "interests": [i.strip() for i in interests_raw.split(",") if i.strip()],
            "privacy_level": privacy_level or "selective",
        },
        data_root=data_root,
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sequential provider validation | Parallel via `asyncio.gather()` | Phase 4 (this phase) | Reduces validation time from ~(N*3s) to ~3s for N providers |
| Blank SBS profile defaults at startup | Wizard-seeded profile baseline | Phase 4 (this phase) | Users have meaningful persona data from day 1, not after 50 messages |
| `synapse onboard` only | `synapse setup` + `python -m synapse setup` | Phase 4 (this phase) | Standard entry point matching docs and README |
| No post-install verification | `synapse setup --verify` | Phase 4 (this phase) | Users can confirm config is working without debugging |

**Existing (intact after Phase 4):**
- `synapse onboard`: existing command stays, test coverage stays intact
- `ONB-01` through `ONB-16`: all existing tests remain passing
- `write_config()` atomic write with mode 600: unchanged
- `ProfileManager._ensure_defaults()`: called at `__init__` — still initializes all default fields before wizard overwrites specific ones

---

## Open Questions

1. **`python -m synapse setup` vs `synapse setup` entrypoint**
   - What we know: `synapse` is a CLI script entry point in `pyproject.toml[project.scripts]`. There is no `synapse/` Python package.
   - What's unclear: The ROADMAP.md says `python -m synapse setup` — this notation implies `synapse` is an importable module. In a pip-installed context, `synapse setup` (from the script) is the correct way to invoke this. `python -m synapse` only works if there is a `synapse/` package with `__main__.py`.
   - Recommendation: Plan 04-01 must decide: (a) rename `synapse_cli.py` to `synapse/__init__.py` + `synapse/__main__.py` (package refactor), OR (b) add `workspace/__main__.py` as a convenience alias and document `synapse setup` as the canonical command. Option (b) is lower risk. The requirement text should be read as "the command a user runs to set up Synapse" not literally `python -m synapse setup`.

2. **SBS profile path for `sbs_the_partner` during wizard**
   - What we know: Two SBS instances run: `sbs_the_creator` and `sbs_the_partner`. Each has its own profile directory.
   - What's unclear: Should the wizard seed only `sbs_the_creator`? Or both? The requirements say "initial SBS profile" — singular.
   - Recommendation: Seed only `sbs_the_creator` (the primary user persona). `sbs_the_partner` is intentionally different. Add a note for the user that the partner persona is separate.

3. **Phase 3 sub-agents for parallel validation — required or optional?**
   - What we know: The ROADMAP says "wizard can use sub-agents for parallel provider validation". Phase 3 adds `AgentRegistry` and sub-agent spawning.
   - What's unclear: If Phase 4 executes before Phase 3 is complete, parallel validation needs a simpler approach (`asyncio.gather()` + `run_in_executor()`).
   - Recommendation: Use `asyncio.gather()` directly in `run_verify()` for Phase 4. Sub-agent integration can be a Phase 4.1 refinement after Phase 3 ships. This decouples the phases and meets the 5-minute target independently.

---

## Validation Architecture

`workflow.nyquist_validation` is not set in `.planning/config.json` (absent = false). Skipping this section per instructions.

---

## Sources

### Primary (HIGH confidence)

- `workspace/cli/onboard.py` — Existing wizard orchestration; `run_wizard()`, `_run_non_interactive()`, `_run_interactive()` signatures
- `workspace/cli/provider_steps.py` — `validate_provider()`, `ValidationResult`, `VALIDATION_MODELS`, `_KEY_MAP`
- `workspace/cli/channel_steps.py` — `validate_telegram_token()`, `validate_discord_token()`, `validate_slack_tokens()`, `CHANNEL_LIST`
- `workspace/cli/wizard_prompter.py` — `WizardPrompter` protocol, `QuestionaryPrompter`, `StubPrompter`
- `workspace/sci_fi_dashboard/sbs/profile/manager.py` — `ProfileManager`, layer schema, `save_layer()` write guard
- `workspace/synapse_cli.py` — CLI entry point, existing `onboard` command shape
- `workspace/synapse_config.py` — `SynapseConfig.load()`, `write_config()`, `resolve_data_root()`
- `workspace/scripts/import_whatsapp.py` — WhatsApp history importer CLI interface
- `workspace/tests/test_onboard.py` — Existing test coverage (ONB-01 through ONB-16)
- `workspace/tests/pytest.ini` — Test framework config: pytest + asyncio-mode=auto
- `pyproject.toml` — Dependencies: typer, questionary, rich (bundled), litellm, httpx; Python 3.11

### Secondary (MEDIUM confidence)

- `.planning/ROADMAP.md` — Phase 4 success criteria and plan breakdown (authoritative for this project)
- `.planning/REQUIREMENTS.md` — ONBOARD2-01 through ONBOARD2-05 definitions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use and versioned in pyproject.toml
- Architecture patterns: HIGH — existing wizard architecture fully inspected; all patterns verified from source
- Pitfalls: HIGH — all pitfalls derived from reading actual implementation code, not assumptions
- SBS profile schema: HIGH — read directly from `ProfileManager` source including all layer field names

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable internal codebase; dependencies are pinned)
