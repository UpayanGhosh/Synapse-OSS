# Research Phase 4 — Tools MCP Server Upgrade

> Generated 2026-04-02 by 3 parallel Explore agents.

---

## Agent 1: Sentinel API & Bug Audit

### tools.py — Function Signatures & Return Types

**`init_sentinel(project_root: Path) -> None`**
- Initializes the global `_sentinel` instance once at app startup.
- All tool functions guard with `if not _sentinel: raise RuntimeError("Sentinel not initialized")`.

**`agent_read_file(path: str, reason: str = "agent requested") -> str`**
- Returns file content on success.
- On denial: catches `SentinelError`, returns `"[SENTINEL DENIED]: {str(e)}"`.
- Calls `_sentinel.safe_read(path, reason)`.

**`agent_write_file(path: str, content: str, reason: str = "") -> str`**
- Returns `"[SUCCESS]: Written to {path}"` on success.
- On denial: `"[SENTINEL DENIED]: {str(e)}"`.
- Calls `_sentinel.safe_write(path, content, reason)` (which returns `bool`); wraps in message.

**`agent_delete_file(path: str, reason: str = "") -> str`**
- Returns `"[SUCCESS]: Deleted {path}"` or `"[SENTINEL DENIED]: {str(e)}"`.
- Calls `_sentinel.safe_delete(path, reason)`.

**`agent_list_directory(path: str, reason: str = "") -> str`**
- Returns newline-separated list of filenames, or `"[SENTINEL DENIED]: {str(e)}"`.
- Calls `_sentinel.check_access()` + `_sentinel._resolve_path()` + `iterdir()`.

**Correct import path:** `from sbs.sentinel.tools import agent_read_file, agent_write_file, agent_delete_file, agent_list_directory`

---

### gateway.py — Sentinel Class

**`Sentinel.__init__(self, project_root: Path, audit_dir: Path = None)`**
- Stores `project_root.resolve()`, sets up `AuditLogger`.
- Pre-computes absolute paths for fast lookup.

**`safe_read(path, reason) -> str`**
- Returns file contents (UTF-8).
- Raises `SentinelError` if access denied.
- Flow: `check_access()` → resolve path → read → return content.

**`safe_write(path, content, reason) -> bool`**
- Returns `True` on success.
- Raises `SentinelError` if access denied.
- Flow: `check_access()` → resolve → backup existing → ensure parent dir → write → return `True`.

**`_is_within_project(resolved) -> bool`**
- Tries `resolved.relative_to(self.project_root)` — `True` if succeeds, `False` on `ValueError`.
- Prevents path traversal.

**`_classify_path(path) -> ProtectionLevel`**
- Priority order (highest first): CRITICAL_FILES → CRITICAL_DIRECTORIES → PROTECTED_FILES → WRITABLE_ZONES → default **PROTECTED** (fail-closed).

---

### manifest.py — ProtectionLevel Enum

```python
class ProtectionLevel(Enum):
    CRITICAL  = "critical"   # Total lockout
    PROTECTED = "protected"  # Read-only
    MONITORED = "monitored"  # Read-write with audit
    OPEN      = "open"       # Unrestricted
```

**CRITICAL_FILES (18):** `api_gateway.py`, `main.py`, `run.py`, `app.py`, `sbs/orchestrator.py`, `sbs/injection/compiler.py`, `sbs/profile/manager.py`, `sbs/sentinel/*`, `.env`, `config.py`, `settings.py`, `requirements.txt`, `pyproject.toml`, `data/profiles/current/core_identity.json`

**CRITICAL_DIRECTORIES (6):** `sbs/sentinel/`, `sbs/feedback/`, `.git/`, `__pycache__/`, `venv/`, `.venv/`

**PROTECTED_FILES (6):** `sbs/ingestion/schema.py`, `sbs/ingestion/logger.py`, `sbs/processing/realtime.py`, `sbs/processing/batch.py`, `sbs/processing/selectors/exemplar.py`, `sbs/vacuum.py`

**WRITABLE_ZONES (8):** `data/raw/`, `data/indices/`, `data/profiles/current/`, `data/profiles/archive/`, `data/temp/`, `data/exports/`, `generated/`, `logs/`

---

### tools_server.py Bug Status

**NO BUG — already fixed.**

The CLAUDE.md note about `Sentinel().agent_read_file()` is stale. Current code correctly calls module-level functions:
- Lines 64-65: `from sbs.sentinel.tools import agent_read_file` → called directly.
- Lines 71-72: `from sbs.sentinel.tools import agent_write_file` → called directly.

No instance methods are called; Sentinel layer is properly enforced via wrapper functions.

---

## Agent 2: Atomic Write & Paging Patterns

### Atomic Write Pattern (media/store.py lines 176–191)

