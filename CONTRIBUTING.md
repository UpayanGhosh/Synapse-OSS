# Contributing to Synapse-OSS

Thanks for your interest in contributing! This document tells you everything you need to get started.

## Table of Contents

- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [How to Contribute](#how-to-contribute)
- [Good First Issues](#good-first-issues)
- [Pull Request Process](#pull-request-process)

---

## Quick Start

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/Synapse-OSS.git
cd Synapse-OSS

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install dev tools
pip install pytest pytest-asyncio pytest-timeout ruff black

# 5. Copy the example config
cp synapse.json.example ~/.synapse/synapse.json
# Edit it with your API keys

# 6. Run the tests to confirm your setup works
cd workspace
pytest tests/ -v -m "not performance"
```

You should see **300+ tests passing**. If something fails, open an issue and we'll help you debug it.

---

## Project Structure

```
workspace/
├── sci_fi_dashboard/
│   ├── api_gateway.py        # FastAPI app — all HTTP routes
│   ├── llm_router.py         # SynapseLLMRouter (litellm.Router wrapper)
│   ├── memory_engine.py      # Hybrid RAG orchestrator
│   ├── sqlite_graph.py       # Knowledge graph (SQLite)
│   ├── channels/             # Channel abstraction (WhatsApp/Telegram/Discord/Slack)
│   ├── gateway/              # Async pipeline (flood → dedup → queue → worker)
│   └── sbs/                  # Soul-Brain Sync persona engine
├── cli/                      # Onboarding wizard (typer + questionary)
├── tests/                    # All tests
├── synapse_config.py         # SynapseConfig dataclass (reads synapse.json)
└── main.py                   # CLI entry point
baileys-bridge/
└── index.js                  # Node.js WhatsApp bridge (Baileys)
```

---

## Running Tests

```bash
cd workspace

# Run all tests
pytest tests/ -v

# Skip slow performance tests (recommended during development)
pytest tests/ -v -m "not performance"

# Run a specific file
pytest tests/test_channels.py -v

# Run a specific test
pytest tests/test_queue.py::TestTaskQueue::test_enqueue -v

# Run by category
pytest tests/ -m unit
pytest tests/ -m integration
pytest tests/ -m smoke
```

> Tests that require live services (Ollama, Qdrant, WhatsApp bridge) are automatically
> skipped when those services are not running. No extra mocking setup required.

---

## Code Style

We use `ruff` for linting and `black` for formatting. Both run automatically in CI on every PR.

```bash
# Check for lint errors
ruff check workspace/

# Auto-fix lint errors
ruff check workspace/ --fix

# Format code
black workspace/

# Check formatting without changing files
black workspace/ --check
```

Config lives in `pyproject.toml`. Key settings: Python 3.11 target, line length 100.

---

## How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/UpayanGhosh/Synapse-OSS/issues) first.
2. Use the **Bug Report** template when opening a new issue.
3. Include: Python version, OS, steps to reproduce, expected vs actual behavior.

### Suggesting Features

1. Check [existing issues](https://github.com/UpayanGhosh/Synapse-OSS/issues) and [discussions](https://github.com/UpayanGhosh/Synapse-OSS/discussions).
2. Use the **Feature Request** template.
3. Explain the use case — what problem does this solve?

### Adding a New LLM Provider

The router is model-agnostic via `litellm`. To add a new provider:

1. Add the provider's API key entry to `synapse.json.example` under `providers`.
2. Add the env var mapping to `_KEY_MAP` in `workspace/sci_fi_dashboard/llm_router.py`.
3. Add a test in `workspace/tests/test_llm_router.py`.
4. Update `synapse.json.example` `model_mappings` with a sample role using the new provider.

### Adding a New Messaging Channel

1. Create `workspace/sci_fi_dashboard/channels/your_channel.py` implementing `BaseChannel`.
2. Register it in `workspace/sci_fi_dashboard/channels/__init__.py`.
3. Wire it into `api_gateway.py` inside the `lifespan()` context manager.
4. Add tests in `workspace/tests/test_your_channel.py`.
5. Document the required config keys in `synapse.json.example`.

---

## Good First Issues

Look for issues tagged [`good first issue`](https://github.com/UpayanGhosh/Synapse-OSS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
These are self-contained tasks that don't require deep codebase knowledge.

Typical areas:
- Adding a new litellm provider to `_KEY_MAP` and `synapse.json.example`
- Improving error messages in the onboarding wizard (`workspace/cli/`)
- Adding test coverage for an untested edge case
- Documentation improvements

---

## Pull Request Process

1. **Branch off `main`:**
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Write tests** for new behavior. PRs adding features without tests will be asked to add them.

3. **Run the full suite before pushing:**
   ```bash
   cd workspace && pytest tests/ -v -m "not performance"
   ruff check workspace/ && black workspace/ --check
   ```

4. **Open a PR** against `main` and fill in the PR template.

5. **CI must pass.** The GitHub Actions workflow runs lint + tests on every PR automatically.

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
Please be respectful and constructive in all interactions.

---

## Questions?

Open a [Discussion](https://github.com/UpayanGhosh/Synapse-OSS/discussions) — happy to help you get oriented.
