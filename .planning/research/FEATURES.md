# Features Research: Python App Onboarding UX

**Research Date:** 2026-02-27
**Dimension:** Features
**Source:** Real install failure (problems_faced.md) + open-source onboarding patterns

---

## Table Stakes
*(Must have or users give up and never come back)*

### Installation
- [ ] **No cryptic errors during pip install** — if a package fails, tell the user why and what to do
- [ ] **Works on all 3 target OSes** (Windows 11, macOS Apple Silicon, Ubuntu) with the same command
- [ ] **Clear prerequisite list** — README / onboarding script lists what must be installed first (Python, Git, Ollama, OpenClaw)
- [ ] **Single install command** — `pip install -r requirements.txt` must complete without manual intervention

### Runtime Startup
- [ ] **App starts without crashing** when optional services (Ollama) are not present
- [ ] **Tells user what's broken** — if a feature is unavailable, say so explicitly at startup
- [ ] **No encoding crash on Windows** — ASCII-safe print statements throughout

### Configuration
- [ ] **`.env` validation at startup** — detect empty/placeholder keys, name the affected feature
- [ ] **Clear `.env.example`** — every key documented with what it enables

---

## Differentiators
*(Better than 90% of open-source self-hosted Python projects)*

### Onboarding Scripts
- [ ] **OS-aware installer** — `synapse_onboard.sh` / `.bat` adapts behavior per platform
- [ ] **Dependency check before install** — detect if Python 3.11+, pip, git are present before attempting install
- [ ] **Post-install verification** — run a quick health check at the end of onboarding ("services started", "Gemini key valid")

### Runtime Messaging
- [ ] **Feature availability summary at startup** — one clear block showing what's ON vs OFF based on installed services and configured keys
- [ ] **Actionable fix messages** — "Ollama not found. Install from ollama.com, then restart." (not just a stack trace)

---

## Anti-Features
*(Things that look like improvements but add complexity without value for this project)*

| Feature | Why NOT to build it |
|---------|---------------------|
| Interactive setup wizard (ncurses/rich TUI) | High complexity, breaks in non-TTY environments |
| Auto-install missing packages at runtime | Surprises users, modifies their environment without consent |
| Docker / docker-compose setup | Heavy; target audience is non-technical friends, not DevOps |
| Version pinning enforcement | Breaks installs; let pip resolve; pin only what's known to conflict |
| Automatic .env file generation | Could overwrite real config; user must own their secrets |

---

## Feature Dependencies

```
ASCII-safe source code
    ↓ (prerequisite for)
App starts without crash on Windows
    ↓ (enables)
.env validation at startup
    ↓ (enables)
Feature availability summary
```

```
Platform-aware requirements.txt
    ↓ (prerequisite for)
pip install completes on Windows
    ↓ (enables)
Browser tool works on Windows
```

```
Optional Ollama import guard
    ↓ (prerequisite for)
App starts without Ollama
    ↓ (enables)
Feature availability messaging for Ollama
```

---

## Complexity Notes

| Feature | Complexity | Risk |
|---------|-----------|------|
| ASCII emoji replacement | Very low — grep + replace | Low |
| PEP 508 platform markers in requirements.txt | Low — one line change | Low |
| Optional Ollama import guard | Low — try/except pattern | Low (but test fallback path) |
| Playwright adapter for Windows | Medium — new module + abstraction | Medium (test on real Windows) |
| .env startup validator | Low — simple dict check | Low |
| Feature availability summary at startup | Low — print block in api_gateway.py | Low |