```python
tmp = dest.with_suffix(dest.suffix + ".tmp")
fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MEDIA_FILE_MODE)
try:
    with os.fdopen(fd, "wb") as fh:
        fh.write(buffer)
except Exception:
    with contextlib.suppress(OSError):
        os.unlink(str(tmp))
    raise

os.replace(str(tmp), str(dest))

# Re-enforce permissions after replace (umask drift guard)
with contextlib.suppress(OSError):
    os.chmod(str(dest), MEDIA_FILE_MODE)
```

- `os.O_WRONLY | os.O_CREAT | os.O_TRUNC` for atomic creation.
- `os.fdopen()` wraps the raw fd.
- Temp file cleanup on exception.
- `os.replace()` is atomic rename on both Windows and POSIX.
- Permission re-enforcement after rename (umask drift guard).

### Alternate Atomic Pattern — JSONL (compaction.py lines 161–173)

```python
fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    os.replace(tmp_path, str(path))
except Exception:
    with contextlib.suppress(OSError):
        os.unlink(tmp_path)
    raise
```

Uses `tempfile.mkstemp()` to avoid name collisions; same rename + cleanup pattern.

---

### File Mode Constants (media/constants.py)

```python
MEDIA_FILE_MODE = 0o644      # rw-r--r--
MEDIA_DIR_MODE  = 0o700      # rwx------
DEFAULT_TTL_MS  = 120_000    # 2 minutes
```

**Size Limits:**
| Type     | Limit  |
|----------|--------|
| Image    | 6 MB   |
| Audio    | 16 MB  |
| Video    | 16 MB  |
| Document | 100 MB |
| Fallback | 5 MB   |

---

### MIME Detection (media/mime.py)

```python
def detect_mime(
    data: bytes,
    header_mime: str | None = None,
    filename: str | None = None,
) -> str:
```

Strategy (in order): python-magic on raw bytes → caller-supplied `header_mime` → extension lookup → fallback `"application/octet-stream"`.

---

### Existing Pagination / Truncation Patterns

| Location | Pattern | Value |
|----------|---------|-------|
| `retriever.py:99` | `limit: int = 5` result cap | 5 results |
| `memory_manager.py:25` | Byte truncation `content[:_TWO_MB]` | 2 MB |
| `interactions.py:15` | Char truncation `text[:_MAX_SNAPSHOT_CHARS]`, returns `truncated: bool` | 50 000 chars |
| `media/fetch.py:77` | Streaming `chunk_size=65_536` with running total guard | 64 KB chunks |
| `compaction.py:104` | Token-split `len(content) // 4` heuristic | — |

**Key pattern for read tool paging:** `interactions.py` approach — return `{"content": text[:limit], "truncated": bool, "total_bytes": int}` is the established codebase idiom.

---

## Agent 3: MCP Server Template & Edit Tooling

### base.py — Full Contents Summary

Minimal utility module:
- Adds dashboard dir and workspace dir to `sys.path`.
- Configures `synapse.mcp` logger.
- `setup_logging()` function: stderr-only logging (stdout reserved for MCP stdio transport — critical constraint).

**Import in every MCP server:** `from base import setup_logging`

---

### MCP Tool Schema Pattern (execution_server.py)

```python
Tool(
    name="tool_name",
    description="Human-readable description.",
    inputSchema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
            "param2": {
                "type": "string",
                "enum": ["option_a", "option_b"],
                "description": "...",
            },
            "param3": {"type": "integer", "description": "...", "default": 100},
        },
        "required": ["param1"],
    },
)
```

- All tools use standard JSON Schema in `inputSchema`.
- `required` array lists mandatory params.
- Optional params use `"default"` in description (not enforced by schema, just documented).
- Dispatch in `call_tool(name, arguments)` via if/elif chain.

---

### Current tools_server.py Tool List

| Tool | Schema | Sentinel-gated? |
|------|--------|-----------------|
| `web_search` | `{url: string}` | No |
| `read_file` | `{path: string}` | Yes — `agent_read_file` |
| `write_file` | `{path: string, content: string}` | Yes — `agent_write_file` |

---

### difflib Availability

**YES — stdlib, always available.** Not in requirements.txt (not needed). Not currently used in codebase. Import: `from difflib import unified_diff` or `difflib.ndiff`.

---

### Workspace Root Resolution (synapse_config.py)

**Three-layer precedence:**
1. `SYNAPSE_HOME` env var (if set)
2. `<data_root>/synapse.json` — providers, channels, model_mappings, gateway, session, mcp
3. Empty dicts as defaults

**Derived paths from `data_root`:**
```
db_dir  = data_root / "workspace" / "db"
sbs_dir = data_root / "workspace" / "sci_fi_dashboard" / "synapse_data"
log_dir = data_root / "logs"
```

**No explicit `workspace` or `project_root` config field.** The workspace is the directory containing `api_gateway.py`. For MCP servers that need the project root, use `Path(__file__).parent.parent` (from `mcp_servers/` → `sci_fi_dashboard/`).
