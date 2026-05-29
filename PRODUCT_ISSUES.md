# Synapse-OSS — Product Issues Tracker

Generated 2026-05-03 from a code-grounded product review. Use this as a fix-one-by-one tracker.

Each item follows the same structure:
- **Problem** — what is actually wrong, with evidence
- **Impact** — why it costs you adoption, credibility, or stability
- **Solution** — concrete approach with example code/config where useful
- **Done when** — acceptance criteria you can check yourself

Severity legend: **P0** = blocks adoption / credibility. **P1** = real user pain. **P2** = quality / polish.

---

## Progress (2026-05-03 batch)

A 28-agent parallel batch shipped fixes for all 30 confident + partial items flagged in this tracker. The 4 items that genuinely require local execution (2.3 hosted demo, 3.1 `llm_router` split, 3.2 `synapse_config` refactor, 6.1 reranker eval) were intentionally not attempted.

**Status legend:**
- ✅ **Shipped** — code/docs landed on this branch, statically reviewable
- ⚠️ **Needs runtime verification** — code shipped but you must run/build/deploy to confirm
- 🟡 **Partial** — only one tier of a multi-tier fix landed (deeper fix deferred)

| Issue | Status | What landed | What you still need to do |
|---|---|---|---|
| 1.1 README stale metrics | ✅ | `scripts/collect_metrics.sh`, `scripts/render_readme.py`, `.github/workflows/metrics.yml`, `docs/_generated/metrics.json` (seed: 800/228/556), README rewritten with `<!--METRIC:*-->` placeholders | Push to `main` and verify the bot push succeeds (workflow has `contents:write`; if branch protection blocks bot pushes, swap to a PR-creation step) |
| 1.2 ARCHITECTURE.md routes | ✅ | New "API Gateway: orchestrator + routes/ package" section + 12-row routes table; multiuser link added | — |
| 1.3 CLAUDE.md stale bug warning | ✅ | Warning paragraph deleted (verified bug fixed at `tools_server.py:141, 159, 161`); `workspace/tests/test_mcp_tools_smoke.py` pins the contract; 4 `cd workspace` patterns in CLAUDE.md converted to subshell form | — |
| 1.4 HOW_TO_RUN Ollama callout | ✅ | Architecture callout, "Why Ollama is required", and "1.3 — Ollama (Required)" subsection rewritten. **Issue spec was wrong** about the cascade — actual is FastEmbed→Gemini→`RuntimeError`, not "FTS fallback". Agent corrected to say the gateway raises and won't ingest until one provider is installed | — |
| 1.5 Multiuser undocumented | ✅ | `docs/multiuser.md` with all 9 modules documented against actual code (richer than spec wording — e.g. `session_store.py` has 3-layer locking + watchdog, not just atomic JSON) | — |
| 1.6 Naming sprawl | ✅ | `api_gateway.py:95` banner: `[Synapse] Booting gateway...`; module docstring header updated; `CONTRIBUTING.md` "Naming and identifiers" section. Real `antigravity_*` symbols (Google CodeAssist provider) left intact — they reference an external product | Full `sci_fi_dashboard` → `synapse` package rename intentionally deferred |
| 2.1 One-command demo | ⚠️ | `docker-compose.demo.yml`, `synapse.demo.json`, `docs/demo-profile.md`. Also: `.gitignore` whitelist for `synapse.demo.json` (existing `*.json` rule was masking it) | `docker compose -f docker-compose.demo.yml up` and confirm playground reachable |
| 2.2 Web UI playground | ⚠️ | `routes/playground.py` + `static/playground.html` (single-file, no build step). WS protocol matched against `ws_server.py:155-162` (auth via `params.auth.token`). `api_gateway.py` wired the include after the existing routers | Start gateway, open `http://localhost:8000/`, confirm chat round-trips and the profile side panel populates after a few messages |
| 2.4 .env.example overload | ✅ | New `.env.example` (696 B / 18 lines) + `.env.example.advanced` (4599 B, full 12-provider reference preserved verbatim) | — |
| 2.5 No-cloud profile | ✅ | `synapse.local-only.json` (7 roles on Ollama, FastEmbed, dual-cog timeout 10s) + `docs/local-only-benchmark.md` (methodology stub, explicitly placeholder) | Run the benchmark when you have an Ollama host (issue 6.1 territory) |
| 3.3 Legacy api_gateway handles | ✅ | Legacy block deleted. Verified across `workspace/tests/`, `sci_fi_dashboard/`, `scripts/`: **no importer of `channel_registry` or `WhatsAppChannel` from api_gateway** — clean removal | — |
| 3.4 CWD-shifting bash | ✅ | Shell scripts at the repo root inspected: **none had `cd workspace` patterns** (already migrated to delegate to the `synapse` CLI). Doc fixes shipped via 1.3 (CLAUDE.md ×4), HOW_TO_RUN (×3), README (×2) | — |
| 4.1 Hemisphere isolation | 🟡 | **Tier 1 only** — `workspace/tests/test_hemisphere_isolation.py`: 102 test invocations (50 + 50 fuzz parametrized + 2 behavioral pins), uses real `LanceDBVectorStore` on tmp_path, mocks reranker to deterministic fallback so the SQL prefilter is actually exercised | **Tier 2 (physical DB split into `memory_safe.db` / `memory_spicy.db`) intentionally deferred** — too risky without integration testing |
| 4.2 SECURITY.md | ✅ | Created with full vuln-disclosure policy, GitHub handle verified via `git remote -v` | Replace `security@<your-domain>` placeholder before public release |
| 4.3 SBOM/signed releases | ⚠️ | `.github/workflows/release.yml` ships keyless OIDC cosign signing + CycloneDX SBOM upload | Push a `v*` tag to verify cosign + sbom-action both work in your runner |
| 5.1 SBS profile read | ⚠️ | `GET /persona/profile/{user}` added to `routes/persona.py`. Resolves via `deps.sbs_registry[user]` (real layout — registry of `SBSOrchestrator`s, not separate `sbs_the_creator`/`sbs_the_partner` attributes). Auth: `_require_gateway_auth` matches existing pattern | Run gateway, `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/persona/profile/the_creator` |
| 5.2 SBS profile patch | ⚠️ | `PATCH /persona/profile/{user}/{layer}`. Audit trail: appends to `meta.overrides` (capped 200). `core_identity` rejected with 403 (clearer than letting `save_layer` raise `PermissionError`). Non-dict payloads rejected with 400 | Same — exercise the endpoint and confirm overrides survive a restart |
| 5.3 Memory inspector | ⚠️ | `GET /memory/list` (paginated, hemisphere-filtered, optional `q` substring) + `DELETE /memory/{doc_id}` with **full cascade**: `documents` + `documents_fts` + `vec_items` (sqlite-vec) + `entity_links` + LanceDB. Required additive methods on `MemoryEngine`, `VectorStore` base, and `LanceDBVectorStore` | Run gateway and exercise both endpoints. Note: `user` query param is accepted but not SQL-filtered (no per-user column in `documents` schema today — flagged in code) |
| 6.2 KG limits doc | ✅ | `docs/kg-limits.md` with verified schema (`nodes(name, type, properties, created_at, updated_at)`, `edges(source, target, relation, weight, evidence, created_at)`, indexes, WAL pragma); operational claims (vacuum 30m, prune 10m, `weight<0.1` threshold) verified against `gentle_worker.py`; `sqlite_graph.py` docstring linked | — |
| 6.3 Load tests | ⚠️ | `workspace/tests/load/` with 3 tests (burst 500 / dedup 1000 / floodgate 100msg/s × 5s) + `BurstHarness` conftest mirroring the production wire-up. `load` and `slow` markers registered in `workspace/tests/pytest.ini`; opt-in via `--run-slow` so default `pytest` stays fast | `( cd workspace && pytest -m load --run-slow -v )` |
| 6.4 SBS-drift test | ⚠️ | `workspace/tests/test_sbs_drift.py` — 9 functions, 16 collected cases (parametrized over 8 layers). **No LLM stub needed** — agent verified the SBS distillation path is purely deterministic regex+SQL+word-counting. Used `random.seed(0xC0FFEE)` for ExemplarSelector | `( cd workspace && pytest tests/test_sbs_drift.py -v )` |
| 7.1 SQLite ceiling docs | ✅ | "Scaling notes" section in HOW_TO_RUN.md + "Project state" line in README.md disclosing single-user-per-instance + Postgres-on-roadmap | — |
| 7.2 Deploy automation | ⚠️ | `Dockerfile` (non-root uid 10001, healthcheck on `/health` — verified path), `deploy/synapse.service` (systemd hardening), `deploy/README.md`. **3 corrections from spec**: dropped `COPY synapse_config.py` (lives in `workspace/`); CMD uses `sci_fi_dashboard.api_gateway:app` not `workspace.sci_fi_dashboard...` (would `ModuleNotFoundError`); volume `/home/synapse/.synapse` to match non-root uid | `docker build -t synapse:latest .` and a smoke-run |
| 7.3 GOVERNANCE.md | ✅ | Solo-maintenance disclosed; co-maintainer bar (≥5 PRs over 3+ months); SemVer; cross-links to SECURITY/CODE_OF_CONDUCT verified to exist | — |
| 8.1 Untracked HTML | ✅ | `.gitignore` appended `interview-prep.html` + `content/generated/`. **Flagged for follow-up:** existing `*.json` block has a `!workspace/sci_fi_dashboard/entities.json` whitelist exception that contradicts CLAUDE.md's "ships as empty `{}` placeholder" — could let real data slip in | Decide whether to remove the `entities.json` whitelist exception |
| 8.2 CLAUDE.md.original | ✅ | `git mv CLAUDE.md.original docs/archive/CLAUDE.md.pre-rewrite.md` + archive header note + `docs/archive/README.md` | — |
| 8.3 .cursorrules drift | ✅ | `.github/workflows/lint-editor-rules.yml` (parity check on PR + push); `<!-- ... -->` parity-notice header added to **both** files (markdown comment, not `#` since these are markdown). Both files still byte-identical (1921 B each) | — |
| 8.4 Ad-hoc test scripts | ✅ | Moved: `test_pruning.py`, `test_sbs.py` (renamed → `test_sbs_orchestrator_smoke.py` to avoid collision), `test_ui.py` → `workspace/tests/`; `verify_dual_cognition.py`, `verify_soul.py` → `scripts/verify/`. Imports rewritten to absolute. `.planning/codebase/STRUCTURE.md` stale lines removed. **Pre-existing finding:** `verify_soul.py` imports `sci_fi_dashboard.knowledge_graph` which no longer exists (left as-is — broken before the move) | Decide whether to fix or delete `verify_soul.py` |
| 9.1 Comparison table | ✅ | Mem0 / MemGPT / Pieces / ChatGPT row added inside the new top-of-README structure | — |
| 9.2 README reorg | ✅ | 43,655 B → 27,016 B (689 lines). Vision content **fully preserved** under `## Vision` (H2s downgraded to H3/H4 to nest). New top: pitch → 60-second Docker path → "What it actually does" → comparison → Install → Architecture → Project state | — |

