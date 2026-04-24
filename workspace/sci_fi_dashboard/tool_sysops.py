"""System-operations tools — Claude-Code-like toolkit for the persona.

Tools exposed:
    bash_exec      — run a shell command with safety guards (owner-only)
    edit_file      — find/replace on a file, Sentinel-gated
    grep_tool      — ripgrep-powered search
    glob_tool      — filesystem pattern match
    edit_synapse_config
                   — edit ~/.synapse/synapse.json with JSON validation + backup
                     (lives outside Sentinel's project_root, so has its own safety)
    list_directory — directory listing (Sentinel-gated)

Safety contracts (shared across all write/exec tools):
    * owner_only = True   ← factory returns None for non-owner sessions
    * non-zero exit / SentinelError maps to ToolResult(is_error=True)
    * stdout/stderr capped at 60 KB per call
    * command timeout capped at 60 s
    * admin / privilege-escalation patterns are hard-blocked
    * deletes are NOT exposed — destructive ops require a separate consent path

See tool_registry.py for the ToolContext / SynapseTool contract.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from sci_fi_dashboard.tool_registry import (
    SynapseTool,
    ToolContext,
    ToolFactory,
    ToolResult,
    error_result,
    text_result,
)

# ---------------------------------------------------------------------------
# Shared safety primitives
# ---------------------------------------------------------------------------

# Commands that attempt to escalate to admin / modify system state — always denied.
# Matched as whole words / tokens (case-insensitive) inside the command string.
_ADMIN_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsudo\b",
        r"\bsu\s",
        r"\brunas\b",
        r"\bnet\s+user\b",
        r"\bnet\s+localgroup\b",
        r"\bnetsh\b",
        r"\breg\s+add\s+HKLM",
        r"\breg\s+delete\s+HKLM",
        r"\bicacls\b.*\/grant",
        r"\btakeown\b",
        r"\bschtasks\b",
        r"\bmklink\s+\/D",
        r"\bformat\s+[a-z]:",
        r"\bdiskpart\b",
        r"\bshutdown\b",
        r"\brestart-computer\b",
        r"\bchown\b",
        r"\bchmod\b\s+\+s",  # setuid
    )
)

# Commands that delete or destroy data — require explicit consent workflow,
# which doesn't exist yet, so block until it does.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\s+-rf\b",
        r"\brm\s+-fr\b",
        r"\brmdir\s+\/s",
        r"\brd\s+\/s",
        r"\bdel\s+\/s",
        r"\bformat\b",
        r">\s*\/dev\/sd",
        r"\bdd\s+.*of=\/dev",
        r"\bmkfs\b",
        r"\bgit\s+push.*--force\b",
        r"\bgit\s+push.*-f\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-fd\b",
    )
)

_MAX_OUTPUT_BYTES = 60_000
_MAX_TIMEOUT_S = 60
_DEFAULT_TIMEOUT_S = 30


def _reject(command: str) -> str | None:
    """Return a denial reason if the command is blocked, else None."""
    for p in _ADMIN_PATTERNS:
        if p.search(command):
            return f"admin/privileged command pattern denied: {p.pattern}"
    for p in _DESTRUCTIVE_PATTERNS:
        if p.search(command):
            return (
                f"destructive command pattern denied (consent workflow required): "
                f"{p.pattern}"
            )
    return None


def _truncate(data: bytes, limit: int = _MAX_OUTPUT_BYTES) -> str:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    head = data[: limit // 2].decode("utf-8", errors="replace")
    tail = data[-limit // 2 :].decode("utf-8", errors="replace")
    return f"{head}\n...[{len(data) - limit} bytes elided]...\n{tail}"


# ---------------------------------------------------------------------------
# bash_exec — shell execution with safety
# ---------------------------------------------------------------------------


def _bash_exec_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return error_result("command is empty")
        deny = _reject(command)
        if deny:
            return error_result(deny)

        timeout = min(int(arguments.get("timeout", _DEFAULT_TIMEOUT_S)), _MAX_TIMEOUT_S)
        cwd = arguments.get("cwd") or ctx.workspace_dir

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return error_result(f"command timed out after {timeout}s")
        except Exception as e:
            return error_result(f"subprocess failed: {e}")

        payload = {
            "command": command,
            "cwd": cwd,
            "exit_code": proc.returncode,
            "stdout": _truncate(stdout),
            "stderr": _truncate(stderr),
        }
        is_error = proc.returncode != 0
        return ToolResult(content=json.dumps(payload, ensure_ascii=False), is_error=is_error)

    return SynapseTool(
        name="bash_exec",
        description=(
            "Run a shell command in the project. Output capped at 60KB, timeout capped "
            "at 60s. Denies sudo / runas / format / rm -rf / git push --force etc. "
            "Returns JSON {command, cwd, exit_code, stdout, stderr}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory. Defaults to workspace root.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds before the command is killed (max 60).",
                },
            },
            "required": ["command"],
        },
        execute=_execute,
        owner_only=True,
        serial=True,
    )


# ---------------------------------------------------------------------------
# edit_file — find/replace on an existing file (Sentinel-gated)
# ---------------------------------------------------------------------------


def _edit_file_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        path = str(arguments.get("path", "")).strip()
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not path or old is None or new is None:
            return error_result("path, old_string, new_string are required")

        try:
            from sci_fi_dashboard.sbs.sentinel.tools import (
                agent_read_file,
                agent_write_file,
            )

            current = agent_read_file(path, reason="edit_file: pre-check")
            if current.startswith("[SENTINEL DENIED]"):
                return error_result(current)
            if old not in current:
                return error_result(
                    "old_string not found in file — the Edit tool requires exact match."
                )
            count = current.count(old)
            if count > 1 and not arguments.get("replace_all"):
                return error_result(
                    f"old_string appears {count}x; pass replace_all=true to replace all "
                    "or add surrounding context to make old_string unique."
                )
            updated = current.replace(old, new) if arguments.get("replace_all") else current.replace(
                old, new, 1
            )
            result = agent_write_file(path, updated, reason=arguments.get("reason", "edit_file"))
            if result.startswith("[SENTINEL DENIED]"):
                return error_result(result)
            return text_result(f"edited {path} ({count if arguments.get('replace_all') else 1} replacement(s))")
        except Exception as e:
            return error_result(f"edit_file failed: {e}")

    return SynapseTool(
        name="edit_file",
        description=(
            "Find-and-replace a string in a file. Sentinel-gated. old_string must be "
            "unique unless replace_all=true. Matches Claude Code's Edit tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path."},
                "old_string": {"type": "string", "description": "Exact text to find."},
                "new_string": {"type": "string", "description": "Replacement text."},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence (default false).",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    "description": "Short audit-log reason for the edit.",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        execute=_execute,
        owner_only=True,
    )


# ---------------------------------------------------------------------------
# grep_tool — search file contents (ripgrep if available, fallback to Python)
# ---------------------------------------------------------------------------


def _grep_factory(ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        pattern = str(arguments.get("pattern", ""))
        path = str(arguments.get("path", ctx.workspace_dir))
        glob = arguments.get("glob")
        ignore_case = arguments.get("ignore_case", False)
        max_results = min(int(arguments.get("max_results", 100)), 500)

        if not pattern:
            return error_result("pattern is required")

        rg = shutil.which("rg")
        if rg:
            args = [rg, "--no-heading", "--line-number", "--max-count", str(max_results)]
            if ignore_case:
                args.append("-i")
            if glob:
                args.extend(["--glob", glob])
            args.extend([pattern, path])
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                out = _truncate(stdout)
                if proc.returncode not in (0, 1):
                    return error_result(_truncate(stderr) or "rg failed")
                return text_result(out or "(no matches)")
            except asyncio.TimeoutError:
                return error_result("grep timed out")

        # Python fallback
        import re as _re

        flags = _re.IGNORECASE if ignore_case else 0
        try:
            rx = _re.compile(pattern, flags)
        except _re.error as e:
            return error_result(f"invalid regex: {e}")
        matches: list[str] = []
        base = Path(path)
        files = base.rglob(glob) if glob else base.rglob("*")
        for f in files:
            if not f.is_file():
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        matches.append(f"{f}:{i}:{line[:240]}")
                        if len(matches) >= max_results:
                            return text_result("\n".join(matches))
            except Exception:
                continue
        return text_result("\n".join(matches) if matches else "(no matches)")

    return SynapseTool(
        name="grep_tool",
        description=(
            "Search file contents for a regex pattern. Uses ripgrep when available; "
            "returns `path:line:preview` style matches. Max 500 results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern."},
                "path": {"type": "string", "description": "Directory or file to search."},
                "glob": {"type": "string", "description": "Optional glob to restrict files."},
                "ignore_case": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# glob_tool — find files by pattern
# ---------------------------------------------------------------------------


def _glob_factory(ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        pattern = str(arguments.get("pattern", "")).strip()
        root = str(arguments.get("path", ctx.workspace_dir))
        if not pattern:
            return error_result("pattern is required")
        max_results = min(int(arguments.get("max_results", 200)), 1000)
        base = Path(root)
        if not base.exists():
            return error_result(f"path does not exist: {root}")
        matches = []
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            if fnmatch.fnmatch(str(f), pattern) or fnmatch.fnmatch(f.name, pattern):
                matches.append(str(f))
                if len(matches) >= max_results:
                    break
        return text_result("\n".join(matches) if matches else "(no matches)")

    return SynapseTool(
        name="glob_tool",
        description=(
            "Find files whose path or name matches a glob pattern (e.g. '**/*.py'). "
            "Returns newline-delimited absolute paths."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern."},
                "path": {"type": "string", "description": "Root directory to search."},
                "max_results": {"type": "integer", "default": 200},
            },
            "required": ["pattern"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# edit_synapse_config — bespoke tool for ~/.synapse/synapse.json
# Lives outside Sentinel's project_root, so has its own JSON+backup safety.
# ---------------------------------------------------------------------------


def _edit_synapse_config_factory(ctx: ToolContext) -> SynapseTool | None:
    if not ctx.sender_is_owner:
        return None

    config_path = Path.home() / ".synapse" / "synapse.json"

    async def _execute(arguments: dict) -> ToolResult:
        action = str(arguments.get("action", "get"))

        if not config_path.exists():
            return error_result(f"config not found: {config_path}")

        try:
            raw = config_path.read_text(encoding="utf-8")
            cfg = json.loads(raw)
        except Exception as e:
            return error_result(f"failed to load config: {e}")

        if action == "get":
            key_path = arguments.get("key_path")
            if not key_path:
                return text_result(json.dumps(cfg, indent=2))
            node = cfg
            for part in key_path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return error_result(f"key_path not found: {key_path}")
                node = node[part]
            return text_result(json.dumps(node, indent=2))

        if action == "set":
            key_path = arguments.get("key_path")
            value = arguments.get("value")
            if not key_path:
                return error_result("key_path required for set")

            # Validate model mapping values — format check only (provider/model).
            # Real "is this model real" check happens at LLM call time via litellm
            # router. For discovery of what models are actually available, use the
            # list_available_models tool first.
            if key_path.startswith("model_mappings.") and key_path.endswith(".model"):
                if not isinstance(value, str) or "/" not in value:
                    return error_result(
                        f"model value {value!r} is missing a provider prefix. "
                        "Format is 'provider/model-name' — e.g. "
                        "'gemini/gemini-2.5-flash', 'github_copilot/gpt-4o', "
                        "'github_copilot/gemini-2.0-flash-001', "
                        "'ollama_chat/llama3.2:3b'. "
                        "Call list_available_models to see what's actually "
                        "reachable on this host before guessing."
                    )

            parts = key_path.split(".")
            node = cfg
            for part in parts[:-1]:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value

            # Atomic write with backup
            backup = config_path.with_suffix(f".json.bak.{int(time.time())}")
            backup.write_text(raw, encoding="utf-8")
            tmp = config_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            tmp.replace(config_path)

            # Hot-reload: re-read config into the running process and rebuild
            # the LLM router so the change takes effect immediately.
            reload_msg = ""
            try:
                from synapse_config import SynapseConfig
                from sci_fi_dashboard import _deps as deps

                new_cfg = SynapseConfig.load()
                deps._synapse_cfg = new_cfg
                if hasattr(deps, "synapse_llm_router") and deps.synapse_llm_router:
                    deps.synapse_llm_router._config = new_cfg
                    deps.synapse_llm_router._rebuild_router()
                    reload_msg = " — router hot-reloaded, no restart needed."
            except Exception as e:
                reload_msg = f" — hot-reload failed ({e}); restart server to apply."

            return text_result(
                f"set {key_path} = {value!r} (backup: {backup.name}).{reload_msg}"
            )

        return error_result(f"unknown action: {action}")

    return SynapseTool(
        name="edit_synapse_config",
        description=(
            "Read or set values in ~/.synapse/synapse.json. action=get returns the "
            "config (or a sub-path via key_path like 'model_mappings.code.model'). "
            "action=set writes a new value at key_path with JSON validation and a "
            "timestamped backup. Restart server after set. Owner only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set"],
                    "description": "get reads, set writes.",
                },
                "key_path": {
                    "type": "string",
                    "description": "Dotted key path e.g. 'model_mappings.code.model'.",
                },
                "value": {
                    "description": "New value (any JSON) for set. Ignored for get.",
                },
            },
            "required": ["action"],
        },
        execute=_execute,
        owner_only=True,
    )


# ---------------------------------------------------------------------------
# list_directory — list a directory (Sentinel-gated)
# ---------------------------------------------------------------------------


def _list_directory_factory(_ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        path = str(arguments.get("path", ".")).strip()
        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_list_directory

            out = agent_list_directory(path, reason=arguments.get("reason", "list_directory"))
            if out.startswith("[SENTINEL DENIED]"):
                return error_result(out)
            return text_result(out or "(empty)")
        except Exception as e:
            return error_result(f"list_directory failed: {e}")

    return SynapseTool(
        name="list_directory",
        description="List entries in a directory. Sentinel-gated.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path."},
                "reason": {"type": "string", "description": "Optional audit reason."},
            },
            "required": ["path"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# list_available_models — discover what models are actually reachable
# ---------------------------------------------------------------------------


def _list_available_models_factory(_ctx: ToolContext) -> SynapseTool:
    async def _execute(arguments: dict) -> ToolResult:
        provider_filter = str(arguments.get("provider", "")).strip().lower()

        out: dict = {"providers": {}}

        # --- GitHub Copilot /models ---
        if not provider_filter or provider_filter == "github_copilot":
            try:
                import httpx  # type: ignore[import]

                from sci_fi_dashboard.llm_router import _get_copilot_token

                token = _get_copilot_token()
                if token and token != "missing":
                    from litellm.llms.github_copilot.common_utils import (
                        GITHUB_COPILOT_API_BASE,
                        get_copilot_default_headers,
                    )

                    headers = {
                        "Authorization": f"Bearer {token}",
                        **get_copilot_default_headers(),
                    }
                    url = f"{GITHUB_COPILOT_API_BASE.rstrip('/')}/models"
                    async with httpx.AsyncClient(timeout=15.0) as c:
                        r = await c.get(url, headers=headers)
                        r.raise_for_status()
                        data = r.json()
                    entries = data.get("data", data if isinstance(data, list) else [])
                    models = []
                    for m in entries:
                        mid = m.get("id") if isinstance(m, dict) else str(m)
                        if mid:
                            models.append(f"github_copilot/{mid}")
                    out["providers"]["github_copilot"] = sorted(set(models))
                else:
                    out["providers"]["github_copilot"] = {"error": "no copilot token"}
            except Exception as e:
                out["providers"]["github_copilot"] = {"error": str(e)}

        # --- Ollama /api/tags ---
        if not provider_filter or provider_filter == "ollama":
            try:
                import httpx  # type: ignore[import]
                import os

                base = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(f"{base.rstrip('/')}/api/tags")
                    r.raise_for_status()
                    data = r.json()
                models = [f"ollama_chat/{m['name']}" for m in data.get("models", [])]
                out["providers"]["ollama"] = sorted(set(models))
            except Exception as e:
                out["providers"]["ollama"] = {"error": str(e)}

        # --- Configured (synapse.json) providers as hints ---
        try:
            cfg_path = Path.home() / ".synapse" / "synapse.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg_providers = list((cfg.get("providers") or {}).keys())
                out["providers_configured"] = cfg_providers
                out["current_mappings"] = {
                    role: v.get("model")
                    for role, v in (cfg.get("model_mappings") or {}).items()
                }
        except Exception:
            pass

        return text_result(json.dumps(out, indent=2))

    return SynapseTool(
        name="list_available_models",
        description=(
            "Discover which LLM models are actually reachable from this host. "
            "Queries GitHub Copilot's /models endpoint and the local Ollama "
            "daemon, and returns the current synapse.json model mappings. Use "
            "this BEFORE edit_synapse_config when the user asks to change a "
            "model — so you pick a real model name, not a guess."
        ),
        parameters={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Optional filter: 'github_copilot' or 'ollama'.",
                }
            },
        },
        execute=_execute,
    )


def register_sysops_tools(registry, memory_engine=None, project_root: str = "") -> None:
    """Register the sysops tool bundle on the given ToolRegistry."""
    registry.register_factory("bash_exec", _bash_exec_factory)
    registry.register_factory("edit_file", _edit_file_factory)
    registry.register_factory("grep_tool", _grep_factory)
    registry.register_factory("glob_tool", _glob_factory)
    registry.register_factory("edit_synapse_config", _edit_synapse_config_factory)
    registry.register_factory("list_directory", _list_directory_factory)
    registry.register_factory("list_available_models", _list_available_models_factory)