**Counts:** 20 ✅ shipped · 9 ⚠️ needs runtime verification · 1 🟡 partial · 0 ❌ skipped (within the 30-item scope)

**Out of scope of this batch (still need work):**
- **2.3 Public hosted demo** — needs a real Fly.io/Railway deploy
- **3.1 `llm_router.py` split (2,579 lines)** — refactor of this size needs the test suite running to verify routing semantics didn't shift
- **3.2 `synapse_config.py` → frozen pydantic model** — 50+ importers, can't validate by reading
- **6.1 Reranker eval** — by definition needs a benchmark run with real embeddings

---

## 1. Documentation drift  *(P0)*

The single largest credibility risk. Multiple docs describe a system that no longer exists.

---

### 1.1 README has stale metrics  *(P0)*

**Problem.** README's "Before / After Phoenix v3" table claims `302 tests across 24 files`. Actual count today: **800 test functions across 228 test files** (`grep -rh "^def test_\|^async def test_" workspace/tests/ | wc -l` and `find workspace/tests -name 'test_*.py' | wc -l`). Other figures in the same table (RAM percentages, retrieval latency P95, vocabulary count) have not been re-measured against the current code path.

**Impact.** A technical reader who runs the same one-liner I ran will see the discrepancy in 30 seconds and assume the rest of the README is fiction. Stale numbers are worse than missing numbers.

**Solution.** Generate the metrics in CI rather than hand-editing them.

Example — a tiny script that emits a JSON fragment, plus a README placeholder that gets substituted:

```bash
# scripts/collect_metrics.sh
#!/usr/bin/env bash
set -euo pipefail
TESTS=$(grep -rh "^def test_\|^async def test_" workspace/tests/ | wc -l | tr -d ' ')
FILES=$(find workspace/tests -name "test_*.py" | wc -l | tr -d ' ')
PY_FILES=$(find workspace -name "*.py" | wc -l | tr -d ' ')
cat > docs/_generated/metrics.json <<EOF
{"tests": $TESTS, "test_files": $FILES, "py_files": $PY_FILES, "generated_at": "$(date -u +%FT%TZ)"}
EOF
```

Then in CI:

```yaml
# .github/workflows/metrics.yml
- run: bash scripts/collect_metrics.sh
- run: python scripts/render_readme.py  # substitutes <!--METRIC:tests--> placeholders
- run: |
    if ! git diff --quiet README.md; then
      git config user.email "ci@synapse"; git config user.name "ci"
      git add README.md docs/_generated/metrics.json
      git commit -m "chore: refresh README metrics" && git push
    fi
```

**Done when.** Every numeric claim in README is either `<!--METRIC:name-->` substituted by CI, or removed. A `git blame` on README never shows a human editing a number.

---

### 1.2 ARCHITECTURE.md predates the routes refactor  *(P0)*

**Problem.** `api_gateway.py` is now a 602-line orchestrator that imports from a `routes/` package (`chat`, `agents`, `cron`, `health`, `knowledge`, `persona`, `sessions`, `skills`, `snapshots`, `websocket`, `whatsapp`). `ARCHITECTURE.md` and `CLAUDE.md`'s "Request Flow" diagram still describe the gateway as if all logic lives in `api_gateway.py`.

**Impact.** A new contributor reads ARCHITECTURE.md, opens `api_gateway.py` to find the chat endpoint, doesn't see it (it's in `routes/chat.py`), and wastes 20 minutes orienting.

**Solution.** Replace the prose flow diagram with a generated module map, and add a one-liner per route module.

Example block to add to ARCHITECTURE.md:

```markdown
## Route modules (FastAPI APIRouter)
| File | Path prefix | Purpose |
|---|---|---|
| `routes/chat.py` | `/chat`, `/chat/{user}` | Async webhook + sync persona chat |
| `routes/agents.py` | `/agents` | Subagent spawn / progress |
| `routes/cron.py` | `/cron` | Schedule + run-log endpoints |
| `routes/health.py` | `/healthz`, `/memory_health` | Liveness + ingestion telemetry |
| `routes/knowledge.py` | `/knowledge` | Memory inspect, KG queries |
| `routes/persona.py` | `/persona` | SBS profile read/write |
| `routes/sessions.py` | `/sessions` | List / reset / archive |
| `routes/skills.py` | `/skills` | Skill registry |
| `routes/snapshots.py` | `/snapshots` | Memory snapshot lifecycle |
| `routes/websocket.py` | `/ws` | WebSocket gateway |
| `routes/whatsapp.py` | `/whatsapp/*` | Bridge webhook surface |
```

**Done when.** ARCHITECTURE.md table matches `ls workspace/sci_fi_dashboard/routes/*.py`, and a CI check fails if the lists diverge.

---

### 1.3 CLAUDE.md warns about a bug that no longer exists  *(P0)*

**Problem.** CLAUDE.md says:

> **Known bug in `tools_server.py`**: `read_file`/`write_file` call `Sentinel().agent_read_file()` which is incorrect — `agent_read_file` is a module-level function in `sbs/sentinel/tools.py`, not a method on `Sentinel`.

The actual code in `mcp_servers/tools_server.py` is correct:

```python
# read_file branch
from sbs.sentinel.tools import _sentinel
resolved = _sentinel.check_access(arguments["path"], "read", "mcp read_file")
result = read_file_paged(str(resolved), ...)

# write_file branch
from sbs.sentinel.tools import agent_write_file
result = agent_write_file(arguments["path"], arguments["content"])
```

No `Sentinel().agent_read_file()` call exists anywhere in the file.

**Impact.** Agents (including future Claude sessions) skip valid functionality assuming it's broken. False warnings train readers to ignore real warnings.

**Solution.** Delete the warning paragraph from CLAUDE.md. If you want a "verified" tag in the codebase, add a tiny smoke test:

```python
# workspace/tests/test_mcp_tools_smoke.py
def test_tools_server_read_write_paths_exist():
    """Pin the contract: tools_server uses module-level funcs, not Sentinel methods."""
    src = Path("workspace/sci_fi_dashboard/mcp_servers/tools_server.py").read_text()
    assert "Sentinel().agent_read_file" not in src
    assert "_sentinel.check_access" in src
    assert "agent_write_file" in src
```

**Done when.** CLAUDE.md no longer mentions the bug; a pinning test is in `workspace/tests/`.

---

### 1.4 HOW_TO_RUN.md's "Ollama is REQUIRED" callout is wrong  *(P0)*

**Problem.** HOW_TO_RUN.md says:

> Why Ollama is required: Every message you send and every fact Synapse learns is converted into a 768-dimensional embedding vector using Ollama's `nomic-embed-text` model.

But `embedding/factory.py` cascades `FastEmbed (local ONNX) → Gemini API → fail`. Ollama isn't even in the cascade. FastEmbed needs no external service; Gemini needs only an API key.

**Impact.** New users install Ollama for nothing, doubling perceived setup cost and turning a 5-minute path into a 20-minute one.

**Solution.** Rewrite the callout against the actual code:

```markdown
## How embeddings work

Synapse picks an embedding provider in this order:
1. **FastEmbed** (default) — local ONNX, no external service, ~150 MB on first run.
2. **Gemini API** — fallback if FastEmbed isn't installed and `GEMINI_API_KEY` is set.

If neither is available, semantic search degrades to FTS-only and a warning is logged.
You do not need Ollama for embeddings. (Ollama is only used if you point a chat
role at a local model, e.g. `vault` for private conversations.)
```

**Done when.** HOW_TO_RUN.md no longer claims Ollama is required for memory. Quick Start verified on a clean machine with `pip install -r requirements.txt` + `GEMINI_API_KEY` and nothing else.

---

### 1.5 Multiuser layer is undocumented  *(P1)*

**Problem.** `workspace/sci_fi_dashboard/multiuser/` ships `compaction.py`, `context_assembler.py`, `conversation_cache.py`, `identity_linker.py`, `memory_manager.py`, `session_key.py`, `session_store.py`, `tool_loop_detector.py`, `transcript.py`. Zero narrative documentation. The directory isn't mentioned in README, ARCHITECTURE, or CLAUDE.md.

**Impact.** A real subsystem is invisible. Outside contributors can't extend it; reviewers can't reason about it.

**Solution.** Add `docs/multiuser.md` with a one-paragraph purpose per module and a request-flow snippet:

```markdown
# Multiuser

Synapse was built single-user; this layer adds per-user keying without forking the data layer.

| Module | Responsibility |
|---|---|
| `session_key.py` | Compute `session_id` from `dmScope` policy (`main` / `per-peer` / `per-channel-peer` / `per-account-channel-peer`). |
| `identity_linker.py` | Maps raw peer IDs (Telegram chat_id, WhatsApp jid) to a canonical user. Backed by `synapse.json → session.identityLinks`. |
| `session_store.py` | SQLite store of active sessions; reads/writes `SessionEntry` rows. |
| `context_assembler.py` | Builds the per-user persona + memory window for `persona_chat()`. |
| `memory_manager.py` | Per-user hemisphere selection + write isolation. |
| `compaction.py` | Trims long transcripts before LLM call (token-budget aware). |
| `conversation_cache.py` | LRU of recent turns to skip re-reading SQLite each turn. |
| `tool_loop_detector.py` | Breaks runaway tool-call loops in subagent runs. |
| `transcript.py` | Canonical transcript serializer used by both ingestion and compaction. |
```

**Done when.** `docs/multiuser.md` exists, is linked from ARCHITECTURE.md and README, and each module's docstring matches its row in the table.

---

### 1.6 Naming sprawl: `Synapse` vs `Antigravity Gateway` vs `sci_fi_dashboard`  *(P1)*

**Problem.** Three names for one thing:
- Product / repo: `Synapse`
- Python package: `sci_fi_dashboard`
- Runtime banner: `print("[MEM] Booting Antigravity Gateway v2...")` (`api_gateway.py:99`)

**Impact.** Confusing for newcomers; ugly in logs; fragile because someone will eventually rename one and forget the others.

**Solution.** Pick one canonical name (`synapse`). The package rename is the heavy lift — do it carefully or defer. The cheap wins are immediate:

```python
# api_gateway.py
- print("[MEM] Booting Antigravity Gateway v2...")
+ print("[Synapse] Booting gateway...")
```

For the package rename (deferred path), document the legacy alias in CONTRIBUTING.md and provide a thin shim:

```python
# workspace/synapse/__init__.py  (new canonical package)
from sci_fi_dashboard import *  # noqa: F401, F403  -- legacy alias, do not import from sci_fi_dashboard in new code
```

**Done when.** Logs show one name. CONTRIBUTING.md states which name is canonical and which are legacy.

---

## 2. Onboarding friction  *(P0)*

The biggest reason a fresh visitor doesn't become a user.

---

### 2.1 No one-command demo path  *(P0)*

**Problem.** Today's flow: install Python 3.11, install Node, install Ollama, pull `nomic-embed-text` (~900 MB — and unnecessary, see 1.4), get a cloud API key, edit `synapse.json`, optionally pair WhatsApp, seed persona. Even on a fast machine: 30+ minutes.

**Impact.** Most evaluators bounce before message #1. The product's strongest moment (SBS continuity) is downstream of an installation cliff.

**Solution.** Ship a `docker compose` profile that gets to a working CLI chat in <5 minutes with zero cloud keys.

Example minimal compose:

```yaml
# docker-compose.demo.yml
services:
  synapse:
    build: .
    image: synapse:demo
    ports: ["8000:8000"]
    environment:
      - SYNAPSE_PROFILE=demo
      - SYNAPSE_EMBEDDING_PROVIDER=fastembed
      - SYNAPSE_LLM_PROFILE=demo_local
    volumes:
      - synapse-data:/root/.synapse
volumes:
  synapse-data:
```

```jsonc
// synapse.demo.json — checked in, uses fastembed + a small free-tier model
{
  "embedding": { "provider": "fastembed" },
  "model_mappings": {
    "casual": { "model": "openrouter/google/gemini-2.0-flash-exp:free" },
    "traffic_cop": { "model": "openrouter/google/gemini-2.0-flash-exp:free" }
  },
  "session": { "dual_cognition_enabled": false }
}
```

Add a one-liner to README:

```bash
docker compose -f docker-compose.demo.yml up
# then:
docker exec -it synapse-synapse-1 python -m workspace.main chat
```

**Done when.** Fresh clone → `docker compose -f docker-compose.demo.yml up` → working chat in <5 minutes on a machine with no Python, no Node, no Ollama.

---

### 2.2 No web UI / browser playground  *(P0)*

**Problem.** The only "use Synapse" surfaces are CLI, WhatsApp, Telegram, Discord, Slack. There is no `http://localhost:8000/` chat page. A user cannot try the product from a browser without pairing a chat account.

**Impact.** The fastest possible "feel the product" loop doesn't exist. WhatsApp pairing in particular takes 5+ minutes and requires a real phone — that's the *demo*.

**Solution.** Ship a single-file HTML chat page served by FastAPI. No build pipeline, no React. Stream tokens via SSE or the existing `/ws` endpoint.

Example:

```python
# workspace/sci_fi_dashboard/routes/playground.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter()
_HTML = (Path(__file__).parent.parent / "static" / "playground.html").read_text()

@router.get("/", response_class=HTMLResponse)
async def playground():
    return _HTML
```

```html
<!-- workspace/sci_fi_dashboard/static/playground.html — single file, ~200 lines -->
<!doctype html>
<html><head><title>Synapse Playground</title></head>
<body>
  <div id="log"></div>
  <input id="in" placeholder="Talk to Synapse..." />
  <script>
    const ws = new WebSocket("ws://" + location.host + "/ws");
    // ... append messages, handle tokens, show SBS profile snapshot panel
  </script>
</body></html>
```

**Done when.** `http://localhost:8000/` opens a usable chat page out of the box, including a side panel that shows the live SBS profile (pairs naturally with item 5.1).

---

### 2.3 No public hosted demo  *(P1)*

**Problem.** Non-installers cannot feel the SBS continuity claim. The strongest IP of the project is invisible until you've spent an hour installing.

**Impact.** Most outsiders read the manifesto, never install, never come back.

**Solution.** A read-only ephemeral demo on free-tier infra. Reset every hour, single shared instance, hard message cap per IP. Use the demo profile from 2.1.

Cheapest path: a free-tier Fly.io / Railway deploy of the Docker image with a cron that wipes `~/.synapse/` every hour.

**Done when.** README has `Try it now: https://demo.synapse.sh` (or similar) and the link works.

---

### 2.4 `.env.example` lists 12 providers and overwhelms first-time users  *(P1)*

**Problem.** `.env.example` (4.6 KB) lists Gemini, Anthropic, OpenAI, Groq, OpenRouter, Mistral, xAI, Cohere, Together AI, and more. Only Gemini is marked REQUIRED. A first-time user has to scroll through 12 unfamiliar providers before they can save a working file.

**Impact.** Choice paralysis at the worst possible moment.

**Solution.** Split into a minimal default and an advanced reference.

```bash
# .env.example  -- the minimal default
# One key gets you started. Everything else is optional.

# REQUIRED for the default chat path
GEMINI_API_KEY=""

# Optional: add ANY of these to expand routing options
# See .env.example.advanced for the full list (12 providers)
```

```bash
# .env.example.advanced  -- the full reference
# (current contents of .env.example)
```

**Done when.** New `.env.example` is under 30 lines. Advanced one is linked from HOW_TO_RUN.md.

---

### 2.5 No "no-cloud" mode validated end-to-end  *(P2)*

**Problem.** The privacy story is "you can run everything locally" but there is no documented `synapse.json` profile that does this, and no benchmark of local-only quality.

**Impact.** Privacy-conscious users can't tell whether the local path actually works or how badly it degrades quality.

**Solution.** Ship a checked-in `synapse.local-only.json` profile and a one-page benchmark.

```jsonc
// synapse.local-only.json
{
  "embedding": { "provider": "fastembed" },
  "model_mappings": {
    "traffic_cop": { "model": "ollama_chat/llama3.2:3b" },
    "casual":      { "model": "ollama_chat/llama3.2:3b" },
    "code":        { "model": "ollama_chat/qwen2.5-coder:7b" },
    "analysis":    { "model": "ollama_chat/llama3.1:8b" },
    "vault":       { "model": "ollama_chat/mistral:7b" },
    "oracle":      { "model": "ollama_chat/llama3.2:3b" }
  },
  "providers": {
    "ollama": { "api_base": "http://localhost:11434" }
  }
}
```

Then `docs/local-only-benchmark.md` reports retrieval latency, response quality (a small held-out conversation set scored by GPT-4 or human), and known regressions.

**Done when.** `cp synapse.local-only.json ~/.synapse/synapse.json` produces a working chat with zero cloud egress, and the benchmark exists.

---

## 3. Code-level debt  *(P1)*

---

### 3.1 `llm_router.py` is 2,579 lines  *(P1)*

**Problem.** A single file holds: GitHub Copilot OAuth shim, Ollama defaults + context-window override, fallback chain logic, model resolution, retry/refresh, prompt-tier validation, traffic-cop integration, role mapping, LLMResult dataclass. Any change risks unintended interaction.

**Impact.** Routing bugs are hard to isolate; new contributors avoid the file; review cost is high.

**Solution.** Split by provider concern, keep the public API stable.

Proposed layout:

```
workspace/sci_fi_dashboard/llm_router/
├── __init__.py          # re-exports SynapseLLMRouter, LLMResult (preserves imports)
├── core.py              # Router class, role resolution, fallback orchestration
├── result.py            # LLMResult dataclass
├── traffic_cop.py       # route_traffic_cop()
├── prompt_tiers.py      # tier validation (move from prompt_tiers.py if helpful)
└── providers/
    ├── copilot.py       # ghu_ token shim, refresh, header injection
    ├── ollama.py        # _OLLAMA_DEFAULT_OPTS, num_ctx override
    └── litellm_default.py
```

Migration tactic — do it in two PRs:

```python
# PR 1: extract LLMResult and traffic_cop, no behavioral change
# PR 2: extract provider adapters one at a time, with tests pinning behavior
```

**Done when.** No file in `llm_router/` exceeds 500 lines. `from sci_fi_dashboard.llm_router import SynapseLLMRouter` still works. Every existing test in `tests/` passes unchanged.

---

### 3.2 `synapse_config.py` blast radius  *(P1)*

**Problem.** Imported by 50+ files. CLAUDE.md itself flags this as a gotcha. Any signature change ripples everywhere; this discourages even necessary changes.

**Impact.** Config evolves slower than the code that uses it; fields proliferate as workarounds; refactors get postponed.

**Solution.** Narrow the public surface to a frozen dataclass / pydantic model. Move helpers to a private submodule. Document the contract.

```python
# workspace/synapse_config/__init__.py
from synapse_config.public import SynapseConfig, load_config, providers_for
__all__ = ["SynapseConfig", "load_config", "providers_for"]
```

```python
# workspace/synapse_config/public.py
from pydantic import BaseModel, Field

class ProvidersConfig(BaseModel):
    gemini: dict | None = None
    anthropic: dict | None = None
    # ...

class SessionConfig(BaseModel):
    dmScope: str = "main"
    dual_cognition_enabled: bool = True
    dual_cognition_timeout: float = 5.0
    # ...

class SynapseConfig(BaseModel, frozen=True):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    model_mappings: dict = Field(default_factory=dict)
    # ...
```

Then internals like `_inject_provider_keys` move to `synapse_config/_internal.py` and are imported by `api_gateway.py` only.

**Done when.** The 50+ importers either import only from the narrow public surface, or are flagged in a follow-up issue. Fields cannot be added by accident — pydantic rejects unknown keys.

---

### 3.3 `api_gateway.py` still exports backwards-compat handles  *(P2)*

**Problem.** `api_gateway.py:59-62`:

```python
# Backwards-compatible test/operator handles. Runtime code should use deps/routes directly.
from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel  # noqa: E402
channel_registry = deps.channel_registry
```

The comment admits this is legacy.

**Impact.** Tests probably still depend on these names, blocking the routes refactor from completing cleanly.

**Solution.** Find every importer, migrate them to `deps`, then delete.

```bash
grep -rn "from sci_fi_dashboard.api_gateway import" workspace/tests/
grep -rn "import api_gateway" workspace/tests/
```

For each hit, rewrite:

```python
# before
from sci_fi_dashboard.api_gateway import channel_registry
# after
from sci_fi_dashboard import _deps as deps
deps.channel_registry...
```

Then delete the legacy lines from `api_gateway.py`.

**Done when.** No file outside `api_gateway.py` imports `channel_registry` or `WhatsAppChannel` from it; the legacy block is gone.

---

### 3.4 CWD-shifting Bash patterns in scripts and docs  *(P2)*

**Problem.** README and `synapse_*.sh` scripts use `cd workspace && ...` patterns that mutate working directory mid-session. During this review, that pattern broke subsequent commands silently. Same risk for any user copy-pasting from docs.

**Impact.** Quietly broken environments; reproductions fail without obvious cause.

**Solution.** Use absolute paths or `pushd`/`popd` so the cwd is restored.

```bash
# before
cd workspace && pytest tests/ -v

# after
( cd workspace && pytest tests/ -v )    # subshell — cwd auto-restores
# or
pytest --rootdir workspace workspace/tests/ -v
```

**Done when.** No script mutates cwd permanently; README commands all work from repo root without manual `cd`.

---

## 4. Privacy & safety  *(P1)*

---

### 4.1 Hemisphere isolation is a tag, not a boundary  *(P1)*

**Problem.** "spicy" memories live in the same SQLite DB as "safe" ones, separated only by a `hemisphere_tag` column. A single routing bug in `memory_engine.query()` could leak spicy content to a cloud LLM call.

**Impact.** The Vault privacy claim is policy-enforced, not structurally enforced. One regression and the claim is dead.

**Solution.** Two-tier defense.

**Tier 1 — fuzz-style integrity test:**

```python
# workspace/tests/test_hemisphere_isolation.py
import pytest
from memory_engine import MemoryEngine, add_memory

@pytest.mark.parametrize("seed", range(100))
def test_safe_query_never_returns_spicy(seed):
    engine = MemoryEngine(...)
    # seed corpus with mixed hemisphere docs
    for i in range(50):
        hem = "spicy" if i % 3 == 0 else "safe"
        add_memory(f"doc_{i}_{hem}_content", hemisphere=hem)
    results = engine.query("anything", hemisphere="safe", limit=20)
    assert all("spicy" not in r["text"] for r in results)
```

**Tier 2 — physical split (later, if integrity tests aren't enough):**

```python
# db.py
def get_db_connection(hemisphere: str = "safe"):
    if hemisphere == "spicy":
        return sqlite3.connect(SYNAPSE_DIR / "memory_spicy.db")
    return sqlite3.connect(SYNAPSE_DIR / "memory.db")
```

**Done when.** A 100-iteration fuzz test passes in CI on every PR. (Optional: physical split landed for full structural enforcement.)

---

### 4.2 No SECURITY.md / vuln report channel  *(P2)*

**Problem.** Project handles personal chat history, runs MCP tools, and has external API keys, but there is no documented vulnerability disclosure path.

**Impact.** OSS hygiene gap; researchers who find issues have no clean way to report them privately.

**Solution.** Standard `SECURITY.md`:

```markdown
# Security Policy

## Reporting a vulnerability
Email security@<your-domain> or open a GitHub Security Advisory.
Please do not file public issues for security reports.

## Triage SLA
Acknowledgement within 72 hours. Initial assessment within 7 days.

## Supported versions
The latest tagged release on `main`. Older releases are not patched.
```

**Done when.** `SECURITY.md` exists at the repo root and is referenced from README.

---

### 4.3 No SBOM / signed releases  *(P2)*

**Problem.** GitHub releases are unsigned and ship no SBOM. Users have no way to verify what they downloaded.

**Solution.** GitHub Action that attaches an SBOM and a signature on tag push.

```yaml
# .github/workflows/release.yml
- uses: anchore/sbom-action@v0
  with: { format: cyclonedx-json, output-file: sbom.json }
- uses: sigstore/cosign-installer@v3
- run: cosign sign-blob --yes sbom.json --output-signature sbom.json.sig
- uses: softprops/action-gh-release@v2
  with: { files: "sbom.json\nsbom.json.sig" }
```

**Done when.** Latest release page shows `sbom.json` and `sbom.json.sig` artifacts.

---

## 5. Personalization observability  *(P1)*

The strongest IP claim is currently invisible to users.

---

### 5.1 SBS profile is invisible  *(P1)*

**Problem.** SBS continuously rebuilds an 8-layer behavioral profile (~2 KB), but the user has no way to see it. The README says "your AI learns how to talk to you" — and gives the user no way to verify that.

**Impact.** Users can't tell whether SBS is actually working, can't catch wrong distillations, can't trust the system.

**Solution.** Read endpoint + UI panel.

```python
# routes/persona.py
@router.get("/persona/profile/{user}")
async def get_profile(user: str):
    sbs = deps.sbs_for(user)
    return {
        "core_identity": sbs.profile.core_identity,
        "linguistic": sbs.profile.linguistic,
        "emotional_state": sbs.profile.emotional_state,
        "domain": sbs.profile.domain,
        "interaction": sbs.profile.interaction,
        "vocabulary": sbs.profile.vocabulary,
        "exemplars": sbs.profile.exemplars,
        "meta": sbs.profile.meta,
        "last_rebuild_at": sbs.profile.last_rebuild_at,
    }
```

In the playground page (2.2), render this as a side panel that updates after each batch rebuild.

**Done when.** `GET /persona/profile/the_creator` returns the live profile; playground shows a "what Synapse thinks of you" panel.

---

### 5.2 No way to edit / correct the profile  *(P1)*

**Problem.** Once SBS distills something wrong about you, the only correction path is implicit feedback (which may take dozens of messages) or hand-editing JSON state.

**Impact.** Wrong distillations compound. Users feel locked in to the system's mistakes.

**Solution.** A `PATCH` endpoint with audit trail.

```python
# routes/persona.py
@router.patch("/persona/profile/{user}/{layer}")
async def patch_profile(user: str, layer: str, body: dict):
    sbs = deps.sbs_for(user)
    if layer not in sbs.profile.LAYERS:
        raise HTTPException(400, f"unknown layer: {layer}")
    sbs.profile.override_layer(layer, body["value"], reason=body.get("reason", "user override"))
    sbs.profile.persist()
    return {"ok": True, "layer": layer}
```

UI: each layer in the side panel has an "edit" pencil + a "reset to learned value" undo.

**Done when.** Users can override any layer from the playground; overrides are persisted and survive a restart.

---

### 5.3 No memory inspector  *(P1)*

**Problem.** Users cannot see what facts Synapse stored. `/memory_health` returns counts; nothing returns the actual memory rows.

**Impact.** Trust collapses if the user can't audit what's remembered. (Critical for a project that explicitly handles personal chat history.)

**Solution.** Paginated read + delete endpoints, gated by gateway token.

```python
# routes/knowledge.py
@router.get("/memory/list")
async def list_memory(
    user: str,
    hemisphere: str = "safe",
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    return memory_engine.list_documents(
        user=user, hemisphere=hemisphere, search=q, limit=limit, offset=offset
    )

@router.delete("/memory/{doc_id}")
async def delete_memory(doc_id: str):
    memory_engine.delete_document(doc_id)
    return {"ok": True}
```

**Done when.** Playground has a memory tab with search, pagination, and per-row delete. Deletes propagate to vector store, FTS, and KG.

---

## 6. Memory & RAG quality  *(P2)*

---

### 6.1 Reranker is small (TinyBERT-L-2-v2)  *(P2)*

**Problem.** Cheap and fast, but quality ceiling is bounded for long or nuanced queries. There is no published evaluation against larger rerankers.

**Solution.** Decide explicitly. Build a small held-out query set (50–100 queries with expected top doc), benchmark TinyBERT-L-2 vs `ms-marco-MiniLM-L-12-v2` vs `bge-reranker-v2-m3`, publish the table.

```python
# scripts/eval_reranker.py
QUERIES = [
    {"q": "what did I say about the marathon", "expected_doc_id": "..."},
    # ...50 more
]
for model in ["ms-marco-TinyBERT-L-2-v2", "ms-marco-MiniLM-L-12-v2", "bge-reranker-v2-m3"]:
    p_at_1, p_at_5, p95_latency = run_eval(model, QUERIES)
    print(f"{model}\tP@1={p_at_1:.2f}\tP@5={p_at_5:.2f}\tP95={p95_latency}ms")
```

**Done when.** `docs/reranker-eval.md` contains the table; the code either keeps the small model with a one-paragraph "why" comment in `memory_engine.py`, or upgrades.

---

### 6.2 KG is SPO triples in SQLite — expressive limits undocumented  *(P2)*

**Problem.** `sqlite_graph.py` (242 lines) provides subject-predicate-object storage. Light footprint, but anything beyond depth-1 path queries is slow. There is no doc on what queries are reasonable.

**Solution.** Document the limits with examples that work and examples that don't.

```markdown
# docs/kg-limits.md

## Queries that are fast (<10 ms)
- "What does X relate to?"  (1-hop)
- "All triples about subject S"

## Queries that get slow (>1 s on 100k triples)
- "Path from X to Y of length ≤4"
- "All subjects that share predicate P with at least 3 others"

## When to consider migrating
If your usage is dominated by multi-hop traversal, plan a migration to Neo4j or
KuzuDB. For Synapse's current chat-grounded use case, SPO is sufficient.
```

**Done when.** `docs/kg-limits.md` exists; `sqlite_graph.py` docstring links to it.

---

### 6.3 No load / concurrency tests  *(P2)*

**Problem.** README claims "zero dropped messages under load." No test demonstrates this.

**Solution.** A `tests/load/` suite using `pytest-asyncio` to fan out N concurrent sends and assert message accounting.

```python
# workspace/tests/load/test_pipeline_burst.py
import asyncio, pytest

@pytest.mark.asyncio
async def test_no_dropped_under_burst():
    sent_ids = [f"msg_{i}" for i in range(500)]
    await asyncio.gather(*(send_message(mid) for mid in sent_ids))
    await wait_for_queue_drain(timeout=60)
    processed = get_processed_message_ids()
    assert set(processed) == set(sent_ids), f"dropped: {set(sent_ids) - set(processed)}"
```

**Done when.** `tests/load/` exists with at least: burst test, dedup test, FloodGate batch test. Runs on PR.

---

### 6.4 No SBS-drift regression test  *(P2)*

**Problem.** SBS rebuilds the profile every 50 messages. Nothing asserts the profile is stable for stable inputs or drifts predictably for known input patterns.

**Solution.** Seed a synthetic conversation, run the batch pipeline, assert profile fields within tolerance.

```python
# workspace/tests/test_sbs_drift.py
def test_directness_layer_stable_across_rebuilds():
    msgs = [synthetic_msg("direct, terse") for _ in range(100)]
    sbs = run_batch_pipeline(msgs)
    assert sbs.profile.linguistic["directness"] >= 0.7

def test_emotional_state_shifts_with_stressed_pattern():
    calm = [synthetic_msg("everything's fine") for _ in range(50)]
    stressed = [synthetic_msg("I can't keep up, deadlines everywhere") for _ in range(50)]
    sbs = run_batch_pipeline(calm + stressed)
    assert sbs.profile.emotional_state["recent_pattern"] == "stressed"
```

**Done when.** Suite covers each of the 8 profile layers with at least one stability and one drift test.

---

## 7. Production / scaling ceiling  *(P2)*

---

### 7.1 SQLite-only data layer  *(P2)*

**Problem.** Multiuser layer (`multiuser/`) exists, but the underlying store is SQLite. Concurrent writers from many users will hit lock contention regardless of WAL.

**Solution.** Document the ceiling honestly. If you want to lift it, abstract `db.py` and add a Postgres adapter behind a feature flag.

```python
# db.py
def get_db_connection():
    backend = os.environ.get("SYNAPSE_DB_BACKEND", "sqlite")
    if backend == "postgres":
        from db_postgres import get_pg_connection
        return get_pg_connection()
    return _get_sqlite_connection()
```

**Done when.** Either README explicitly states "single-user-per-instance, multi-user planned" with an issue link, or a Postgres backend ships behind an env var with a smoke test.

---

### 7.2 No deploy automation  *(P2)*

**Problem.** Only deploy story is `synapse_start.sh` / `.bat`. No Dockerfile (despite item 2.1 needing one), no systemd unit, no health probes wired to a process manager.

**Solution.** Ship both:

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY workspace ./workspace
EXPOSE 8000
HEALTHCHECK --interval=30s CMD curl -f http://localhost:8000/healthz || exit 1
CMD ["uvicorn", "workspace.sci_fi_dashboard.api_gateway:app", "--host", "0.0.0.0", "--port", "8000"]
```

```ini
# deploy/synapse.service
[Unit]
Description=Synapse Gateway
After=network.target

[Service]
Type=simple
User=synapse
WorkingDirectory=/opt/synapse
ExecStart=/usr/bin/uvicorn workspace.sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Done when.** Both files exist, are referenced from HOW_TO_RUN.md, and the Docker image builds in CI.

---

### 7.3 Bus factor of 1  *(P2)*

**Problem.** Solo-dev project. Strategic risk for any user committing personal AI to this stack.

**Solution.** Don't manufacture contributors; document how decisions are made and how a second maintainer would be onboarded.

```markdown
# GOVERNANCE.md
## Current state
Synapse is currently maintained by one person (@UpayanGhosh). Decisions are made
by the maintainer.

## Pull requests
Welcome. Please open an issue first for non-trivial changes.

## Becoming a maintainer
The maintainer may invite a co-maintainer after sustained review-quality
contributions over 3+ months. Co-maintainers share merge rights.
```

**Done when.** `GOVERNANCE.md` exists; README links to it.

---

## 8. Repository hygiene  *(P2)*

---

### 8.1 `interview-prep.html` (205 KB) untracked at repo root  *(P2)*

**Problem.** Build artifact from `/interview-prep` skill is sitting at the repo root, untracked. It's been there for the entire review.

**Solution.** Either gitignore it or move to a generated-output folder.

```gitignore
# .gitignore
interview-prep.html
```

Or:

```bash
mkdir -p content/generated && mv interview-prep.html content/generated/
echo "content/generated/" >> .gitignore
```

**Done when.** `git status` is clean on a fresh clone after running the skill.

---

### 8.2 `CLAUDE.md.original` lives next to `CLAUDE.md`  *(P2)*

**Problem.** Two CLAUDE.md files in the repo root, the `.original` is 7.6 KB and the live one is 19.4 KB. Suggests an unfinished migration.

**Solution.** Decide. If the `.original` was the pre-rewrite snapshot kept for reference, move it under `docs/archive/`. Otherwise delete.

```bash
mkdir -p docs/archive && git mv CLAUDE.md.original docs/archive/CLAUDE.md.pre-rewrite.md
```

**Done when.** Only one CLAUDE.md exists at the repo root.

---

### 8.3 `.cursorrules` and `.windsurfrules` are byte-identical  *(P2)*

**Problem.** Both files are 1789 bytes, same date. Two editor-config files that drift independently are a maintenance trap.

**Solution.** Generate one from the other, or share a common file.

```bash
# Make .windsurfrules a symlink to .cursorrules (works on Linux/Mac/WSL)
rm .windsurfrules && ln -s .cursorrules .windsurfrules
```

Or maintain `AGENTS.md` as the source of truth and have a CI check that the editor files match:

```yaml
# .github/workflows/lint.yml
- run: |
    diff .cursorrules .windsurfrules || (echo "editor rule files diverged" && exit 1)
```

**Done when.** It is impossible for the two files to drift.

---

### 8.4 Ad-hoc test scripts in the production module  *(P2)*

**Problem.** `workspace/sci_fi_dashboard/` contains `test_pruning.py`, `test_sbs.py`, `test_ui.py`, `test.sh`, `verify_dual_cognition.py`, `verify_soul.py`. These look like one-off scripts that ended up next to production code.

**Impact.** pytest discovery may pick them up; readers can't tell what's library code vs throwaway script.

**Solution.** Move to the right home.

```bash
mkdir -p scripts/verify
git mv workspace/sci_fi_dashboard/verify_*.py scripts/verify/
git mv workspace/sci_fi_dashboard/test.sh scripts/verify/

# If test_pruning.py / test_sbs.py / test_ui.py are real tests, move into the suite:
git mv workspace/sci_fi_dashboard/test_*.py workspace/tests/
# else move to scripts/verify/ too
```

**Done when.** No `test_*.py` or `verify_*.py` lives outside `workspace/tests/` or `scripts/`.

---

## 9. Differentiation messaging  *(P2)*

---

### 9.1 README does not position vs the competitive set  *(P2)*

**Problem.** The space is more crowded than the README implies (Mem0, MemGPT/Letta, Pieces, OpenAssistant memory forks). Readers familiar with those tools won't see what makes Synapse different.

**Solution.** A short honest comparison section.

```markdown
## How Synapse compares

| Tool | What it nails | Where Synapse differs |
|---|---|---|
| Mem0 | Drop-in memory layer for any LLM app | Synapse is a full personal-AI architecture, not a memory SDK; ships with channels, persona, routing |
| MemGPT / Letta | Long-context simulated via tiered memory | Synapse explicitly models behavioral substrate (SBS), not just facts |
| Pieces | Developer-context AI | Synapse targets personal continuity, not coding context |
| ChatGPT memory items | Polished UX, locked to OpenAI | Synapse is self-hostable, model-agnostic, multi-channel |
```

**Done when.** README has this section above the fold (within first 250 lines).

---

### 9.2 Manifesto-to-reference ratio is too high  *(P2)*

**Problem.** README is ~43 KB, dominated by vision prose. Builders bounce; non-builders cannot install.

**Solution.** Reorganize: keep the vision but move it below the install path.

Suggested top-of-README skeleton:

```markdown
# Synapse
[badges]
> One-line pitch.

[GIF / screenshot]

## Try it in 60 seconds
docker compose -f docker-compose.demo.yml up
open http://localhost:8000/

## What it actually does
- multi-channel personal AI (WhatsApp, Telegram, Discord, Slack, CLI, web)
- hybrid RAG memory (FastEmbed + LanceDB + FlashRank)
- SBS — an evolving behavioral profile, rebuilt every 50 messages
- Dual Cognition — optional reflective pass before replying
- privacy-aware routing — local Vault model for sensitive topics

## Install
[5-line happy path. Link to HOW_TO_RUN.md for everything else.]

## Architecture
[link]

## Vision  ← all the manifesto content moves here
[the current first 400 lines of README]
```

**Done when.** First 200 lines of README contain pitch, screenshot, install command, and a 10-line "what it actually does" — nothing else.

---

## Summary

- **P0 must-fix to unblock adoption (5 items):** stale README metrics, stale ARCHITECTURE.md, stale CLAUDE.md bug warning, stale Ollama-required claim, no one-command demo, no web UI.
- **P1 quality bar (~10 items):** code debt (`llm_router.py`, `synapse_config.py`), hemisphere isolation tests, SBS observability, memory inspector.
- **P2 polish (~12 items):** RAG benchmarks, deploy automation, repo hygiene, comparative messaging.

**Shortest path to a meaningfully better perceived product:** §1 (docs) and §2 (onboarding) first. Everything else compounds slower.

**Quick wins (1 hour each):** 1.3 (delete stale CLAUDE.md warning), 1.4 (rewrite Ollama callout), 8.1 (gitignore interview-prep.html), 8.2 (move CLAUDE.md.original), 8.3 (symlink editor rules).
